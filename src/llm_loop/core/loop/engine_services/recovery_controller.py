"""ERR1210 mechanical recovery service.

P2-B contract: program code does not strip semantic prompt content, defer/replay old
program slots, or stack blind/resend recovery loops. For exact HTTP 400/code 1210 it may
losslessly normalize a consecutive tail-user wire shape and retry that *changed* payload
once. If no structural transform applies, the original provider error is reported.
"""
from __future__ import annotations

import contextlib
import logging
import os
from typing import TYPE_CHECKING, Any, cast

from llm_loop.core.loop.err1210 import Err1210RecoveryResult, is_err1210, snapshot_offending_payload
from llm_loop.core.session import Session
from llm_loop.llm.errors import LLMError
from llm_loop.resources.provider_calls import (
    foreground_task_provider_chat,
    foreground_task_provider_stream,
)
from llm_loop.resources.provider_settlement import (
    ProviderAttemptKind,
    ProviderCallIdentity,
)
from llm_loop.runtime.causality import exceptional_attempt_payload

if TYPE_CHECKING:
    from collections.abc import Iterator

    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)


class RecoveryController:
    """Bounded provider-wire recovery for the proven GLM tail-user incompatibility."""

    _AGG_SEPARATOR: str = "\n\n" + "=" * 28 + "\n\n"
    _AGG_MAX_TAIL_USERS: int = 16

    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    def _reachability_begin_attempt(
        self, *, kind: str, attempt_index: int, model: str, provider: str
    ) -> str:
        try:
            tool_cycle = getattr(self._host, "_tool_cycle", None)
            fn = getattr(tool_cycle, "_reachability_begin_attempt", None)
            if callable(fn):
                return str(
                    fn(kind=kind, attempt_index=attempt_index, model=model, provider=provider) or ""
                )
        except Exception:  # noqa: BLE001 - telemetry fail-open
            logger.debug("recovery reachability bind failed (fail-open)", exc_info=True)
        return ""

    def _reachability_finalize(self, outcome: str) -> None:
        try:
            tool_cycle = getattr(self._host, "_tool_cycle", None)
            fn = getattr(tool_cycle, "_reachability_finalize", None)
            if callable(fn):
                fn(outcome)
        except Exception:  # noqa: BLE001 - telemetry fail-open
            logger.debug("recovery reachability finalize failed (fail-open)", exc_info=True)

    def _aggregate_tail_users(self, messages: list[dict]) -> list[dict] | None:
        """Losslessly merge 2..16 consecutive tail user frames into one wire frame."""
        try:
            if not messages or messages[-1].get("role") != "user":
                return None
            i = len(messages) - 1
            while i >= 0 and messages[i].get("role") == "user":
                i -= 1
            tail_start = i + 1
            n_tail = len(messages) - tail_start
            if n_tail < 2 or n_tail > self._AGG_MAX_TAIL_USERS:
                return None
            parts: list[str] = []
            for m in messages[tail_start:]:
                c = m.get("content")
                if not isinstance(c, str):
                    return None
                parts.append(c)
            merged = self._AGG_SEPARATOR.join(parts)
            return messages[:tail_start] + [{"role": "user", "content": merged}]
        except Exception:  # noqa: BLE001 - transform failure means no recovery
            logger.warning("err1210: 尾部 user 聚合异常（fail-open）", exc_info=True)
            return None

    def _try_err1210_recovery(
        self,
        *,
        exc: LLMError,
        sess: Session,
        messages: list[dict],
        tools_param: list[dict],
        llm_client: Any,
        chat_model_arg: str | None,
        timeout_s: float | None,
        session_id: str,
        model_label: str = "",
        metadata_registry: Any = None,
        round_no: int = 0,
        provider_call: ProviderCallIdentity | None = None,
    ) -> Err1210RecoveryResult:
        """For exact 1210, retry once only when tail-user normalization changes the payload."""
        del metadata_registry
        result = Err1210RecoveryResult()
        if os.environ.get("ERR1210_RECOVERY", "1") != "1" or not is_err1210(exc):
            return result
        try:
            seq = self._host._run_state().err1210_run_seq
            attempted = getattr(self._host, "_err1210_attempted", None) or {}
            if attempted.get(session_id) == seq:
                result.attempted = True
                result.exhausted = True
                return result
            result.attempted = True
            self._host._err1210_attempted = {**attempted, session_id: seq}
            model_ref = model_label or chat_model_arg or getattr(llm_client, "model", "")
            snapshot_offending_payload(
                messages=messages,
                tools=tools_param,
                params={"timeout_s": timeout_s, "round_no": round_no},
                session_id=session_id,
                model=model_ref,
                is_compact_first=bool(self._host._run_state().compact_event_was_compacted),
                data_dir=getattr(self._host.settings, "data_dir", "data"),
            )
            retry_messages = self._aggregate_tail_users(messages)
            if retry_messages is None:
                self._host._record_action(
                    "err1210.recovery",
                    "no_transform",
                    "exact 1210 but no consecutive tail-user wire transform applies; retry_count=0",
                )
                return result
            result.transformed_tail_users = len(messages) - len(retry_messages) + 1
            result.provider_retry_count = 1
            self._host._record_action(
                "err1210.recovery",
                "aggregate_retry",
                f"tail_users={result.transformed_tail_users}; retry_count=1; mode=aggregate",
            )
            resp, retry_exc = self._retry_consume_stream(
                llm_client=llm_client,
                messages=retry_messages,
                tools_param=tools_param,
                chat_model_arg=chat_model_arg,
                timeout_s=timeout_s,
                session_id=session_id,
                model_label=model_ref,
                round_no=round_no,
                attempt_index=1,
                transform={
                    "wire_shape_changed": True,
                    "messages_before": len(messages),
                    "messages_after": len(retry_messages),
                    "tail_users_merged": int(result.transformed_tail_users or 0),
                },
                provider_call=provider_call,
            )
            if resp is not None:
                result.resp = resp
                result.recovered = True
                self._host._record_action(
                    "err1210.recovery",
                    "recovered",
                    f"tail_users={result.transformed_tail_users}; mode=aggregate",
                )
            elif retry_exc is not None and is_err1210(retry_exc):
                result.exhausted = True
                self._host._record_action(
                    "err1210.recovery",
                    "exhausted",
                    f"tail_users={result.transformed_tail_users}; retry still 1210",
                )
            return result
        except Exception:  # noqa: BLE001 - recovery must not hide the original error
            logger.warning("err1210: recovery failed-open", exc_info=True)
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
        transform: dict[str, Any] | None = None,
        provider_call: ProviderCallIdentity | None = None,
    ) -> tuple[Any | None, LLMError | None]:
        """Consume one changed-payload retry to completion without emitting partial deltas."""
        del metadata_registry
        kwargs: dict[str, Any] = {"messages": messages, "tools": tools_param, "timeout_s": timeout_s}
        if chat_model_arg:
            kwargs["model"] = chat_model_arg
        stream_fn = getattr(llm_client, "chat_stream", None)
        try:
            _attempt_id = self._reachability_begin_attempt(
                kind="err1210_retry",
                attempt_index=attempt_index,
                model=model_label or chat_model_arg or getattr(llm_client, "model", ""),
                provider=getattr(llm_client, "provider", ""),
            )
            with contextlib.suppress(Exception):
                self._host._event_append(
                    session_id,
                    "request.attempt",
                    exceptional_attempt_payload(
                        attempt_id=_attempt_id,
                        kind="err1210_retry",
                        attempt_index=attempt_index,
                        round_no=round_no,
                        client=llm_client,
                        messages=messages,
                        tools=tools_param,
                        transform=dict(transform or {"wire_shape_changed": True}),
                        provider_call_id=getattr(provider_call, "call_id", ""),
                    ),
                )
            _owner_ref = (
                f"task:{session_id}:round:{round_no}:err1210:"
                f"{attempt_index}:{_attempt_id}"
            )
            _provider_id = str(getattr(llm_client, "provider", "") or "")
            _model_id = chat_model_arg or getattr(llm_client, "model", "")
            if callable(stream_fn):
                it = cast(
                    "Iterator[Any]",
                    foreground_task_provider_stream(
                        self._host,
                        llm_client,
                        stream_fn,
                        kwargs,
                        owner_ref=_owner_ref,
                        provider_id=_provider_id,
                        model_id=_model_id,
                        provider_call=provider_call,
                        attempt_kind=ProviderAttemptKind.ERR1210_RETRY,
                        site_index=attempt_index,
                    ),
                )
                while True:
                    try:
                        next(it)
                    except StopIteration as stop:
                        return stop.value, None
            return (
                foreground_task_provider_chat(
                    self._host,
                    llm_client,
                    llm_client.chat,
                    kwargs,
                    owner_ref=_owner_ref,
                    provider_id=_provider_id,
                    model_id=_model_id,
                    provider_call=provider_call,
                    attempt_kind=ProviderAttemptKind.ERR1210_RETRY,
                    site_index=attempt_index,
                ),
                None,
            )
        except Exception as retry_exc:  # noqa: BLE001
            self._reachability_finalize("provider_error")
            self._host._record_action(
                "err1210.recovery", "retry_error", f"retry failed: {str(retry_exc)[:200]}"
            )
            return None, retry_exc if isinstance(retry_exc, LLMError) else None

    def _err1210_init(self) -> None:
        """Initialize per-engine attempt bookkeeping; no prompt/defer state exists."""
        self._host._err1210_attempted = {}
        self._host._run_state().err1210_run_seq = 0

    def _err1210_run_begin(self) -> None:
        """Give each run at most one structural 1210 recovery opportunity."""
        self._host._run_state().err1210_run_seq += 1

    def _err1210_attempt_recovery(
        self,
        *,
        exc: LLMError,
        sess: Session,
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
        provider_call: ProviderCallIdentity | None = None,
    ) -> tuple[bool, Any, float, int]:
        result = Err1210RecoveryResult()
        try:
            result = self._try_err1210_recovery(
                exc=exc,
                sess=sess,
                messages=messages,
                tools_param=tools_param,
                llm_client=llm_client,
                chat_model_arg=chat_model_arg,
                timeout_s=self._host._runtime_timeout(),
                session_id=session_id,
                model_label=model_label,
                metadata_registry=metadata_registry,
                round_no=round_no,
                provider_call=provider_call,
            )
            if result.recovered and result.resp is not None:
                return True, result.resp, 0.0, result.provider_retry_count
        except Exception:  # noqa: BLE001
            logger.warning("err1210: engine recovery hook failed-open", exc_info=True)
        return False, current_resp, current_round_ms, int(result.provider_retry_count or 0)

    def _e1210_llm_error_finalize(
        self, session_id: str, exc: LLMError, msg_count: int, defer_reason: str
    ) -> str:
        """Return truthful current-user error text; legacy defer bookkeeping is retired."""
        del session_id, msg_count, defer_reason
        from llm_loop.feedback.honesty import llm_error_text

        return llm_error_text(exc)
