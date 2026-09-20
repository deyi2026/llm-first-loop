from __future__ import annotations

import importlib
import importlib.util
import inspect
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from llm_loop.browser.action_ref import ActionRefResolution
from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import (
    current_run_generation,
    current_session_id,
    current_workspace_root,
)
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import ToolExecutionJournal
from llm_loop.event_log.store import EventStore


def _journal(tmp_path: Path):
    events = EventStore(tmp_path / "events", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=sessions,
    )
    call = ToolCall(id="p4live-s1-call", name="future_actionref_tool", arguments={})
    return journal, sessions, sid, call


def _strict_api() -> tuple[ModuleType, Any, type[BaseException]]:
    module = importlib.import_module("llm_loop.core.tool_execution_journal")
    authority = getattr(module, "current_action_ref_effect_binding_authority", None)
    error = getattr(module, "ActionRefEffectBindingError", None)
    assert callable(authority), "G2-S1 missing strict ActionRef effect-binding authority"
    assert error is not None, "G2-S1 missing stable strict-binding error type"
    return module, authority, error


def _bridge_api() -> tuple[ModuleType, Any, type[BaseException]]:
    spec = importlib.util.find_spec("llm_loop.browser.action_ref_execution")
    assert spec is not None, "G2-S1 missing durable ActionRef execution-bridge module"
    module = importlib.import_module("llm_loop.browser.action_ref_execution")
    store = getattr(module, "ActionRefExecutionBridgeStore", None)
    error = getattr(module, "ActionRefExecutionBridgeError", None)
    assert store is not None, "G2-S1 missing ActionRefExecutionBridgeStore"
    assert error is not None, "G2-S1 missing stable execution-bridge error type"
    return module, store, error


def _resolution(*, suffix: str = "a") -> ActionRefResolution:
    return ActionRefResolution(
        action_ref=f"actionref://browser/v0.1/{suffix * 32}",
        binding_id=f"binding-{suffix}",
        binding_digest=f"digest-{suffix}",
        target_kind="object",
        grounding_ref=f"grounding://browser/v0.1/test/object-{suffix}",
        observed_snapshot_id=f"snapshot-{suffix}",
        scope_ref=f"scope-{suffix}",
        semantic_object_or_resource_identity=f"object-{suffix}",
        browser_target_id_sha256=f"target-sha-{suffix}",
    )


class _ActiveAttempt:
    def __init__(
        self,
        *,
        journal: ToolExecutionJournal,
        sessions: SessionStore,
        sid: str,
        call: ToolCall,
        tmp_path: Path,
        run_generation: str = "run-s1",
    ) -> None:
        self.journal = journal
        self.sessions = sessions
        self.sid = sid
        self.call = call
        self.tmp_path = tmp_path
        self.run_generation = run_generation
        self.execution_id = "execution-s1"
        self._tokens: list[tuple[Any, Any]] = []
        self._run_token: object | None = None
        self._effect_cm: Any = None

    def __enter__(self):
        self._tokens = [
            (current_session_id, current_session_id.set(self.sid)),
            (current_workspace_root, current_workspace_root.set(str(self.tmp_path.resolve()))),
            (current_run_generation, current_run_generation.set(self.run_generation)),
        ]
        self._run_token = self.sessions._activate_run_save_token(  # noqa: SLF001
            self.sid, run_generation=self.run_generation
        )
        self._effect_cm = self.journal.effect_context(
            session_id=self.sid,
            execution_id=self.execution_id,
            round_no=3,
            call=self.call,
            workspace_root=str(self.tmp_path),
        )
        self._effect_cm.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
        if self._effect_cm is not None:
            self._effect_cm.__exit__(exc_type, exc, tb)
        if self._run_token is not None:
            self.sessions._deactivate_run_save_token(self.sid, self._run_token)  # noqa: SLF001
        for var, token in reversed(self._tokens):
            var.reset(token)
        return False


def test_s1_unbound_actionref_authority_rejects_while_legacy_direct_remains_allowed() -> None:
    module, authority, error = _strict_api()

    with module.current_effect_mutation_authority() as legacy_allowed:
        assert legacy_allowed is True

    with pytest.raises(error) as exc, authority():
        pass
    assert getattr(exc.value, "code", None) == "action_ref_effect_binding_required"


def test_s1_bound_authority_exposes_exact_outer_identity_and_revocation_fails_closed(
    tmp_path: Path,
) -> None:
    module, authority, error = _strict_api()
    journal, sessions, sid, call = _journal(tmp_path)

    with _ActiveAttempt(
        journal=journal, sessions=sessions, sid=sid, call=call, tmp_path=tmp_path
    ) as attempt:
        with authority() as binding:
            assert binding.session_id == sid
            assert binding.execution_id == attempt.execution_id
            assert binding.round_no == 3
            assert binding.tool_call_id == call.id
            assert binding.tool_name == call.name
            assert binding.workspace_root == str(tmp_path.resolve())
            assert binding.origin_run_generation == "run-s1"

        assert module.revoke_effect_binding_for_call(call.id) is True
        with pytest.raises(error) as exc, authority():
            pass
        assert getattr(exc.value, "code", None) == "action_ref_effect_binding_revoked"


@pytest.mark.parametrize("mismatch", ["session", "workspace", "run_generation"])
def test_s1_bound_authority_rejects_owner_context_drift(tmp_path: Path, mismatch: str) -> None:
    _module, authority, error = _strict_api()
    journal, sessions, sid, call = _journal(tmp_path)

    with _ActiveAttempt(
        journal=journal, sessions=sessions, sid=sid, call=call, tmp_path=tmp_path
    ):
        if mismatch == "session":
            token_var = current_session_id
            token = token_var.set("other-session")
        elif mismatch == "workspace":
            other = tmp_path / "other-workspace"
            other.mkdir()
            token_var = current_workspace_root
            token = token_var.set(str(other))
        else:
            token_var = current_run_generation
            token = token_var.set("run-other")
        try:
            with pytest.raises(error) as exc, authority():
                pass
            assert getattr(exc.value, "code", None) == "action_ref_effect_binding_owner_mismatch"
        finally:
            token_var.reset(token)


