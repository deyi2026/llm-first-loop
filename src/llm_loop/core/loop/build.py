"""消息构建 mixin（EVO-20260817-e63f712f，engine.py 防膨胀拆分）.

2026-08-18 自 engine.py 迁出（engine.py 1200 行触发防膨胀守卫 test_complexity_reduction，
按建议拆 _BuildMixin）。职责: 提交 LLM 的消息序列构建（system prompt + 记忆注入 +
协调通道 inbox + 窗口锚定 + 预算分级压缩 + 缓存门禁 + 投影一致性门闸）。

纯重构: 方法体原样迁移（零行为变更），原路径可导入语义保持（REQ-REF-06 对齐）。
依赖（engine 其他 mixin）: _planned_model_label / _record_action / _runtime_extract_interval / _runtime_history_budget /
_inject_interop_messages / _cache_monitor / _last_snapshot_count / _last_compact_ratio。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条)

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from llm_loop.core.episode_history import provider_message_visible

# EVO-20260818: projection_ver/check 提升到模块级（消除函数内 import 遮蔽导致的 F823）——
# 与 engine.py 顶部 re-export 同模式；stable_digest 既有模块级使用
from llm_loop.core.history import (
    is_cache_compacted_for,
    projection_check,  # noqa: F401 (history 工具, 函数内使用)
    projection_ver,  # noqa: F401 (history 工具, 函数内使用)
    )
from llm_loop.core.injection_budget import (
    DEFAULT_INJECTION_BUDGET_CHARS,
)
from llm_loop.core.loop.err1210 import (
    InjectedEntry,
    SlotKind,
    content_prefix_sha,
)
from llm_loop.core.loop.focus import wrap_injection
from llm_loop.core.prompt_eligibility import (
    PROGRAM_FINAL_PROTOCOL_BOUNDARY,
)

# Cognitive Runtime：装配面已全部迁 stages/cognitive.py 自持（B4-C4-01 步1/2/3）；
# 此处仅留 compile_decision_packet 传参 budget 阶段（惰性容错，import 失败回退平铺）。
try:  # noqa: SIM105
    from llm_loop.cognitive.compiler import compile_decision_packet
except Exception:  # noqa: BLE001 — fail-open 回退平铺聚合（零回归）
    compile_decision_packet = None  # type: ignore[assignment]

# 快照文本函数已迁 core/session_snapshot.py（零 llm_loop 依赖叶子模块，R9-P3-01）——
# 顶层 import 不再触发循环：build→engine 运行时反向边删除（步2/3 断环点），engine→build 正向边保留
from llm_loop.core.message import Message
from llm_loop.core.prompt import build_system_prompt
from llm_loop.core.prompt_build import BuildDecision
from llm_loop.core.prompt_build.stages.authorization import resolve_authorized
from llm_loop.core.prompt_build.stages.base_assembly import run_base_assembly
from llm_loop.core.prompt_build.stages.budget_application import apply_injection_budget
from llm_loop.core.prompt_build.stages.cognitive import (  # B4-C4-01: COG 门控迁独占模块
    _cog_allowlist_hit as _cog_allowlist_hit,  # re-export：tests 三处从此导入（零测试改动）
)
from llm_loop.core.prompt_build.stages.cognitive import (
    _cog_freeze_enabled as _cog_freeze_enabled,
)
from llm_loop.core.prompt_build.stages.cognitive import (
    resolve_cognitive_gate,
    run_cognitive_packet,
    run_cognitive_state,
)
from llm_loop.core.prompt_build.stages.history_budget_prep import run_history_budget_prep
from llm_loop.core.prompt_build.stages.history_postprocess import run_history_postprocess
from llm_loop.core.prompt_build.stages.history_projection import run_history_projection
from llm_loop.core.prompt_build.stages.ingress_resolution import resolve_ingress
from llm_loop.core.prompt_build.stages.injection_assembly import assemble_injections
from llm_loop.core.prompt_build.stages.projection_gate import (
    GATE_STATE_UNSET,
)
from llm_loop.core.prompt_build.stages.tail_assembly import (
    merge_persisted_tail_injections as merge_persisted_tail_injections,  # re-export：test_direction_c_tail_merge 从此导入（零测试改动）
)
from llm_loop.core.prompt_build.stages.tail_assembly import run_tail_assembly
from llm_loop.core.prompt_build.stages.tail_slot_collect import (
    collect_persisted_and_recovery,
    consume_tail_slots,
)
from llm_loop.core.prompt_build.stages.trace_isolation import run_trace_isolation
from llm_loop.core.prompt_build.stages.user_truth import (
    run_user_truth_wire,  # noqa: F401 — re-export 兼容面（阶段内部已移 tail_assembly）
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _provider_visible_chars(messages: list[Message], provider_id: str, start: int = 0) -> int:
    """Count history chars actually visible to one provider after mid-compaction."""
    return sum(
        len(m.content)
        for m in messages[max(0, start) :]
        if not is_cache_compacted_for(m, provider_id)
        and provider_message_visible(m)
    )


def _growth_nudge_kind(
    history_total: int,
    prev_total: int | None,
    *,
    prep_at: float,
    force_at: float,
    growth_floor: int,
) -> str | None:
    """增长率 nudge 判定（EVO-20260824-54d46549，billion-context 拷问产出, 双轨）.

    - "force"  : history_total > 预算×compact_ratio（90% 默认）→ 必警（压缩在即, bypass 增长率）
    - "growth" : 80% 准备态 + 距上次预警增长 ≥ 阈值 → 增长率门控触发（重任务早提示）
    - None     : 首轮基线（无增长参照）/ 未到 80% / 增长不足 / 已在压缩态——不警

    纯函数（无 self 依赖），供 _build_llm_messages 预警逻辑调用与单测。
    """
    if history_total > force_at:
        return "force"
    if prev_total is None:
        return None  # 首轮建立基线, 不预警（无增长参照）
    growth = history_total - prev_total
    if history_total > prep_at and growth >= growth_floor and history_total <= force_at:
        return "growth"
    return None


def _tool_round_zero_tail(msgs: list[Message]) -> list[Message]:
    """工具轮极小窗口: 保留【最近用户指令 + 最近完整协议配对组】.

    结构: [user(当前任务), assistant(tool_calls 最后声明), ...其全部 tool 回执]。
    中间轮次（早期配对组）不入载荷——极小窗口本意（任务锚点摘要补偿早期动作）。

    两项硬约束（2026-08-24 实证修复）:
    1. C1 协议: 声明↔回执必须同窗（原固定 base[-2:] 在多回执时截断配对组 → 孤儿回执;
       实证 "声明 3 个工具调用仅 1 条回执缺 2 条"）。
    2. 聊天模板: llama.cpp Qwen 模板要求载荷含 user 消息, 缺 user 直接 500
       "No user query found in messages"（实证 llama-server Qwen3.8 500）——
       故必须带上最近一条 user（任务指令）, 不能只发配对组。
    """
    n = len(msgs)
    if n == 0:
        return msgs
    group_start = -1
    for i in range(n - 1, -1, -1):
        if getattr(msgs[i], "role", "") == "assistant" and getattr(msgs[i], "tool_calls", None):
            group_start = i
            break
    user_idx = -1
    for i in range(n - 1, -1, -1):
        if getattr(msgs[i], "role", "") == "user":
            user_idx = i
            break
    if user_idx >= 0 and group_start >= 0:
        if user_idx >= group_start:
            # 最近 user 已在配对组之后（中断恢复/续跑）→ 整段保留, 不重复前置
            return msgs[group_start:]
        return msgs[user_idx : user_idx + 1] + msgs[group_start:]
    if user_idx >= 0:  # 无配对组 → 从任务指令起（模型可能直接回答）
        return msgs[user_idx:]
    if group_start >= 0:  # 无 user（异常会话）→ 配对组兜底（模板可能拒, 但保协议）
        return msgs[group_start:]
    return msgs[-2:] if n >= 2 else msgs


def _reasoning_tail_for(
    settings: Any,
    *,
    resolved_label: str = "",
    registry_snapshot: Any | None = None,
) -> int:
    """R8.21/E05: bind reasoning replay to the actual planned provider.

    Historical reasoning is not generic task context.  Keep only bytes required by
    the selected provider's replay protocol:

    - local endpoints: no replay requirement -> strip all (``-2``);
    - GLM preserved/interleaved thinking: replay all still-visible reasoning (``0``);
    - DeepSeek tool requests: replay all still-visible assistant reasoning (``0``);
    - MiniMax thinking disabled: strip all; thinking enabled: preserve all because
      interleaved-thinking state is part of its official agent protocol;
    - unknown provider: preserve the configured legacy policy fail-safe.

    Crucially this uses ``resolved_label`` + the same immutable planning registry as
    history budget/model planning.  The former implementation inspected only the
    global default ``settings.llm_base_url``, so a session model switch could apply
    the wrong provider's reasoning policy.
    """
    configured = int(getattr(settings, "reasoning_tail", 0) or 0)
    provider_id = resolved_label.partition("/")[0].strip().lower() if resolved_label else ""
    model_id = resolved_label.partition("/")[2] if "/" in resolved_label else ""
    base = ""
    model_spec = None
    if registry_snapshot is not None and provider_id:
        try:
            provider_spec = registry_snapshot.providers.get(provider_id)
            if provider_spec is not None:
                base = str(getattr(provider_spec, "base_url", "") or "")
                model_spec = (getattr(provider_spec, "models", None) or {}).get(model_id)
        except Exception:  # noqa: BLE001 — unknown registry shape => configured fail-safe
            base = ""

    # Compatibility for direct/unit build paths that do not supply a registry snapshot:
    # only use the global endpoint when there is no explicit provider identity.
    if not base and not provider_id:
        base = str(getattr(settings, "llm_base_url", "") or "")
    try:
        from urllib.parse import urlparse

        host = (urlparse(base).hostname or "").lower()
    except Exception:  # noqa: BLE001 — 解析失败按非本地（保守：云端协议约束优先）
        host = ""
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return -2
    base_lower = base.lower()
    if provider_id == "deepseek" or "deepseek.com" in base_lower:
        return 0
    if provider_id in {"glm", "zhipu"} or "bigmodel.cn" in base_lower:
        return 0
    if provider_id == "minimax" or "minimax.io" in base_lower or "minimax.chat" in base_lower:
        if model_spec is not None and getattr(model_spec, "thinking", None) is False:
            return -2
        if model_spec is not None and getattr(model_spec, "thinking", None) is True:
            return 0
    return configured


class _BuildMixin:
    def _post_run_cache_health(
        self,
        final_answer: str,
        sess,
        tokens_in: int,
        tokens_cache_hit: int,
        model_used: str,
    ) -> str:
        """EVO-20260817-72fcd94a L3: 缓存健康闭环（run 末尾，fail-open）.

        P1 遥测内容/传输分层（2026-08-25 规格）: ①剥离模型本轮自行生成的同格式
        遥测行（⚡ 缓存命中率 ...）——正文只留纯回答；②程序 canonical 遥测只装饰
        返回值（transport 展示），会话正文存纯回答 + metadata.cache_health
        （结构化）——下一轮 LLM 永远看不到程序遥测，杜绝模型伪造循环。
        """
        try:
            if final_answer and "缓存命中率" in final_answer:
                from llm_loop.core.cache_health import strip_cache_telemetry_lines

                final_answer = strip_cache_telemetry_lines(final_answer)
            _cache_hint = self._cache_monitor.record(
                tokens_in, tokens_cache_hit, model_ref=model_used, session_id=sess.session_id
            )
            # 发送前门禁·后检漂移提示（build 时记录）一并注入 final_answer（告警发给用户）
            if self._cache_gate_hint:
                _cache_hint = (
                    f"{_cache_hint}\n\n{self._cache_gate_hint}"
                    if _cache_hint
                    else self._cache_gate_hint
                )
                self._cache_gate_hint = None
            _telemetry_note: str | None = None  # 程序 canonical 遥测（进 metadata，不进正文）
            if _cache_hint:
                self._record_action(
                    "run.cache_monitor",
                    "recovered" if "已恢复" in _cache_hint else "alert",
                    _cache_hint,
                )
                # P1 分层（2026-08-25 §5.5）: alert 路径遥测不进 final_answer 正文——
                # 正文只存纯回答（LLM 永远看不到程序遥测，杜绝模型伪造循环）；
                # 遥测走 metadata.cache_health 结构化 + _record_action 审计，transport 层渲染。
                _telemetry_note = _cache_hint
            else:
                # EVO-20260819-2254e3b4 方案B（用户批准）: 常态缓存命中率展示——
                # 无告警时若开启 CACHE_HIT_SHOW_IN_ANSWER 且窗口有数据，回答末尾附一行
                # 命中率摘要（仅展示，不影响缓存/前缀机制；fail-open）
                try:
                    if (
                        getattr(self.settings, "cache_hit_show_in_answer", False)
                        and final_answer
                        and self._cache_monitor is not None
                    ):
                        _note = self._cache_monitor.format_health_note(session_id=sess.session_id)
                        if _note:
                            final_answer = f"{final_answer}\n\n{_note}"
                            _telemetry_note = _note
                except Exception:  # noqa: BLE001 — fail-open
                    logger.warning("常态缓存命中率注入异常（fail-open）", exc_info=True)
            # P1 内容/传输分层回写: 正文只存纯回答（已剥离伪造行），遥测进
            # metadata.cache_health（结构化），transport 层（web 返回值已含 /
            # 飞书 cross_sync 按 metadata 渲染）再展示。
            if final_answer and sess.messages:
                try:
                    _last_asst = None
                    for _m in reversed(sess.messages):
                        if _m.role == "assistant":
                            _last_asst = _m
                            break
                    if _last_asst is not None:
                        _pure = (
                            strip_cache_telemetry_lines(_last_asst.content or "")
                            if "缓存命中率" in (_last_asst.content or "")
                            else (_last_asst.content or "")
                        )
                        _old_md = dict(_last_asst.metadata or {})
                        _md = dict(_old_md)
                        _degrade_note = getattr(self, "_cache_degrade_note", None)
                        if _degrade_note:
                            # 任务7（§5.7）: 降级事件优先进 metadata.cache_health（kind="degraded"）
                            _md["cache_health"] = {"note": _degrade_note, "kind": "degraded"}
                            self._cache_degrade_note = None
                        elif _telemetry_note:
                            _md["cache_health"] = {
                                "note": _telemetry_note,
                                "kind": "alert" if _cache_hint else "normal",
                            }
                        elif "cache_health" in _md:
                            del _md["cache_health"]
                        _content_changed = _last_asst.content != _pure
                        _metadata_changed = _md != _old_md
                        if _content_changed:
                            _last_asst.content = _pure
                        _last_asst.metadata = _md
                        if _content_changed or _metadata_changed:
                            self.session.save(sess)
                except Exception:  # noqa: BLE001 — 回写失败 fail-open
                    logger.warning("命中率注入回写 session 失败（fail-open）", exc_info=True)
        except Exception:  # noqa: BLE001 — 监控失败 fail-open，不阻断 run
            logger.warning("缓存健康闭环监控异常（fail-open）", exc_info=True)
        return final_answer

    def _breaker_pressure_block(
        self,
        sess,
        effective_budget: int,
        planned_label: str,
    ) -> str | None:
        """P0 压缩风暴熔断（2026-08-25 规格）: 冻结期超安全水位 → context_pressure.

        返回 final_answer 拦截文案（None=放行）。不提交——程序压缩已冻结，超限
        提交=继续制造不可恢复前缀；AI 先 checkpoint/换会话。与 cache_guard 规则 F
        协调: 安全水位 = 预算×BREAKER_PRESSURE_RATIO（默认 0.95 = 规则 F BLOCK
        阈值），breaker 前置拦截后规则 F 永不双拦；逃生轮（pressure_escape）
        放行一次受控压缩提交。

        D'-1.2（R8.24 D-D4）breaker pressure 终止条件收窄: 内部 history budget
        水位（compression breaker active）不再独立终止 run——允许终止 run 的仅剩
        三类: ①真实 provider window 超限；②用户成本政策；③安全。其余场景由
        _build_llm_messages 内置 compaction 链（90% 主动压缩/渐进折叠/锚定视图）
        自行压缩后继续。开关 LFL_BREAKER_PRESSURE_NARROW（默认 0=现状拦截，
        1=收窄放行+observability 事件）；收窄分支异常 fail 回退现状文案。
        """
        try:
            if not self._cache_monitor.breaker_active_for(sess.session_id):
                return None
            # 锚定视图口径（实际提交量——锚点压缩不删 sess.messages，全量口径
            # 会让上下文压力永不解除）
            _anchors = sess.history_anchors or {}
            _provider_id = planned_label.partition("/")[0] or "default"
            _a = int(_anchors.get(_provider_id, 0) or 0)
            _chars_now = _provider_visible_chars(
                sess.messages, _provider_id, min(_a, len(sess.messages))
            )
            if not self._cache_monitor.context_pressure_decision(
                sess.session_id, _chars_now, effective_budget
            ):
                return None
            self._cache_monitor.note_context_pressure(
                sess.session_id,
                reason="over_safety_cap",
                chars_total=_chars_now,
                budget=effective_budget,
                model_ref=planned_label,
            )
            # D'-1.2 收窄态: 内部水位信息降为 optimizer/observability 事件——
            # 不终止 run，超限载荷由 _build_llm_messages 内置 compaction 链
            # （衔接 B 包 E17 runtime compact）压缩后继续；指令性输出取消
            # （通知面属 B 包 E19 改道）。
            if os.environ.get("LFL_BREAKER_PRESSURE_NARROW", "0") == "1":
                logger.info(
                    "event=breaker.context_pressure_narrowed chars=%d budget=%d model=%s"
                    "（内部水位超安全水位——run 不终止，compaction 链自行压缩后继续）",
                    _chars_now,
                    effective_budget,
                    planned_label,
                )
                self._record_action(
                    "action.llm_decide",
                    "breaker_context_pressure_narrowed",
                    f"chars={_chars_now:,} budget={effective_budget:,}（optimizer 观测——run 继续）",
                )
                return None
            self._record_action(
                "action.llm_decide",
                "breaker_context_pressure",
                f"chars={_chars_now:,} budget={effective_budget:,}",
            )
            return (
                f"[上下文压力] 压缩风暴熔断中：上下文 {_chars_now:,} 字符已超"
                f"安全水位（预算 {effective_budget:,}），程序压缩已冻结"
                "（防止前缀持续失效、命中率钉死）。请先执行压缩 checkpoint"
                "（归档历史可 search_archive 检索找回）或换新会话后继续。"
            )
        except Exception:  # noqa: BLE001 — fail-open
            return None

    def _session_digest(self, sess):
        """会话汇总档案实例缓存（EVO-20260829-06c96021；生命周期随会话）.

        lazy getattr 初始化——mixin 无 __init__ 契约，不侵入宿主类装配。
        MVP 内存态；持久化（P2 FR-6）落地后经 persist_dir 接入。
        """
        cache = getattr(self, "_digest_cache", None)
        if cache is None:
            cache = {}
            self._digest_cache = cache  # type: ignore[attr-defined]
        d = cache.get(sess.session_id)
        if d is None:
            from llm_loop.core.session_digest import SessionDigest

            d = SessionDigest(sess.session_id)
            cache[sess.session_id] = d
        return d

    def _build_llm_messages(
        self,
        sess,
        memory_msgs: list[Message],
        max_chars: int | None = None,
        model: str | None = None,  # P1-7: per-call 模型覆盖（判定本地 provider 跳过推送式注入）
        planned_label: str | None = None,  # 热重载一致性: 复用本轮已解析标签，避免构造期二次读registry
        registry_snapshot: Any | None = None,  # R8.21: reasoning policy must bind to this round's provider
        emergency_compact: bool = False,  # EVO-20260818: M53 拒绝逃生——head_keep=0 锚点前移激进压缩
        tool_round_zero: bool = False,  # 2026-08-21: 工具轮零历史——只发 system+摘要+最近结果
    ) -> list[dict]:
        """构造提交 LLM 的消息序列（system prompt + 记忆注入 + 历史 + 压缩另存）.

        M54: max_chars 可覆盖默认预算（模型窗口感知压缩）；None = 运行时预算（零回归）。
        P1-10: 窗口锚定——按 provider 固定历史起点（只追加不挤旧, 超预算优先降级中段),
        前缀稳定命中引擎/服务端缓存; 锚点写入 sess.history_anchors 随会话持久化。
        """
        decision = BuildDecision()  # R9-P4/B4-P1-01: 判定显式化载体（design T5-B），C1-C4 拆分时逐项迁入
        resolved_label: str = (
            planned_label
            if planned_label is not None
            else self._planned_model_label(model, sess)
        )
        provider_id = resolved_label.partition("/")[0] or "default"
        # err1210 T4.1（spec err1210_locating）: 注入登记旁路重置——每轮 build 覆盖，
        # 消费后不清除（供审计补查）；纯旁路记录，不向注入产物 dict 添加任何自定义键。
        self._last_build_injections = []
        self._last_build_defer_replayed = False
        anchors = sess.history_anchors or {}
        sess_anchor = int(anchors.get(provider_id, 0) or 0)
        system_prompt = build_system_prompt()
        # EVO-2026XXXX（spec §5.3.1-1c）: memory 检索注入不再前置——检索结果（top_k 语义/
        # 关键词召回）随本轮查询变化，前置在 system 之后会每轮改变前缀首段 → 前缀断
        # （2026-08-18 审计断点归因: 96%→2% 全量失效，delta 仅 614 tokens）。
        # 改为提交视图尾部追加（GATE_NOTE 模式，转 user），system+稳定历史前缀字节不变。
        # 入口解析/过期清理 → stages/ingress_resolution.py（BuildInputs 产出段；
        # 四过滤器链 storage truth 零改动，仅 provider 视图收窄）
        inputs = resolve_ingress(
            sess_messages=sess.messages,
            memory_msgs=memory_msgs,
            current_turn_ref=getattr(self, "_current_turn_ref", None),
            record_action=self._record_action,
        )
        base = inputs.base_messages
        _base_original_indices = inputs.filtered_indices
        _original_base_index_by_id = inputs.base_index_by_id
        _r6_ingress_truth = inputs.r6_ingress_truth
        # agent_trace_leak 4.2 α 挂载点 → stages/trace_isolation.py（KEEP-HARD 薄接线；
        # 三态分流 D-D1 / fail-open spec 5.4.3-1 语义原样；本体在 core/trace_leak/）
        base, _base_original_indices = run_trace_isolation(
            base,
            base_indices=_base_original_indices,
            index_by_id=_original_base_index_by_id,
            sess=sess,
            current_ingress=_r6_ingress_truth,
            event_sink=self._event_append,
            decision=decision,
        )
        _leak_downgrade_parts = (
            decision.trace_isolation["downgrade_parts"]
            if decision.trace_isolation
            else []
        )
        # P1 遥测内容/传输分层（2026-08-25）: legacy 历史（旧会话已把 ⚡ 缓存命中率
        # 行写进 assistant 正文）与模型伪造行——build 提交视图一律剥离（正文=纯回答；
        # 权威遥测走 metadata.cache_health → transport 渲染）。剥离只影响提交视图，
        # 存档/存储原文不动（archive_sink 收到的是剥离后副本——遥测行属噪音，无信息损失）。
        if any(
            m.role == "assistant" and "缓存命中率" in (m.content or "") for m in base
        ):
            from dataclasses import replace

            from llm_loop.core.cache_health import strip_cache_telemetry_lines

            base = [
                replace(m, content=strip_cache_telemetry_lines(m.content))
                if (m.role == "assistant" and "缓存命中率" in (m.content or ""))
                else m
                for m in base
            ]
        # 2026-08-21 工具轮零历史（TOOL_ROUND_ZERO_HISTORY=1 / provider 配置）: 工具轮只发
        # system+摘要+最近完整协议配对组（assistant(tool_calls)+全部 tool 回执）——前缀
        # （system+摘要）固定 → KV 命中 → prefill 秒级（本地模型实测 4-13 tokens
        # prefill 仅 0.2-0.8s）。
        # 注意: 保留最近配对组而非固定 -2 条（2026-08-24: 多回执截断会破坏 C1 配对）。
        # R8.10 / P0-B2 supersession: a persisted program final is user-visible storage
        # truth, but its fault/cancel/guard prose has no automatic next-turn authority.
        # Dropping the assistant frame outright would turn user→program-assistant→user into
        # consecutive user roles and can recreate the provider 1210 shape.  Provider view
        # therefore keeps only one byte-stable assistant protocol boundary while retiring
        # all historical program-result detail.  Storage/event truth remains untouched.
        from dataclasses import replace

        from llm_loop.feedback.honesty import PROGRAM_FEEDBACK_PREFIXES

        base = [
            (
                replace(m, content=PROGRAM_FINAL_PROTOCOL_BOUNDARY, reasoning_content=None)
                if (
                    m.role == "assistant"
                    and (
                        (m.metadata or {}).get("answer_origin") == "program"
                        or str(m.content or "").startswith(PROGRAM_FEEDBACK_PREFIXES)
                    )
                )
                else m
            )
            for m in base
        ]
        if tool_round_zero:
            _pre_zero_base = base
            _pre_zero_pos = {id(_m): _idx for _idx, _m in enumerate(_pre_zero_base)}
            base = _tool_round_zero_tail(base)
            _base_original_indices = [
                _base_original_indices[_pre_zero_pos[id(_m)]]
                for _m in base
                if id(_m) in _pre_zero_pos
            ]
        # base 装配 → stages/base_assembly.py（interop 注入/门禁预检/快照节流；
        # stable_fp 与 last_snapshot_count 调用点回写 self 面）
        _asm = run_base_assembly(
            base=base,
            system_prompt=system_prompt,
            session_id=sess.session_id,
            sess_message_count=len(sess.messages),
            sess_anchor=sess_anchor,
            inject_interop=self._inject_interop_messages,
            cache_monitor=self._cache_monitor,
            runtime_extract_interval=self._runtime_extract_interval,
            memory=self.memory,
            evolution_store=self.evolution_store,
            last_snapshot_count=self._last_snapshot_count,
        )
        base = _asm.base
        prefix_len = _asm.prefix_len
        self._cache_gate_stable_fp = _asm.stable_fp
        self._last_snapshot_count = _asm.last_snapshot_count
        # 历史投影接线三段 → stages/（budget_prep / projection / postprocess；
        # 调 history 现函数，Phase 7 前不动其内部）
        _prep = run_history_budget_prep(
            sess_messages=sess.messages,
            provider_id=provider_id,
            sess_anchor=sess_anchor,
            max_chars=max_chars,
            runtime_history_budget=self._runtime_history_budget,
            archive=self.archive,
            registry=self.registry,
            archive_sink_cb=self._archive_sink,
            decision=decision,
            record_action=self._record_action,
            last_nudge_total=getattr(self, "_last_nudge_total", None),
            provider_visible_chars=_provider_visible_chars,
            growth_nudge_kind=_growth_nudge_kind,
        )
        archive_sink = _prep.archive_sink
        effective_budget = _prep.effective_budget
        self._last_build_info = {
            "base": base,
            "system_prompt": system_prompt,
            "memory_msgs": memory_msgs,
            "budget": effective_budget,
        }
        self._last_nudge_total = _prep.last_nudge_total
        self._last_compact_ratio = _prep.compact_ratio
        _proj = run_history_projection(
            base=base,
            system_prompt=system_prompt,
            filtered_indices=_base_original_indices,
            sess_anchor=sess_anchor,
            prefix_len=prefix_len,
            session_id=sess.session_id,
            max_chars=max_chars,
            runtime_history_budget_value=self._runtime_history_budget(),
            compact_ratio=_prep.compact_ratio,
            archive_sink=archive_sink,
            settings=self.settings,
            provider_id=provider_id,
            emergency_compact=emergency_compact,
            reasoning_tail=_reasoning_tail_for(
                self.settings,
                resolved_label=resolved_label,
                registry_snapshot=registry_snapshot,
            ),
            r6_ingress_truth=_r6_ingress_truth,
            registry=self.registry,
            cache_monitor=self._cache_monitor,
            effective_budget=effective_budget,
            progressive_fold_k=_prep.fold_k,
        )
        built = _proj.built
        anchor_box = _proj.anchor_box
        compacted_box = _proj.compacted_box
        cache_compacted_box = _proj.cache_compacted_box
        compact_view_box = _proj.compact_view_box
        degrade_box = _proj.degrade_box
        _post = run_history_postprocess(
            cache_compacted_box=cache_compacted_box,
            compacted_box=compacted_box,
            compact_view_box=compact_view_box,
            degrade_box=degrade_box,
            anchor_box=anchor_box,
            filtered_indices=_base_original_indices,
            prefix_len=prefix_len,
            sess=sess,
            sess_anchor=sess_anchor,
            provider_id=provider_id,
            resolved_label=resolved_label,
            effective_budget=effective_budget,
            compact_event_seq=getattr(self, "_compact_event_seq", 0),
            compact_event_was_compacted=getattr(self, "_compact_event_was_compacted", False),
            cache_monitor=self._cache_monitor,
            resolve_msg_seq=self._resolve_msg_seq,
            event_append=self._event_append,
            provider_visible_chars=_provider_visible_chars,
        )
        self._last_history_compacted = _post.last_history_compacted
        self._compact_event_seq = _post.compact_event_seq
        self._compact_event_was_compacted = _post.compact_event_was_compacted
        _anchor_moved_this_build = _post.anchor_moved
        self._cache_degrade_note = _post.cache_degrade_note
        # INJECTION-GOVERNANCE R8.8: Evidence Ledger/Manifest remains durable and
        # queryable through list/search/read_evidence, but the recovery index itself no
        # longer has automatic prompt eligibility. This also closes the old R2 bypass.
        # Keep an empty fingerprint field for projection telemetry schema compatibility.
        _evidence_manifest_content = ""

        # B4-C2-04: 尾部槽收集迁 stages/tail_slot_collect（三函数）；授权投影→B4-C3-01 升格 authorization。
        # self 面写收窄：一次性消费清理/状态机新值由调用点回写；probe/recovery 读点先算传入。
        _pending_recovery = getattr(self, "_program_recovery_tail_message", None)
        self._program_recovery_tail_message = None
        _inject_parts: list[tuple[str | None, str]] = []  # (slot|None=hint, content)——P1 9.1 聚合收集
        collect_persisted_and_recovery(
            inject_parts=_inject_parts,
            current_turn_ref=getattr(self, "_current_turn_ref", None),
            pending_recovery=_pending_recovery,
            memory_msgs=memory_msgs,
            sess=sess,
            r6_ingress_truth=_r6_ingress_truth,
            record_action=self._record_action,
        )
        _interop_tail = getattr(self, "_interop_tail_messages", None)
        _tip_tail = getattr(self, "_tip_tail_messages", None)
        tail_msgs = _interop_tail  # 原位合并语义（gate 水印面用：interop+tip 合列表）
        if _tip_tail:
            tail_msgs = (tail_msgs or []) + _tip_tail
        _outcome = consume_tail_slots(
            inject_parts=_inject_parts,
            interop_tail=_interop_tail,
            tip_tail=_tip_tail,
            defer_refs=getattr(self, "_deferred_replay_refs", None) or [],
            replay_slots=getattr(self, "_deferred_replay_slots", None) or set(),
            note_defer_replayed=self._note_defer_replayed,
            record_action=self._record_action,
            cache_monitor=self._cache_monitor,
            session_id=sess.session_id,
        )
        self._deferred_replay_refs = _outcome.defer_refs
        self._deferred_replay_slots = _outcome.replay_slots
        self._interop_tail_messages = None  # 一次性消费（每轮重扫 pending）
        self._tip_tail_messages = None  # 经验提示同机制一次性消费（下轮工具执行再注入）
        _identity_cache = getattr(self, "_authorized_task_identity_cache", None)
        if _identity_cache is None:
            _identity_cache = {}
            self._authorized_task_identity_cache = _identity_cache
        # B4-C3-01: task_active 升格 authorization 阶段（A-2 承载）；决策入 BuildDecision.authorization_slots
        decision.authorization_slots = resolve_authorized(
            inject_parts=_inject_parts,
            sess=sess,
            settings=self.settings,
            current_turn_ref=getattr(self, "_current_turn_ref", None),
            r6_ingress_truth=_r6_ingress_truth,
            identity_cache=_identity_cache,
            record_action=self._record_action,
        )
        # R8.8 eligibility precedes semantic profile/budget. ``infer_layer`` may retain
        # B4-C3-02: 注入装配迁 stages/injection_assembly（eligibility→quarantine→
        # β 观测→packet init→memory 授权双面注入）；consumed_filtering 判定独立
        # 防护模块（A-1 consumed 半面，D13 验收面①）；决策入 BuildDecision（A-4）。
        _assembly = assemble_injections(
            inject_parts=_inject_parts,
            leak_downgrade_parts=_leak_downgrade_parts,
            sess=sess,
            r6_ingress_truth=_r6_ingress_truth,
            record_action=self._record_action,
        )
        _inject_parts = _assembly.inject_parts
        _inject_keys = _assembly.inject_keys
        _packet_parts = _assembly.packet_parts
        _packet_keys = _assembly.packet_keys
        _packet_memory_seq = _assembly.packet_memory_seq
        _lat_mode = _assembly.consumed_filtering.get("lat_mode", "off")  # COG 锚点观测用（同轮同值）
        decision.consumed_filtering = _assembly.consumed_filtering
        decision.injection_eligibility = _assembly.injection_eligibility
        # 尾部连续 user 恒 ≤1（1210 结构性消除）；聚合失败 fail-open 降级零注入（不阻断构建）
        # Cognitive Runtime 门控解析 → stages/cognitive.py（B4-C4-01 第 1 步；design
        # §2.1.2 #12 独占模块，RETRIEVAL-ONLY，冻结态 promote 禁止）。tier/anchor_mode/
        # dual_source_guard 语义与 CR-R1 空 slots header-only 不变量（零注入安静轮
        # decision_visible=True）见该模块；冻结/提升决策入 decision.cog_freeze。
        _cog = resolve_cognitive_gate(
            self.settings,
            sess=sess,
            built=built,
            inject_parts_present=bool(_inject_parts),
            decision=decision,
        )
        _cog_mode_candidate = _cog.mode
        _cog_promoted = _cog.promoted
        _cog_compute_candidate = _cog.compute_candidate
        _has_existing_program = _cog.has_existing_program
        _recovery_render_parts: list[str] = []
        if _inject_parts or _cog_compute_candidate or _has_existing_program:
            try:
                # 认知运行时状态装配 → stages/cognitive.py（B4-C4-01 第 2 步）：load/
                # schema v2 三态解包/Read Barrier（GoalStore 三路一致性 + rebuild
                # 回存 + state_revision 单调继承 + state_rebuild telemetry）/投影
                # 渲染/锚点消费面退出（E-D3 latent 留痕）+ 投影替代
                # （DUAL_SOURCE_GUARD）。语义原样，产物经 CognitiveStateOutcome 回接。
                _cs = run_cognitive_state(
                    self.settings,
                    sess=sess,
                    mode_candidate=_cog_mode_candidate,
                    promoted=_cog_promoted,
                    lat_mode=_lat_mode,
                    anchor_sess=self._focus.anchor_sess,
                    record_action=self._record_action,
                )
                _anchor_mode = _cs.anchor_mode
                _tier_on = _cs.tier_on
                _cog_mode = _cs.mode
                _cog_enforce = _cs.enforce
                _cog_sid = _cs.sid
                _sem_state = _cs.sem_state
                _env = _cs.env
                _projection = _cs.projection
                _anchor = _cs.anchor

                # B4-C3-03: 预算切分迁 stages/budget_application（R2/L2-1 单一总预算门闸
                # + R4 recovery 拉出）；决策入 BuildDecision.budget；self._last_injection_budget 回写。
                _budget_outcome = apply_injection_budget(
                    built=built,
                    inject_parts=_inject_parts,
                    inject_keys=_inject_keys,
                    packet_parts=_packet_parts,
                    packet_keys=_packet_keys,
                    projection=_projection,
                    anchor=_anchor,
                    sem_state=_sem_state,
                    cog_enforce=_cog_enforce,
                    tier_on=_tier_on,
                    compile_decision_packet=compile_decision_packet,
                    recovery_render_parts=_recovery_render_parts,
                    injection_budget_chars=int(
                        getattr(
                            self.settings,
                            "injection_budget_chars",
                            DEFAULT_INJECTION_BUDGET_CHARS,
                        )
                    ),
                    record_action=self._record_action,
                )
                _inject_parts = _budget_outcome.inject_parts
                _inject_keys = _budget_outcome.inject_keys
                _packet_parts = _budget_outcome.packet_parts
                _packet_keys = _budget_outcome.packet_keys
                _recovery_render_parts = _budget_outcome.recovery_render_parts
                _projection = _budget_outcome.projection
                _anchor = _budget_outcome.anchor
                _sem_state = _budget_outcome.sem_state
                self._last_injection_budget = _budget_outcome.budget_result
                decision.budget = _budget_outcome.budget

                # packet 装配/telemetry → stages/cognitive.py（B4-C4-01 第 3 步）：CR-R1
                # header 先行（空 slots 不抑制 header；header 已含投影 → anchor 位不重复
                # 注入）/CR-R1.1 shadow 同构（产物仅 telemetry 度量，prompt 平铺旧行为）/
                # CR-R1 4.2 生产预算接线（超上界降级仅 HOT）/CR-R1 6.2 packet_compile +
                # tier_degraded telemetry（_CogPacketEvt 显式键型随迁）。产物经
                # CognitivePacketOutcome 回接。
                _cp = run_cognitive_packet(
                    self.settings,
                    inject_parts=_inject_parts,
                    packet_parts=_packet_parts,
                    sem_state=_sem_state,
                    anchor=_anchor,
                    tier_on=_tier_on,
                    enforce=_cog_enforce,
                    sid=_cog_sid,
                    env=_env,
                    mode=_cog_mode,
                    promoted=_cog_promoted,
                )
                _agg = _cp.agg
                _agg_anchor = _cp.agg_anchor
                # R4 recovery is rendered as its own program message before the ordinary
                # background appendix.  R6 immediately absorbs both into one user envelope,
                # leaving recovery as the explicit executable exception before exact user truth.
                if _recovery_render_parts and _r6_ingress_truth is not None:
                    built.append({"role": "user", "content": _recovery_render_parts[0]})
                if _agg.strip():
                    _agg_content = wrap_injection(_agg, _agg_anchor)
                    built.append({"role": "user", "content": _agg_content})
                    # err1210 9.1: 聚合登记（单 entry；strip/defer 消费端经 AGGREGATED 分支）
                    # CR-R1.1（审查项5）: seg_sources 携带投影前原始段——defer 恢复
                    # 不从 wire 反推（WARM 投影截断会永久丢失原文）。
                    self._last_build_injections.append(
                        InjectedEntry(
                            msg_idx=len(built) - 1,
                            slot_kind=SlotKind.AGGREGATED,
                            prefix_sha=content_prefix_sha(_agg_content),
                            message_ref=None,
                            seg_sources=tuple(
                                (str(_k), _c) for _k, _c in _inject_parts
                            ),
                        )
                    )
                # 空 slots 且无 header：安静轮零注入（不造空条、不登记）
            except Exception:  # noqa: BLE001 — 聚合失败 fail-open（零注入降级 + WARN）
                logger.warning(
                    "build: 尾部注入聚合失败，本轮零注入降级（fail-open）", exc_info=True
                )
        # 尾段装配 → stages/tail_assembly.py（B4-CLOSE-01 步A）：user_truth wire
        # 投影（R6 单信封 KEEP-HARD）→ 方向 C 持久化注入合并（非 ingress 路径）→
        # 投影一致性门闸（水印 + gate_state 回写）→ cache 门禁后检（fail-open）→
        # 压缩审计（BuildAudit）。产物经 TailAssemblyOutcome 回接。
        _ta = run_tail_assembly(
            built=built,
            base=base,
            memory_msgs=memory_msgs,
            system_prompt=system_prompt,
            tail_msgs=tail_msgs,
            prefix_len=prefix_len,
            resolved_label=resolved_label,
            effective_budget=effective_budget,
            sess_anchor=sess_anchor,
            provider_id=provider_id,
            evidence_manifest_content=_evidence_manifest_content,
            registry_snapshot=registry_snapshot,
            reasoning_tail_fn=_reasoning_tail_for,
            compact_view_box=compact_view_box,
            anchor_moved=_anchor_moved_this_build,
            ingress_truth=_r6_ingress_truth,
            injections=self._last_build_injections,
            settings=self.settings,
            sess=sess,
            decision=decision,
            record_action=self._record_action,
            cache_monitor=self._cache_monitor,
            cache_gate_stable_fp=self._cache_gate_stable_fp,
            last_history_compacted=self._last_history_compacted,
            anchor_sess=self._focus.anchor_sess,
        )
        self._last_build_injections = _ta.injections
        if _ta.gate_state is not GATE_STATE_UNSET:
            self._projection_guard_state = _ta.gate_state
        self._cache_gate_hint = _ta.cache_gate_hint
        return _ta.built
