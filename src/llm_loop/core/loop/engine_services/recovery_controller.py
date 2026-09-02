"""RecoveryController——err1210 P0 恢复 / defer 回存 / 运行时重试路由（R9 Phase 5 T6-A）.

B5-W1-03 迁入（design :475 改造类引用面）：_Err1210Mixin（err1210.py 14 法）方法体
逐字平移，``self.`` → ``self._host.``（宿主 = LoopEngine，实例态
_err1210_attempted/_last_request_msg_count_by_session 留宿主持有；运行态字段
（deferred_replay_*/err1210_run_seq/auto_continue_1210/program_recovery_tail_message
等）经 ``self._host._run_state()`` per-session 桶读写（B5-W4-03 RunStateManager），
跨面依赖 _record_action/_event_append/_runtime_timeout/_cache_monitor 归宿主）。行为零变化：

- err1210 P0 = 剥离尾部注入 → defer 回存槽位 → 单次重试（全路径 fail-open）
- fallback 面已随 W4-02c 服务化（engine_services/fallback.py: FallbackService）；本模块对其零运行时依赖
- classify_and_route 门面（W5-01 RunCoordinator 组装消费预留）

宿主依赖（engine 持有）：settings / _cache_monitor / _record_action / _event_append /
_runtime_timeout / _run_state（per-session 运行态桶：deferred_replay_*/
err1210_run_seq/auto_continue_1210/program_recovery_tail_message）/
_AGG_MAX_TAIL_USERS / _AGG_SEPARATOR / err1210 实例态四容器。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (host 属性来自 LoopEngine 混入体系，pyright 无法静态解析，文件级关闭这两条；
#   沿 termination_controller.py 既有豁免口径)

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast

from llm_loop.core.loop.err1210 import (
    _DEFER_REPLAY_TOTAL_LIMIT,
    Err1210RecoveryResult,
    InjectedEntry,
    InjectionSpan,
    SlotKind,
    content_prefix_sha,
    is_err1210,
    parse_aggregated_slots,
    record_defer_event,
    snapshot_offending_payload,
)
from llm_loop.event_log.model import EVENT_PROGRAM_RECOVERY
from llm_loop.llm.errors import LLMError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import ModelSession

logger = logging.getLogger(__name__)


class RecoveryController:
    """err1210 恢复域 service：分类 → 降级/回存 → 单次重试 → 运行时重试路由."""

    # 原 _Err1210Mixin 类属性（HEAD 351-352 逐字迁入——B5-W1-03 校验补遗：类属性属本域非宿主面）
    _AGG_SEPARATOR: str = "\n\n" + "=" * 28 + "\n\n"
    _AGG_MAX_TAIL_USERS: int = 16  # 群条数上限(防误聚真实多轮 user 对话)

    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    """P0 状态机（engine 挂载；self 属性由 LoopEngine.__init__ 提供）."""

    if TYPE_CHECKING:
        _err1210_attempted: dict[str, int]
        _last_request_msg_count_by_session: dict[str, int]

    # ── 3.2 compact 首请求判定 ──

    def _is_compact_first_request(self, sess: ModelSession, messages: list[dict]) -> bool:
        """主信号: build.py:561 显式标记；辅助信号: 会话级相邻请求消息数骤降（≥30% 且 ≥8 条）.

        任一成立即 True（spec 5.1.1-1"或"语义）。
        """
        if getattr(self._host, "_last_history_compacted", False):
            return True
        counts = getattr(self._host, "_last_request_msg_count_by_session", None) or {}
        prev = counts.get(sess.session_id)
        if prev and len(messages) < prev:
            drop = prev - len(messages)
            if drop >= 8 and drop >= prev * 0.30:
                return True
        return False

    # ── 3.3 尾部注入剥离 ──

    def _strip_tail_injections(self, messages: list[dict]) -> tuple[list[dict], InjectionSpan] | None:
        """读 build 登记，身份复核 + 尾部连续段校验 → copy-on-write 剥离副本.

        任一失败返回 None 记 WARN（spec 5.1.1-5a：无法区分则整体保留放弃降级）。
        登记区间记录法天然正确处理"尾部 user 末位为真实输入"形态（只切登记过的条目）。
        """
        try:
            entries = sorted(
                self._host._run_state().last_build_injections or [],
                key=lambda e: e.msg_idx,
            )
            if not entries:
                logger.info("err1210: 无注入登记，放弃降级（1210 或与注入群无关）")
                return None
            span = InjectionSpan(entries=tuple(entries))
            if not span.is_tail_contiguous(messages):
                logger.warning(
                    "err1210: 注入登记未构成尾部连续段，放弃降级（安全侧不误剥）idxs=%s n=%d",
                    [e.msg_idx for e in entries],
                    len(messages),
                )
                return None
            from llm_loop.core.cache_health import GATE_NOTE_CONTENT
            from llm_loop.core.loop.focus import _INJECTION_PREFIX
            from llm_loop.core.user_truth_wire import USER_TRUTH_SEPARATOR

            for e in entries:
                m = messages[e.msg_idx]
                content = m.get("content")
                if not isinstance(content, str) or m.get("role") != "user":
                    logger.warning("err1210: 注入身份复核失败（非 user/非 str），放弃降级 idx=%d", e.msg_idx)
                    return None
                if content_prefix_sha(content) != e.prefix_sha:
                    logger.warning("err1210: 注入前缀 sha 不匹配，放弃降级 idx=%d", e.msg_idx)
                    return None
                if e.slot_kind == SlotKind.USER_ENVELOPE:
                    if (
                        not e.user_truth
                        or USER_TRUTH_SEPARATOR not in content
                        or not content.endswith(e.user_truth)
                    ):
                        logger.warning(
                            "err1210: R6 user envelope 恒等校验失败，放弃降级 idx=%d",
                            e.msg_idx,
                        )
                        return None
                elif e.slot_kind == SlotKind.GATE_NOTE:
                    if content != GATE_NOTE_CONTENT:
                        logger.warning("err1210: gate_note 恒等校验失败，放弃降级 idx=%d", e.msg_idx)
                        return None
                elif not content.startswith(_INJECTION_PREFIX):
                    logger.warning(
                        "err1210: 注入前缀标识缺失（绕过 wrap_injection?），放弃降级 idx=%d", e.msg_idx
                    )
                    return None
            # R6 envelope 是“program prefix + exact human suffix”单条 user。异常降级只能
            # 剥 program prefix，绝不能把 user truth 一起删除。当前 build 每轮登记最多一个
            # USER_ENVELOPE，且它是 provider payload 尾条。
            if len(entries) == 1 and entries[0].slot_kind == SlotKind.USER_ENVELOPE:
                e = entries[0]
                return (
                    list(messages[: e.msg_idx])
                    + [{"role": "user", "content": e.user_truth}],
                    span,
                )
            # legacy copy-on-write：新 list，前缀逐字节不变（spec 5.1.1-2a）
            stripped = list(messages[: entries[0].msg_idx])
            return stripped, span
        except Exception:  # noqa: BLE001 — 剥离失败 fail-open（放弃降级）
            logger.warning("err1210: 剥离过程异常，放弃降级（fail-open）", exc_info=True)
            return None

    # ── 3.3b 尾部连续 user 聚合（1210 结构触发的兜底恢复，EXPERIENCE-20260828-glm-1210-user）──
    # 实验实锤(2026-08-28, 快照 20260827T190036788Z 单变量重放): 智谱 GLM 端点对尾部
    # 连续多条 user 做结构校验触发 1210——原样重放复现 400/1210, 仅将尾部 6 条 user
    # 合并为 1 条(内容逐字保留)后 HTTP 200。压缩产物帧(归档摘要/压缩声明等)不在注入
    # 槽登记内, 剥离路径对 compact 首请求的该形态 8/8 失效——本聚合分支为其兜底。

    _AGG_SEPARATOR: str = "\n\n" + "=" * 28 + "\n\n"
    _AGG_MAX_TAIL_USERS: int = 16  # 群条数上限(防误聚真实多轮 user 对话)

    def _aggregate_tail_users(self, messages: list[dict]) -> list[dict] | None:
        """尾部连续 user 群(≥2 条, 全 str content)聚合为单条 user(逐字保留).

        copy-on-write: 前缀列表对象复用(逐字节不变); 任一不满足返回 None 记 INFO。
        聚合消息 role=user、content=各条原文以 _AGG_SEPARATOR 连接——仅结构变化,
        语义零损失(实验 B 变体验证: finish=tool_calls 正常, 80404 tokens)。
        """
        try:
            tail_start = len(messages)
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") != "user":
                    tail_start = i + 1
                    break
            else:
                tail_start = 0  # 全 user 极端形态(理论不可达, 防御)
            n_tail = len(messages) - tail_start
            if n_tail < 2:
                return None
            if n_tail > self._AGG_MAX_TAIL_USERS:
                logger.info(
                    "err1210: 尾部 user 群 %d 条超上限 %d, 放弃聚合", n_tail, self._AGG_MAX_TAIL_USERS
                )
                return None
            parts: list[str] = []
            for m in messages[tail_start:]:
                c = m.get("content")
                if not isinstance(c, str):  # 多模态/空内容不聚, 安全侧放弃
                    return None
                parts.append(c)
            merged = self._AGG_SEPARATOR.join(parts)
            return messages[:tail_start] + [{"role": "user", "content": merged}]
        except Exception:  # noqa: BLE001 — 聚合失败 fail-open(放弃, 走既有上抛)
            logger.warning("err1210: 聚合过程异常，放弃（fail-open）", exc_info=True)
            return None

    # ── 3.4 defer 回存（槽位复位语义）──

    def _defer_store(
        self,
        sess: ModelSession,
        entries: list[InjectedEntry],
        messages: list[dict] | None = None,
    ) -> bool:
        """按 slot_kind 分派复位；幂等；≤8 上限超限优先保留 interop（spec 6.3-5）.

        回存失败仅 WARN 不阻断重试（spec 4.2-2）。返回是否全部成功（观测用）。
        messages 为 build 产物（P1 9.1 AGGREGATED 拆解用，可空）。
        """
        ok = True
        try:
            by_slot: dict[SlotKind, list[InjectedEntry]] = {}
            for e in entries:
                by_slot.setdefault(e.slot_kind, []).append(e)
            # P1 9.1: AGGREGATED 拆解——聚合 entry 还原段级槽位后回存。
            # hotcard/gate_note 段回流 by_slot 复用既有复位分支；hint 段跳过。
            # CR-R1.1（审查项5）: interop/tip 段恢复源优先 entry.seg_sources
            # （投影前原始内容）——Projection 是 view 不是 Source of Truth；
            # WARM 投影截断后 wire 反推会把原文永久缩水（314→120 chars）。
            # 无 seg_sources（旧 entry/构造缺省）时 fallback wire 解析（标注风险）。
            agg_es = (by_slot.pop(SlotKind.AGGREGATED, None) or []) + (
                by_slot.pop(SlotKind.USER_ENVELOPE, None) or []
            )
            for e in agg_es:
                _src_segs = [(s, c) for s, c in (e.seg_sources or ()) if c]
                if _src_segs:
                    segs = _src_segs
                elif e.slot_kind == SlotKind.USER_ENVELOPE:
                    # R6 envelope may contain only persisted/compact program context. Those
                    # sources are durable and need no one-shot defer replay; never parse the
                    # mixed wire envelope and risk treating the human suffix as program data.
                    continue
                else:
                    try:
                        m = (
                            messages[e.msg_idx]
                            if messages and 0 <= e.msg_idx < len(messages)
                            else {}
                        )
                        segs = parse_aggregated_slots(str(m.get("content") or ""))
                    except Exception:  # noqa: BLE001 — 取段失败按空处理
                        segs = []
                    if segs:
                        logger.debug(
                            "err1210: AGGREGATED defer 走 wire 反推（无 seg_sources）——"
                            "WARM 投影段可能截断，恢复语义可能失真",
                        )
                if not segs:
                    logger.warning(
                        "err1210: AGGREGATED 拆解为空（idx=%d），该聚合条目按丢失处理（fail-open）",
                        e.msg_idx,
                    )
                    ok = False
                    continue
                from llm_loop.core.message import Message, MessageSource

                for slot_s, seg in segs:
                    if not seg:
                        continue
                    try:
                        k = SlotKind(slot_s)
                    except ValueError:
                        continue  # hint 段非消费槽
                    try:
                        if k in (SlotKind.INTEROP, SlotKind.TIP):
                            attr = (
                                "_interop_tail_messages"
                                if k == SlotKind.INTEROP
                                else "_tip_tail_messages"
                            )
                            r = Message(
                                role="system", content=seg, source=MessageSource.SYSTEM
                            )
                            active = getattr(self._host, attr, None) or []
                            setattr(self._host, attr, [r] + active)  # 前置拼接（旧先注入）
                            _st = self._host._run_state()
                            _st.deferred_replay_refs = list(_st.deferred_replay_refs or [])
                            _st.deferred_replay_refs.append((k, r))
                            record_defer_event(
                                "defer_stored",
                                sess.session_id,
                                str(k),
                                {"count": 1, "via": "aggregated"},
                            )
                        else:
                            # hotcard/gate_note 段回流既有复位分支（338 行后）
                            by_slot.setdefault(k, []).append(
                                InjectedEntry(
                                    msg_idx=e.msg_idx,
                                    slot_kind=k,
                                    prefix_sha=content_prefix_sha(seg),
                                    message_ref=None,
                                )
                            )
                    except Exception:  # noqa: BLE001 — 单段失败不阻断其余段
                        ok = False
                        logger.warning(
                            "err1210: AGGREGATED 段回存失败 slot=%s（fail-open）",
                            slot_s,
                            exc_info=True,
                        )
            # R8.14/E24: HOTCARD automatic prompt eligibility is retired.  A legacy
            # injection entry may still reach this parser after hot reload/retry, but it
            # must not reset consumed state and thereby regain future prompt authority.
            if SlotKind.HOTCARD in by_slot:
                record_defer_event(
                    "defer_dropped",
                    sess.session_id,
                    str(SlotKind.HOTCARD),
                    {"reason": "prompt_eligibility_retired"},
                )
                del by_slot[SlotKind.HOTCARD]

            # 总量 ≤8（interop/tip 按消息条数，gate_note 各 1）
            total = sum(len(v) for k, v in by_slot.items() if k in (SlotKind.INTEROP, SlotKind.TIP))
            total += 1 if SlotKind.GATE_NOTE in by_slot else 0
            dropped_overflow: list[SlotKind] = []
            if total > _DEFER_REPLAY_TOTAL_LIMIT:
                keep_interop = by_slot.get(SlotKind.INTEROP, [])[:_DEFER_REPLAY_TOTAL_LIMIT]
                for k in (SlotKind.TIP, SlotKind.GATE_NOTE):
                    if k in by_slot:
                        dropped_overflow.append(k)
                        del by_slot[k]
                if len(keep_interop) < len(by_slot.get(SlotKind.INTEROP, [])):
                    for _e in by_slot[SlotKind.INTEROP][_DEFER_REPLAY_TOTAL_LIMIT:]:
                        record_defer_event(
                            "defer_dropped",
                            sess.session_id,
                            str(SlotKind.INTEROP),
                            {"reason": "overflow"},
                        )
                    by_slot[SlotKind.INTEROP] = keep_interop
                for k in dropped_overflow:
                    record_defer_event(
                        "defer_dropped", sess.session_id, str(k), {"reason": "overflow"}
                    )

            # interop/tip: 回填内存槽（deferred 前置拼接——旧消息先注入，spec 5.1.3-3；
            # is 身份去重保证幂等：重复回存同一 Message 不累积，spec 5.1.1-3b）
            for slot, attr in ((SlotKind.INTEROP, "_interop_tail_messages"), (SlotKind.TIP, "_tip_tail_messages")):
                es = by_slot.get(slot)
                if not es:
                    continue
                refs = [e.message_ref for e in es if e.message_ref is not None]
                try:
                    active = getattr(self._host, attr, None) or []
                    new_refs = [r for r in refs if not any(r is a for a in active)]
                    if new_refs:
                        setattr(self._host, attr, new_refs + active)  # 幂等：整槽赋值语义
                        # 重注入检测（build 消费时 is 身份匹配 → defer_replayed）
                        _st = self._host._run_state()
                        _st.deferred_replay_refs = list(_st.deferred_replay_refs or [])
                        _st.deferred_replay_refs.extend((slot, r) for r in new_refs)
                    record_defer_event(
                        "defer_stored",
                        sess.session_id,
                        str(slot),
                        {"count": len(refs), "shas": [e.prefix_sha for e in es]},
                    )
                except Exception:  # noqa: BLE001 — 单槽失败不阻断其余
                    ok = False
                    logger.warning("err1210: defer 回填 %s 失败（fail-open）", slot, exc_info=True)

            # gate_note: pending 置位
            if SlotKind.GATE_NOTE in by_slot:
                try:
                    self._host._cache_monitor.restore_gate_note(sess.session_id)
                    _st = self._host._run_state()
                    _st.deferred_replay_slots = {str(SlotKind.GATE_NOTE), *_st.deferred_replay_slots}
                    record_defer_event("defer_stored", sess.session_id, str(SlotKind.GATE_NOTE), {})
                except Exception:  # noqa: BLE001
                    ok = False
                    logger.warning("err1210: gate_note 复位异常（fail-open）", exc_info=True)
            return ok
        except Exception:  # noqa: BLE001 — defer 整体失败不阻断重试
            logger.warning("err1210: defer 回存异常（fail-open，不阻断重试）", exc_info=True)
            return False

    # ── 3.6 P0 主入口 ──

    def _try_err1210_recovery(
        self,
        *,
        exc: LLMError,
        sess: ModelSession,
        messages: list[dict],
        tools_param: list[dict],
        llm_client: Any,
        chat_model_arg: str | None,
        timeout_s: float | None,
        session_id: str,
        model_label: str = "",
        metadata_registry: Any = None,
        round_no: int = 0,
    ) -> Err1210RecoveryResult:
        """编排: 判定 → 快照 → 剥离 → defer 回存 → 单次重试 → 耗尽标记（design 2.2.2-④）.

        recovered=False 时 engine 按既有错误路径继续（overflow/fallback/如实反馈）。
        全路径 fail-open：内部未捕获异常等价 recovered=False。
        """
        result = Err1210RecoveryResult()
        if os.environ.get("ERR1210_RECOVERY", "1") != "1":
            return result  # 总开关关闭：零行为（完全回到现行）
        try:
            if not is_err1210(exc):
                return result
            # 修复A: 门禁移除——任意 1210 均尝试降级（原"compact 首请求"边界外的
            # 场景: 注入叠加尾部连续 user 的非 compact 轮，主区 883b4725 实证）。
            # compact_first 降级为快照标记信号（真实判定），不再作触发门禁。
            seq = self._host._run_state().err1210_run_seq
            attempted = getattr(self._host, "_err1210_attempted", None) or {}
            if attempted.get(session_id) == seq:
                # 本 run 内已尝试（单次重试防循环，per-run 语义）
                result.attempted = True
                result.exhausted = True
                return result
            result.attempted = True

            compact_first = self._is_compact_first_request(sess, messages)
            model_ref = (
                chat_model_arg
                or getattr(llm_client, "model", "")
                or getattr(self._host.settings, "llm_model", "")
            )
            entries = sorted(
                self._host._run_state().last_build_injections or [],
                key=lambda e: e.msg_idx,
            )
            span = InjectionSpan(entries=tuple(entries)) if entries else None

            # ① 快照（剥离前完整载荷；失败不阻断）
            snapshot_offending_payload(
                messages=messages,
                tools=tools_param,
                params={
                    "model": model_ref,
                    "max_tokens": getattr(llm_client, "max_tokens", None),
                    "thinking_mode": getattr(llm_client, "thinking_mode", None),
                    "reasoning_effort": getattr(llm_client, "reasoning_effort", None),
                    "timeout_s": timeout_s,
                    "provider": getattr(llm_client, "provider", ""),
                },
                session_id=session_id,
                model=model_ref,
                is_compact_first=compact_first,
                span=span,
                data_dir=self._host.settings.data_dir,
            )

            # ①.5 blind retry——原样重发（2026-08-29 定位实证，GOAL-20260829-a9a6c0f0）:
            # GLM 对 compact 后首请求间歇性 1210 拒绝，同 payload 重发 5/5 必成功；
            # 失败请求尾部仅 1 条归档摘要、无注入群可剥，strip 方向打偏（主区 883b4725
            # 6/6 恢复失败实证）。原样重试优先：成功零内容损失且不消费/复位任何槽位。
            # 失败（仍 1210 或网络异常）→ 回退既有 strip/aggregate 路径（保底不删）。
            # provider 调用预算：原始失败 1 + blind 1 + strip 重试 1 ≤ 3（异常路径，可控）。
            # env ERR1210_BLIND_RETRY=0 单独关闭本分支（回退 9088d4e 行为）。
            blind_attempted = False
            if os.environ.get("ERR1210_BLIND_RETRY", "1") == "1":
                blind_attempted = True
                resp_b, exc_b = self._retry_consume_stream(
                    llm_client=llm_client,
                    messages=messages,
                    tools_param=tools_param,
                    chat_model_arg=chat_model_arg,
                    timeout_s=timeout_s,
                    session_id=session_id,
                    model_label=model_label or model_ref,
                    metadata_registry=metadata_registry,
                    round_no=round_no,
                    attempt_index=1,
                )
                if resp_b is not None:
                    result.resp = resp_b
                    result.recovered = True
                    # 耗尽标记（对齐 ④ 语义：blind 成功也消耗本 run 降级机会，防二次尝试）
                    self._host._err1210_attempted = {**attempted, session_id: seq}
                    self._host._record_action(
                        "err1210.recovery",
                        "blind_retry_ok",
                        "原样重发成功（零内容损失，未走剥离/聚合）；mode=blind",
                    )
                    return result
                self._host._record_action(
                    "err1210.recovery",
                    "blind_retry_1210" if (exc_b is not None and is_err1210(exc_b)) else "blind_retry_err",
                    "原样重发未恢复（"
                    + ("仍 1210" if (exc_b is not None and is_err1210(exc_b)) else "非 1210 异常")
                    + "），回退剥离/聚合路径；mode=blind-fail",
                )

            # ② defer 回存（消费过的槽复位——无论剥离成败，防注入随一次性消费丢失）
            # P1 9.1: 传 messages 供 AGGREGATED 拆解（聚合 entry → 段级槽位复位）
            result.deferred_ok = self._defer_store(sess, entries, messages)

            # ③ 剥离（登记注入槽形态）→ 失败则尾部 user 聚合兜底（压缩帧形态，
            #    1210 结构触发实锤：连续多条 user 触发智谱校验，EXPERIENCE-20260828-glm-1210-user）
            retry_mode = "strip"
            stripped = self._strip_tail_injections(messages)
            if stripped is not None:
                retry_messages, span = stripped
                result.stripped_count = len(span.entries)
                # Snapshot 2 形态（GPT 审计第五条）：strip 后尾部仍残留 ≥2 连续 user
                # （部分注入剥离后残留压缩帧连续 user）→ strip 结果上二次聚合，
                # 保持单次重试不增 provider 调用（strip + normalize + one retry）
                residual = self._aggregate_tail_users(retry_messages)
                if residual is not None:
                    retry_messages = residual
                    retry_mode = "strip+aggregate"
                    self._host._record_action(
                        "err1210.recovery",
                        "aggregate_retry",
                        "剥离后尾部仍残留连续 user 群，二次聚合后重试（mode=strip+aggregate）",
                    )
            else:
                aggregated = self._aggregate_tail_users(messages)
                if aggregated is None:
                    if blind_attempted:
                        # blind 已消耗一次（如网络瞬态失败）+ 剥离/聚合均不适用 →
                        # 原样单次重试兜底（主区 883b4725 实证：compact 首请求
                        # 1210 原样重发高成功率；耗尽标记照写防循环，本 run 至多一次）。
                        # blind 关闭（env ERR1210_BLIND_RETRY=0）时保持 9088d4e
                        # aborted 语义不变（无法区分则放弃，安全侧不盲试）。
                        retry_messages = messages
                        retry_mode = "raw-fallback"
                        self._host._record_action(
                            "err1210.recovery",
                            "raw_retry",
                            "剥离与聚合均不适用，blind 失败后原样单次重试兜底；mode=raw-fallback",
                        )
                    else:
                        self._host._record_action(
                            "err1210.recovery",
                            "aborted",
                            f"剥离与聚合均不适用放弃降级；defer_ok={result.deferred_ok}",
                        )
                        # 耗尽标记仍写入（本 compact 事件不再尝试，防循环）
                        self._host._err1210_attempted = {**attempted, session_id: seq}
                        return result
                else:
                    retry_messages = aggregated
                    retry_mode = "aggregate"
                    self._host._record_action(
                        "err1210.recovery",
                        "aggregate_retry",
                        "剥离校验失败，尾部连续 user 群聚合后重试（mode=aggregate）",
                    )

            # ④ 单次重试（先标记防循环——本 compact 事件至多一次降级）
            self._host._err1210_attempted = {**attempted, session_id: seq}
            resp, retry_exc = self._retry_consume_stream(
                llm_client=llm_client,
                messages=retry_messages,
                tools_param=tools_param,
                chat_model_arg=chat_model_arg,
                timeout_s=timeout_s,
                session_id=session_id,
                model_label=model_label or model_ref,
                metadata_registry=metadata_registry,
                round_no=round_no,
                attempt_index=2 if blind_attempted else 1,
            )
            mode_desc = (
                f"剥离 {result.stripped_count} 条后"
                if retry_mode == "strip"
                else "原样重发后"
                if retry_mode == "raw-fallback"
                else "尾部 user 聚合后"
            )
            if resp is not None:
                result.resp = resp
                result.recovered = True
                self._host._record_action(
                    "err1210.recovery",
                    "recovered",
                    f"{mode_desc}重试成功；defer_ok={result.deferred_ok}；mode={retry_mode}",
                )
            elif retry_exc is not None and is_err1210(retry_exc):
                result.exhausted = True
                record_defer_event(
                    "defer_exhausted", session_id, "all", {"stripped": result.stripped_count, "mode": retry_mode}
                )
                self._host._record_action(
                    "err1210.recovery",
                    "exhausted",
                    f"{mode_desc}重试仍 1210（耗尽上抛）；mode={retry_mode}",
                )
            else:
                # 非 1210 二次异常（网络/超时）：recovered=False，原 1210 语义不被掩盖，
                # 详情已在 _retry_consume_stream 内记 action——engine 继续既有错误链
                pass
            return result
        except Exception:  # noqa: BLE001 — 外层兜底等价 recovered=False
            logger.warning("err1210: 恢复过程异常（fail-open 等价 recovered=False）", exc_info=True)
            return result

    def _retry_consume_stream(
        self,
        *,
        llm_client: Any,
        messages: list[dict],
        tools_param: list[dict],
        chat_model_arg: str | None,
        timeout_s: float | None,
        session_id: str,
        model_label: str = "",
        metadata_registry: Any = None,
        round_no: int = 0,
        attempt_index: int = 1,
    ) -> tuple[Any | None, LLMError | None]:
        """单次重试并完整消费新流（不 yield 增量——外层已过 yield 点，design 风险 6）.

        返回 (resp, retry_exc)：成功 resp 非 None；失败 resp=None 且 retry_exc 为二次
        异常（1210 复现 / 网络 / 超时——调用方区分耗尽与其他失败）。
        1210 在响应体阶段抛出、原流尚无 delta 输出——无重复输出风险。
        """
        kwargs: dict[str, Any] = {
            "messages": messages,
            "tools": tools_param,
            "timeout_s": timeout_s,
        }
        if chat_model_arg:
            kwargs["model"] = chat_model_arg
        stream_fn = getattr(llm_client, "chat_stream", None)
        try:
            # R8: 1210 retries are real provider attempts and need the same
            # per-attempt shadow attribution as primary/fallback calls.
            try:
                from llm_loop.core.injection_profile import shadow_profile_event_payload
                from llm_loop.event_log.model import EVENT_INJECTION_PROFILE_SHADOW

                self._host._event_append(
                    session_id,
                    EVENT_INJECTION_PROFILE_SHADOW,
                    shadow_profile_event_payload(
                        model_label=model_label
                        or chat_model_arg
                        or getattr(llm_client, "model", ""),
                        registry=metadata_registry,
                        round_no=round_no,
                        attempt_kind="err1210_retry",
                        attempt_index=attempt_index,
                    ),
                )
            except Exception:  # noqa: BLE001 — audit never changes retry semantics
                logger.debug(
                    "err1210 injection.profile.shadow 写入失败（fail-open）",
                    exc_info=True,
                )
            if callable(stream_fn):
                it = cast("Iterator[Any]", stream_fn(**kwargs))
                while True:  # 完整消费至流尾；StopIteration.value 即完整 resp（client 侧聚合）
                    try:
                        next(it)
                    except StopIteration as stop:
                        return stop.value, None
            return llm_client.chat(**kwargs), None
        except Exception as retry_exc:  # noqa: BLE001 — 二次异常不掩盖原 1210
            self._host._record_action(
                "err1210.recovery",
                "retry_error",
                f"重试失败: {str(retry_exc)[:200]}",
            )
            return None, retry_exc if isinstance(retry_exc, LLMError) else None

    # ── 供 build/engine 接线调用的辅助（任务组 4）──

    def _note_defer_replayed(self, session_id: str, slot_kind: SlotKind, count: int = 1) -> None:
        """build 消费 defer 回填消息时记 defer_replayed（观测闭环，spec 4.4-2）."""
        record_defer_event(
            "defer_replayed", session_id, str(slot_kind), {"count": count}
        )
        self._host._run_state().last_build_defer_replayed = True

    # ── engine 接线点（任务组 4.3 瘦身: engine.py 行数守卫只留最小调用）──

    def _err1210_init(self) -> None:
        """engine.__init__ 调用（tasks 4.2）: per-session 恢复状态字段初始化.

        - _err1210_attempted: per-session 耗尽标记（值 = compact 事件 seq；新事件自然不等 → 降级机会重获）
        - _last_request_msg_count_by_session: 骤降兜底判定数据源（每次成功请求后更新）

        运行态字段（err1210_run_seq/auto_continue_1210/program_recovery_tail_message
        及 defer 重注入检测等）经 _RunState per-session 桶读写（B5-W4-03：
        RunStateManager 对象化，原属性 shim 退役——err1210 P0-A）。
        """
        self._host._err1210_attempted = {}
        self._host._last_request_msg_count_by_session = {}
        # 修复A（2026-08-29 用户批准 B+A 组合）: per-run 降级机会序号。
        _st = self._host._run_state()
        _st.err1210_run_seq = 0
        # R9（2026-08-29 用户需求「1210 自动继续」）: 程序化重发计数（每 run 限 1 次）
        _st.auto_continue_1210 = 0
        # INJECTION-GOVERNANCE R4: recovery 是一次性 runtime slot，不进入 durable 对话历史。
        _st.program_recovery_tail_message = None

    def _err1210_run_begin(self) -> None:
        """engine 每 run 入口调用（对齐 _reset_overflow_state 先例）: run seq 递增.

        attempted 键语义从"compact 事件 seq"迁移为"run seq"——非 compact 轮的
        1210（注入叠加尾部连续 user 形态，主区 883b4725 实证）同样获得一次
        降级机会；每 run 至多一次，防循环语义不劣化。
        """
        self._host._run_state().err1210_run_seq += 1
        # R9: 每 run 重置程序化重发计数（防循环语义）
        _st = self._host._run_state()
        _st.auto_continue_1210 = 0
        # R4: 异常中断遗留的 pending recovery 不得跨新的 human run 复活。
        _st.program_recovery_tail_message = None

    def _err1210_attempt_recovery(
        self,
        *,
        exc: LLMError,
        sess: ModelSession,
        messages: list[dict],
        tools_param: list[dict],
        llm_client: Any,
        chat_model_arg: str | None,
        session_id: str,
        current_resp: Any,
        current_round_ms: float,
        model_label: str = "",
        metadata_registry: Any = None,
        round_no: int = 0,
    ) -> tuple[bool, Any, float]:
        """engine except 接线点（tasks 4.3）: compact 首请求 1210 定向降级重试.

        剥离尾部一次性注入槽 → defer 回存 → 单次重试（重试流完整消费、不 yield
        增量——design 风险 6）。恢复成功返回 (True, 新 resp, 0.0)——engine 控制流
        自然落回 action.llm_decide 正常路径（与 fallback 成功合流同构）；
        失败返回 (False, current_resp, current_round_ms) 原样继续既有错误链
        （1210 本就 4xx 不进 fallback，走如实反馈——fail-open 与现行行为一致；
        恢复轮无 TTFT/耗时单列——design 风险 6，如实不伪造）。
        env ERR1210_RECOVERY=0 完全旁路。
        """
        try:
            result = self._try_err1210_recovery(
                exc=exc, sess=sess, messages=messages, tools_param=tools_param,
                llm_client=llm_client, chat_model_arg=chat_model_arg,
                timeout_s=self._host._runtime_timeout(), session_id=session_id,
                model_label=model_label, metadata_registry=metadata_registry,
                round_no=round_no,
            )
            if result.recovered and result.resp is not None:
                return True, result.resp, 0.0
        except Exception:  # noqa: BLE001 — P0 fail-open 兜底（等价未恢复）
            logger.warning("err1210: engine 接线异常（fail-open）", exc_info=True)
        return False, current_resp, current_round_ms

    def _err1210_note_defer_lost(self, session_id: str, reason: str) -> None:
        """defer 重注入轮再次失败 → 槽丢失观测（spec 5.1.3-5；fail-open）."""
        if self._host._run_state().last_build_defer_replayed:
            record_defer_event(
                "defer_lost_on_reinject", session_id, "all", {"reason": reason}
            )
            self._host._run_state().last_build_defer_replayed = False

    def _err1210_try_runtime_retry(
        self,
        *,
        exc: Exception,
        sess: ModelSession,
        llm_client: Any,
        chat_model_arg: str | None,
        session_id: str,
        timeout_s: float | None = None,
        model_label: str = "",
        metadata_registry: Any = None,
        round_no: int = 0,
        rebuild_fn: Any = None,
    ) -> Any | None:
        """R8.24-B B-2.4（批 B2⑥，B-D2）: 恢复链未覆盖 1210 的 runtime rebuild/retry once.

        替代原 R9"程序化用户重发"（_err1210_try_auto_continue——武装 next-build
        slot、engine continue 多耗一轮 LLM 调用，且 slot 文本进模型可见面）：
        当场重建请求（1210 自愈机制实证 = wire 归档/注入消费状态变化后重组
        即成功）并单次重试——零 prompt、零模型可见文本（B-G7
        programmatic user resend chars=0）。

        - 每 run 限 1 次（沿用 auto_continue_1210 R9 计数语义防循环）；
        - ERR1210_RECOVERY=0 完全旁路（与恢复链同门）；
        - rebuild_fn 为 None / 重建失败 / 非 1210 / 已耗尽 → 返回 None，
          engine 走真实终态（不 retry——副作用安全前提不满足即放弃）；
        - 与恢复链既有 blind retry（:643 起）并存，优先级 blind → rebuild → 终态。
        """
        try:
            if self._host._run_state().auto_continue_1210 >= 1:
                return None
            if not isinstance(exc, LLMError) or not is_err1210(exc):
                return None
            if os.environ.get("ERR1210_RECOVERY", "1") != "1":
                return None
            if rebuild_fn is None:
                return None
            rebuilt = rebuild_fn()
            if not rebuilt:
                return None
            messages, tools_param = rebuilt
        except Exception:  # noqa: BLE001 — 判定失败不阻断原路径
            return None
        self._host._run_state().auto_continue_1210 = 1
        _turn_ref = self._host._run_state().current_turn_ref
        self._host._record_action(
            "llm_call",
            "runtime_retry_1210",
            "1210 恢复链耗尽，rebuild + 单次 runtime 重试（零 prompt 注入）",
        )
        # Durable audit remains event-scoped; the retry itself touches no
        # conversation surface at all (zero-prompt recovery, B-G7).
        try:
            _estore = getattr(self._host, "_event_store", None)
            if _estore is not None and getattr(_estore, "enabled", False):
                _estore.append(
                    sess.session_id,
                    EVENT_PROGRAM_RECOVERY,
                    {
                        "action": "runtime_rebuild_retry_once",
                        "trigger": "provider_1210",
                        "turn_ref": _turn_ref,
                        "scope": "in_process_zero_prompt",
                    },
                )
        except Exception:  # noqa: BLE001 — audit failure must not block recovery
            logger.debug("program.recovery 事件写入失败（fail-open）", exc_info=True)
        resp, retry_exc = self._retry_consume_stream(
            llm_client=llm_client,
            messages=messages,
            tools_param=tools_param,
            chat_model_arg=chat_model_arg,
            timeout_s=timeout_s if timeout_s is not None else self._host._runtime_timeout(),
            session_id=session_id,
            model_label=model_label,
            metadata_registry=metadata_registry,
            round_no=round_no,
            attempt_index=2,
        )
        if resp is not None:
            self._host._record_action("llm_call", "runtime_retry_1210", "recovered")
            return resp
        self._host._record_action(
            "llm_call",
            "runtime_retry_1210",
            f"retry_failed: {str(retry_exc or exc)[:200]}",
        )
        return None

    def _e1210_llm_error_finalize(
        self, session_id: str, exc: Exception, msg_count: int, defer_reason: str
    ) -> str:
        """llm_error 终止前置（fallback_exhausted / llm_error 两处共用）: 观测收敛 + 反馈文本."""
        from llm_loop.feedback.honesty import llm_error_text

        self._err1210_note_defer_lost(session_id, defer_reason)  # 二阶失败观测（spec 5.1.3-5）
        self._err1210_note_request_count(session_id, msg_count)  # 修复B: 失败轮也更新骤降数据源
        return llm_error_text(exc)

    def _err1210_note_request_count(self, session_id: str, msg_count: int) -> None:
        """骤降兜底判定数据源（tasks 4.2 + 修复B 2026-08-29）: 成功与失败轮均更新.

        原语义"仅成功轮更新"存在死锁式失效：连续失败轮越多，prev 越陈旧，
        骤降判定越不可能触发（主区 883b4725 三连败实证）。失败轮也更新后
        prev 恒为最近一次请求，骤降语义即"相邻两次请求"如实反映。
        """
        self._host._last_request_msg_count_by_session[session_id] = msg_count
