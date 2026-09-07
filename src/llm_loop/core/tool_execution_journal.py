"""Reusable crash-safe tool execution journal.

This module owns only mechanical execution facts. It never decides whether a tool
should be called, retried, or considered semantically sufficient. A caller that has
a durable assistant(tool_calls) declaration may use the journal to record
``declared -> started -> finished -> receipt_committed``. Recovery closes incomplete
states without automatically re-executing a tool whose outcome is unknown.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal, cast

from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.core.session import Session, SessionStore, _validate_session_id
from llm_loop.event_log.model import build_message_payload

logger = logging.getLogger(__name__)


class _EffectBinding:
    """Process-local bridge from one WAL execution attempt to a mechanical tool effect."""

    __slots__ = (
        "journal",
        "session_id",
        "execution_id",
        "round_no",
        "tool_call_id",
        "tool_name",
        "workspace_root",
    )

    def __init__(
        self,
        *,
        journal: ToolExecutionJournal,
        session_id: str,
        execution_id: str,
        round_no: int,
        tool_call_id: str,
        tool_name: str,
        workspace_root: str,
    ) -> None:
        self.journal = journal
        self.session_id = session_id
        self.execution_id = execution_id
        self.round_no = round_no
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name
        self.workspace_root = workspace_root


_current_effect_binding: contextvars.ContextVar[_EffectBinding | None] = contextvars.ContextVar(
    "llm_loop_tool_effect_binding", default=None
)
_current_effect_bindings: contextvars.ContextVar[dict[str, _EffectBinding] | None] = (
    contextvars.ContextVar("llm_loop_tool_effect_bindings", default=None)
)


def current_tool_effect_binding() -> _EffectBinding | None:
    """Return the exact process-local execution binding visible to the current tool call."""
    return _current_effect_binding.get()


@contextlib.contextmanager
def activate_effect_binding_for_call(tool_call_id: str) -> Iterator[None]:
    """Select one binding from a batch before copying context into the tool worker thread."""
    bindings = _current_effect_bindings.get()
    binding = bindings.get(str(tool_call_id or "")) if bindings else None
    if binding is None:
        yield
        return
    token = _current_effect_binding.set(binding)
    try:
        yield
    finally:
        _current_effect_binding.reset(token)


class ToolExecutionJournal:
    """One mechanical WAL contract shared by LoopEngine and SubAgentRunner."""

    def __init__(
        self,
        *,
        event_store: Any | None,
        result_root: str | Path,
        session_store: SessionStore,
        event_append: Callable[[str, str, dict], Any] | None = None,
        message_event_append: Callable[[Session, Message], Any] | None = None,
        receipt_committed_hook: Callable[[str, Message], object] | None = None,
    ) -> None:
        self.event_store = event_store
        self.result_root = Path(result_root)
        self.session_store = session_store
        self._event_append_override = event_append
        self._message_event_append_override = message_event_append
        self._receipt_committed_hook = receipt_committed_hook

    @property
    def enabled(self) -> bool:
        return self.event_store is not None and bool(getattr(self.event_store, "enabled", False))

    def _append_event(self, session_id: str, event_type: str, payload: dict) -> Any | None:
        if self._event_append_override is not None:
            return self._event_append_override(session_id, event_type, payload)
        store = self.event_store
        if store is None or not bool(getattr(store, "enabled", False)):
            return None
        try:
            return store.append(session_id, event_type, payload)
        except Exception:  # noqa: BLE001 - observability transport is fail-open
            logger.warning("tool execution WAL event write failed: %s", event_type, exc_info=True)
            return None

    def _append_message_event(self, sess: Session, msg: Message) -> Any | None:
        if self._message_event_append_override is not None:
            return self._message_event_append_override(sess, msg)
        store = self.event_store
        if store is None or not bool(getattr(store, "enabled", False)):
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
        except Exception:  # noqa: BLE001 - recovery never re-executes on logging failure
            logger.warning("tool execution recovery message event write failed", exc_info=True)
            return None

    @staticmethod
    def execution_id(session_id: str, round_no: int, call: Any) -> str:
        """Stable attempt id without exposing raw arguments in the event stream."""
        raw = json.dumps(
            {
                "session_id": str(session_id),
                "round": int(round_no or 0),
                "tool_call_id": str(getattr(call, "id", "") or ""),
                "tool_name": str(getattr(call, "name", "") or ""),
                "arguments": getattr(call, "arguments", {}) or {},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:32]

    def result_path(self, session_id: str, execution_id: str) -> Path:
        sid = _validate_session_id(session_id)
        safe_id = hashlib.sha256(str(execution_id).encode("utf-8", "replace")).hexdigest()[:32]
        return self.result_root / sid / f"{safe_id}.json"

    @staticmethod
    def message_snapshot(message: Message) -> dict[str, Any]:
        return {
            "role": message.role,
            "content": message.content,
            "source": message.source.value,
            "tool_call_id": message.tool_call_id,
            "status": message.status.value if message.status else None,
            "tool_name": message.tool_name,
            "error_detail": message.error_detail,
            "tool_calls": message.tool_calls,
            "reasoning_content": message.reasoning_content,
            "duration_ms": message.duration_ms,
            "metadata": dict(message.metadata or {}),
        }

    @staticmethod
    def message_from_snapshot(snapshot: dict[str, Any]) -> Message:
        status = None
        raw_status = snapshot.get("status")
        if raw_status:
            with contextlib.suppress(ValueError):
                status = ToolResultStatus(str(raw_status))
        source = MessageSource.SYSTEM
        with contextlib.suppress(ValueError):
            source = MessageSource(str(snapshot.get("source") or "system"))
        raw_role = str(snapshot.get("role") or "tool")
        role = cast(
            Literal["user", "assistant", "tool", "system"],
            raw_role if raw_role in {"user", "assistant", "tool", "system"} else "tool",
        )
        return Message(
            role=role,
            content=str(snapshot.get("content") or ""),
            source=source,
            tool_call_id=str(snapshot.get("tool_call_id") or "") or None,
            status=status,
            tool_name=str(snapshot.get("tool_name") or "") or None,
            error_detail=snapshot.get("error_detail"),
            tool_calls=snapshot.get("tool_calls"),
            reasoning_content=snapshot.get("reasoning_content"),
            duration_ms=float(snapshot.get("duration_ms") or 0.0),
            metadata=dict(snapshot.get("metadata") or {}),
        )

    def declared(self, sess: Session, call: Any, *, round_no: int) -> str:
        """Persist declaration after the assistant(tool_calls) frame is durable."""
        execution_id = self.execution_id(sess.session_id, round_no, call)
        args_raw = json.dumps(
            getattr(call, "arguments", {}) or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        event = self._append_event(
            sess.session_id,
            "tool.execution.declared",
            {
                "execution_id": execution_id,
                "round": int(round_no or 0),
                "tool_call_id": str(getattr(call, "id", "") or ""),
                "tool_name": str(getattr(call, "name", "") or ""),
                "args_sha256": hashlib.sha256(args_raw.encode("utf-8", "replace")).hexdigest(),
            },
        )
        if self.enabled and event is None:
            return ""
        return execution_id

    def started(self, session_id: str, *, execution_id: str, round_no: int, call: Any) -> bool:
        """Persist started before execution; enabled WAL must confirm durability."""
        if not self.enabled:
            return True
        event = self._append_event(
            session_id,
            "tool.execution.started",
            {
                "execution_id": execution_id,
                "round": int(round_no or 0),
                "tool_call_id": str(getattr(call, "id", "") or ""),
                "tool_name": str(getattr(call, "name", "") or ""),
            },
        )
        return event is not None

    @contextlib.contextmanager
    def effect_context(
        self,
        *,
        session_id: str,
        execution_id: str,
        round_no: int,
        call: Any,
        workspace_root: str,
    ) -> Iterator[None]:
        """Bind one exact WAL attempt to effect-aware tool code without changing its schema."""
        binding = _EffectBinding(
            journal=self,
            session_id=_validate_session_id(session_id),
            execution_id=str(execution_id),
            round_no=int(round_no or 0),
            tool_call_id=str(getattr(call, "id", "") or ""),
            tool_name=str(getattr(call, "name", "") or ""),
            workspace_root=str(Path(workspace_root).expanduser().resolve()),
        )
        token = _current_effect_binding.set(binding)
        try:
            yield
        finally:
            _current_effect_binding.reset(token)

    @contextlib.contextmanager
    def effect_bindings(
        self,
        *,
        session_id: str,
        execution_ids: dict[str, str],
        round_no: int,
        calls: list[Any],
        workspace_root: str,
    ) -> Iterator[None]:
        """Bind a batch by provider tool_call_id; ToolRegistry selects the active call mechanically."""
        sid = _validate_session_id(session_id)
        workspace = str(Path(workspace_root).expanduser().resolve())
        bindings: dict[str, _EffectBinding] = {}
        for call in calls:
            call_id = str(getattr(call, "id", "") or "")
            execution_id = str(execution_ids.get(call_id) or "")
            if not call_id or not execution_id:
                continue
            bindings[call_id] = _EffectBinding(
                journal=self,
                session_id=sid,
                execution_id=execution_id,
                round_no=int(round_no or 0),
                tool_call_id=call_id,
                tool_name=str(getattr(call, "name", "") or ""),
                workspace_root=workspace,
            )
        token = _current_effect_bindings.set(bindings)
        try:
            yield
        finally:
            _current_effect_bindings.reset(token)

    @staticmethod
    def _canonical_effect_scope(workspace_root: str, canonical_path: str) -> tuple[str, str] | None:
        workspace = Path(workspace_root).expanduser().resolve()
        target = Path(canonical_path).expanduser().resolve()
        try:
            target.relative_to(workspace)
        except ValueError:
            return None
        return str(workspace), str(target)

    @staticmethod
    def _sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _sha256_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def effect_prepared(
        self,
        session_id: str,
        *,
        execution_id: str,
        round_no: int,
        tool_call_id: str,
        tool_name: str,
        workspace_root: str,
        canonical_path: str,
        effect_kind: str,
        before_bytes: bytes,
        expected_after_bytes: bytes,
    ) -> bool:
        """Durably record exact file bytes intended for mutation before the mutation can occur."""
        if not self.enabled:
            return True
        scope = self._canonical_effect_scope(workspace_root, canonical_path)
        if scope is None:
            return False
        workspace, target = scope
        event = self._append_event(
            _validate_session_id(session_id),
            "tool.execution.effect_prepared",
            {
                "execution_id": str(execution_id),
                "round": int(round_no or 0),
                "tool_call_id": str(tool_call_id or ""),
                "tool_name": str(tool_name or ""),
                "effect_kind": str(effect_kind or ""),
                "workspace_root": workspace,
                "canonical_path": target,
                "before_sha256": self._sha256_bytes(before_bytes),
                "before_size": len(before_bytes),
                "expected_after_sha256": self._sha256_bytes(expected_after_bytes),
                "expected_after_size": len(expected_after_bytes),
            },
        )
        return event is not None

    def effect_observed(
        self,
        *,
        session_id: str,
        execution_id: str,
        round_no: int,
        tool_call_id: str,
        tool_name: str,
        workspace_root: str,
        canonical_path: str,
        effect_kind: str,
        actual_after_bytes: bytes,
        expected_after_bytes: bytes,
        actual_mtime_ns: int | None = None,
    ) -> bool:
        """Record the exact post-write bytes observed by the tool; failure never invents durability."""
        if not self.enabled:
            return False
        scope = self._canonical_effect_scope(workspace_root, canonical_path)
        if scope is None:
            return False
        workspace, target = scope
        actual_sha = self._sha256_bytes(actual_after_bytes)
        expected_sha = self._sha256_bytes(expected_after_bytes)
        event = self._append_event(
            _validate_session_id(session_id),
            "tool.execution.effect_observed",
            {
                "execution_id": str(execution_id),
                "round": int(round_no or 0),
                "tool_call_id": str(tool_call_id or ""),
                "tool_name": str(tool_name or ""),
                "effect_kind": str(effect_kind or ""),
                "workspace_root": workspace,
                "canonical_path": target,
                "actual_after_sha256": actual_sha,
                "actual_size": len(actual_after_bytes),
                "actual_mtime_ns": actual_mtime_ns,
                "matches_expected": actual_sha == expected_sha,
            },
        )
        return event is not None

    def effect_snapshot(
        self, session_id: str, execution_id: str, *, workspace_root: str
    ) -> dict[str, Any] | None:
        """Read current file identity for one durable effect without inferring execution causation."""
        store = self.event_store
        if store is None or not bool(getattr(store, "enabled", False)) or not store.exists(session_id):
            return None
        prepared: dict[str, Any] | None = None
        observed: dict[str, Any] | None = None
        finished = False
        for event in store.read(_validate_session_id(session_id)) or []:
            payload = getattr(event, "payload", None) or {}
            if str(payload.get("execution_id") or "") != str(execution_id):
                continue
            etype = str(getattr(event, "type", ""))
            if etype == "tool.execution.finished":
                finished = True
            elif etype == "tool.execution.effect_prepared":
                prepared = dict(payload)
            elif etype == "tool.execution.effect_observed":
                observed = dict(payload)
        if prepared is None:
            return None

        base: dict[str, Any] = {
            "execution_id": str(execution_id),
            "effect_kind": str(prepared.get("effect_kind") or ""),
            "workspace_root": str(prepared.get("workspace_root") or ""),
            "canonical_path": str(prepared.get("canonical_path") or ""),
            "before_sha256": str(prepared.get("before_sha256") or ""),
            "expected_after_sha256": str(prepared.get("expected_after_sha256") or ""),
            "effect_observed_durable": observed is not None,
            # A durable prepared fact means mutation may have been attempted even if a
            # separately expected started row is unavailable/corrupt. Never infer
            # non-execution from that partial log shape.
            "execution_outcome": "finished" if finished else "unknown",
            "causation_proven": False,
            "auto_reexecuted": False,
            "path_inspected": False,
        }
        requested_workspace = str(Path(workspace_root).expanduser().resolve())
        if requested_workspace != base["workspace_root"]:
            base["effect_state"] = "workspace_mismatch"
            return base
        scope = self._canonical_effect_scope(base["workspace_root"], base["canonical_path"])
        if scope is None:
            base["effect_state"] = "path_outside_workspace"
            return base
        _workspace, target_text = scope
        target = Path(target_text)
        try:
            current_sha, current_size = self._sha256_file(target)
        except FileNotFoundError:
            base["effect_state"] = "missing"
            base["path_inspected"] = True
            return base
        except OSError as exc:
            base["effect_state"] = "unreadable"
            base["read_error_type"] = type(exc).__name__
            return base
        base["path_inspected"] = True
        base["current_sha256"] = current_sha
        base["current_size"] = current_size
        if current_sha == base["expected_after_sha256"]:
            base["effect_state"] = "current_matches_expected_after"
        elif current_sha == base["before_sha256"]:
            base["effect_state"] = "current_matches_before"
        else:
            base["effect_state"] = "current_diverged"
        if observed is not None:
            base["observed_actual_after_sha256"] = str(observed.get("actual_after_sha256") or "")
            base["observed_matches_expected"] = bool(observed.get("matches_expected"))
        return base

    def finished(
        self,
        session_id: str,
        *,
        execution_id: str,
        round_no: int,
        call: Any,
        tool_message: Message,
    ) -> str:
        """Durably store the exact future tool receipt before ordinary history append."""
        snapshot = {
            "version": 1,
            "session_id": str(session_id),
            "execution_id": str(execution_id),
            "round": int(round_no or 0),
            "tool_call_id": str(getattr(call, "id", "") or ""),
            "tool_name": str(getattr(call, "name", "") or ""),
            "message": self.message_snapshot(tool_message),
        }
        raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()
        path = self.result_path(session_id, execution_id)
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
        self._append_event(
            session_id,
            "tool.execution.finished",
            {
                "execution_id": execution_id,
                "round": int(round_no or 0),
                "tool_call_id": str(getattr(call, "id", "") or ""),
                "tool_name": str(getattr(call, "name", "") or ""),
                "result_state_sha256": digest,
                "result_state_chars": len(raw),
                "status": tool_message.status.value if tool_message.status else None,
            },
        )
        return digest

    def load_result(
        self, session_id: str, execution_id: str, *, expected_sha256: str
    ) -> Message | None:
        if not expected_sha256:
            return None
        try:
            raw = self.result_path(session_id, execution_id).read_text(encoding="utf-8")
            if hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest() != expected_sha256:
                return None
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("execution_id") != execution_id:
                return None
            message = payload.get("message")
            return self.message_from_snapshot(message) if isinstance(message, dict) else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def receipt_committed(
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
        event = self._append_event(
            session_id,
            "tool.execution.receipt_committed",
            {
                "execution_id": execution_id,
                "round": int(round_no or 0),
                "tool_call_id": str(tool_call_id or ""),
                "tool_name": str(tool_name or ""),
                "result_state_sha256": str(result_state_sha256 or ""),
                "recovered": bool(recovered),
            },
        )
        # With WAL enabled, keep the exact sidecar until the commit fact itself is
        # durable. A later repair can settle from the already-durable tool receipt.
        committed = bool(self.enabled and event is not None)
        if not self.enabled or event is not None:
            with contextlib.suppress(OSError, ValueError):
                self.result_path(session_id, execution_id).unlink(missing_ok=True)
        if committed and tool_message is not None and self._receipt_committed_hook is not None:
            try:
                self._receipt_committed_hook(session_id, tool_message)
            except Exception:  # noqa: BLE001 - commit truth survives derived-cache failure
                logger.warning("tool receipt committed hook failed", exc_info=True)
        return committed

    def recover(self, session_id: str, sess: Session) -> int:
        """Close incomplete WAL facts without automatically re-executing a tool."""
        store = self.event_store
        if store is None or not bool(getattr(store, "enabled", False)) or not store.exists(session_id):
            return 0
        try:
            states: dict[str, dict[str, Any]] = {}
            for event in store.read(session_id) or []:
                etype = str(getattr(event, "type", ""))
                if not etype.startswith("tool.execution."):
                    continue
                payload = getattr(event, "payload", None) or {}
                execution_id = str(payload.get("execution_id") or "")
                if not execution_id:
                    continue
                state = states.setdefault(execution_id, {"declared_seq": int(event.seq)})
                if etype == "tool.execution.declared":
                    state.update({"declared": payload, "declared_seq": int(event.seq)})
                elif etype == "tool.execution.started":
                    state["started"] = payload
                elif etype == "tool.execution.finished":
                    state["finished"] = payload
                elif etype == "tool.execution.receipt_committed":
                    state["committed"] = payload

            recovered = 0
            for execution_id, state in sorted(
                states.items(), key=lambda item: int(item[1].get("declared_seq") or 0)
            ):
                declared = state.get("declared")
                if not isinstance(declared, dict) or state.get("committed"):
                    continue
                call_id = str(declared.get("tool_call_id") or "")
                tool_name = str(declared.get("tool_name") or "")
                round_no = int(declared.get("round") or 0)
                if not call_id:
                    continue
                finished = state.get("finished")
                existing_receipt = next(
                    (m for m in sess.messages if m.role == "tool" and m.tool_call_id == call_id),
                    None,
                )
                if existing_receipt is not None:
                    self.receipt_committed(
                        session_id,
                        execution_id=execution_id,
                        round_no=round_no,
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        result_state_sha256=str(
                            (finished or {}).get("result_state_sha256")
                            if isinstance(finished, dict)
                            else ""
                        ),
                        recovered=True,
                        tool_message=existing_receipt,
                    )
                    continue

                declaration_present = any(
                    m.role == "assistant"
                    and any(
                        str((tc or {}).get("id") or "") == call_id
                        for tc in (m.tool_calls or [])
                    )
                    for m in sess.messages
                )
                if not declaration_present:
                    continue

                if isinstance(finished, dict):
                    result_sha = str(finished.get("result_state_sha256") or "")
                    msg = self.load_result(
                        session_id, execution_id, expected_sha256=result_sha
                    )
                    if msg is None:
                        msg = Message(
                            role="tool",
                            content=(
                                "[状态: error] execution_completed=true; "
                                "result_unavailable_after_restart=true; auto_reexecuted=false"
                            ),
                            source=MessageSource.SYSTEM,
                            tool_call_id=call_id,
                            tool_name=tool_name,
                            status=ToolResultStatus.ERROR,
                            metadata={
                                "tool_execution_recovery": {
                                    "state": "finished_result_unavailable",
                                    "auto_reexecuted": False,
                                    "execution_id": execution_id,
                                }
                            },
                        )
                elif state.get("started"):
                    result_sha = ""
                    from llm_loop.core.run_context import current_workspace_root

                    effect = self.effect_snapshot(
                        session_id,
                        execution_id,
                        workspace_root=current_workspace_root.get(),
                    )
                    effect_suffix = (
                        f"; effect_state={effect['effect_state']}; causation_proven=false"
                        if effect is not None and effect.get("effect_state")
                        else ""
                    )
                    recovery_meta: dict[str, Any] = {
                        "state": "started_outcome_unknown",
                        "auto_reexecuted": False,
                        "execution_id": execution_id,
                    }
                    if effect is not None:
                        recovery_meta["effect"] = effect
                    msg = Message(
                        role="tool",
                        content=(
                            "[状态: error] execution_outcome=unknown_after_restart; "
                            f"auto_reexecuted=false{effect_suffix}"
                        ),
                        source=MessageSource.SYSTEM,
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        status=ToolResultStatus.ERROR,
                        metadata={"tool_execution_recovery": recovery_meta},
                    )
                else:
                    result_sha = ""
                    msg = Message(
                        role="tool",
                        content=(
                            "[状态: error] executed=false; reason_code=restart_before_execution; "
                            "auto_reexecuted=false"
                        ),
                        source=MessageSource.SYSTEM,
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        status=ToolResultStatus.ERROR,
                        metadata={
                            "tool_execution_recovery": {
                                "state": "declared_not_started",
                                "auto_reexecuted": False,
                                "execution_id": execution_id,
                            }
                        },
                    )
                sess.messages.append(msg)
                message_event = self._append_message_event(sess, msg)
                if message_event is not None:
                    self.receipt_committed(
                        session_id,
                        execution_id=execution_id,
                        round_no=round_no,
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        result_state_sha256=result_sha,
                        recovered=True,
                        tool_message=msg,
                    )
                recovered += 1
            if recovered:
                self.session_store.save(sess)
            return recovered
        except Exception:  # noqa: BLE001 - recovery is fail-open and never auto-reexecutes
            logger.warning("tool execution WAL recovery failed; no tool was re-executed", exc_info=True)
            return 0
