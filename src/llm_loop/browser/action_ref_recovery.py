"""Exact no-replay crash correlation for P4-LIVE ActionRef Browser mutations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from llm_loop.browser.action import BrowserActionReceiptStore
from llm_loop.browser.action_ref_execution import (
    ActionRefExecutionBridgeError,
    ActionRefExecutionBridgeStore,
)
from llm_loop.core.message import Message, MessageSource, ToolResultStatus

RecoveryState = Literal[
    "prepared_before_browser_running",
    "browser_running_outcome_unknown",
    "browser_terminal_exact",
]


class ActionRefCrashCorrelationError(RuntimeError):
    """Stable fail-closed rejection for invalid/ambiguous recovery evidence."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}")


@dataclass(frozen=True)
class ActionRefRecoveryDecision:
    state: RecoveryState
    execution_id: str
    bridge_id: str
    tool_call_id: str
    tool_name: str
    action_id: str
    receipt_seq_before: int | None
    running_receipt_present: bool
    terminal_receipt: dict[str, Any] | None
    auto_reexecuted: bool = False


def action_ref_execution_root(data_root: str | Path) -> Path:
    return Path(data_root).expanduser() / "audit" / "action_ref_execution"


def browser_action_receipt_root(data_root: str | Path) -> Path:
    return Path(data_root).expanduser() / "browser_action"


def render_browser_action_receipt_tool_content(receipt: dict[str, Any]) -> str:
    status = "success" if str(receipt.get("status") or "") == "ok" else "error"
    payload = json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"[状态: {status}] {payload}"