def test_s1_bound_authority_rejects_inactive_origin_run(tmp_path: Path) -> None:
    _module, authority, error = _strict_api()
    journal, sessions, sid, call = _journal(tmp_path)

    with _ActiveAttempt(
        journal=journal, sessions=sessions, sid=sid, call=call, tmp_path=tmp_path
    ) as attempt:
        assert attempt._run_token is not None  # noqa: SLF001
        sessions._deactivate_run_save_token(sid, attempt._run_token)  # noqa: SLF001
        attempt._run_token = None  # noqa: SLF001
        with pytest.raises(error) as exc, authority():
            pass
        assert getattr(exc.value, "code", None) == "action_ref_effect_binding_inactive_run"


def test_s1_execution_bridge_prepared_uses_only_current_outer_binding_identity(
    tmp_path: Path,
) -> None:
    _module, store_type, _error = _bridge_api()
    signature = inspect.signature(store_type.prepare_current)
    forbidden = {
        "session_id",
        "execution_id",
        "tool_call_id",
        "workspace_root",
        "origin_run_generation",
    }
    assert forbidden.isdisjoint(signature.parameters), (
        "outer WAL identity must come only from the current ToolExecutionJournal binding"
    )

    journal, sessions, sid, call = _journal(tmp_path)
    store = store_type(tmp_path / "actionref-executions")
    with _ActiveAttempt(
        journal=journal, sessions=sessions, sid=sid, call=call, tmp_path=tmp_path
    ) as attempt:
        record = store.prepare_current(
            resolution=_resolution(),
            inner_action_id="inner-action-1",
            expected_version="snapshot-a",
        )

    assert record["state"] == "prepared"
    assert record["execution_id"] == attempt.execution_id
    assert record["tool_call_id"] == call.id
    assert record["tool_name"] == call.name
    assert record["session_id"] == sid
    assert record["workspace_root"] == str(tmp_path.resolve())
    assert record["origin_run_generation"] == "run-s1"
    assert record["action_ref"] == _resolution().action_ref
    assert record["action_ref_binding_digest"] == _resolution().binding_digest
    assert record["grounding_ref"] == _resolution().grounding_ref
    assert record["inner_action_id"] == "inner-action-1"
    assert record["expected_version"] == "snapshot-a"
    assert record["browser_target_id_sha256"] == _resolution().browser_target_id_sha256


def test_s1_execution_bridge_is_idempotent_but_same_execution_cannot_rebind(
    tmp_path: Path,
) -> None:
    _module, store_type, error = _bridge_api()
    journal, sessions, sid, call = _journal(tmp_path)
    store = store_type(tmp_path / "actionref-executions")

    with _ActiveAttempt(
        journal=journal, sessions=sessions, sid=sid, call=call, tmp_path=tmp_path
    ):
        first = store.prepare_current(
            resolution=_resolution(),
            inner_action_id="inner-action-1",
            expected_version="snapshot-a",
        )
        second = store.prepare_current(
            resolution=_resolution(),
            inner_action_id="inner-action-1",
            expected_version="snapshot-a",
        )
        assert second == first

        with pytest.raises(error) as exc:
            store.prepare_current(
                resolution=_resolution(suffix="b"),
                inner_action_id="inner-action-2",
                expected_version="snapshot-b",
            )
        assert getattr(exc.value, "code", None) == "action_ref_execution_binding_conflict"


def test_s1_execution_bridge_prepare_write_failure_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, store_type, _error = _bridge_api()
    journal, sessions, sid, call = _journal(tmp_path)
    store = store_type(tmp_path / "actionref-executions")

    def fail_write(_path, _value):  # noqa: ANN001, ANN202
        raise OSError("injected PREPARED durability failure")

    monkeypatch.setattr(module, "_write_json_create_only", fail_write)
    with _ActiveAttempt(
        journal=journal, sessions=sessions, sid=sid, call=call, tmp_path=tmp_path
    ) as attempt:
        with pytest.raises(OSError, match="PREPARED durability failure"):
            store.prepare_current(
                resolution=_resolution(),
                inner_action_id="inner-action-1",
                expected_version="snapshot-a",
            )
        assert not store.record_path(attempt.execution_id).exists()


def test_s1_prepared_without_browser_running_is_no_dispatch_no_replay(tmp_path: Path) -> None:
    _module, store_type, _error = _bridge_api()
    journal, sessions, sid, call = _journal(tmp_path)
    store = store_type(tmp_path / "actionref-executions")

    with _ActiveAttempt(
        journal=journal, sessions=sessions, sid=sid, call=call, tmp_path=tmp_path
    ) as attempt:
        store.prepare_current(
            resolution=_resolution(),
            inner_action_id="inner-action-1",
            expected_version="snapshot-a",
        )

    recovery = store.classify_prepared_without_browser_running(attempt.execution_id)
    assert recovery["state"] == "prepared_before_browser_running"
    assert recovery["execution_id"] == attempt.execution_id
    assert recovery["executed"] is False
    assert recovery["dispatch_attempted"] is False
    assert recovery["auto_reexecuted"] is False


def test_s1_execution_bridge_has_no_browser_dispatch_dependency() -> None:
    module, _store_type, _error = _bridge_api()
    source = inspect.getsource(module)
    assert "BrowserActionAdapter" not in source
    assert "CdpBrowserMutationActuator" not in source
    assert ".dispatch(" not in source
