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
from typing import TYPE_CHECKING

from llm_loop.core.cache_health import GATE_NOTE_CONTENT  # 门禁干预知情标记

# EVO-20260818: projection_ver/check 提升到模块级（消除函数内 import 遮蔽导致的 F823）——
# 与 engine.py 顶部 re-export 同模式；stable_digest 既有模块级使用
from llm_loop.core.history import (
    is_cache_compacted_for,
    projection_check,  # noqa: F401 (history 工具, 函数内使用)
    projection_ver,  # noqa: F401 (history 工具, 函数内使用)
    stable_digest,  # 投影门闸
)
from llm_loop.core.loop.err1210 import (
    InjectedEntry,
    SlotKind,
    content_prefix_sha,
)
from llm_loop.core.loop.focus import build_task_anchor, wrap_injection
from llm_loop.core.loop.hotcard import pop_hotcard, write_hotcard

# Cognitive Runtime（tasks 2.3/2.5/2.6）: tier 分级聚合 + 语义投影替代锚点。
# 惰性容错导入（cognitive 子包独立演进，import 失败时聚合器回退原平铺行为）。
try:  # noqa: SIM105
    from llm_loop.cognitive.compiler import compile_decision_packet, semantic_projection
    from llm_loop.cognitive.state import (
        SemanticStateStore,
        StateEnvelope,
        StateIdentity,
        rebuild_state,
    )
    from llm_loop.cognitive.telemetry import emit_cognitive_event
except Exception:  # noqa: BLE001 — fail-open 回退平铺聚合（零回归）
    compile_decision_packet = None  # type: ignore[assignment]
    semantic_projection = None  # type: ignore[assignment]
    emit_cognitive_event = None  # type: ignore[assignment]
    SemanticStateStore = None  # type: ignore[assignment]
    StateEnvelope = None  # type: ignore[assignment]

