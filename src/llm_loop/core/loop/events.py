"""事件/审计/通知/载荷 mixin（EVO-20260816-f94bf3b8，engine.py 防膨胀拆分）.

2026-08-16 自 engine.py 迁出（engine.py 1114 行触发防膨胀守卫 test_complexity_reduction，
按测试意图 >1110 应拆分评审）。职责: 动作观察者（H-UI）/ 事件源化（D1）/
阶段-动作记录（架构自省）/ 推送式架构上报 / 会话-记忆载荷构造 / 断连落盘。

纯重构: 方法体原样迁移（零行为变更），原路径可导入语义保持（REQ-REF-06 对齐）。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条)


from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llm_loop.core.interruption_resume import open_execution_facts, select_open_checkpoint_events
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.reference_injection import is_human_user_message
from llm_loop.core.session import _validate_session_id
from llm_loop.core.tool_execution_journal import ToolExecutionJournal
from llm_loop.event_log.model import build_message_payload
from llm_loop.introspection.events import ArchitectureEvent, ArchitectureEventType
from llm_loop.memory.episode import stable_episode_ref

logger = logging.getLogger(__name__)


class _EventsMixin:
    """事件/通知/审计/载荷辅助（self 状态来自 LoopEngine.__init__）."""

    def set_action_observer(self, fn: Callable[[str, dict], None] | None) -> None:
        """H-UI: 注入/移除动作观察者.

        事件: ("thinking", {"round": N}) / ("tool_call", {"tool_name", "args_summary"})
        / ("tool_result", {"tool_name", "status"}) / ("answer", {}) / ("done", {})。
        观察者同步调用（引擎线程内），异常 fail-open；传 None 移除。
        """
        self._action_observer = fn

    def _record_program_fault(self, kind: str) -> None:
        """R2/A6: 程序故障计数（fail-open 聚合，AI 经 architecture_status 感知）."""
        try:
            if self.status is not None:
                self.status.record_program_fault(kind)
        except Exception:  # noqa: BLE001 — 计数失败 fail-open
            logger.debug("程序故障计数失败（fail-open）: %s", kind, exc_info=True)

    def _notify_action(self, event_type: str, **payload) -> None:
        """动作事件通知（fail-open：观察者异常/缺失均不阻断主循环）."""
        fn = self._action_observer
        if fn is None:
            return
        try:
            fn(event_type, payload)
        except Exception:  # noqa: BLE001 — 观察者异常不影响 AI 发挥
            logger.debug("动作观察者异常（fail-open）: %s", event_type)

    # ── D1 事件源化辅助（fail-open：禁用/异常如实记录，不抛穿主循环）──

    def _event_append(self, session_id: str, event_type: str, payload: dict) -> Any:
        """D1 事件写入（fail-open：未注入/禁用/异常均如实 warning，不抛穿主循环）.

        B1/EVO-20260902-41898b20: 返回已落盘 Event（含 seq——B2 truncated 索引
        幂等键数据源）；未注入/禁用/失败返回 None。存量调用方忽略返回值，零回归。
        """
        store = getattr(self, "_event_store", None)
        if store is None or getattr(store, "enabled", False) is False:
            return None
        try:
            return store.append(session_id, event_type, payload)
        except Exception as exc:  # noqa: BLE001 — 事件写入失败不阻断循环（fail-open）
            logger.warning("事件写入失败（fail-open）: %s", exc)
            self._record_program_fault("event_write")
            return None

    def _ensure_session_created(self, sess) -> None:
        """会话首次落库时生成 session.created（顶层字段快照，缺失如实置空）."""
        store = getattr(self, "_event_store", None)
        if store is None or getattr(store, "enabled", False) is False:
            return
        try:
            if store.exists(sess.session_id):
                return
            payload = {
                "version": sess.to_dict().get("version", 4),
                "title": sess.title,
                "created_at": sess.created_at,
                "updated_at": sess.updated_at,
                "status": sess.status,
                "parent_id": sess.parent_id,
                "branch_id": sess.branch_id,
                "branch_summary": sess.branch_summary,
                "model_override": sess.model_override,
                "pinned": sess.pinned,
                "channel": sess.channel,
            }
            store.append(sess.session_id, "session.created", payload)
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("session.created 事件写入失败（fail-open）: %s", exc)

    def _append_message_event(self, sess, msg: Message) -> Any | None:
        """消息落库点事件（payload 与 Session.to_dict() 消息字段逐一对齐）."""
        store = getattr(self, "_event_store", None)
        if store is None or getattr(store, "enabled", False) is False:
            return None
        try:
            return store.append(
                sess.session_id,
                "message.appended",
                build_message_payload(
                    index=len(sess.messages) - 1,
                    role=msg.role,
                    content=msg.content,
                    source=msg.source.value,
                    tool_call_id=msg.tool_call_id,
                    status=msg.status.value if msg.status else None,
                    tool_name=msg.tool_name,
                    error_detail=msg.error_detail,
                    tool_calls=msg.tool_calls,
                    reasoning_content=msg.reasoning_content,
                    metadata=msg.metadata,
                ),
            )
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("message.appended 事件写入失败（fail-open）: %s", exc)
            return None

    def _resolve_msg_seq(self, session_id: str, msg: Message) -> int | None:
        """尽力定位消息在会话中的序号（tool_call_id 优先，其次内容匹配；失败如实 None）.

        P1-7(2026-08-15, 性能): 压缩归档对每条消息调用本方法（大会话数百次），
        原实现每次 session.load 读盘——优先用 run 中已绑定的内存会话（P0-5
        _run_sessions），miss 才回退磁盘 load（零行为差异，快 2-3 个数量级）。
        """
        try:
            sess = self._run_sessions.get(session_id) or self.session.load(session_id)
            # build_history_messages 常态保留原 Message 对象引用；先用 identity 精确定位，
            # 避免长回答/重复工具回执内容相同导致 content fallback 永远命中第一条。
            for i, m in enumerate(sess.messages):
                if m is msg:
                    return i
            for i, m in enumerate(sess.messages):
                if msg.tool_call_id and m.tool_call_id == msg.tool_call_id:
                    return i
            for i, m in enumerate(sess.messages):
                if m.role == msg.role and m.content == msg.content:
                    return i
            # prompt-view 清理可能通过 dataclasses.replace 生成等价副本，使 content 与
            # session 原文不同；ts 在 replace 时保持不变，可作为最终稳定定位兜底。
            for i, m in enumerate(sess.messages):
                if m.role == msg.role and m.ts == msg.ts:
                    return i
        except Exception:  # noqa: BLE001 — 定位失败如实 None
            logger.debug("消息序号定位失败（fail-open）: session=%s", session_id, exc_info=True)
        return None

    # ── 阶段记录（架构自省）──
    def _phase(self, phase: str) -> None:
        if self.status:
            self.status.record_phase(phase)

    def _record_action(self, phase: str, action_type: str, detail: str) -> None:
        if self.status:
            self.status.record_action(phase, action_type, detail)

    def _report(
        self,
        event_type: ArchitectureEventType,
        fact: str,
        reason: str,
        suggestion: str,
        capability_requirements: tuple[str, ...] = (),
    ) -> Message | None:
        """推送式架构上报（冷却去重）；返回可注入消息或 None."""
        if self.status is None or not self.status.enabled:
            return None
        event = ArchitectureEvent(
            event_type=event_type,
            fact=fact,
            reason=reason,
            suggestion=suggestion,
            # R2 No Unreachable Advice: 产生点结构化能力需求随事件透传（build_message 落 metadata）
            capability_requirements=tuple(capability_requirements),
        )
        if self.status.report_event(event):
            return self.status.build_report_message(event)
        return None

    def _session_payload(self, sess: Any) -> str:
        """构造会话 JSON 原文（备份用，不摘要/改写/压缩）."""
        import json as _json

        return _json.dumps(sess.to_dict(), ensure_ascii=False, indent=2)

    def _memory_payload(self) -> str:
        """构造记忆索引 JSON 原文（备份用，不摘要/改写/压缩）."""
        import json as _json

        if self.memory is None:
            return "[]"
        return _json.dumps(
            [e.to_dict() for e in self.memory._entries],  # noqa: SLF001
            ensure_ascii=False,
            indent=2,
        )

    def _fault_feedback(self, component: str, exc: Exception) -> Message:
        """程序辅助组件故障增强反馈（M12 T49; M17 FR-REVIEW-AI-03 拆至 loop_feedback.py）."""
        from llm_loop.feedback.loop_feedback import build_fault_feedback_message

        return build_fault_feedback_message(
            component,
            exc,
            fault_classifier=self.fault_classifier,
            selfheal_budget=self.selfheal_budget,
            audit_dir=self.settings.audit_dir,
        )

    def _inject_interruption_recovery(self, session_id: str, sess) -> None:
        """R8.19/E32: detect an event/session gap and repair it program-side.

        ``event_logs`` is the durable truth source.  A killed process can leave the
        session JSON behind the append-only event stream, but that is a runtime
        consistency problem, not model work.  The historical implementation emitted a
        one-shot ``[会话中断恢复]`` system tip and asked the model to inspect event logs.
        That polluted working context and delegated deterministic reconciliation to the
        LLM.

        R8.24-B B-3.3（B-D8, repair-before-lifecycle）: this repair is wired at the
        run ingress (engine.run, before the main loop) so deterministic mechanical
        repairs always settle before any lifecycle/prompt-eligibility decision
        (build-time retirement, turn-ref judgement).  Repair output carries zero
        model-visible semantics (aligned with E19); ordering is load-bearing and
        covered by tests.

        Production ingress calls this repair before appending the new human message, so
        an event-log-only open run (including its exact human ingress) is restored before
        lifecycle retirement can classify history.  Legacy/direct callers may already
        have a live trailing human message; in that shape the same routine preserves that
        live object and inserts only replay-only history before it.  Observability stays
        prompt-neutral (``prompt_chars=0``).  Replay/prefix failure is fail-open: keep the
        live session untouched and report the repair failure out of band; never synthesize
        prompt prose.
        """
        try:
            _estore = getattr(self, "_event_store", None)
            if _estore is None or not getattr(_estore, "enabled", False):
                return
            if not _estore.exists(session_id):
                return
            _events = _estore.read(session_id)
            _el_count = sum(1 for e in _events if e.type == "message.appended")
            _mem_count = len(sess.messages)
            replayed = self.session._load_from_event_log(session_id)  # noqa: SLF001
            if replayed is None:
                # If the event stream is not ahead there is nothing deterministic to
                # recover from it.  A replay failure only becomes recovery telemetry
                # when the durable stream claims to contain more messages than memory.
                if _el_count > _mem_count:
                    self._record_action(
                        "run.interruption_recovery",
                        "repair_failed",
                        f"event_messages={_el_count};memory_messages={_mem_count};reason=replay_failed;prompt_chars=0",
                    )
                return

            live = list(sess.messages)
            current_user = live[-1] if live and live[-1].role == "user" else None
            live_prefix = live[:-1] if current_user is not None else live
            replay_messages = list(replayed.messages)

            def _identity(msg: Message) -> tuple[Any, ...]:
                return (
                    msg.role,
                    msg.content,
                    str(msg.source),
                    msg.tool_call_id,
                    str(msg.status) if msg.status is not None else None,
                    msg.tool_name,
                    msg.error_detail,
                    msg.tool_calls,
                    msg.reasoning_content,
                    dict(msg.metadata or {}),
                )

            prefix_len = len(live_prefix)
            if len(replay_messages) < prefix_len:
                # Event log is behind the already-loaded historical prefix.  It has no
                # recovery material for this turn; preserve the live session unchanged.
                return
            if [_identity(m) for m in replay_messages[:prefix_len]] != [
                _identity(m) for m in live_prefix
            ]:
                self._record_action(
                    "run.interruption_recovery",
                    "repair_failed",
                    f"event_messages={_el_count};memory_messages={_mem_count};reason=prefix_mismatch;prompt_chars=0",
                )
                return

            replay_tail = replay_messages[prefix_len:]
            if current_user is not None and replay_tail:
                current_key = _identity(current_user)
                matching_positions = [
                    i for i, message in enumerate(replay_tail) if _identity(message) == current_key
                ]
                if matching_positions:
                    # The ingress event must be the final replayed message.  If it is
                    # found earlier, event ordering is ambiguous and we refuse to guess.
                    if matching_positions != [len(replay_tail) - 1]:
                        self._record_action(
                            "run.interruption_recovery",
                            "repair_failed",
                            f"event_messages={_el_count};memory_messages={_mem_count};reason=current_user_order;prompt_chars=0",
                        )
                        return
                    replay_tail = replay_tail[:-1]

            if not replay_tail:
                return  # normal aligned run, or only the live current-user event differs

            repaired = live_prefix + replay_tail
            if current_user is not None:
                repaired.append(current_user)
            sess.messages[:] = repaired
            self._record_action(
                "run.interruption_recovery",
                "repaired",
                f"event_messages={_el_count};memory_messages={_mem_count};recovered={len(replay_tail)};prompt_chars=0",
            )
        except Exception:  # noqa: BLE001 — deterministic repair failure stays out of prompt
            logger.debug("中断对账修复异常（fail-open）", exc_info=True)
            with contextlib.suppress(Exception):
                self._record_action(
                    "run.interruption_recovery",
                    "repair_failed",
                    "reason=exception;prompt_chars=0",
                )

    def _recover_pre_ingress_runtime_state(self, session_id: str, sess) -> None:
        """Settle deterministic crash state before lifecycle and new human ingress."""
        self._inject_interruption_recovery(session_id, sess)
        self._recover_inflight_tool_executions(session_id, sess)

    def _materialize_open_model_checkpoint(
        self,
        session_id: str,
        checkpoint_event: Any,
        latest_checkpoint_event: Any | None,
        mechanical_execution: dict[str, Any],
    ) -> dict[str, Any]:
        """Materialize one structurally selected model checkpoint for restart."""
        payload = dict(getattr(checkpoint_event, "payload", None) or {})
        native_sha = str(payload.get("native_state_sha256") or "")
        state: dict[str, Any] = {
            "source": "open_stream_checkpoint",
            "text_tail": str(payload.get("text_tail") or ""),
            "reasoning_tail": str(payload.get("reasoning_tail") or ""),
            "provider": str(payload.get("provider") or ""),
            "model": str(payload.get("model") or ""),
            "partial_sha256": str(payload.get("partial_sha256") or ""),
            "checkpoint_seq": int(getattr(checkpoint_event, "seq", 0) or 0),
        }
        if latest_checkpoint_event is not None:
            latest_payload = dict(getattr(latest_checkpoint_event, "payload", None) or {})
            state["latest_checkpoint_seq"] = int(
                getattr(latest_checkpoint_event, "seq", 0) or 0
            )
            if latest_checkpoint_event is not checkpoint_event:
                state["sparse_latest_skipped"] = True
                state["latest_checkpoint_model_chars"] = int(
                    latest_payload.get("text_chars") or 0
                ) + int(latest_payload.get("reasoning_chars") or 0)
                draft_count = int(latest_payload.get("tool_call_draft_count") or 0)
                native_chars = int(latest_payload.get("native_state_chars") or 0)
                if draft_count or native_chars:
                    mechanical_execution.setdefault(
                        "provider_state",
                        {
                            "round": int(latest_payload.get("round") or 0),
                            "provider": str(latest_payload.get("provider") or ""),
                            "model": str(latest_payload.get("model") or ""),
                            "tool_call_draft_count": draft_count,
                            "native_state_persisted": bool(native_chars),
                        },
                    )

        native = self._load_inflight_native_state(
            session_id,
            expected_sha256=native_sha,
            expected_round=int(payload.get("round") or 0),
            expected_provider=str(state.get("provider") or ""),
            expected_model=str(state.get("model") or ""),
            expected_partial_sha256=str(state.get("partial_sha256") or ""),
        )
        if native is not None:
            if isinstance(native.get("text_full"), str):
                state["text_tail"] = native["text_full"]
            if isinstance(native.get("reasoning_full"), str):
                state["reasoning_tail"] = native["reasoning_full"]
            state["full_snapshot"] = True
            if isinstance(native.get("provider_replay"), dict):
                state["provider_replay"] = native["provider_replay"]
            drafts = native.get("tool_call_drafts")
            if isinstance(drafts, list):
                state["tool_call_drafts"] = [
                    dict(item) for item in drafts if isinstance(item, dict)
                ]
            state["native_state_sha256"] = native_sha

        self._promote_open_model_checkpoint(session_id, checkpoint_event, payload, state)
        return state

    def _promote_open_model_checkpoint(
        self,
        session_id: str,
        checkpoint_event: Any,
        payload: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        """Make the selected useful checkpoint searchable before sidecar cleanup."""
        checkpoint_seq = int(getattr(checkpoint_event, "seq", 0) or 0)
        partial_sha = str(state.get("partial_sha256") or "")
        source_key = str(checkpoint_seq) if checkpoint_seq > 0 else partial_sha[:20]
        if not source_key:
            return
        trunc_ref = f"truncated:checkpoint:{source_key}"
        artifact_ref = ""
        if state.get("full_snapshot"):
            try:
                artifact_ref = self._capture_truncation_artifact(
                    session_id,
                    reason="open_stream_checkpoint",
                    round_no=int(payload.get("round") or 0),
                    provider=str(state.get("provider") or ""),
                    model=str(state.get("model") or ""),
                    text_full=str(state.get("text_tail") or ""),
                    reasoning_full=str(state.get("reasoning_tail") or ""),
                    partial_sha256=partial_sha,
                    provider_replay=(
                        state.get("provider_replay")
                        if isinstance(state.get("provider_replay"), dict)
                        else None
                    ),
                    tool_call_drafts=(
                        state.get("tool_call_drafts")
                        if isinstance(state.get("tool_call_drafts"), list)
                        else None
                    ),
                )
            except Exception:  # noqa: BLE001 — resume stays fail-open
                logger.warning("open-stream exact artifact 晋升失败", exc_info=True)
        index_truncated = getattr(getattr(self, "episode_store", None), "index_truncated_run", None)
        if not callable(index_truncated):
            return
        try:
            index_truncated(
                session_id,
                run_end_reason="open_stream_checkpoint",
                last_round=int(payload.get("round") or 0),
                run_end_seq=0,
                text_tail=str(payload.get("text_tail") or ""),
                reasoning_tail=str(payload.get("reasoning_tail") or ""),
                partial_chars=int(payload.get("text_chars") or 0)
                + int(payload.get("reasoning_chars") or 0),
                partial_sha256=partial_sha,
                artifact_ref=artifact_ref,
                ref=trunc_ref,
            )
            state["truncation_ref"] = trunc_ref
            if artifact_ref:
                state["artifact_ref"] = artifact_ref
        except Exception:  # noqa: BLE001 — resume stays fail-open
            logger.warning("open-stream truncated 索引失败", exc_info=True)

    def _prepare_open_interruption_resume(self, session_id: str) -> dict[str, Any] | None:
        """Merge latest useful model state with latest mechanical execution facts."""
        estore = getattr(self, "_event_store", None)
        if estore is None or not getattr(estore, "enabled", False):
            return None
        events = list(estore.read(session_id) or [])
        last_run_end = max(
            (pos for pos, event in enumerate(events) if str(getattr(event, "type", "")) == "run.end"),
            default=-1,
        )
        open_events = events[last_run_end + 1 :]
        # Current human ingress itself is appended after the last run.end, so it cannot
        # prove an interrupted prior run. Require an actual open execution/model fact
        # before surfacing session-wide nonterminal background jobs as recovery state.
        has_open_run_fact = any(
            str(getattr(event, "type", "")) == "request.meta"
            or str(getattr(event, "type", "")) == "llm.partial_checkpoint"
            or str(getattr(event, "type", "")).startswith("tool.execution.")
            or str(getattr(event, "type", "")).startswith("external.execution.")
            for event in open_events
        )
        if not has_open_run_fact:
            return None
        model_checkpoint, latest_checkpoint = select_open_checkpoint_events(open_events)
        mechanical = open_execution_facts(events, after_pos=last_run_end)
        state: dict[str, Any] | None = None
        if model_checkpoint is not None:
            state = self._materialize_open_model_checkpoint(
                session_id, model_checkpoint, latest_checkpoint, mechanical
            )
        elif latest_checkpoint is not None:
            payload = dict(getattr(latest_checkpoint, "payload", None) or {})
            native_sha = str(payload.get("native_state_sha256") or "")
            native = self._load_inflight_native_state(
                session_id,
                expected_sha256=native_sha,
                expected_round=int(payload.get("round") or 0),
                expected_provider=str(payload.get("provider") or ""),
                expected_model=str(payload.get("model") or ""),
                expected_partial_sha256=str(payload.get("partial_sha256") or ""),
            )
            replay = native.get("provider_replay") if isinstance(native, dict) else None
            if isinstance(replay, dict):
                seq = int(getattr(latest_checkpoint, "seq", 0) or 0)
                state = {
                    "source": "open_stream_checkpoint",
                    "text_tail": "",
                    "reasoning_tail": "",
                    "provider": str(payload.get("provider") or ""),
                    "model": str(payload.get("model") or ""),
                    "partial_sha256": str(payload.get("partial_sha256") or ""),
                    "provider_replay": replay,
                    "checkpoint_seq": seq,
                    "latest_checkpoint_seq": seq,
                }
        if mechanical:
            state = state or {
                "source": "open_execution_state",
                "text_tail": "",
                "reasoning_tail": "",
            }
            state["mechanical_execution"] = mechanical
        return state

    def _prepare_interruption_resume(self, session_id: str, sess) -> None:
        """Prepare one-shot exact model continuity for the current human ingress.

        Two durable sources are accepted, newest/open source winning:
        1) a persisted ``llm_interrupted`` assistant storage row from a controlled
           cancel/provider error/disconnect;
        2) the latest unsettled ``llm.partial_checkpoint`` after the most recent
           ``run.end`` (process restart/kill while streaming).

        The result lives only in the per-session run bucket.  It is not appended as
        conversational history and contains no program-authored recovery prose.
        """
        bucket = self._run_state()
        bucket.interruption_resume = None
        try:
            from llm_loop.core.episode_history import is_human_user_message

            messages = list(getattr(sess, "messages", []) or [])
            if not messages or not is_human_user_message(messages[-1]):
                return
            current_idx = len(messages) - 1
            previous_human = None
            for idx in range(current_idx - 1, -1, -1):
                if is_human_user_message(messages[idx]):
                    previous_human = idx
                    break

            persisted: dict[str, Any] | None = None
            if previous_human is not None:
                for idx in range(current_idx - 1, previous_human, -1):
                    message = messages[idx]
                    md = message.metadata if isinstance(message.metadata, dict) else {}
                    if md.get("llm_interrupted") is not True:
                        continue
                    provider_truncated = md.get("provider_truncated") is True
                    # Generic provider/model failure is a durable failure fact, not
                    # automatically a resumable stream. Do not feed its captured
                    # runaway reasoning back on the next human ingress. Exact
                    # provider truncation and open-stream crash checkpoints keep
                    # their existing continuity paths.
                    if not provider_truncated and str(md.get("run_end_reason") or "") == "llm_error":
                        break
                    # A later genuine model assistant means this partial was already
                    # superseded; never resurrect stale reasoning merely because it is
                    # still durable storage truth.
                    superseded = False
                    for later in messages[idx + 1 : current_idx]:
                        lmd = later.metadata if isinstance(later.metadata, dict) else {}
                        if (
                            later.role == "assistant"
                            and lmd.get("answer_origin") == "model"
                            and lmd.get("llm_interrupted") is not True
                        ):
                            superseded = True
                            break
                    if superseded:
                        break
                    text_tail = str(md.get("interrupted_text_tail") or "")
                    if not text_tail:
                        # Backward-compatible recovery for pre-contract rows: use only
                        # the model-origin portion before the human-readable truncation
                        # annotation; never feed the program annotation back.
                        raw = str(message.content or "")
                        if "\n[截断标注]" in raw:
                            text_tail = raw.split("\n[截断标注]", 1)[0]
                        elif not raw.startswith("[截断标注]"):
                            text_tail = raw
                    reasoning_tail = str(
                        md.get("interrupted_reasoning_tail")
                        or message.reasoning_content
                        or ""
                    )
                    native_sha = str(md.get("interrupted_native_state_sha256") or "")
                    if text_tail or reasoning_tail or native_sha:
                        persisted = {
                            "source": (
                                "persisted_provider_truncated"
                                if provider_truncated
                                else "persisted_interrupted"
                            ),
                            "text_tail": text_tail,
                            "reasoning_tail": reasoning_tail,
                            "provider": str(md.get("interrupted_provider") or ""),
                            "model": str(
                                md.get("interrupted_model")
                                or getattr(message, "model_used", "")
                                or ""
                            ),
                            "partial_sha256": str(md.get("partial_sha256") or ""),
                            "provider_truncated": provider_truncated,
                            "finish_reason": str(
                                md.get("provider_finish_reason")
                                or md.get("run_end_reason")
                                or ""
                            ),
                        }
                        native = self._load_inflight_native_state(
                            session_id,
                            expected_sha256=native_sha,
                            expected_provider=str(persisted.get("provider") or ""),
                            expected_model=str(persisted.get("model") or ""),
                            expected_partial_sha256=str(persisted.get("partial_sha256") or ""),
                        )
                        if native is not None:
                            full_text = native.get("text_full")
                            full_reasoning = native.get("reasoning_full")
                            if isinstance(full_text, str):
                                persisted["text_tail"] = full_text
                            if isinstance(full_reasoning, str):
                                persisted["reasoning_tail"] = full_reasoning
                            persisted["full_snapshot"] = True
                            replay = native.get("provider_replay")
                            drafts = native.get("tool_call_drafts")
                            if isinstance(replay, dict):
                                persisted["provider_replay"] = replay
                            if isinstance(drafts, list):
                                persisted["tool_call_drafts"] = [
                                    dict(item) for item in drafts if isinstance(item, dict)
                                ]
                            persisted["native_state_sha256"] = native_sha
                    break

            open_checkpoint = self._prepare_open_interruption_resume(session_id)

            state = open_checkpoint or persisted
            if state is None:
                return
            bucket.interruption_resume = state
            with contextlib.suppress(Exception):
                self._record_action(
                    "run.interruption_resume",
                    "prepared",
                    "source={};model={};chars={}".format(
                        state.get("source", ""),
                        state.get("model", ""),
                        len(state.get("text_tail", ""))
                        + len(state.get("reasoning_tail", "")),
                    ),
                )
        except Exception:  # noqa: BLE001 — continuity is fail-open, never blocks ingress
            bucket.interruption_resume = None
            logger.debug("中断续思准备失败（fail-open）", exc_info=True)

    def _persist_long_answer(self, session_id: str, final_answer: str) -> str:
        """EVO-20260820-5bf342ae ②: 长回答（>8000 chars）落盘并附路径（信息零丢失）.

        路径用内容哈希（非时间戳）——final_answer 作为 assistant 消息进历史后续轮次
        回传，时间戳路径每轮变 → 该消息字节变 → 前缀断（12 实验规律，2026-08-21 修复）；
        内容哈希: 同一回答→同路径（回传稳定命中）。fail-open: 落盘失败返回原样不阻断。
        """
        try:
            if final_answer and len(final_answer) > 8000:
                import hashlib
                import uuid

                _sid = _validate_session_id(session_id)
                _la_dir = Path(self.settings.data_dir) / "audit" / "long_answers" / _sid
                _la_dir.mkdir(parents=True, exist_ok=True)
                _la_digest = hashlib.sha256(final_answer.encode("utf-8", errors="replace")).hexdigest()[:16]
                _la_file = _la_dir / f"{_la_digest}.md"
                _tmp = _la_dir / f".{_la_file.name}.{uuid.uuid4().hex}.tmp"
                try:
                    _tmp.write_text(final_answer, encoding="utf-8")
                    _tmp.replace(_la_file)
                finally:
                    _tmp.unlink(missing_ok=True)
                return f"{final_answer}\n\n[长回答已落盘] {_la_file}"
        except Exception:  # noqa: BLE001 — 落盘失败 fail-open
            logger.debug("长回答落盘失败（fail-open）")
        return final_answer

    def _set_session_override(self, sess, value: str | None) -> None:
        """M48（design §5.3）: switch_model 调用的会话 override 写入回调.

        直接修改 in-memory sess（引用已加载的 Session 对象）, loop 末 self.session.save(sess)
        会自动持久化。失败由 tools_model.run_switch_model 内部捕获并如实回执。
        """
        sess.model_override = value
        if self.correction_ctx is not None:
            self.correction_ctx.session_model_override = value

    def _resolve_session_binding(self, session_id: str):
        """P0-5: 按会话解析 switch_model 绑定（getter/setter），供 registry_model 经
        contextvar 定位本会话 sess——并发 run 各自写自己的 Session 对象.
        会话不在活跃绑定表（非 run 期间调用）→ None，调用方回退 ctx 环境字段.
        """
        with self._run_state_mgr.guard:
            sess = self._run_sessions.get(session_id)
        if sess is None:
            return None
        return (
            lambda: sess.model_override,
            lambda value: self._set_session_override(sess, value),
        )

    def _resolve_current_episode_ref(self, session_id: str) -> str:
        """Mechanically derive the active human turn's eventual Episode ref.

        ``stable_episode_ref`` is also used by final Episode indexing.  Deriving
        it here from the exact in-memory user message + its real message index
        makes provenance available during tool execution without trusting a
        model-supplied id or accidentally using the previous durable episode.
        """
        if self._run_state_mgr.bound_session_id() != session_id:
            return ""
        with self._run_state_mgr.guard:
            sess = self._run_sessions.get(session_id)
        if sess is None:
            return ""
        turn_ref = self._run_state().current_turn_ref
        if turn_ref is None or turn_ref < 0 or turn_ref >= len(sess.messages):
            return ""
        user_message = sess.messages[turn_ref]
        if not is_human_user_message(user_message):
            return ""
        return stable_episode_ref(session_id, user_message, turn_ref)

    def _check_event_rotate(self, session_id: str) -> None:
        """P1-1: run 末事件日志滚动检查（fail-open；未接线/未启用零行为）."""
        store = self._event_store
        if store is None:
            return
        try:
            store.check_rotate(session_id)
        except Exception:  # noqa: BLE001 — 滚动检查失败不影响 run 结果
            logger.warning("事件日志滚动检查失败（fail-open）: sid=%s", session_id, exc_info=True)

    def _on_stream_disconnect(self, sess, partial_parts: list[str]) -> None:
        """Persist genuine model partial output on client disconnect without program prose.

        The historical implementation appended ``[对话已中断]`` to assistant content.
        That annotation could re-enter a later provider request as if the model had said
        it.  Interruption is runtime metadata/event state; only bytes actually emitted by
        the model belong in assistant content.  Even with zero partial text we still save
        the session so the user ingress/event log cannot drift from the JSON snapshot.
        """
        partial = "".join(partial_parts).strip()
        try:
            self._event_append(
                sess.session_id,
                "llm.interrupted",
                {
                    "reason": "client_disconnect",
                    "partial_chars": len(partial),
                },
            )
            if partial:
                msg = Message(
                    role="assistant",
                    content=partial,
                    source=MessageSource.USER,
                    metadata={
                        "answer_origin": "model",
                        "run_end_reason": "client_disconnect",
                        "llm_interrupted": True,
                        "episode_resolution_candidate": False,
                    },
                )
                sess.messages.append(msg)
                self._append_message_event(sess, msg)
            self.session.save(sess)
        except Exception:  # noqa: BLE001 -- disconnect close path must remain fail-open
            logger.warning("断连会话保存失败（fail-open）: sid=%s", sess.session_id, exc_info=True)

    # ── B1(EVO-20260902-41898b20)：取消/出错中断的半截产物限量落盘 ──

    @staticmethod
    def _env_tail_limit(name: str, default: int) -> int:
        """尾部限量 env 读取（非负 int；非法/缺省回退 default；0=关闭该项）。"""
        raw = os.environ.get(name)
        if raw is None or raw == "":
            return default
        try:
            return max(0, int(raw))
        except ValueError:
            return default

    def _inflight_native_state_path(self, session_id: str) -> Path:
        """Return the private overwrite-only sidecar for provider-native crash state."""
        sid = _validate_session_id(session_id)
        return Path(self.settings.data_dir) / "audit" / "inflight" / f"{sid}.json"

    def _persist_inflight_native_state(
        self,
        session_id: str,
        *,
        round_no: int,
        provider: str,
        model: str,
        partial_sha256: str,
        text_full: str = "",
        reasoning_full: str = "",
        provider_replay: dict[str, Any] | None,
        tool_call_drafts: list[dict[str, Any]] | None,
    ) -> tuple[str, int, int]:
        """Atomically persist full in-flight model state + opaque provider state.

        The append-only event keeps only bounded tails + digest; this private sidecar
        keeps all model bytes received so far, plus provider replay and non-executable
        tool drafts.  Recovery accepts it only when the digest matches.  Tool drafts
        are storage facts, never executable ToolCalls.
        """
        if not text_full and not reasoning_full and not provider_replay and not tool_call_drafts:
            return "", 0, 0
        snapshot = {
            "version": 1,
            "session_id": str(session_id),
            "round": int(round_no or 0),
            "provider": str(provider or ""),
            "model": str(model or ""),
            "partial_sha256": str(partial_sha256 or ""),
            "text_full": str(text_full or ""),
            "reasoning_full": str(reasoning_full or ""),
            "provider_replay": provider_replay if isinstance(provider_replay, dict) else None,
            "tool_call_drafts": [
                dict(item) for item in (tool_call_drafts or []) if isinstance(item, dict)
            ],
        }
        raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()
        path = self._inflight_native_state_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(raw, encoding="utf-8")
            with contextlib.suppress(OSError):
                tmp.chmod(0o600)
            tmp.replace(path)
            with contextlib.suppress(OSError):
                path.chmod(0o600)
        finally:
            tmp.unlink(missing_ok=True)
        return digest, len(raw), len(snapshot["tool_call_drafts"])

    def _load_inflight_native_state(
        self,
        session_id: str,
        *,
        expected_sha256: str,
        expected_round: int | None = None,
        expected_provider: str = "",
        expected_model: str = "",
        expected_partial_sha256: str = "",
    ) -> dict[str, Any] | None:
        """Load a sidecar only when its content digest matches the checkpoint fact."""
        if not expected_sha256:
            return None
        try:
            raw = self._inflight_native_state_path(session_id).read_text(encoding="utf-8")
            digest = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()
            if digest != expected_sha256:
                return None
            value = json.loads(raw)
            if not isinstance(value, dict):
                return None
            if expected_round is not None and int(value.get("round") or 0) != int(expected_round):
                return None
            if expected_provider and str(value.get("provider") or "") != expected_provider:
                return None
            if expected_model and str(value.get("model") or "") != expected_model:
                return None
            if (
                expected_partial_sha256
                and str(value.get("partial_sha256") or "") != expected_partial_sha256
            ):
                return None
            return value
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _clear_inflight_native_state(self, session_id: str) -> None:
        """Best-effort cleanup after a later completed run supersedes crash state."""
        with contextlib.suppress(OSError, ValueError):
            self._inflight_native_state_path(session_id).unlink(missing_ok=True)

    def _capture_truncation_artifact(
        self,
        session_id: str,
        *,
        reason: str,
        round_no: int,
        provider: str,
        model: str,
        text_full: str = "",
        reasoning_full: str = "",
        partial_sha256: str = "",
        provider_replay: dict[str, Any] | None = None,
        tool_call_drafts: list[dict[str, Any]] | None = None,
    ) -> str:
        """Persist exact model-origin partial bytes before any bounded tail projection.

        This is storage/retrieval only. The returned artifact never authorizes replay;
        provider continuation eligibility remains owned by the existing continuity path.
        """
        store = getattr(self, "episode_store", None)
        capture = getattr(store, "capture_truncated_artifact", None)
        if not callable(capture):
            return ""
        return str(
            capture(
                session_id,
                reason=reason,
                round_no=round_no,
                provider=provider,
                model=model,
                text_full=text_full,
                reasoning_full=reasoning_full,
                partial_sha256=partial_sha256,
                provider_replay=provider_replay,
                tool_call_drafts=tool_call_drafts,
            )
            or ""
        )

    def _tool_execution_journal(self) -> ToolExecutionJournal:
        """Return the shared mechanical WAL facade used by every execution loop."""
        return ToolExecutionJournal(
            event_store=getattr(self, "_event_store", None),
            result_root=Path(self.settings.data_dir) / "audit" / "tool_execution",
            session_store=self.session,
            event_append=self._event_append,
            message_event_append=self._append_message_event,
            receipt_committed_hook=getattr(self, "_tool_receipt_committed_hook", None),
        )

    @staticmethod
    def _tool_execution_id(session_id: str, round_no: int, call: Any) -> str:
        return ToolExecutionJournal.execution_id(session_id, round_no, call)

    def _tool_execution_result_path(self, session_id: str, execution_id: str) -> Path:
        return self._tool_execution_journal().result_path(session_id, execution_id)

    @staticmethod
    def _tool_message_snapshot(message: Message) -> dict[str, Any]:
        return ToolExecutionJournal.message_snapshot(message)

    @staticmethod
    def _tool_message_from_snapshot(snapshot: dict[str, Any]) -> Message:
        return ToolExecutionJournal.message_from_snapshot(snapshot)

    def _tool_execution_declared(self, sess, call: Any, *, round_no: int) -> str:
        return self._tool_execution_journal().declared(sess, call, round_no=round_no)

    def _tool_execution_started(
        self, session_id: str, *, execution_id: str, round_no: int, call: Any
    ) -> bool:
        return self._tool_execution_journal().started(
            session_id, execution_id=execution_id, round_no=round_no, call=call
        )

    def _tool_execution_finished(
        self,
        session_id: str,
        *,
        execution_id: str,
        round_no: int,
        call: Any,
        tool_message: Message,
    ) -> str:
        return self._tool_execution_journal().finished(
            session_id,
            execution_id=execution_id,
            round_no=round_no,
            call=call,
            tool_message=tool_message,
        )

    def _load_tool_execution_result(
        self, session_id: str, execution_id: str, *, expected_sha256: str
    ) -> Message | None:
        return self._tool_execution_journal().load_result(
            session_id, execution_id, expected_sha256=expected_sha256
        )

    def _tool_execution_receipt_committed(
        self,
        session_id: str,
        *,
        execution_id: str,
        round_no: int,
        tool_call_id: str,
        tool_name: str,
        result_state_sha256: str = "",
        recovered: bool = False,
        tool_message: Message | None = None,
    ) -> bool:
        return self._tool_execution_journal().receipt_committed(
            session_id,
            execution_id=execution_id,
            round_no=round_no,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            result_state_sha256=result_state_sha256,
            recovered=recovered,
            tool_message=tool_message,
        )

    def _recover_inflight_tool_executions(self, session_id: str, sess) -> int:
        recovered = self._tool_execution_journal().recover(session_id, sess)
        if recovered:
            self._record_action(
                "run.tool_execution_recovery",
                "recovered",
                f"count={recovered};auto_reexecuted=0;prompt_chars=0",
            )
        return recovered

    def _on_llm_partial_checkpoint(
        self,
        sess,
        *,
        text_parts: list[str],
        reasoning_parts: list[str],
        round_no: int = 0,
        provider: str = "",
        model: str = "",
        provider_replay: dict[str, Any] | None = None,
        tool_call_drafts: list[dict[str, Any]] | None = None,
    ) -> None:
        """Persist an in-flight model-output checkpoint without creating chat history.

        The checkpoint is model-origin recovery state for process restart/crash, not
        a completed assistant message and not a program instruction.  Normal run.end
        or a later completed assistant settles it; only an otherwise-open stream may
        be projected once on the next genuine human ingress.
        """
        try:
            text_full = "".join(text_parts)
            reasoning_full = "".join(reasoning_parts)
            if (
                not text_full
                and not reasoning_full
                and not provider_replay
                and not tool_call_drafts
            ):
                return
            text_limit = self._env_tail_limit("INTERRUPT_TEXT_TAIL_CHARS", 4000)
            reasoning_limit = self._env_tail_limit("INTERRUPT_REASONING_TAIL_CHARS", 8000)
            text_tail = text_full[-text_limit:] if text_limit and text_full else ""
            reasoning_tail = (
                reasoning_full[-reasoning_limit:]
                if reasoning_limit and reasoning_full
                else ""
            )
            partial_sha = hashlib.sha256(
                (text_full + reasoning_full).encode("utf-8", "replace")
            ).hexdigest()
            native_sha = ""
            native_chars = 0
            draft_count = 0
            try:
                native_sha, native_chars, draft_count = self._persist_inflight_native_state(
                    sess.session_id,
                    round_no=round_no,
                    provider=provider,
                    model=model,
                    partial_sha256=partial_sha,
                    text_full=text_full,
                    reasoning_full=reasoning_full,
                    provider_replay=provider_replay,
                    tool_call_drafts=tool_call_drafts,
                )
            except Exception:  # noqa: BLE001 — full/native sidecar is fail-open
                logger.debug("provider-native in-flight sidecar 写入失败（fail-open）", exc_info=True)
            self._event_append(
                sess.session_id,
                "llm.partial_checkpoint",
                {
                    "round": int(round_no or 0),
                    "provider": str(provider or ""),
                    "model": str(model or ""),
                    "text_tail": text_tail,
                    "reasoning_tail": reasoning_tail,
                    "text_chars": len(text_full),
                    "reasoning_chars": len(reasoning_full),
                    "partial_sha256": partial_sha,
                    "native_state_sha256": native_sha,
                    "native_state_chars": native_chars,
                    "tool_call_draft_count": draft_count,
                },
            )
        except Exception:  # noqa: BLE001 — checkpointing must never break streaming
            logger.debug("LLM in-flight checkpoint 写入失败（fail-open）", exc_info=True)

    def _on_llm_interrupted(
        self,
        sess,
        *,
        text_parts: list[str],
        reasoning_parts: list[str],
        reason: str,
        error_digest: str = "",
        round_no: int = 0,
        provider: str = "",
        model: str = "",
        provider_replay: dict[str, Any] | None = None,
        tool_call_drafts: list[dict[str, Any]] | None = None,
        transport_facts: dict[str, Any] | None = None,
        timing: dict[str, Any] | None = None,
    ) -> None:
        """B1(EVO-20260902-41898b20)：user_stop/llm_error 中断时半截产物落盘.

        仿 P1-6 `_on_stream_disconnect` 纪律：如实标注（不伪装完整）+ 会话/事件
        双轨 + 立即保存 + 全程 fail-open（事件日志为主锚）。差异：
        - 尾部限量保存（INTERRUPT_TEXT_TAIL_CHARS 默认 4000 / INTERRUPT_REASONING_TAIL_CHARS
          默认 8000；设 0 关闭该项），超限前缀如实标注"仅尾部 N/M 字符"；
        - 推理尾随行落 `reasoning_content`（Message 原生字段，存储面本就持久化）；
        - 缓存 `self._last_interrupted` 供 B2 truncated episode 索引；
        - `llm.interrupted` 事件恒写（零内容中断同样可检索）；
        - llm_error 且零内容时不加独立消息行（噪声控制；事实由事件+truncated 索引承载）。

        wire 安全：metadata.llm_interrupted=true → lifecycle provider projection 直接
        退役本行；存储/事件/truncated 索引仍保留真相，零新增 provider 面。
        """
        try:
            text_full = "".join(text_parts)
            reasoning_full = "".join(reasoning_parts)
            total_partial = len(text_full) + len(reasoning_full)
            partial_sha = hashlib.sha256(
                (text_full + reasoning_full).encode("utf-8", "replace")
            ).hexdigest()
            artifact_ref = ""
            artifact_store_available = callable(
                getattr(getattr(self, "episode_store", None), "capture_truncated_artifact", None)
            )
            try:
                artifact_ref = self._capture_truncation_artifact(
                    sess.session_id,
                    reason=str(reason or ""),
                    round_no=round_no,
                    provider=provider,
                    model=model,
                    text_full=text_full,
                    reasoning_full=reasoning_full,
                    partial_sha256=partial_sha,
                    provider_replay=provider_replay,
                    tool_call_drafts=tool_call_drafts,
                )
            except Exception:  # noqa: BLE001 — interruption delivery must still close
                logger.warning(
                    "中断 exact artifact 写入失败；回退会话全文持久化", exc_info=True
                )
            text_limit = self._env_tail_limit("INTERRUPT_TEXT_TAIL_CHARS", 4000)
            reasoning_limit = self._env_tail_limit("INTERRUPT_REASONING_TAIL_CHARS", 8000)
            if artifact_ref or not artifact_store_available:
                text_tail = text_full[-text_limit:] if text_limit and text_full else ""
                reasoning_tail = (
                    reasoning_full[-reasoning_limit:]
                    if reasoning_limit and reasoning_full
                    else ""
                )
            else:
                # A configured exact store failed. Do not discard model bytes in the
                # same path that just failed to create their long-term recovery source.
                text_tail = text_full
                reasoning_tail = reasoning_full
            native_sha = ""
            native_chars = 0
            draft_count = 0
            try:
                native_sha, native_chars, draft_count = self._persist_inflight_native_state(
                    sess.session_id,
                    round_no=round_no,
                    provider=provider,
                    model=model,
                    partial_sha256=partial_sha,
                    text_full=text_full,
                    reasoning_full=reasoning_full,
                    provider_replay=provider_replay,
                    tool_call_drafts=tool_call_drafts,
                )
            except Exception:  # noqa: BLE001 — full/native sidecar is fail-open
                logger.debug("中断 provider-native sidecar 写入失败（fail-open）", exc_info=True)
            info: dict[str, Any] = {
                "round": int(round_no or 0),
                "reason": str(reason or ""),
                "error_digest": str(error_digest or "")[:200],
                "text_tail": text_tail,
                "reasoning_tail": reasoning_tail,
                "partial_chars": total_partial,
                "partial_sha256": partial_sha,
                "native_state_sha256": native_sha,
                "artifact_ref": artifact_ref,
            }
            self._last_interrupted = info  # B2 truncated 索引数据源（run 结束时消费）
            # 事件主锚：恒写（审计与 B2 索引共用数据源；fail-open 内置）
            self._event_append(
                sess.session_id,
                "llm.interrupted",
                {
                    "round": info["round"],
                    "reason": info["reason"],
                    "error_digest": info["error_digest"],
                    "text_tail_chars": len(text_tail),
                    "reasoning_tail_chars": len(reasoning_tail),
                    "partial_chars": total_partial,
                    "partial_sha256": partial_sha,
                    "native_state_sha256": native_sha,
                    "truncation_artifact_ref": artifact_ref,
                    "native_state_chars": native_chars,
                    "tool_call_draft_count": draft_count,
                    "finish_reason": str((transport_facts or {}).get("finish_reason") or ""),
                    "completion_tokens": (transport_facts or {}).get("completion_tokens"),
                    "reasoning_tokens": (transport_facts or {}).get("reasoning_tokens"),
                    "provider_truncated": (transport_facts or {}).get("provider_truncated"),
                    "timing": dict(timing or {}),
                },
            )
            if not text_tail and not reasoning_tail and info["reason"] != "cancelled":
                return  # llm_error 零半截产物：不加消息行（不伪装、不加噪）
            note = f"\n[截断标注] reason={info['reason']}; 保存尾 {len(text_tail)}/{len(text_full)} 字符"
            if len(reasoning_full) > len(reasoning_tail):
                note += f"; 推理保存尾 {len(reasoning_tail)}/{len(reasoning_full)} 字符"
            if info["error_digest"]:
                note += f"; error={info['error_digest']}"
            if text_tail:
                content = text_tail + note  # 如实标注：尾部非完整回答
            else:
                head = f"[截断标注] 本回合被中断（reason={info['reason']}）。"
                if text_full and not text_tail:
                    head += "回答文本未保存（tail limit=0）。"
                elif not text_full:
                    head += "未产生回答内容。"
                if reasoning_tail:
                    head += f"推理保存尾 {len(reasoning_tail)} 字符。"
                content = head + note.strip()
            msg = Message(
                role="assistant",
                content=content,
                source=MessageSource.SYSTEM,
                reasoning_content=reasoning_tail or None,
                metadata={
                    "answer_origin": "program",
                    "run_end_reason": info["reason"],
                    "llm_interrupted": True,
                    "partial_chars": total_partial,
                    "partial_sha256": partial_sha,
                    # Exact model-origin tails are kept separately from the
                    # human-readable truncation annotation in ``content`` so the
                    # next-run continuity projection never feeds program prose back
                    # to the model.
                    "interrupted_text_tail": text_tail,
                    "interrupted_reasoning_tail": reasoning_tail,
                    "interrupted_provider": str(provider or ""),
                    "interrupted_model": str(model or ""),
                    "interrupted_native_state_sha256": native_sha,
                    "truncation_artifact_ref": artifact_ref,
                    "interrupted_tool_call_draft_count": draft_count,
                },
            )
            sess.messages.append(msg)
            self._append_message_event(sess, msg)  # 双轨：事件同步（fail-open 内置）
            self.session.save(sess)  # 闭合双轨漂移（同 P1-6）
        except Exception:  # noqa: BLE001 — 中断落盘失败不抛穿（取消/异常路径）
            logger.warning(
                "中断半截产物落盘失败（fail-open）: sid=%s reason=%s",
                getattr(sess, "session_id", "?"),
                reason,
                exc_info=True,
            )
