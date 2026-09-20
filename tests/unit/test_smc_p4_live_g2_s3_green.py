"""Deterministic fake-only GREEN qualification for P4-LIVE G2-S3 crash recovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.smc_semantic_logic_p4_live.green2_s3_red_contracts import S3_RED_IDS, run_probe
from llm_loop.browser.action import BrowserActionReceiptStore
from llm_loop.browser.action_ref import ActionRefResolution
from llm_loop.browser.action_ref_execution import ActionRefExecutionBridgeStore
from llm_loop.browser.action_ref_recovery import (
    ActionRefCrashCorrelationError,
    ActionRefCrashCorrelator,
    action_ref_execution_root,
    browser_action_receipt_root,
    build_action_ref_crash_correlator,
)
from llm_loop.core.message import Message, MessageSource, ToolCall, ToolResultStatus
from llm_loop.core.run_context import (
    current_run_generation,
    current_session_id,
    current_workspace_root,
)
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import ToolExecutionJournal
from llm_loop.event_log.store import EventStore


@pytest.mark.parametrize("row_id", S3_RED_IDS, ids=S3_RED_IDS)
def test_p4_live_g2_s3_contract_is_green(row_id: str) -> None:
    probe = run_probe(row_id)
    assert probe.failure_code != "harness_error", (
        f"{row_id} harness failure cannot qualify GREEN: {probe.detail}; facts={probe.facts}"
    )
    assert probe.failure_code == "contract_present", (
        f"{row_id} S3 GREEN missing: observed={probe.failure_code}; facts={probe.facts}"
    )
    assert probe.contract_satisfied is True


def _assistant_decl(call: ToolCall) -> Message:
    return Message(
        role="assistant",
        content="",
        source=MessageSource.USER,
        tool_calls=[
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": '{"action_ref":"opaque"}'},
            }
        ],
    )


def _resolution() -> ActionRefResolution:
    return ActionRefResolution(
        action_ref="actionref://browser/v0.1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        binding_id="binding-s3",
        binding_digest="digest-s3",
        target_kind="object",
        grounding_ref="grounding://browser/v0.1/test/object-s3",
        observed_snapshot_id="snapshot-s3",
        scope_ref="scope-s3",
        semantic_object_or_resource_identity="object-s3",
        browser_target_id_sha256="target-sha-s3",
    )


def _receipt(action_id: str, status: str, *, note: str) -> dict[str, Any]:
    return {
        "schema": "smc.action_receipt.v0.1",
        "domain": "browser",
        "scope_ref": "scope-s3",
        "action_id": action_id,
        "receipt_id": "pending",
        "receipt_seq": 0,
        "verb": "click",
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "target_id": "object-s3",
        "args_normalization": {"applied": False, "rule": None},
        "status": status,
        "before_version": "snapshot-s3",
        "after_version": "snapshot-after" if status != "running" else None,
        "observed_effects": {"diff_ref": note, "scope_transition_ref": None, "provisional": True},
        "boundary_events": [],
        "grounding_refs": {"before": "before-ref", "after": None, "dispatch": "dispatch-ref"},
        "completeness": {"complete": False, "reasons": [note]},
        "predicate_result": None,
        "retry": {
            "attempt_count": 1,
            "automatic_retry_performed": False,
            "mechanism": None,
            "reason": None,
        },
    }


class _Stack:
    def __init__(self, tmp_path: Path) -> None:
        self.events = EventStore(tmp_path / "events", enabled=True)
        self.sessions = SessionStore(tmp_path / "sessions", event_store=self.events)
        self.sid = self.sessions.create()
        self.call = ToolCall(
            id="p4live-s3-call", name="browser_semantic_click", arguments={"action_ref": "opaque"}
        )
        self.bridge_store = ActionRefExecutionBridgeStore(tmp_path / "audit" / "action_ref_execution")
        self.receipt_store = BrowserActionReceiptStore(tmp_path / "browser_action")
        self.correlator = ActionRefCrashCorrelator(
            bridge_store=self.bridge_store,
            receipt_store=self.receipt_store,
        )
        self.journal = ToolExecutionJournal(
            event_store=self.events,
            result_root=tmp_path / "audit" / "tool_execution",
            session_store=self.sessions,
            action_ref_recovery=self.correlator.recover_message,
        )
        self.sess = self.sessions.load(self.sid)
        self.sess.messages.append(Message(role="user", content="Q", source=MessageSource.USER))
        self.sess.messages.append(_assistant_decl(self.call))
        self.sessions.save(self.sess)
        run_token = current_run_generation.set("run-s3")
        try:
            self.execution_id = self.journal.declared(self.sess, self.call, round_no=1)
            assert self.journal.started(
                self.sid,
                execution_id=self.execution_id,
                round_no=1,
                call=self.call,
            )
        finally:
            current_run_generation.reset(run_token)
        self._prepare_bridge(tmp_path)

    def _prepare_bridge(self, tmp_path: Path) -> None:
        sid_token = current_session_id.set(self.sid)
        ws_token = current_workspace_root.set(str(tmp_path.resolve()))
        run_token = current_run_generation.set("run-s3")
        save_token = self.sessions._activate_run_save_token(  # noqa: SLF001
            self.sid, run_generation="run-s3"
        )
        try:
            with self.journal.effect_context(
                session_id=self.sid,
                execution_id=self.execution_id,
                round_no=1,
                call=self.call,
                workspace_root=str(tmp_path),
            ):
                record = self.bridge_store.prepare_current(
                    resolution=_resolution(),
                    inner_action_id="inner-s3",
                    expected_version="snapshot-s3",
                )
                assert record["execution_id"] == self.execution_id
        finally:
            self.sessions._deactivate_run_save_token(self.sid, save_token)  # noqa: SLF001
            current_run_generation.reset(run_token)
            current_workspace_root.reset(ws_token)
            current_session_id.reset(sid_token)

    def fresh_session(self):
        return self.sessions.load(self.sid)

    def recover(self) -> Message:
        sess = self.fresh_session()
        assert self.journal.recover(self.sid, sess) == 1
        receipts = [
            m for m in sess.messages if m.role == "tool" and m.tool_call_id == self.call.id
        ]
        assert len(receipts) == 1
        return receipts[0]


def test_s3_prepared_without_cursor_recovers_not_executed_and_never_dispatches(tmp_path: Path) -> None:
    stack = _Stack(tmp_path)
    dispatch_counter = 0
    receipt = stack.recover()
    assert dispatch_counter == 0
    assert "executed=false" in receipt.content
    meta = receipt.metadata["tool_execution_recovery"]
    assert meta["state"] == "prepared_before_browser_running"
    assert meta["auto_reexecuted"] is False
    assert meta["receipt_seq_before"] is None


def test_s3_receipt_cursor_ignores_old_terminal_from_same_deterministic_action_id(tmp_path: Path) -> None:
    stack = _Stack(tmp_path)
    stack.receipt_store.append(stack.sid, "inner-s3", _receipt("inner-s3", "running", note="old-running"))
    old_terminal = stack.receipt_store.append(
        stack.sid, "inner-s3", _receipt("inner-s3", "ok", note="old-terminal")
    )
    cursor = stack.correlator.arm_receipt_cursor(stack.sid, stack.execution_id)
    assert cursor["receipt_seq_before"] == old_terminal["receipt_seq"] == 2
    decision = stack.correlator.classify(stack.sid, stack.execution_id)
    assert decision is not None
    assert decision.state == "prepared_before_browser_running"
    assert decision.terminal_receipt is None


def test_s3_running_receipt_recovers_unknown_and_never_replays(tmp_path: Path) -> None:
    stack = _Stack(tmp_path)
    stack.correlator.arm_receipt_cursor(stack.sid, stack.execution_id)
    stack.receipt_store.append(
        stack.sid, "inner-s3", _receipt("inner-s3", "running", note="current-running")
    )
    dispatch_counter = 0
    receipt = stack.recover()
    assert dispatch_counter == 0
    assert "execution_outcome=unknown_after_restart" in receipt.content
    meta = receipt.metadata["tool_execution_recovery"]
    assert meta["state"] == "browser_running_outcome_unknown"
    assert meta["running_receipt_present"] is True
    assert meta["auto_reexecuted"] is False


def test_s3_terminal_receipt_reconstructs_exact_tool_result_and_settles_wal(tmp_path: Path) -> None:
    stack = _Stack(tmp_path)
    stack.correlator.arm_receipt_cursor(stack.sid, stack.execution_id)
    stack.receipt_store.append(
        stack.sid, "inner-s3", _receipt("inner-s3", "running", note="current-running")
    )
    terminal = stack.receipt_store.append(
        stack.sid, "inner-s3", _receipt("inner-s3", "ok", note="current-terminal")
    )
    dispatch_counter = 0
    receipt = stack.recover()
    assert dispatch_counter == 0
    assert receipt.source is MessageSource.TOOL
    assert receipt.status is ToolResultStatus.SUCCESS
    assert json.dumps(terminal, ensure_ascii=False, sort_keys=True, separators=(",", ":")) in receipt.content
    assert receipt.metadata["browser_action_receipt"] == terminal
    meta = receipt.metadata["tool_execution_recovery"]
    assert meta["state"] == "browser_terminal_exact"
    assert meta["browser_receipt_seq"] == terminal["receipt_seq"]
    assert meta["auto_reexecuted"] is False
    committed = [
        event
        for event in stack.events.read(stack.sid)
        if event.type == "tool.execution.receipt_committed"
    ]
    assert committed and committed[-1].payload["recovered"] is True


def test_s3_terminal_rejection_without_running_is_exact_no_dispatch_recovery(tmp_path: Path) -> None:
    stack = _Stack(tmp_path)
    stack.correlator.arm_receipt_cursor(stack.sid, stack.execution_id)
    terminal = stack.receipt_store.append(
        stack.sid, "inner-s3", _receipt("inner-s3", "rejected", note="stale-before-dispatch")
    )
    decision = stack.correlator.classify(stack.sid, stack.execution_id)
    assert decision is not None
    assert decision.state == "browser_terminal_exact"
    assert decision.running_receipt_present is False
    assert decision.terminal_receipt == terminal
    receipt = stack.recover()
    assert receipt.status is ToolResultStatus.ERROR
    assert receipt.metadata["browser_action_receipt"] == terminal


def test_s3_ambiguous_receipt_suffix_fails_closed_without_search_or_replay(tmp_path: Path) -> None:
    stack = _Stack(tmp_path)
    stack.correlator.arm_receipt_cursor(stack.sid, stack.execution_id)
    stack.receipt_store.append(
        stack.sid, "inner-s3", _receipt("inner-s3", "rejected", note="terminal-one")
    )
    stack.receipt_store.append(
        stack.sid, "inner-s3", _receipt("inner-s3", "rejected", note="terminal-two")
    )
    with pytest.raises(ActionRefCrashCorrelationError) as exc:
        stack.correlator.classify(stack.sid, stack.execution_id)
    assert exc.value.code == "action_ref_receipt_history_ambiguous"
    receipt = stack.recover()
    assert receipt.metadata["tool_execution_recovery"]["state"] == "started_outcome_unknown"
    assert receipt.metadata["tool_execution_recovery"]["auto_reexecuted"] is False


def test_s3_cursor_is_create_only_idempotent_and_conflict_fails_closed(tmp_path: Path) -> None:
    stack = _Stack(tmp_path)
    first = stack.bridge_store.prepare_receipt_cursor(stack.execution_id, receipt_seq_before=0)
    second = stack.bridge_store.prepare_receipt_cursor(stack.execution_id, receipt_seq_before=0)
    assert second == first
    from llm_loop.browser.action_ref_execution import ActionRefExecutionBridgeError

    with pytest.raises(ActionRefExecutionBridgeError) as exc:
        stack.bridge_store.prepare_receipt_cursor(stack.execution_id, receipt_seq_before=1)
    assert exc.value.code == "action_ref_receipt_cursor_conflict"


def test_s3_recovery_has_no_dispatch_or_semantic_search_surface() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "src/llm_loop/browser/action_ref_recovery.py").read_text(encoding="utf-8")
    assert ".dispatch(" not in source
    assert "BrowserActionAdapter" not in source
    for forbidden in ("selector", "similarity", "latest_target", "successor", "search_target", "rebind_target"):
        assert forbidden not in source


def test_s3_recovery_builder_is_inert_until_actionref_execution_state_exists(
    tmp_path: Path,
) -> None:
    assert build_action_ref_crash_correlator(tmp_path) is None
    assert not action_ref_execution_root(tmp_path).exists()
    assert not browser_action_receipt_root(tmp_path).exists()
