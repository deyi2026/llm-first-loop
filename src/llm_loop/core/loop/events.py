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
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import _validate_session_id
from llm_loop.event_log.model import build_message_payload
from llm_loop.introspection.events import ArchitectureEvent, ArchitectureEventType

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

    def _append_message_event(self, sess, msg: Message) -> None:
        """消息落库点事件（payload 与 Session.to_dict() 消息字段逐一对齐）."""
        store = getattr(self, "_event_store", None)
        if store is None or getattr(store, "enabled", False) is False:
            return
        try:
            store.append(
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
    ) -> Message | None:
        """推送式架构上报（冷却去重）；返回可注入消息或 None."""
        if self.status is None or not self.status.enabled:
            return None
        event = ArchitectureEvent(
            event_type=event_type, fact=fact, reason=reason, suggestion=suggestion
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

        The current user has already been appended to ``sess`` (and normally to the
        event log) before this hook runs.  Repair therefore preserves that live object,
        validates the pre-user prefix against event replay, inserts only replay-only
        historical messages before the current user, and records observability with
        ``prompt_chars=0``.  Replay/prefix failure is fail-open: keep the live session
        untouched and report the repair failure out of band; never synthesize prompt
        prose.
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
        # EVO-20260825 任务8（§5.8）: emergency_compact 后 60s 内 switch_model →
        # wasted 审计（紧急压缩锚点前移归档被模型切换覆盖——前缀按新模型重建白做）。
        try:
            _cm = getattr(self, "_cache_monitor", None)
            if _cm is not None and value:
                _cm.note_switch_model_after_compact(sess.session_id, value)
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("switch_model 覆盖检测审计异常（fail-open）", exc_info=True)

    def _resolve_session_binding(self, session_id: str):
        """P0-5: 按会话解析 switch_model 绑定（getter/setter），供 registry_model 经
        contextvar 定位本会话 sess——并发 run 各自写自己的 Session 对象.
        会话不在活跃绑定表（非 run 期间调用）→ None，调用方回退 ctx 环境字段.
        """
        with self._run_states_guard:
            sess = self._run_sessions.get(session_id)
        if sess is None:
            return None
        return (
            lambda: sess.model_override,
            lambda value: self._set_session_override(sess, value),
        )

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
        """P1-6(2026-08-15，审计发现 #17)：LLM 流式中客户端断连（GeneratorExit）的落盘处理.

        部分回答如实落会话（中断标注，不伪装完整）+ 事件双轨同步 + 立即保存——
        闭合"事件日志已追加而 session JSON 未保存"的双轨漂移。保存失败 fail-open。
        """
        partial = "".join(partial_parts).strip()
        note = "\n[对话已中断] 客户端断连，以上为不完整部分回答（如实标注，可能截断于任意位置）。"
        content = (partial + note) if partial else "[对话已中断] 客户端断连，本回合未产生回答内容。"
        msg = Message(role="assistant", content=content, source=MessageSource.SYSTEM)
        sess.messages.append(msg)
        try:
            self._append_message_event(sess, msg)  # 双轨：事件同步（fail-open 内置）
            self.session.save(sess)
        except Exception:  # noqa: BLE001 — 断连保存失败不抛穿（生成器关闭路径）
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

    def _on_llm_interrupted(
        self,
        sess,
        *,
        text_parts: list[str],
        reasoning_parts: list[str],
        reason: str,
        error_digest: str = "",
        round_no: int = 0,
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

        wire 安全：metadata.answer_origin="program" → 投影层既有谓词（base_assembly）
        将本行替换为字节稳定 `[program-final]` 占位且 reasoning 置 None，零新增 provider 面。
        """
        try:
            text_full = "".join(text_parts)
            reasoning_full = "".join(reasoning_parts)
            text_limit = self._env_tail_limit("INTERRUPT_TEXT_TAIL_CHARS", 4000)
            reasoning_limit = self._env_tail_limit("INTERRUPT_REASONING_TAIL_CHARS", 8000)
            text_tail = text_full[-text_limit:] if text_limit and text_full else ""
            reasoning_tail = reasoning_full[-reasoning_limit:] if reasoning_limit and reasoning_full else ""
            total_partial = len(text_full) + len(reasoning_full)
            partial_sha = hashlib.sha256(
                (text_full + reasoning_full).encode("utf-8", "replace")
            ).hexdigest()
            info: dict[str, Any] = {
                "round": int(round_no or 0),
                "reason": str(reason or ""),
                "error_digest": str(error_digest or "")[:200],
                "text_tail": text_tail,
                "reasoning_tail": reasoning_tail,
                "partial_chars": total_partial,
                "partial_sha256": partial_sha,
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