# build_session_snapshot_text 定义于 engine（loop 包内）——顶层 import 会触发
# engine→build→loop/__init__ 循环（engine import build 在前），故用函数内延迟 import
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt import build_system_prompt

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _provider_visible_chars(messages: list[Message], provider_id: str, start: int = 0) -> int:
    """Count history chars actually visible to one provider after mid-compaction."""
    return sum(
        len(m.content)
        for m in messages[max(0, start) :]
        if not is_cache_compacted_for(m, provider_id)
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

    def _build_llm_messages(
        self,
        sess,
        memory_msgs: list[Message],
        max_chars: int | None = None,
        model: str | None = None,  # P1-7: per-call 模型覆盖（判定本地 provider 跳过推送式注入）
        planned_label: str | None = None,  # 热重载一致性: 复用本轮已解析标签，避免构造期二次读registry
        emergency_compact: bool = False,  # EVO-20260818: M53 拒绝逃生——head_keep=0 锚点前移激进压缩
        tool_round_zero: bool = False,  # 2026-08-21: 工具轮零历史——只发 system+摘要+最近结果
    ) -> list[dict]:
        """构造提交 LLM 的消息序列（system prompt + 记忆注入 + 历史 + 压缩另存）.

        M54: max_chars 可覆盖默认预算（模型窗口感知压缩）；None = 运行时预算（零回归）。
        P1-10: 窗口锚定——按 provider 固定历史起点（只追加不挤旧, 超预算优先降级中段),
        前缀稳定命中引擎/服务端缓存; 锚点写入 sess.history_anchors 随会话持久化。
        """
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
        base = list(sess.messages)
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
        # P0-B2（2026-08-28 批准）: 程序反馈投影语义标记——历史中的程序反馈 assistant
        # 消息（错误/熔断/守卫/耗尽文本）投影时加前缀，防下轮模型误读为"assistant
        # 已回答过"（恢复链语义污染治理）。前缀判定同时覆盖 B1 落库前存量（source
        # 仍为 USER 的历史错误消息）；存储原文不动，仅提交视图（同遥测剥离模式）。
        from dataclasses import replace

        from llm_loop.feedback.honesty import PROGRAM_FEEDBACK_PREFIXES

        # GPT 审计批次2: answer_origin 优先（保存点写入的单一真相源），prefix 仅 legacy 兜底
        base = [
            (
                replace(m, content=f"[程序反馈·非模型回答] {m.content}")
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
            base = _tool_round_zero_tail(base)
        prefix_len = 0
        # RULE-AI-14 协调通道: 程序级自动注入 DSH→LFL 待处理消息（每轮 run 必感知，
        # 非仅提示词引导；实现见 core/loop/interop.py _InteropMixin，fail-open）
        # 注入位置: memory 之后、历史之前（2026-08-16 优化: system_prompt+memory 前缀
        # 有/无消息轮字节级一致，服务端缓存命中不受 inbox 影响）
        base, prefix_len = self._inject_interop_messages(base, prefix_len, sess.session_id)
        # EVO-20260817-72fcd94a L3 发送前门禁·预检（程序常态锚点管理）: 稳定段指纹
        # （system+注入）与该 session 基线不符 → 强制缓存友好压缩，当次 build 即合规化。fail-open。
        try:
            self._cache_gate_stable_fp = stable_digest(
                [(m.role, m.content) for m in base[:prefix_len]] + [system_prompt]
            )
            self._cache_monitor.preflight(sess.session_id, self._cache_gate_stable_fp)
        except Exception:  # noqa: BLE001
            self._cache_gate_stable_fp = ""
        # EVO-20260811-9ccdec97: 会话状态快照节流——每间隔注入状态帧（定位锚点，fail-open）
        # M58 配置面收敛: 间隔走 runtime（动态优先，AI 可调）
        # P1-10: 仅无锚时注入（锚定后快照为推送式注入（已打标被跳过提交）, 且避免锚点换算复杂化）
        # EVO-20260818-8c8791c2: 快照【尾部追加】而非 insert(0)——前缀区只留 system+稳定历史头，
        # 快照内容（消息数/记忆数/演进摘要）每轮变化，驻留前缀区即每轮断前缀（gate_drift_count=12
        # 实证，命中 17%↔98% 间歇）；尾部追加后变化只影响尾部新增段，前缀字节稳定（对齐 memory/interop）
        if sess_anchor == 0:
            try:
                interval = self._runtime_extract_interval()
                if len(sess.messages) - self._last_snapshot_count >= interval:
                    evo_summary = None
                    if self.evolution_store is not None and hasattr(
                        self.evolution_store, "summary"
                    ):
                        try:
                            s = self.evolution_store.summary()
                            evo_summary = s if isinstance(s, dict) else None
                        except Exception:
                            evo_summary = None
                    # EVO-20260818: 函数内延迟 import（engine 已加载，防顶层循环；修复
                    # 基线 NameError——原无任何 import，快照注入从未生效（被 fail-open 吞掉））
                    from llm_loop.core.loop.engine import build_session_snapshot_text

                    snapshot = Message(
                        role="system",
                        content=build_session_snapshot_text(
                            len(sess.messages), self.memory.count(), evo_summary
                        ),
                        source=MessageSource.SYSTEM,
                        metadata={
                            "injected_system": True
                        },  # P1-7: 快照=推送式注入（本地 provider 下不进提交）
                    )
                    base.append(
                        snapshot
                    )  # EVO-20260818-8c8791c2: 尾部追加（原 insert(0) 驻留前缀区断前缀）
                    # prefix_len 不再 +1（快照不进前缀区——稳定段指纹 base[:prefix_len] 不含动态内容）
                    self._last_snapshot_count = len(sess.messages)
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "会话状态快照注入失败（fail-open）", exc_info=True
                )
        from llm_loop.core.history import build_history_messages

        archive_sink = None
        if self.archive is not None or getattr(
            self.registry, "evidence_history_capture_enabled", False
        ):
            archive_sink = self._archive_sink
        # R1: 存构建中间值，供主循环在 tools_param 构造后计算 breakdown（含 tool_schema_chars）
        effective_budget = max_chars if max_chars is not None else self._runtime_history_budget()
        self._last_build_info = {
            "base": base,
            "system_prompt": system_prompt,
            "memory_msgs": memory_msgs,
            "budget": effective_budget,
        }
        # EVO-20260817: 预算分级管理——①80% 准备态（审计提示，不压缩）:
        # 长任务大几率撞顶，接近预算时让 AI 感知"下轮可能主动整理压缩"（压缩仍保留
        # 关键事实帧+档案零丢失，不打断推理）；②90% 压缩态（compact_ratio, env 可调）:
        # 预算附近提前平滑压缩（裁到 COMPRESS_TARGET_RATIO 留缓冲），优于撞顶被动压缩。
        try:
            _history_total = _provider_visible_chars(sess.messages, provider_id, sess_anchor)
            _compact_ratio = float(os.environ.get("COMPACT_RATIO", "0.9"))
            if 0 < _compact_ratio < 1.0:
                # EVO-20260824-54d46549 增长率 nudge（billion-context 拷问产出, 双轨）:
                # - 强制轨: 超预算×compact_ratio（90% 默认）→ 必预警（压缩在即, bypass 增长率）
                # - 增长率轨: 80% 准备态 → 距上次预警增长 ≥ 阈值（预算×5% 或 20K 字符）才预警
                #   （重任务增长快早提示, 普通对话增长慢不打扰——替换原固定 80% 每轮必警）
                _force_at = effective_budget * _compact_ratio
                _prep_at = effective_budget * 0.8
                _growth_floor = max(
                    int(effective_budget * 0.05),
                    int(os.environ.get("NUDGE_GROWTH_CHARS", "20000")),
                )
                _prev_total = getattr(self, "_last_nudge_total", None)
                _kind = _growth_nudge_kind(
                    _history_total,
                    _prev_total,
                    prep_at=_prep_at,
                    force_at=_force_at,
                    growth_floor=_growth_floor,
                )
                if _kind == "force":
                    self._record_action(
                        "understand.compact_prep",
                        "approaching_budget",
                        f"history {_history_total} 字符 超预算×{_compact_ratio}（{int(_force_at)}），"
                        f"本轮/下轮触发主动压缩整理；压缩保留关键事实帧+档案零丢失，不影响推理",
                    )
                    self._last_nudge_total = _history_total
                elif _kind == "growth" and _prev_total is not None:
                    _growth = _history_total - int(_prev_total)
                    self._record_action(
                        "understand.compact_prep",
                        "growth_nudge",
                        f"history {_history_total} 字符 ≥预算 80%（{int(_prep_at)}），"
                        f"距上次预警增长 {_growth} ≥ {_growth_floor}（增长率门控触发）——"
                        f"下一轮可能在 {int(_force_at)} 触发主动压缩整理；"
                        "压缩保留关键事实帧+档案零丢失，不影响推理",
                    )
                    self._last_nudge_total = _history_total
        except Exception:  # noqa: BLE001
            _compact_ratio = 1.0
        self._last_compact_ratio = _compact_ratio
        # EVO-20260824-54d46549 渐进折叠配置（env, 默认关零回归）: PROGRESSIVE_FOLD_K>0 时
        # 压缩改为"每次最多折最老 K 个配对组"（平滑曲线 + guard 不 BLOCK + 智力无断崖）
        _progressive_fold_k = int(os.environ.get("PROGRESSIVE_FOLD_K", "0"))
        # P1-10: 锚点相对传入列表 = 会话锚点 + 前置（memory/快照）长度
        anchor_arg = sess_anchor + prefix_len if sess_anchor > 0 else 0
        anchor_box: list[int] = []
        compacted_box: list[bool] = []
        cache_compacted_box: list[Message] = []
        compact_view_box: list[dict] = []
        degrade_box: list[dict] = []
        built = build_history_messages(
            base,
            system_prompt,
            max_chars=max_chars if max_chars is not None else self._runtime_history_budget(),
            compact_ratio=self._last_compact_ratio,  # EVO-20260817: 预算分级主动压缩
            session_id=sess.session_id,
            archive_sink=archive_sink,
            # RULE-AI-00: 不再传 summarizer（压缩路径不自动 LLM 摘要，AI 主动触发）
            layer_tool_trim=getattr(
                self.settings, "tool_trim_enabled", False
            ),  # EVO-20260811-7baa2737: 历史分层降级
            tool_trim_age=getattr(self.settings, "tool_trim_age", 0),  # R3: 0=自适应
            tool_trim_threshold=getattr(
                self.settings, "tool_trim_threshold", 8000
            ),  # EVO-A: 降级长度阈值（默认 8000）
            # 2026-08-20 回滚修复: 移除悬空 tool_tail 参数——history.py 的
            # build_history_messages() 不接受该参数（3点基线无此功能，config 恒为 0），
            # 回滚后每次对话 TypeError；参数支持在 backup/20260819-after-3am 分支
            reasoning_tail=getattr(self.settings, "reasoning_tail", 0),  # M66 思考链瘦身（T-P0-1-1 默认 0=全保留）
            # P1-7/spec §5.3.1-5（2026-08-18 审计断点归因绝对化）: 推送式注入（架构上报/
            # 预算预警/轮数预警/声明提醒/自我评估提醒/快照）一律不进提交视图——不再受
            # provider inject_system_notices 开关影响（原按 provider 放行 → 注入消息转 user
            # 后仍插历史中部 → 前缀断）。AI 感知走 architecture_status 等工具，不依赖注入。
            skip_injected_system=True,
            # P1-10: 窗口锚定
            history_anchor=anchor_arg,
            anchor_out=anchor_box,
            compacted_out=compacted_box,
            # EVO-20260817-9d3e1f2c: 缓存友好压缩——保留锚点头部（前缀命中）只归档中段;
            # EVO-20260818: HEAD_KEEP_RATIO 默认 0.10→0.15；2026-08-25 DeepSeek 生产实测
            # 中段分叉只有“曾作为完整请求端点”的 fixed-head 能稳定复用，因此 DeepSeek
            # 默认提高到 effective budget 的 0.35（其它 provider 仍 0.15）。配合压缩目标
            # 0.5，相当于 fixed-head 最多约占压缩后历史水位 70%，同时保留最近尾部语义。
            # 生产等价直连实测：300K→150K 视图首次压缩命中 71.1%（不含工具schema固定
            # 前缀）；0.30/0.65 档仅57.2%。force 档位 DeepSeek 默认 0.40 / 其它 provider
            # 0.20（L3 拦截强制保留——须高于常规档位，
            # max() 两侧同值会吞掉强制语义，grill-me 2.10）; 0=关闭回到锚点前移行为；env 可调
            # emergency_compact（M53 拒绝逃生）: 强制 head_keep=0——head 保留时锚点不前移
            # （history.py），超限会话历史永不缩小 → 拒绝死循环；锚点前移归档才真正缩小
            # 2026-08-25 中段压缩: progressive fold 重新允许 head_keep。被折中段写入
            # provider级 cache_compacted_for 标记，后续 build 自动过滤，所以无需靠锚点
            # 前移来防重复归档；压缩轮缓存断点从序列开头推到固定头部之后。
            head_keep_chars=(
                0  # emergency_compact 仍保留从头推进的最终逃生语义
                if emergency_compact
                else max(
                    int(
                        effective_budget
                        * float(
                            os.environ.get(
                                "HEAD_KEEP_RATIO", "0.35" if provider_id == "deepseek" else "0.15"
                            )
                        )
                    ),
                    int(
                        effective_budget
                        * float(
                            os.environ.get(
                                "HEAD_KEEP_FORCE_RATIO",
                                "0.40" if provider_id == "deepseek" else "0.20",
                            )
                        )
                    )
                    if self._cache_monitor.force_head_keep
                    else 0,
                )
            ),
            # fixed-head 占压缩目标水位上限。历史层默认 0.50 保持旧行为；DeepSeek 提到
            # 0.70，允许 0.35×effective_budget 的 head 真正留下（target=.5 时占70%），
            # 仍给最近 tail 约30%目标水位；原子组边界会自然留出更多。env 可显式覆盖调参。
            head_keep_target_ratio=float(
                os.environ.get(
                    "HEAD_KEEP_TARGET_RATIO", "0.70" if provider_id == "deepseek" else "0.50"
                )
            ),
            # 2026-08-21 追加式压缩: 归档后追加确定性摘要（APPEND_COMPRESSION=1 启用,
            # 默认关零回归）——任务语义连贯 + 前缀稳定（同归档→同摘要字节→缓存命中）
            _append_summary_enabled=os.environ.get("APPEND_COMPRESSION", "0") == "1",
            # EVO-20260824-54d46549 渐进折叠: PROGRESSIVE_FOLD_K>0 时压缩每次最多折最老 K 个
            # 配对组（平滑曲线 + guard 不 BLOCK + 智力无断崖）；0=一次性大裁（零回归）
            progressive_fold=_progressive_fold_k,
            # P0 压缩风暴熔断冻结（2026-08-25）: 冻结期禁压缩/禁锚点前移（前缀字节稳定）
            freeze_compression=self._cache_monitor.breaker_freeze_compression(
                sess.session_id
            ),
            cache_archive_provider=provider_id,
            cache_compacted_out=cache_compacted_box,
            compact_view_stats=compact_view_box,
            degrade_out=degrade_box,
            require_archive_success=getattr(self.registry, "evidence_mode", "off") == "enforce",
        )
        for _compacted_msg in cache_compacted_box:
            _msg_seq = self._resolve_msg_seq(sess.session_id, _compacted_msg)
            if _msg_seq is None:
                logger.warning(
                    "provider中段压缩事件未定位消息序号: sid=%s provider=%s",
                    sess.session_id,
                    provider_id,
                )
                continue
            self._event_append(
                sess.session_id,
                "message.cache_compacted",
                {"msg_seq": _msg_seq, "provider_id": provider_id},
            )
        self._last_history_compacted = bool(compacted_box and compacted_box[0])
        # err1210 T4.1: compact 事件序列号——False→True 转变递增（per-session × per-compact-事件
        # 耗尽标记的"事件标识"，engine 侧 _err1210_attempted 据此判定新事件清除旧标记）
        if self._last_history_compacted and not getattr(self, "_compact_event_was_compacted", False):
            self._compact_event_seq = getattr(self, "_compact_event_seq", 0) + 1
        self._compact_event_was_compacted = self._last_history_compacted
        # EVO-20260825 任务6.2: 压缩后视图体积验证——drop<5%（压缩但视图几乎没缩小）
        # → breaker 审计事件 view_not_shrinking_after_compact（压缩风暴前兆归因）
        if compact_view_box:
            try:
                _stats = compact_view_box[0]
                if _stats.get("drop_pct", 0) < 5:
                    self._cache_monitor.note_view_not_shrinking(
                        pre_chars=_stats["pre_chars"],
                        post_chars=_stats["post_chars"],
                        drop_pct=_stats["drop_pct"],
                        session_id=sess.session_id,
                        model_ref=resolved_label,
                    )
            except Exception:  # noqa: BLE001 — fail-open
                logger.debug("view_not_shrinking 审计注入异常（fail-open）", exc_info=True)
        # EVO-20260825 任务7（§5.7）: 渐进折叠 archive_provider 缺失降级——审计 +
        # 降级提示注入 metadata.cache_health（kind="degraded"，_post_run_cache_health 回写）
        if degrade_box:
            try:
                _deg = degrade_box[0]
                self._cache_monitor.note_degraded(
                    reason=_deg.get("reason", "progressive_fold 要求 cache_archive_provider"),
                    head_keep_chars=_deg.get("head_keep_chars", 0),
                    session_id=sess.session_id,
                    model_ref=resolved_label,
                )
                self._cache_degrade_note = (
                    f"[渐进折叠降级] {_deg.get('reason')}——已关闭渐进折叠，"
                    f"head_keep 预算 {_deg.get('head_keep_chars')} 字符"
                )
            except Exception:  # noqa: BLE001 — fail-open
                logger.debug("archive_provider 降级注入异常（fail-open）", exc_info=True)
        # P1-10: 锚点推进持久化（换算回会话索引, clamp 防御）
        _anchor_moved_this_build = False
        if anchor_box:
            new_anchor = anchor_box[0] - prefix_len
            new_anchor = max(0, min(len(sess.messages), new_anchor))
            # EVO-20260817-72fcd94a L3 归因: 锚点实际前移（≠旧锚点）→ 记入缓存失效归因窗口
            if new_anchor != sess_anchor:
                self._cache_monitor.note_anchor_moved(session_id=sess.session_id)
                _anchor_moved_this_build = True
            # 2026-08-16 锚点推进对齐工具轮边界（现场：tool_call_id is not found 根因）：
            # 锚点不得落在声明↔回执组内——若锚点处是 tool 回执（其声明在锚点前），
            # 拉回至该轮声明起点（整组保留，防孤儿回执）。
            while 0 < new_anchor < len(sess.messages) and sess.messages[new_anchor].role == "tool":
                new_anchor -= 1
            if sess.history_anchors is None:
                sess.history_anchors = {}
            sess.history_anchors[provider_id] = new_anchor
        # P0 压缩风暴熔断（2026-08-25）: 每轮 build 结果通知 monitor——
        # 连续 (compacted 且 anchor_moved) 计数 → 达阈值进入 breaker（冻结压缩+锚点）。
        # chars_total 用锚定视图口径（实际提交量——锚点压缩只前移锚点不删 sess.messages，
        # 全量口径会让压力永不解除）。
        try:
            _view_start = min(sess_anchor, len(sess.messages))
            self._cache_monitor.note_build_result(
                compacted=self._last_history_compacted,
                anchor_moved=_anchor_moved_this_build,
                chars_total=_provider_visible_chars(
                    sess.messages, provider_id, _view_start
                ),
                budget=effective_budget,
                session_id=sess.session_id,
                model_ref=resolved_label,
            )
        except Exception:  # noqa: BLE001 — fail-open
            pass
        # ERC Phase5: provider-neutral Recovery Manifest is regenerated from the durable
        # Evidence Ledger on every build and appended in the dynamic tail.  It is never part
        # of the stable system/tools prefix and never relies on the previous build's text.
        _evidence_manifest_content = ""
        try:
            if getattr(self.registry, "evidence_mode", "off") == "enforce":
                _manifest_limit = max(
                    1, min(20, int(getattr(self.settings, "evidence_manifest_limit", 8) or 8))
                )
                _evidence_manifest_content = self.registry.evidence_recovery_manifest(
                    limit=_manifest_limit
                )
                if _evidence_manifest_content:
                    built.append({"role": "user", "content": _evidence_manifest_content})
        except Exception:  # noqa: BLE001 - recovery tools remain available even if tail render fails
            logger.warning("Evidence Recovery Manifest 构建失败（fail-open）", exc_info=True)
            _evidence_manifest_content = ""

        # EVO-20260818（spec §5.3.1-1 c/d，grill-me B1）: interop 外部协调注入——
        # 尾部追加（GATE_NOTE 模式，转 user），system+稳定历史前缀字节不变（注入轮不断前缀）;
        # env INTEROP_INJECT_TAIL=0 回退旧行为（头部插入，见 interop.py）
        # EVO-2026XXXX（spec §5.3.1-1c）: memory 检索注入尾部追加（GATE_NOTE 模式，转 user）——
        # 检索结果随查询变化（top_k 语义/关键词召回），前置注入每轮改变前缀首段 → 前缀断；
        # 尾部追加保持 system+稳定历史前缀字节不变（命中率不因 memory 变化受损）。
        # 2026-08-22 记忆注入统一包装（用户决策）: memory_msgs（[相关记忆]）此前直接
        # 转 user 尾部追加, 无"[上下文注入·非新指令] 继续当前任务"前缀 → AI 误读为
        # 独立消息 → "没有明确任务" → 反复 search 找回（实证 d1192d8c: 健康检查任务
        # 15+ 次 search_archive/search_records 死循环）。与 tail_msgs 同包装机制。
        # EVO-20260827-f42496bc: memory 注入已改为一次性持久化（engine 检索后
        # wrap+append 进 sess.messages，见 engine.py 理解段）——本函数不再追加
        # 动态 memory 段：历史投影自然带出持久化注入（存储字节稳定，下轮前缀
        # 命中不断崖）。此前每轮在此重新包装追加（含动态 anchor），下一轮真实
        # 回复顶替注入位置 → 前缀字节分叉 → provider 前缀缓存全断（断崖根因）。
        # memory_msgs 参数保留（签名兼容 + fail-open 路径: engine 持久化异常时
        # 仍可走旧动态注入，见下方 fallback 判断）。
        # EVO-20260827-ed4c1350: turn 快照注入位于 turn 入口（会话前部），多轮后
        # 尾部 8 条不再包含它——检查升级为 turn_ref 身份匹配（本 turn 已持久化
        # 即视为成功）；无 turn 上下文（旧会话/直调 build）回退旧尾部检查（零回归）。
        _turn_ref = getattr(self, "_current_turn_ref", None)
        if _turn_ref is not None:
            _persisted_ok = any(
                (getattr(_m, "metadata", None) or {}).get("turn_ref") == _turn_ref
                and (getattr(_m, "metadata", None) or {}).get("injection_kind")
                == "memory_snapshot"
                for _m in sess.messages
            )
        else:
            _persisted_ok = any(
                getattr(_m, "metadata", None)
                and _m.metadata.get("persisted_injection")
                for _m in sess.messages[-8:]
            )
        _inject_parts: list[tuple[str | None, str]] = []  # (slot|None=hint, content)——P1 9.1 聚合收集
        if not _persisted_ok and memory_msgs:
            # fail-open 回退: 持久化失败（engine 异常路径）→ 兜底收集进聚合
            # （P1 9.1: 旧独立 wrap+append 撤销——保尾部连续 user ≤1；memory 非消费槽）
            for _m in memory_msgs:
                _c = str(_m.to_llm_dict().get("content") or "")
                if _c:
                    _inject_parts.append(("memory", _c))
        tail_msgs = getattr(self, "_interop_tail_messages", None)
        _interop_orig = tail_msgs  # err1210 T4.1: 身份匹配用（区分 interop/tip/local 提示）
        # EVO-20260819-7bb7d689: 经验提示尾部追加槽并入统一消费（与 interop 同机制）——
        # 不进历史存储，build 末尾一次性追加（转 user），system+稳定历史前缀字节不变
        tip_msgs = getattr(self, "_tip_tail_messages", None)
        _tip_orig = tip_msgs
        if tip_msgs:
            tail_msgs = (tail_msgs or []) + tip_msgs
        # 2026-08-23 任务1（本地模型行为增强，镜像区同步）: local 轮固定尾部追加轻量行为提示。
        # 内容=给动作/给默认规则/引用代号带证据（对治评测三短板）；走 tail 统一通道
        # （转 user + 非新指令包装，tail_msgs 已纳入投影指纹不破坏一致性），尾部追加
        # 缓存友好（system+稳定历史前缀字节不变）。
        if provider_id == "local":
            tail_msgs = (tail_msgs or []) + [
                Message(
                    role="system",
                    content=(
                        "本地模型行为提示：①回答给'你可以这样做'的具体动作，不只说态度；"
                        "②边界模糊时主动声明默认规则（改≤3文件自主执行、>3或涉生产先列方案等你确认）；"
                        "③引用代号(M22/r4等)须附一句话证据；④不确定先 search_records/search_archive 检索再答。"
                    ),
                    source=MessageSource.SYSTEM,
                )
            ]
        # ── P1 尾部注入聚合（err1210 8.4 Verdict: STRUCTURE_TRIGGER 尾部连续 user 条数，
        # tasks 9.1 方案 A）：四槽产物合并单条 user（--- [slot:xxx] --- 分段标记保留语义），
        # wrap_injection 只包装一次、anchor 单份——build 尾部连续 user 条数恒 ≤1，
        # compact 首请求 1210 结构性消除（merge 变体双样本生产验证）。
        for _m in tail_msgs or []:
            _d = _m.to_llm_dict()
            if _d.get("role") == "system":
                _d["role"] = "user"  # system 静态: 转独立 user 尾部追加
                _c = str(_d.get("content") or "")
                if _c:
                    _d["content"] = _c
            _slot = None
            if _interop_orig and any(_m is _x for _x in _interop_orig):
                _slot = SlotKind.INTEROP
            elif _tip_orig and any(_m is _x for _x in _tip_orig):
                _slot = SlotKind.TIP
            _inject_parts.append((_slot, str(_d.get("content") or "")))
        # err1210 T4.1→9.1: defer 回填消息消费检测（is 身份匹配，聚合收尾统一处理）
        _refs = getattr(self, "_deferred_replay_refs", None) or []
        if _refs and tail_msgs:
            _consumed_ids = {id(_m) for _m in tail_msgs}
            _kept = [
                (_r_slot, _r_ref)
                for _r_slot, _r_ref in _refs
                if not (
                    id(_r_ref) in _consumed_ids
                    and self._note_defer_replayed(sess.session_id, _r_slot)
                )
            ]
            self._deferred_replay_refs = _kept
        self._interop_tail_messages = None  # 一次性消费（每轮重扫 pending）
        self._tip_tail_messages = None  # 经验提示同机制一次性消费（下轮工具执行再注入）
        # EVO-20260826-81f8f674: 任务接力热卡注入——压缩时刻写的热卡在新会话 build 时
        # 取出注入（仅跨会话未消费；pop 即标记 consumed 防陈旧卡反复注入；尾部追加
        # 不破坏前缀缓存；fail-open 绝不阻断构建）。冲突语义: RULE-AI-20 第 7 条兜底。
        try:
            _hotcard_text = pop_hotcard(
                session_id=sess.session_id, data_dir=self.settings.data_dir
            )
            if _hotcard_text:
                # P1 聚合（9.1）: 收集原文，wrap 延后到统一聚合器（原独立 wrap+append 撤销）
                _inject_parts.append((SlotKind.HOTCARD, _hotcard_text))
                # err1210 T4.1: hotcard defer 重注入检测
                _slots = getattr(self, "_deferred_replay_slots", None) or set()
                if str(SlotKind.HOTCARD) in _slots:
                    self._note_defer_replayed(sess.session_id, SlotKind.HOTCARD)
                    _slots.discard(str(SlotKind.HOTCARD))
                    self._deferred_replay_slots = _slots
        except Exception:  # noqa: BLE001 — fail-open
            pass
        # EVO-20260817-72fcd94a: 门禁干预知情标记——干预激活首轮在 built 末尾追加固定
        # user 消息（末尾追加缓存友好，不破坏前缀；转 user 避免守卫规则 B 误报
        # "非首位 system"——2026-08-18 审计 WARN 实证；让 AI 感知上下文结构变化）
        if self._cache_monitor.take_gate_note(session_id=sess.session_id):
            # P1 聚合（9.1）: 收集固定文本（wrap 延后到统一聚合器）
            _inject_parts.append((SlotKind.GATE_NOTE, GATE_NOTE_CONTENT))
            _slots = getattr(self, "_deferred_replay_slots", None) or set()
            if str(SlotKind.GATE_NOTE) in _slots:
                self._note_defer_replayed(sess.session_id, SlotKind.GATE_NOTE)
                _slots.discard(str(SlotKind.GATE_NOTE))
                self._deferred_replay_slots = _slots
        # ── P1 统一聚合器（9.1）: 四槽 parts → 单条 user；sidecar 单 AGGREGATED entry ──
        # 尾部连续 user 恒 ≤1（1210 结构性消除）；聚合失败 fail-open 降级零注入（不阻断构建）
        # Cognitive Runtime（tasks 2.3/2.5/2.6，spec 5.2/5.1.1-3b）:
        # - COG_RUNTIME_TIER_ENABLED 原子切换 tier 分级聚合（在 T1 单管线之上叠加，不新建
        #   第二条聚合管线；=0 回退平铺原行为零回归，spec 5.2.3-1）
        # - COG_RUNTIME_ANCHOR_MODE 三态: semantic=投影替代锚点 / anchor=旧行为 / auto=投影
        #   可用则替代否则回退（design 2.1.3.4 冻结点④）；投影=wrap_injection 的 anchor 位
        #   前导（决策包 HOT 首行，落在尾部聚合条内，不插前缀区——design 1.2.4 缓存约束）
        # - COG_RUNTIME_DUAL_SOURCE_GUARD: 检测锚点与投影同轮并存 → 告警剔除锚点（fail-open）
        # CR-R1（tasks 3.2）: enforce+semantic/auto 时空 slots 亦进块——header-only 注入
        # （零注入安静轮 decision_visible=True，不变量⑤）；其余模式无 parts 不造空条。
        _cog_sem_candidate = (
            str(getattr(self.settings, "cog_runtime_mode", "shadow")).strip().lower()
            == "enforce"
            and str(getattr(self.settings, "cog_runtime_anchor_mode", "auto"))
            in ("semantic", "auto")
        )
        if _inject_parts or _cog_sem_candidate:
            try:
                _anchor_mode = str(getattr(self.settings, "cog_runtime_anchor_mode", "auto"))
                _tier_on = bool(getattr(self.settings, "cog_runtime_tier_enabled", True))
                # CR-R1（tasks 2.2）: COG_RUNTIME_MODE 三态——off/shadow 时 cognitive
                # 不进 prompt（anchor+平铺旧行为；shadow 保留构造计算供 telemetry，
                # 任务 6.2 接线打点）；enforce 时按 ANCHOR_MODE/TIER_ENABLED 现行语义进 prompt。
                _cog_mode = str(getattr(self.settings, "cog_runtime_mode", "shadow")).strip().lower()
                if _cog_mode not in ("off", "shadow", "enforce"):
                    _cog_mode = "shadow"
                if _cog_mode != "enforce":
                    _anchor_mode = "anchor"
                    _tier_on = False
                _sem_state = None
                _env = None  # CR-R1.1: 预初始化——load 失败时 Barrier 仍走 GoalStore 重建
                _projection = ""
                # CR-R1.1（审查项1）: 认知运行时会话身份与任务锚点解耦——anchor_sess
                # 是 Session 对象（build_task_anchor 专用），Cognitive 路径全部使用
                # sess.session_id 字符串。此前混用导致 StateStore 分片对 Session 对象
                # 切片 TypeError 被 fail-open 吞掉、语义投影静默消失（enforce 下
                # Semantic Header 实际不工作）。
                _cog_sid = str(getattr(sess, "session_id", "") or "")
                if _anchor_mode in ("semantic", "auto") and SemanticStateStore is not None:
                    try:
                        _env = SemanticStateStore(
                            os.path.join(self.settings.data_dir, "audit")
                        ).load(_cog_sid)
                        # CR-R1（tasks 1.2）：schema v2 三态解包——仅可信信封且无墓碑
                        # 才投影；STALE_UNTRUSTED/None/墓碑 → 不注入（宁缺勿错，spec 3.2-1）
                        _sem_state = (
                            _env.state
                            if StateEnvelope is not None
                            and isinstance(_env, StateEnvelope)
                            and _env.tombstone is None
                            else None
                        )
                    except Exception:  # noqa: BLE001 — 状态读取 fail-open → 回退 anchor
                        _sem_state = None
                    # CR-R1（tasks 3.1）+ CR-R1.1（审查项4）: Read Barrier——信封与
                    # GoalStore 严格会话读的一致性核验，三路统一：
                    #   信封在场且 identity 匹配 → 直接用；
                    #   信封 mismatch/缺失/STALE_UNTRUSTED → strict 读 GoalStore：
                    #     能安全确认 goal → rebuild+回存（envelope 缺失不再等 compact
                    #     触发 _persist_semantic_state——冷启动首轮即建 header）；
                    #   goal 缺失/终态/异常 → 宁缺勿错置 None（header 不注入）。
                    # "没有 envelope"本身不是"不可信"——GoalStore 无法安全确定当前
                    # Goal 才是不可信（审查报告 §4）。墓碑防复活由三态解包
                    # （_sem_state=None）+ rebuild_state(终态)→None 双层保障。
                    if (
                        StateEnvelope is not None
                        and rebuild_state is not None
                    ):
                        _env_candidate = (
                            _env if isinstance(_env, StateEnvelope) else None
                        )
                        try:
                            from llm_loop.introspection.goal import GoalStore

                            _goal = GoalStore(
                                os.path.join(self.settings.data_dir, "audit")
                            ).get(prefer_session_id=_cog_sid, strict_session=True)
                            if (
                                _env_candidate is not None
                                and _goal
                                and _goal.get("id")
                                and _env_candidate.identity.matches(_goal)
                            ):
                                pass  # 一致：信封可信，直接用
                            elif _goal and _goal.get("id"):
                                _rb = rebuild_state(_goal)  # 重建（终态→None 防复活）
                                if _rb is None:
                                    _sem_state = None  # goal 已终态：投影不可用
                                else:
                                    _cps = _goal.get("checkpoints") or [{}]
                                    # CR-R1.1（审查项11）: state_revision 单调继承——
                                    # 在场 mismatch → old+1；缺失/STALE 首建 → 1。
                                    _prev_rev = (
                                        _env_candidate.identity.state_revision
                                        if _env_candidate is not None
                                        else 0
                                    )
                                    _env = StateEnvelope(
                                        identity=StateIdentity(
                                            session_id=_cog_sid,
                                            goal_id=str(_goal.get("id", "")),
                                            goal_updated_at=str(_goal.get("updated_at", "")),
                                            checkpoint_ts=str((_cps[-1] or {}).get("ts", "")),
                                            state_revision=_prev_rev + 1,
                                        ),
                                        state=_rb,
                                    )
                                    SemanticStateStore(
                                        os.path.join(self.settings.data_dir, "audit")
                                    ).save(_cog_sid, _env)
                                    _sem_state = _rb
                                    logger.info(  # telemetry(state_rebuild)（tasks 6.2 接线）
                                        "build: Read Barrier 不一致→重建语义状态并回存 goal=%s",
                                        _goal.get("id"),
                                    )
                                    if emit_cognitive_event is not None:  # CR-R1 6.2
                                        emit_cognitive_event(
                                            "state_rebuild",
                                            data_dir=self.settings.data_dir,
                                            session_id=_cog_sid,
                                            goal_id=str(_goal.get("id", "")),
                                        )
                            else:
                                _sem_state = None  # goal 缺失→宁缺勿错（header=None）
                        except Exception:  # noqa: BLE001 — Barrier fail-open：宁缺勿错
                            _sem_state = None
                            logger.debug(
                                "build: Read Barrier 核验异常，fail-open 降级无投影",
                                exc_info=True,
                            )
                    if _sem_state is not None and semantic_projection is not None:
                        _projection = semantic_projection(_sem_state)
                _anchor = build_task_anchor(self._focus.anchor_sess)
                if _projection:
                    if _anchor and bool(
                        getattr(self.settings, "cog_runtime_dual_source_guard", True)
                    ):
                        logger.warning(
                            "build: 锚点与投影同轮并存，fail-open 剔除锚点（DUAL_SOURCE_GUARD）"
                        )
                    _anchor = _projection  # 投影替代锚点（演进不并存，spec 5.2.1-7）
                elif _anchor_mode == "semantic":
                    _anchor = ""  # semantic 严格态: 语义不可用不回退锚点（可观测零指针）
                # CR-R1（tasks 3.2）: packet 组装重构——header 先行（Barrier 通过即含投影
                # 前导），空 slots 不抑制 header；header+slots 合并单条聚合条（header 在前，
                # 沿 P1 形态）；header 已含投影 → anchor 位不重复注入（tier 关时投影仍占
                # anchor 位，旧行为保留）。
                _packet = (
                    compile_decision_packet(
                        _inject_parts,
                        _sem_state,
                        # CR-R1 4.2: 生产预算接线——超上界降级仅 HOT（compiler degraded
                        # 路径生产可达，不变量⑧）
                        budget_chars=int(
                            getattr(self.settings, "cog_runtime_packet_budget", 2000)
                        ),
                    )
                    if _tier_on and compile_decision_packet is not None
                    else None
                )
                if _packet is not None:
                    _agg = _packet.render()  # header 在前 + tier 槽位（空 slots→header-only）
                    _agg_anchor = _anchor if not _packet.render_header() else ""
                    if emit_cognitive_event is not None:  # CR-R1 6.2: packet_compile/tier_degraded
                        _tier_of = lambda _s: str(getattr(getattr(_s, "tier", None), "value", ""))  # noqa: E731
                        _hot_chars = sum(
                            len(getattr(_s, "content", "") or "")
                            for _s in _packet.slots
                            if _tier_of(_s) == "hot"
                        )
                        _warm_chars = sum(
                            len(getattr(_s, "compact_repr", "") or "")
                            for _s in _packet.slots
                            if _tier_of(_s) == "warm"
                        )
                        _cold_n = sum(1 for _s in _packet.slots if _tier_of(_s) == "cold")
                        _evt = dict(
                            data_dir=self.settings.data_dir,
                            session_id=_cog_sid,
                            goal_id=str(
                                getattr(getattr(_sem_state, "identity", None), "goal_id", "")
                                or ""
                            ),
                            hot_tokens=_hot_chars // 4,
                            warm_tokens=_warm_chars // 4,
                            cold_ref_count=_cold_n,
                            packet_tokens=len(_agg) // 4,
                            mode=str(getattr(self.settings, "cog_runtime_mode", "")),
                        )
                        emit_cognitive_event("packet_compile", **_evt)
                        if getattr(_packet, "degraded", False):
                            emit_cognitive_event("tier_degraded", **_evt)
                else:
                    _agg = "\n\n".join(
                        f"--- [slot:{s if s else 'hint'}] ---\n{c}"
                        for s, c in _inject_parts
                    )
                    _agg_anchor = _anchor  # 平铺路径：投影/锚点经 anchor 位（旧行为）
                if _agg.strip():
                    _agg_content = wrap_injection(_agg, _agg_anchor)
                    built.append({"role": "user", "content": _agg_content})
                    # err1210 9.1: 聚合登记（单 entry；strip/defer 消费端经 AGGREGATED 分支）
                    self._last_build_injections.append(
                        InjectedEntry(
                            msg_idx=len(built) - 1,
                            slot_kind=SlotKind.AGGREGATED,
                            prefix_sha=content_prefix_sha(_agg_content),
                            message_ref=None,
                        )
                    )
                # 空 slots 且无 header：安静轮零注入（不造空条、不登记）
            except Exception:  # noqa: BLE001 — 聚合失败 fail-open（零注入降级 + WARN）
                logger.warning(
                    "build: 尾部注入聚合失败，本轮零注入降级（fail-open）", exc_info=True
                )
        # EVO-20260817-b6554376: 投影一致性门闸（借鉴 DSH seq 水印，fail-open 不阻断 run）
        # seq（消息数）负责"历史追加"水印；ver（构建参数+动态输入指纹）负责参数水印；
        # ver+seq 匹配而 built_hash 不同 → 非确定性构建/历史被改 → 告警（只读，不阻断）。
        try:
            _fp = lambda msgs: stable_digest([(m.role, m.content) for m in msgs])  # noqa: E731
            _settings_fp = stable_digest(
                {
                    "tool_trim_enabled": getattr(self.settings, "tool_trim_enabled", False),
                    "tool_trim_age": getattr(self.settings, "tool_trim_age", 0),
                    "tool_trim_threshold": getattr(self.settings, "tool_trim_threshold", 8000),
                    "tool_tail": getattr(
                        self.settings, "tool_tail", 0
                    ),  # EVO-20260818-f675796c: tail 窗口
                    "reasoning_tail": getattr(self.settings, "reasoning_tail", 0),
                    "skip_injected_system": True,  # spec §5.3.1-5: 推送式注入一律不进提交
                    "extract_interval_msgs": getattr(self.settings, "extract_interval_msgs", 20),
                    # Phase5: manifest changes are legitimate projection changes, not nondeterminism.
                    "evidence_manifest_fp": stable_digest(_evidence_manifest_content),
                }
            )
            # EVO-20260818: interop 尾部追加后 base[:prefix_len] 仅 memory 段——
            # interop_fp 改为对注入消息指纹（tail 模式）或 memory+inbox 段（旧模式），
            # 保证 ver 与 built 中的尾部注入内容一致（投影一致性不误报）
            _interop_for_fp = tail_msgs if tail_msgs is not None else [m for m in base[:prefix_len]]
            _ver = projection_ver(
                model=resolved_label,
                budget=effective_budget,
                anchor=sess_anchor,
                memory_fp=_fp(memory_msgs),
                interop_fp=stable_digest([(m.role, m.content) for m in _interop_for_fp]),
                system_fp=stable_digest(system_prompt),
                settings_fp=_settings_fp,
            )
            _seq = len(sess.messages)
            # 知情标记剔除: 门闸比较的 built 不含门禁干预注（末尾固定 system 消息）；
            # P1 9.1 聚合后 gate_note 埋入聚合消息（--- [slot:gate_note] --- 段），
            # 含该段的聚合消息整条剔除（近似等价：知情标记不参与投影 hash）
            _c_tail = built[-1].get("content") if built else None
            _built_for_hash = (
                built[:-1]
                if isinstance(_c_tail, str)
                and (
                    _c_tail == GATE_NOTE_CONTENT
                    or "--- [slot:gate_note] ---" in _c_tail
                )
                else built
            )
            _built_hash = stable_digest(_built_for_hash)
            # EVO-20260817: 压缩轮判定——主动/被动压缩归档（built 消息数 < base）属合法
            # 变化（缓存友好压缩锚点不动 → ver 不变但 built 变短），豁免投影 mismatch 误报
            _compressed_this_build = bool(self._last_history_compacted) or len(built) < len(base)
            _guards = sess.projection_guard if sess.projection_guard is not None else {}
            _prev = _guards.get(provider_id)
            _state = projection_check(_prev, ver=_ver, seq=_seq, built_hash=_built_hash)
            self._projection_guard_state = _state
            if _state == "mismatch" and not _compressed_this_build:
                _hint = (
                    f"[投影一致性告警] provider={provider_id} seq={_seq} ver 匹配但构建输出与上次不一致"
                    f"——非确定性构建或历史被改（追加式保证被破坏），前缀缓存可能失效（成本放大 ~50 倍）。"
                    "只读告警，是否处理由你决定。"
                )
                self._record_action("run.projection_guard", "mismatch", _hint)
            # 更新缓存行（mismatch 也更新——保留最近构建作新基准，但已告警过）
            import datetime as _dt

            _guards[provider_id] = {
                "ver": _ver,
                "seq": _seq,
                "built_hash": _built_hash,
                "ts": _dt.datetime.now(_dt.UTC).isoformat(),
            }
            sess.projection_guard = _guards
        except Exception:  # noqa: BLE001 — 门闸失败 fail-open，不阻断 run
            logging.getLogger(__name__).warning("投影一致性门闸异常（fail-open）", exc_info=True)
        # EVO-20260817-72fcd94a L3 发送前门禁·后检（合规再出闸）: 校验稳定段与该 session
        # 基线一致；不一致 → 审计 + hint（run 末注入 final_answer），fail-open 不阻断发送。
        try:
            self._cache_gate_hint = self._cache_monitor.postcheck(
                sess.session_id, self._cache_gate_stable_fp
            )
            if self._cache_gate_hint:
                self._record_action("run.cache_gate", "drift", self._cache_gate_hint)
        except Exception:  # noqa: BLE001 — 门禁失败 fail-open
            self._cache_gate_hint = None
        # EVO-20260817: 压缩产物合规检验（锚点固化模式）——压缩轮审计产物状态:
        # 稳定段指纹（system+注入）不变 → 门禁 preflight/postcheck 自动合规（不误报）;
        # 关键事实帧+档案目录已由 build 注入（AI 持续推理所需信息整理好）;
        # 配对原子性由 _repair_tool_call_pairing 保证。检验通过才出闸（记录 ok）。
        try:
            _compressed = locals().get("_compressed_this_build", False)
            if _compressed:
                _built_chars = sum(len(m.get("content", "")) for m in built)
                _facts_injected = any(
                    isinstance(m, dict)
                    and (
                        "[压缩关键事实]" in m.get("content", "")
                        or "[压缩推理结论]" in m.get("content", "")
                    )
                    for m in built[-8:]
                )
                self._record_action(
                    "run.compact",
                    "ok" if _facts_injected else "warn",
                    f"history {locals().get('_history_total', '?')}→{_built_chars} 字符"
                    f"{'，关键事实帧已注入（推理信息整理完备）' if _facts_injected else '，关键事实帧缺失（告警）'}，"
                    "稳定段未变→门禁合规，投影门闸豁免（压缩属合法变化）",
                )
                # EVO-20260826-81f8f674: 压缩黄金窗口写任务热卡（anchor=最近用户指令+
                # 最近动作；active Goal/checkpoint 与待审演进由 hotcard 模块自取；
                # fail-open 失败仅告警不阻断压缩）
                write_hotcard(
                    origin_session=sess.session_id,
                    anchor=build_task_anchor(self._focus.anchor_sess),
                    data_dir=self.settings.data_dir,
                )
        except Exception:  # noqa: BLE001
            pass
        return built