class ActionRefCrashCorrelator:
    """Correlate only execution_id -> immutable bridge -> exact action_id receipt suffix."""

    def __init__(
        self,
        *,
        bridge_store: ActionRefExecutionBridgeStore,
        receipt_store: BrowserActionReceiptStore,
    ) -> None:
        self.bridge_store = bridge_store
        self.receipt_store = receipt_store

    def _bridge(self, session_id: str, execution_id: str) -> dict[str, Any] | None:
        try:
            bridge = self.bridge_store.load_exact(execution_id)
        except ActionRefExecutionBridgeError as exc:
            if exc.code == "action_ref_execution_binding_unavailable":
                return None
            raise ActionRefCrashCorrelationError(exc.code, exc.detail) from exc
        if str(bridge.get("session_id") or "") != str(session_id):
            raise ActionRefCrashCorrelationError(
                "action_ref_recovery_session_mismatch",
                "outer session does not own the immutable ActionRef execution bridge",
            )
        return bridge

    def arm_receipt_cursor(self, session_id: str, execution_id: str) -> dict[str, Any]:
        """Fence this execution to receipt facts created after the current exact history."""
        bridge = self._bridge(session_id, execution_id)
        if bridge is None:
            raise ActionRefCrashCorrelationError(
                "action_ref_execution_binding_unavailable",
                "cannot arm Browser receipt cursor without PREPARED execution bridge",
            )
        action_id = str(bridge.get("inner_action_id") or "")
        history = self.receipt_store.list_action(session_id, action_id)
        seqs = [self._receipt_seq(item) for item in history]
        baseline = max(seqs, default=0)
        return self.bridge_store.prepare_receipt_cursor(
            execution_id, receipt_seq_before=baseline
        )

    @staticmethod
    def _receipt_seq(receipt: dict[str, Any]) -> int:
        seq = receipt.get("receipt_seq")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0:
            raise ActionRefCrashCorrelationError(
                "action_ref_receipt_history_invalid",
                "Browser receipt sequence is missing or invalid",
            )
        return seq

    def classify(self, session_id: str, execution_id: str) -> ActionRefRecoveryDecision | None:
        bridge = self._bridge(session_id, execution_id)
        if bridge is None:
            return None
        tool_call_id = str(bridge.get("tool_call_id") or "")
        tool_name = str(bridge.get("tool_name") or "")
        action_id = str(bridge.get("inner_action_id") or "")
        bridge_id = str(bridge.get("bridge_id") or "")
        if not tool_call_id or not tool_name or not action_id or not bridge_id:
            raise ActionRefCrashCorrelationError(
                "action_ref_recovery_bridge_incomplete",
                "immutable ActionRef execution bridge is incomplete",
            )

        try:
            cursor = self.bridge_store.load_receipt_cursor(execution_id)
        except ActionRefExecutionBridgeError as exc:
            if exc.code == "action_ref_receipt_cursor_unavailable":
                return ActionRefRecoveryDecision(
                    state="prepared_before_browser_running",
                    execution_id=str(execution_id),
                    bridge_id=bridge_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    action_id=action_id,
                    receipt_seq_before=None,
                    running_receipt_present=False,
                    terminal_receipt=None,
                )
            raise ActionRefCrashCorrelationError(exc.code, exc.detail) from exc

        baseline = int(cursor["receipt_seq_before"])
        history = self.receipt_store.list_action(session_id, action_id)
        suffix: list[dict[str, Any]] = []
        previous = baseline
        for item in history:
            seq = self._receipt_seq(item)
            if seq <= baseline:
                continue
            if seq <= previous or str(item.get("action_id") or "") != action_id:
                raise ActionRefCrashCorrelationError(
                    "action_ref_receipt_history_invalid",
                    "Browser receipt suffix is not exact monotonic action_id history",
                )
            previous = seq
            suffix.append(item)

        if not suffix:
            return ActionRefRecoveryDecision(
                state="prepared_before_browser_running",
                execution_id=str(execution_id),
                bridge_id=bridge_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                action_id=action_id,
                receipt_seq_before=baseline,
                running_receipt_present=False,
                terminal_receipt=None,
            )

        running = [item for item in suffix if str(item.get("status") or "") == "running"]
        terminal = [
            item
            for item in suffix
            if str(item.get("status") or "") in {"ok", "failed", "rejected"}
        ]
        unknown = [
            item
            for item in suffix
            if str(item.get("status") or "") not in {"running", "ok", "failed", "rejected"}
        ]
        if unknown or len(running) > 1 or len(terminal) > 1:
            raise ActionRefCrashCorrelationError(
                "action_ref_receipt_history_ambiguous",
                "Browser receipt suffix is not a single exact ActionRef execution history",
            )
        if terminal:
            return ActionRefRecoveryDecision(
                state="browser_terminal_exact",
                execution_id=str(execution_id),
                bridge_id=bridge_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                action_id=action_id,
                receipt_seq_before=baseline,
                running_receipt_present=bool(running),
                terminal_receipt=dict(terminal[0]),
            )
        if running:
            return ActionRefRecoveryDecision(
                state="browser_running_outcome_unknown",
                execution_id=str(execution_id),
                bridge_id=bridge_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                action_id=action_id,
                receipt_seq_before=baseline,
                running_receipt_present=True,
                terminal_receipt=None,
            )
        raise ActionRefCrashCorrelationError(
            "action_ref_receipt_history_ambiguous",
            "Browser receipt suffix has no recognized exact state",
        )

    def recover_message(
        self,
        session_id: str,
        execution_id: str,
        tool_call_id: str,
        tool_name: str,
    ) -> Message | None:
        decision = self.classify(session_id, execution_id)
        if decision is None:
            return None
        if decision.tool_call_id != str(tool_call_id) or decision.tool_name != str(tool_name):
            raise ActionRefCrashCorrelationError(
                "action_ref_recovery_outer_identity_mismatch",
                "outer WAL call identity differs from immutable ActionRef execution bridge",
            )
        meta: dict[str, Any] = {
            "state": decision.state,
            "auto_reexecuted": False,
            "execution_id": decision.execution_id,
            "bridge_id": decision.bridge_id,
            "action_id": decision.action_id,
            "receipt_seq_before": decision.receipt_seq_before,
            "running_receipt_present": decision.running_receipt_present,
        }
        if decision.state == "prepared_before_browser_running":
            return Message(
                role="tool",
                content=(
                    "[状态: error] executed=false; "
                    "reason_code=restart_before_browser_running; auto_reexecuted=false"
                ),
                source=MessageSource.SYSTEM,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                status=ToolResultStatus.ERROR,
                metadata={"tool_execution_recovery": meta},
            )
        if decision.state == "browser_running_outcome_unknown":
            return Message(
                role="tool",
                content=(
                    "[状态: error] execution_outcome=unknown_after_restart; "
                    "browser_running_receipt=true; auto_reexecuted=false"
                ),
                source=MessageSource.SYSTEM,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                status=ToolResultStatus.ERROR,
                metadata={"tool_execution_recovery": meta},
            )
        receipt = decision.terminal_receipt
        if not isinstance(receipt, dict):
            raise ActionRefCrashCorrelationError(
                "action_ref_terminal_receipt_missing",
                "terminal correlation has no exact Browser receipt",
            )
        meta["browser_receipt_seq"] = int(receipt["receipt_seq"])
        meta["browser_receipt_status"] = str(receipt.get("status") or "")
        return Message(
            role="tool",
            content=render_browser_action_receipt_tool_content(receipt),
            source=MessageSource.TOOL,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            status=(
                ToolResultStatus.SUCCESS
                if str(receipt.get("status") or "") == "ok"
                else ToolResultStatus.ERROR
            ),
            metadata={
                "tool_execution_recovery": meta,
                "browser_action_receipt": dict(receipt),
            },
        )


def build_action_ref_crash_correlator(data_root: str | Path) -> ActionRefCrashCorrelator | None:
    """Build recovery only after an ActionRef execution root already exists."""
    bridge_root = action_ref_execution_root(data_root)
    if not bridge_root.is_dir():
        return None
    return ActionRefCrashCorrelator(
        bridge_store=ActionRefExecutionBridgeStore(bridge_root),
        receipt_store=BrowserActionReceiptStore(browser_action_receipt_root(data_root)),
    )
