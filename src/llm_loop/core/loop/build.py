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

# 快照文本函数已迁 core/session_snapshot.py（零 llm_loop 依赖叶子模块，R9-P3-01）——
# 顶层 import 不再触发循环：build→engine 运行时反向边删除（步2/3 断环点），engine→build 正向边保留
from llm_loop.core.message import Message
from llm_loop.core.prompt_build import BuildDecision
from llm_loop.core.prompt_build.stages.base_assembly import (
    _tool_round_zero_tail as _tool_round_zero_tail,  # re-export：test_build_tool_round_tail 从此导入（零测试改动）
)
from llm_loop.core.prompt_build.stages.base_assembly import run_base_assembly
from llm_loop.core.prompt_build.stages.cognitive import (  # B4-C4-01: COG 门控迁独占模块
    _cog_allowlist_hit as _cog_allowlist_hit,  # re-export：tests 三处从此导入（零测试改动）
)
from llm_loop.core.prompt_build.stages.cognitive import (
    _cog_freeze_enabled as _cog_freeze_enabled,
)
from llm_loop.core.prompt_build.stages.history_pipeline import run_history_pipeline
from llm_loop.core.prompt_build.stages.ingress_resolution import run_ingress_prelude
from llm_loop.core.prompt_build.stages.injection_cognitive import (  # B4-CLOSE-01 步C3
    _UNSET as _BUDGET_UNSET,
)
from llm_loop.core.prompt_build.stages.injection_cognitive import (
    run_injection_cognitive,
)
from llm_loop.core.prompt_build.stages.projection_gate import (
    GATE_STATE_UNSET,
)
from llm_loop.core.prompt_build.stages.tail_assembly import (
    merge_persisted_tail_injections as merge_persisted_tail_injections,  # re-export：test_direction_c_tail_merge 从此导入（零测试改动）
)
from llm_loop.core.prompt_build.stages.tail_assembly import run_tail_assembly
from llm_loop.core.prompt_build.stages.tail_slot_collect import run_tail_collection
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
        M54: max_chars 可覆盖默认预算；None = 运行时预算。P1-10: 窗口锚定——
        按 provider 固定历史起点，前缀稳定命中缓存；锚点随会话持久化。
        """
        decision = BuildDecision()  # R9-P4/B4-P1-01: 判定显式化载体（design T5-B）
        # 预解析簇 → stages/ingress_resolution.py::run_ingress_prelude
        # （B4-CLOSE-01 步D；label/anchor/system_prompt 解析 + ingress/泄漏
        # 隔离/provider 预清洗语义原样；decision 就地演进；旁路重置留调用点）。
        # err1210 T4.1: 注入登记旁路重置——每轮 build 覆盖，消费后不清除（供审计补查）。
        self._last_build_injections = []
        self._last_build_defer_replayed = False
        _pre = run_ingress_prelude(
            decision=decision,
            sess=sess,
            memory_msgs=memory_msgs,
            planned_label=planned_label,
            model=model,
            planned_model_label=self._planned_model_label,
            current_turn_ref=getattr(self, "_current_turn_ref", None),
            record_action=self._record_action,
            event_append=self._event_append,
            tool_round_zero=tool_round_zero,
        )
        resolved_label = _pre.resolved_label
        provider_id = _pre.provider_id
        sess_anchor = _pre.sess_anchor
        system_prompt = _pre.system_prompt
        base = _pre.base
        _base_original_indices = _pre.base_original_indices
        _r6_ingress_truth = _pre.r6_ingress_truth
        _leak_downgrade_parts = _pre.leak_downgrade_parts
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
        # 历史投影三段接线 → stages/history_pipeline.py::run_history_pipeline
        # （B4-CLOSE-01 步C1；prep→projection→postprocess 语义原样，调
        # history 现函数 Phase 7 前不动其内部）；写回面经 outcome 回接。
        _hist = run_history_pipeline(
            sess=sess,
            provider_id=provider_id,
            sess_anchor=sess_anchor,
            max_chars=max_chars,
            base=base,
            system_prompt=system_prompt,
            filtered_indices=_base_original_indices,
            prefix_len=prefix_len,
            emergency_compact=emergency_compact,
            resolved_label=resolved_label,
            registry_snapshot=registry_snapshot,
            r6_ingress_truth=_r6_ingress_truth,
            memory_msgs=memory_msgs,
            decision=decision,
            runtime_history_budget=self._runtime_history_budget,
            archive=self.archive,
            registry=self.registry,
            archive_sink_cb=self._archive_sink,
            record_action=self._record_action,
            settings=self.settings,
            cache_monitor=self._cache_monitor,
            resolve_msg_seq=self._resolve_msg_seq,
            event_append=self._event_append,
            compact_event_seq=getattr(self, "_compact_event_seq", 0),
            compact_event_was_compacted=getattr(
                self, "_compact_event_was_compacted", False
            ),
            last_nudge_total=getattr(self, "_last_nudge_total", None),
            provider_visible_chars_fn=_provider_visible_chars,
            growth_nudge_kind_fn=_growth_nudge_kind,
            reasoning_tail_fn=_reasoning_tail_for,
        )
        built = _hist.built
        effective_budget = _hist.effective_budget
        compact_view_box = _hist.compact_view_box
        _anchor_moved_this_build = _hist.anchor_moved
        self._last_build_info = _hist.last_build_info
        self._last_nudge_total = _hist.last_nudge_total
        self._last_compact_ratio = _hist.last_compact_ratio
        self._last_history_compacted = _hist.last_history_compacted
        self._compact_event_seq = _hist.compact_event_seq
        self._compact_event_was_compacted = _hist.compact_event_was_compacted
        self._cache_degrade_note = _hist.cache_degrade_note
        # INJECTION-GOVERNANCE R8.8: Evidence Ledger/Manifest remains durable and
        # queryable through list/search/read_evidence, but the recovery index itself no
        # longer has automatic prompt eligibility. This also closes the old R2 bypass.
        # Keep an empty fingerprint field for projection telemetry schema compatibility.
        _evidence_manifest_content = ""

        # 尾部槽收集 wiring → stages/tail_slot_collect.py::run_tail_collection
        # （B4-CLOSE-01 步C2；四路槽收集/原位合并/一次性消费语义原样；
        # self 面读写经参数与 outcome 回接，一次性消费清理留在调用点）。
        _pending_recovery = getattr(self, "_program_recovery_tail_message", None)
        self._program_recovery_tail_message = None
        _tailc = run_tail_collection(
            sess=sess,
            memory_msgs=memory_msgs,
            r6_ingress_truth=_r6_ingress_truth,
            record_action=self._record_action,
            cache_monitor=self._cache_monitor,
            current_turn_ref=getattr(self, "_current_turn_ref", None),
            pending_recovery=_pending_recovery,
            interop_tail=getattr(self, "_interop_tail_messages", None),
            tip_tail=getattr(self, "_tip_tail_messages", None),
            defer_refs=getattr(self, "_deferred_replay_refs", None) or [],
            replay_slots=getattr(self, "_deferred_replay_slots", None) or set(),
            note_defer_replayed=self._recovery._note_defer_replayed,
        )
        _inject_parts = _tailc.inject_parts
        tail_msgs = _tailc.tail_msgs
        self._deferred_replay_refs = _tailc.defer_refs
        self._deferred_replay_slots = _tailc.replay_slots
        self._interop_tail_messages = None  # 一次性消费（每轮重扫 pending）
        self._tip_tail_messages = None  # 经验提示同机制一次性消费（下轮工具执行再注入）
        _identity_cache = getattr(self, "_authorized_task_identity_cache", None)
        if _identity_cache is None:
            _identity_cache = {}
            self._authorized_task_identity_cache = _identity_cache
        # 注入+认知接线簇 → stages/injection_cognitive.py::run_injection_cognitive
        # （B4-CLOSE-01 步C3；授权→注入装配→认知门控/状态/预算/packet→聚合登记
        # 语义原样，fail-open 降级留模块内）；decision/built/injections 同对象就地
        # 演进；_last_injection_budget 经 UNSET 哨兵回写（未产生新值不覆盖旧值）。
        _injc = run_injection_cognitive(
            sess=sess,
            settings=self.settings,
            built=built,
            inject_parts=_inject_parts,
            leak_downgrade_parts=_leak_downgrade_parts,
            r6_ingress_truth=_r6_ingress_truth,
            current_turn_ref=getattr(self, "_current_turn_ref", None),
            record_action=self._record_action,
            identity_cache=_identity_cache,
            anchor_sess=self._focus.anchor_sess,
            injections=self._last_build_injections,
            decision=decision,
        )
        if _injc.last_injection_budget is not _BUDGET_UNSET:
            self._last_injection_budget = _injc.last_injection_budget
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
