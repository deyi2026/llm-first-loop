"""Deterministic fake-only GREEN qualification for P4-LIVE G2-S4."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from evals.smc_semantic_logic_p4_live.green2_s4_red_contracts import S4_RED_IDS, run_probe
from evals.smc_semantic_logic_p4_live.red_contracts import _find_named_object, _fixtures
from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
)
from llm_loop.browser.action_ref import (
    ActionRefBindingStore,
    ActionRefIssueContext,
    ActionRefIssuer,
    ActionRefResolver,
)
from llm_loop.browser.action_ref_execution import ActionRefExecutionBridgeStore
from llm_loop.browser.action_ref_recovery import ActionRefCrashCorrelator
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.config import Settings, load_settings
from llm_loop.core.message import Message, MessageSource, ToolCall, ToolResultStatus
from llm_loop.core.run_context import (
    current_run_generation,
    current_session_id,
    current_workspace_root,
)
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import (
    ToolExecutionJournal,
    revoke_effect_binding_for_call,
)
from llm_loop.event_log.store import EventStore
from llm_loop.tools.builtin.browser_action_ref_kernel import ActionRefSemanticCompileBridge
from llm_loop.tools.builtin.browser_action_ref_mutation import (
    ActionRefMutationKernel,
    build_typed_action_ref_mutation_tools,
)
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool


@pytest.mark.parametrize("row_id", S4_RED_IDS, ids=S4_RED_IDS)
def test_s4_structural_contract_is_green(row_id: str) -> None:
    probe = run_probe(row_id)
    assert probe.failure_code == "contract_present", probe.facts
    assert probe.contract_satisfied is True


class _Capture:
    def __init__(self, owner: _Harness) -> None:
        self.owner = owner

    def capture(self) -> dict[str, Any]:
        return copy.deepcopy(self.owner.capture_raw)


class _Actuator:
    class _TargetMismatchError(RuntimeError):
        code = "browser_target_precondition_mismatch"

    def __init__(self, target_id: str = "page-a") -> None:
        self.target_id = target_id
        self.bind_calls: list[str] = []
        self.dispatch_count = 0
        self.dispatches: list[dict[str, Any]] = []

    def bind_observed_target(self, expected_target_id_sha256: str) -> None:
        self.bind_calls.append(expected_target_id_sha256)
        actual = hashlib.sha256(self.target_id.encode("utf-8")).hexdigest()
        if actual != expected_target_id_sha256:
            raise self._TargetMismatchError("browser_target_precondition_mismatch")

    def dispatch(self, *, verb: str, physical_target: str | None, args: dict[str, Any]) -> BrowserDispatchResult:
        self.dispatch_count += 1
        self.dispatches.append({"verb": verb, "physical_target": physical_target, "args": dict(args)})
        return BrowserDispatchResult(acknowledged=True)


class _Harness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.clock = [1000.0]
        self.workspace = str(root.resolve())
        self.run_generation = "run-s4"
        self.events = EventStore(root / "events", enabled=True)
        self.sessions = SessionStore(root / "sessions", event_store=self.events)
        self.sid = self.sessions.create()
        self.perception_store = BrowserPerceptionStore(
            root / "browser", retention_seconds=60, now_fn=lambda: self.clock[0]
        )
        self.binding_store = ActionRefBindingStore(
            root / "action_refs", now_fn=lambda: self.clock[0]
        )
        self.issuer = ActionRefIssuer(
            binding_store=self.binding_store,
            perception_store=self.perception_store,
        )
        self.perception = BrowserPerceptionAdapter(
            store=self.perception_store,
            action_ref_issuer=self.issuer,
            action_ref_context_getter=lambda: ActionRefIssueContext(
                workspace_scope=self.workspace,
                origin_run_generation=self.run_generation,
            ),
        )
        self.capture_raw = copy.deepcopy(_fixtures()["base"])
        self.projection = self.perception.snapshot(self.sid, copy.deepcopy(self.capture_raw), projection_limit=100)
        self.object_ref = str(_find_named_object(self.projection, "Submit")["action_ref"])
        self.resource_ref = str(self.projection["resource_action_ref"])
        self.actuator = _Actuator()
        self.receipts = BrowserActionReceiptStore(root / "browser_action")
        self.action_adapter = BrowserActionAdapter(
            perception=self.perception,
            receipt_store=self.receipts,
            capture_backend=_Capture(self),
            actuator=self.actuator,
        )
        semantic = BrowserSemanticExecuteTool(
            perception=self.perception,
            action_adapter=self.action_adapter,
            session_id_getter=lambda: self.sid,
        )
        self.bridge = ActionRefExecutionBridgeStore(root / "audit" / "action_ref_execution")
        self.correlator = ActionRefCrashCorrelator(
            bridge_store=self.bridge,
            receipt_store=self.receipts,
        )
        self.kernel = ActionRefMutationKernel(
            resolver=ActionRefResolver(
                binding_store=self.binding_store,
                perception_store=self.perception_store,
            ),
            compiler=ActionRefSemanticCompileBridge(compiler=semantic),
            execution_bridge=self.bridge,
            crash_correlator=self.correlator,
            action_adapter=self.action_adapter,
        )
        self.tools = {tool.name: tool for tool in build_typed_action_ref_mutation_tools(self.kernel)}
        self.journal = ToolExecutionJournal(
            event_store=self.events,
            result_root=root / "tool_execution",
            session_store=self.sessions,
            action_ref_recovery=self.correlator.recover_message,
        )

    @contextmanager
    def attempt(
        self,
        tool_name: str,
        execution_id: str,
        *,
        sid: str | None = None,
        workspace: str | None = None,
        run_generation: str | None = None,
    ) -> Iterator[ToolCall]:
        owner_sid = sid or self.sid
        owner_workspace = workspace or self.workspace
        owner_run = run_generation or self.run_generation
        call = ToolCall(id=f"call-{execution_id}", name=tool_name, arguments={})
        sid_token = current_session_id.set(owner_sid)
        ws_token = current_workspace_root.set(owner_workspace)
        run_token = current_run_generation.set(owner_run)
        save_token = self.sessions._activate_run_save_token(owner_sid, run_generation=owner_run)  # noqa: SLF001
        try:
            with self.journal.effect_context(
                session_id=owner_sid,
                execution_id=execution_id,
                round_no=1,
                call=call,
                workspace_root=owner_workspace,
            ):
                yield call
        finally:
            self.sessions._deactivate_run_save_token(owner_sid, save_token)  # noqa: SLF001
            current_run_generation.reset(run_token)
            current_workspace_root.reset(ws_token)
            current_session_id.reset(sid_token)

    @contextmanager
    def wal_attempt(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        label: str,
    ) -> Iterator[tuple[ToolCall, str]]:
        call = ToolCall(id=f"call-{label}", name=tool_name, arguments=dict(arguments))
        sid_token = current_session_id.set(self.sid)
        ws_token = current_workspace_root.set(self.workspace)
        run_token = current_run_generation.set(self.run_generation)
        save_token = self.sessions._activate_run_save_token(  # noqa: SLF001
            self.sid, run_generation=self.run_generation
        )
        try:
            sess = self.sessions.load(self.sid)
            sess.messages.append(
                Message(
                    role="assistant",
                    content="",
                    source=MessageSource.USER,
                    tool_calls=[
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(arguments, sort_keys=True),
                            },
                        }
                    ],
                )
            )
            self.sessions.save(sess)
            execution_id = self.journal.declared(sess, call, round_no=1)
            assert execution_id
            assert self.journal.started(
                self.sid,
                execution_id=execution_id,
                round_no=1,
                call=call,
            )
            with self.journal.effect_context(
                session_id=self.sid,
                execution_id=execution_id,
                round_no=1,
                call=call,
                workspace_root=self.workspace,
            ):
                yield call, execution_id
        finally:
            self.sessions._deactivate_run_save_token(self.sid, save_token)  # noqa: SLF001
            current_run_generation.reset(run_token)
            current_workspace_root.reset(ws_token)
            current_session_id.reset(sid_token)


def test_s4_flag_is_separate_default_off() -> None:
    settings = Settings(llm_api_key="", llm_base_url="", llm_model="test")
    assert settings.browser_action_ref_enabled is False
    assert settings.browser_action_enabled is False
    assert settings.browser_action_ref_mutation_enabled is False
    enabled = load_settings(
        {
            "LLM_API_KEY": "test-key",
            "LLM_BASE_URL": "http://127.0.0.1:9/v1",
            "LLM_MODEL": "test",
            "LFL_BROWSER_ACTION_REF_MUTATION_ENABLED": "1",
        }
    )
    assert enabled.browser_action_ref_mutation_enabled is True


def test_s4_all_five_tools_are_closed_actionref_schemas(tmp_path: Path) -> None:
    h = _Harness(tmp_path)
    expected = {
        "browser_semantic_click": {"action_ref"},
        "browser_semantic_fill": {"action_ref", "text", "mode"},
        "browser_semantic_select": {"action_ref", "value"},
        "browser_semantic_scroll": {"action_ref", "delta_pages"},
        "browser_semantic_navigate": {"action_ref", "url"},
    }
    assert set(h.tools) == set(expected)
    for name, fields in expected.items():
        schema = h.tools[name].parameters
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields


def test_s4_unbound_and_revoked_calls_are_zero_dispatch(tmp_path: Path) -> None:
    h = _Harness(tmp_path)
    result = h.tools["browser_semantic_click"].execute(action_ref=h.object_ref)
    assert result.status is ToolResultStatus.FAILURE
    assert h.actuator.dispatch_count == 0
    assert "action_ref_effect_binding_required" in result.content

    with h.attempt("browser_semantic_click", "exec-revoked") as call:
        assert revoke_effect_binding_for_call(call.id) is True
        result = h.tools["browser_semantic_click"].execute(action_ref=h.object_ref)
    assert result.status is ToolResultStatus.FAILURE
    assert h.actuator.dispatch_count == 0
    assert "action_ref_effect_binding_revoked" in result.content


def test_s4_revocation_after_prepared_before_physical_authority_is_zero_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _Harness(tmp_path)
    args = {"action_ref": h.object_ref}
    real_arm = h.correlator.arm_receipt_cursor

    with h.attempt("browser_semantic_click", "exec-revoked-after-prepared") as call:

        def arm_then_revoke(session_id: str, execution_id: str) -> dict[str, Any]:
            cursor = real_arm(session_id, execution_id)
            assert revoke_effect_binding_for_call(call.id) is True
            return cursor

        monkeypatch.setattr(h.correlator, "arm_receipt_cursor", arm_then_revoke)
        result = h.tools["browser_semantic_click"].execute(**args)

    assert result.status is ToolResultStatus.FAILURE
    assert h.actuator.dispatch_count == 0
    prepared = h.bridge.load_exact("exec-revoked-after-prepared")
    history = h.receipts.list_action(h.sid, str(prepared["inner_action_id"]))
    assert [item["status"] for item in history] == ["running", "failed"]
    assert "dispatch_authority_lost" in history[-1]["completeness"]["reasons"]


def test_s4_bound_click_persists_bridge_cursor_running_terminal_before_one_dispatch(tmp_path: Path) -> None:
    h = _Harness(tmp_path)
    with h.attempt("browser_semantic_click", "exec-click"):
        result = h.tools["browser_semantic_click"].execute(action_ref=h.object_ref)
    assert result.status is ToolResultStatus.SUCCESS
    assert h.actuator.dispatch_count == 1
    prepared = h.bridge.load_exact("exec-click")
    cursor = h.bridge.load_receipt_cursor("exec-click")
    assert cursor["inner_action_id"] == prepared["inner_action_id"]
    history = h.receipts.list_action(h.sid, str(prepared["inner_action_id"]))
    assert [item["status"] for item in history] == ["running", "ok"]
    assert h.actuator.bind_calls == [prepared["browser_target_id_sha256"]]


def test_s4_duplicate_exact_request_dispatches_at_most_once(tmp_path: Path) -> None:
    h = _Harness(tmp_path)
    with h.attempt("browser_semantic_click", "exec-first"):
        first = h.tools["browser_semantic_click"].execute(action_ref=h.object_ref)
    with h.attempt("browser_semantic_click", "exec-second"):
        second = h.tools["browser_semantic_click"].execute(action_ref=h.object_ref)
    assert first.status is ToolResultStatus.SUCCESS
    assert second.status is ToolResultStatus.FAILURE
    assert h.actuator.dispatch_count == 1
    assert json.loads(second.content)["status"] == "rejected"


def test_s4_target_mismatch_and_stale_version_are_zero_dispatch(tmp_path: Path) -> None:
    mismatch = _Harness(tmp_path / "mismatch")
    mismatch.actuator.target_id = "page-b"
    with mismatch.attempt("browser_semantic_click", "exec-target-mismatch"):
        result = mismatch.tools["browser_semantic_click"].execute(action_ref=mismatch.object_ref)
    assert result.status is ToolResultStatus.FAILURE
    assert mismatch.actuator.dispatch_count == 0
    assert "browser_target_precondition_mismatch" in result.content

    stale = _Harness(tmp_path / "stale")
    stale.capture_raw = copy.deepcopy(_fixtures()["navigate"])
    with stale.attempt("browser_semantic_click", "exec-stale"):
        result = stale.tools["browser_semantic_click"].execute(action_ref=stale.object_ref)
    assert result.status is ToolResultStatus.FAILURE
    assert stale.actuator.dispatch_count == 0
    assert json.loads(result.content)["status"] == "rejected"


@pytest.mark.parametrize("failure", ["kind", "session", "workspace", "run", "runtime", "ttl", "tamper"])
def test_s4_actionref_fences_fail_closed_zero_dispatch(tmp_path: Path, failure: str) -> None:
    h = _Harness(tmp_path)
    tool_name = "browser_semantic_click"
    action_ref = h.object_ref
    sid = h.sid
    workspace = h.workspace
    run = h.run_generation
    if failure == "kind":
        tool_name = "browser_semantic_navigate"
    elif failure == "session":
        sid = h.sessions.create()
    elif failure == "workspace":
        other = tmp_path / "other-workspace"
        other.mkdir()
        workspace = str(other.resolve())
    elif failure == "run":
        run = "run-other"
    elif failure == "runtime":
        h.perception_store.runtime_nonce = "changed-runtime-nonce"
    elif failure == "ttl":
        h.clock[0] = 2000.0
    elif failure == "tamper":
        path = h.binding_store.record_path(action_ref)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["grounding_ref"] = "grounding://browser/v0.1/tampered"
        path.write_text(json.dumps(raw, sort_keys=True), encoding="utf-8")

    with h.attempt(tool_name, f"exec-{failure}", sid=sid, workspace=workspace, run_generation=run):
        result = h.tools[tool_name].execute(action_ref=action_ref, **({"url": "https://example.test/b"} if tool_name.endswith("navigate") else {}))
    assert result.status is ToolResultStatus.FAILURE
    assert h.actuator.dispatch_count == 0


def test_s4_all_five_typed_tools_reach_same_fake_actuator_only_under_binding(tmp_path: Path) -> None:
    cases = [
        ("browser_semantic_click", {"action_ref": "object"}),
        ("browser_semantic_fill", {"action_ref": "object", "text": "x", "mode": "replace"}),
        ("browser_semantic_select", {"action_ref": "object", "value": "v"}),
        ("browser_semantic_scroll", {"action_ref": "object", "delta_pages": 1}),
        ("browser_semantic_navigate", {"action_ref": "resource", "url": "https://example.test/b"}),
    ]
    for index, (name, kwargs) in enumerate(cases):
        h = _Harness(tmp_path / str(index))
        args = dict(kwargs)
        args["action_ref"] = h.object_ref if args["action_ref"] == "object" else h.resource_ref
        with h.attempt(name, f"exec-{index}"):
            result = h.tools[name].execute(**args)
        assert result.status is ToolResultStatus.SUCCESS, (name, result.content)
        assert h.actuator.dispatch_count == 1
        assert h.actuator.dispatches[0]["verb"] == name.removeprefix("browser_semantic_")


def test_s4_kernel_order_has_cursor_and_target_bind_before_browser_entry() -> None:
    source = inspect.getsource(ActionRefMutationKernel.execute)
    assert source.index("prepare_current") < source.index("arm_receipt_cursor")
    assert source.index("arm_receipt_cursor") < source.index("bind_observed_target")
    assert source.index("bind_observed_target") < source.index("_action_adapter.execute")


def test_s4_crash_after_prepared_before_cursor_recovers_no_dispatch_no_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _Harness(tmp_path)
    args = {"action_ref": h.object_ref}

    def crash_after_prepared(_session_id: str, _execution_id: str) -> dict[str, Any]:
        raise SystemExit("fault-after-prepared")

    monkeypatch.setattr(h.correlator, "arm_receipt_cursor", crash_after_prepared)
    with (
        pytest.raises(SystemExit, match="fault-after-prepared"),
        h.wal_attempt("browser_semantic_click", args, label="crash-prepared"),
    ):
        h.tools["browser_semantic_click"].execute(**args)

    assert h.actuator.dispatch_count == 0
    sess = h.sessions.load(h.sid)
    assert h.journal.recover(h.sid, sess) == 1
    assert h.actuator.dispatch_count == 0
    recovered = [m for m in sess.messages if m.role == "tool"][-1]
    meta = recovered.metadata["tool_execution_recovery"]
    assert meta["state"] == "prepared_before_browser_running"
    assert meta["auto_reexecuted"] is False


def test_s4_crash_after_running_receipt_recovers_unknown_without_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _Harness(tmp_path)
    args = {"action_ref": h.object_ref}
    real_append = h.receipts.append

    def append_then_crash(session_id: str, action_id: str, receipt: dict[str, Any]):
        persisted = real_append(session_id, action_id, receipt)
        if receipt.get("status") == "running":
            raise SystemExit("fault-after-running")
        return persisted

    monkeypatch.setattr(h.receipts, "append", append_then_crash)
    with (
        pytest.raises(SystemExit, match="fault-after-running"),
        h.wal_attempt("browser_semantic_click", args, label="crash-running") as (
            _call,
            execution_id,
        ),
    ):
        h.tools["browser_semantic_click"].execute(**args)

    assert h.actuator.dispatch_count == 0
    prepared = h.bridge.load_exact(execution_id)
    assert [
        item["status"]
        for item in h.receipts.list_action(h.sid, str(prepared["inner_action_id"]))
    ] == ["running"]
    sess = h.sessions.load(h.sid)
    assert h.journal.recover(h.sid, sess) == 1
    assert h.actuator.dispatch_count == 0
    recovered = [m for m in sess.messages if m.role == "tool"][-1]
    meta = recovered.metadata["tool_execution_recovery"]
    assert meta["state"] == "browser_running_outcome_unknown"
    assert meta["auto_reexecuted"] is False


def test_s4_terminal_receipt_recovers_outer_wal_exactly_without_replay(tmp_path: Path) -> None:
    h = _Harness(tmp_path)
    args = {"action_ref": h.object_ref}
    with h.wal_attempt("browser_semantic_click", args, label="crash-terminal") as (
        _call,
        execution_id,
    ):
        result = h.tools["browser_semantic_click"].execute(**args)
    assert result.status is ToolResultStatus.SUCCESS
    assert h.actuator.dispatch_count == 1

    sess = h.sessions.load(h.sid)
    assert h.journal.recover(h.sid, sess) == 1
    assert h.actuator.dispatch_count == 1
    recovered = [m for m in sess.messages if m.role == "tool"][-1]
    meta = recovered.metadata["tool_execution_recovery"]
    assert meta["state"] == "browser_terminal_exact"
    assert meta["execution_id"] == execution_id
    assert meta["auto_reexecuted"] is False
    assert recovered.metadata["browser_action_receipt"]["status"] == "ok"
