"""One administrator approval -> at most one Web/GLM physical attempt."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.event_log.model import build_message_payload
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_admin_once import (
    AdminOnceEventPlan,
    active_admin_once_plan,
    prepare_admin_once_event_budget,
)
from llm_loop.resources.task_budget_dispatch import (
    bind_task_budget,
    checked_provider_attempt,
    exact_workspace_scope,
)
from llm_loop.resources.task_budget_process_transport import (
    IsolatedTransportProfile,
    bind_isolated_provider_transport,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore
from llm_loop.web.task_budget_canary import (
    WebTaskBudgetCanary,
    _read_operator_config,
    bind_web_canary,
)


def _setup(tmp_path: Path, *, sid: str = "web-session", text: str = "one"):
    events = EventStore(tmp_path / "events")
    event = events.append_durable_human_message(
        sid,
        build_message_payload(
            index=0, role="user", source="user", content=text,
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    now = time.time()
    plan = AdminOnceEventPlan(
        session_id=sid, workspace_scope=exact_workspace_scope(str(tmp_path)),
        authorization_id="a" * 32,
        valid_from_epoch_s=now - 20, valid_until_epoch_s=now + 300,
        event_store=events, budget_store=TaskBudgetStore(tmp_path / "ledger"),
    )
    return event, plan


def _open(plan, event, tmp_path, *, generation="run-1", sid="web-session", text="one", ingress=None):
    return prepare_admin_once_event_budget(
        plan=plan, event=event, session_id=sid,
        workspace_root=str(tmp_path), run_generation=generation,
        user_text=text,
        ingress=issue_ingress("web") if ingress is None else ingress,
    )


def test_one_admin_config_one_attempt_and_unknown_usage(tmp_path: Path) -> None:
    event, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    row = plan.budget_store.read(plan.budget_id)
    assert row["grant"]["limits"]["physical_attempts"] == 1
    assert row["grant"]["limits"]["tool_invocations"] == 0
    assert row["grant"]["capabilities"] == {
        "allowed_tools": [], "allow_wake": False, "allow_subagents": False,
    }
    assert row["grant"]["exact_model_ref"] == "glm-5.3"
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    with bind_task_budget(execution), bind_isolated_provider_transport(IsolatedTransportProfile()):
        with checked_provider_attempt(
            provider_id="glm", model_id="glm-5.3", wire_protocol="openai",
            target_url=url,
        ):
            pass  # offline attempted dispatch receipt, never a real GLM send
        with (
            pytest.raises(TaskBudgetDeniedError, match="budget_exhausted:physical_attempts"),
            checked_provider_attempt(
                provider_id="glm", model_id="glm-5.3", wire_protocol="openai",
                target_url=url,
            ),
        ):
            pytest.fail("second physical attempt forbidden")
    report = plan.budget_store.report(plan.budget_id)
    assert report["used_or_reserved"]["physical_attempts"] == 1
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1


def test_second_event_second_run_and_restart_reuse_same_one_time_cas(tmp_path: Path) -> None:
    first, plan = _setup(tmp_path)
    _open(plan, first, tmp_path)
    second = plan.event_store.append_durable_human_message(
        plan.session_id,
        build_message_payload(
            index=1, role="user", source="user", content="two",
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    recovered = replace(plan, budget_store=TaskBudgetStore(plan.budget_store.directory))
    with pytest.raises(TaskBudgetDeniedError, match="operator_budget_proof_replayed"):
        _open(recovered, second, tmp_path, generation="run-2", text="two")
    with pytest.raises(TaskBudgetDeniedError, match="operator_budget_proof_replayed"):
        _open(recovered, first, tmp_path, generation="run-3")
    assert len(list(plan.budget_store.directory.glob("budget-*.json"))) == 1


def test_parallel_six_runs_only_one_durable_authority(tmp_path: Path) -> None:
    first, plan = _setup(tmp_path)
    events = [first]
    for i in range(1, 6):
        events.append(plan.event_store.append_durable_human_message(
            plan.session_id,
            build_message_payload(
                index=i, role="user", source="user", content=f"q{i}",
                metadata={"origin_layer": "user_instruction", "program_origin": False},
            ),
        ))
    barrier = threading.Barrier(6)

    def race(i):
        barrier.wait(timeout=8)
        try:
            _open(plan, events[i], tmp_path, generation=f"run-{i}",
                  text="one" if i == 0 else f"q{i}")
            return "accepted"
        except TaskBudgetDeniedError as exc:
            return exc.reason

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(race, range(6)))
    assert outcomes.count("accepted") == 1
    assert outcomes.count("operator_budget_proof_replayed") == 5
    assert len(list(plan.budget_store.directory.glob("budget-*.json"))) == 1


@pytest.mark.parametrize("failure", [
    "workspace", "session", "text", "foreign_event", "expired", "delegated",
    "no_web_ingress", "changed_event", "no_durable_event",
])
def test_wrong_scope_and_untrusted_events_zero_provider_attempts(
    tmp_path: Path, failure: str,
) -> None:
    event, plan = _setup(tmp_path)
    sid, text, workspace, ingress = "web-session", "one", str(tmp_path), issue_ingress("web")
    if failure == "workspace":
        workspace = str(tmp_path / "foreign")
    elif failure == "session":
        sid = "foreign"
    elif failure == "text":
        text = "other"
    elif failure == "foreign_event":
        event = replace(event, session_id="foreign")
    elif failure == "expired":
        plan = replace(plan, valid_from_epoch_s=time.time() - 180,
                       valid_until_epoch_s=time.time() - 30)
    elif failure == "delegated":
        ingress = issue_ingress("feishu")
    elif failure == "no_web_ingress":
        ingress = None
    elif failure == "changed_event":
        event = replace(event, payload={**event.payload, "content": "injected"})
    elif failure == "no_durable_event":
        event = replace(event, event_id="00000000-0000-4000-8000-000000000001")
    with pytest.raises(TaskBudgetDeniedError):
        prepare_admin_once_event_budget(
            plan=plan, event=event, session_id=sid,
            workspace_root=workspace, run_generation="run-1",
            user_text=text, ingress=ingress,
        )
    assert not list(plan.budget_store.directory.glob("budget-*.json"))


def test_real_worker_consumes_admin_once_and_cannot_send_fake_provider(
    build_test_engine, tmp_path: Path,
) -> None:
    engine, fake = build_test_engine([])
    sid = engine.session.create()
    plan = AdminOnceEventPlan(
        session_id=sid, workspace_scope=exact_workspace_scope(engine.workspace_root or ""),
        authorization_id="b" * 32,
        valid_from_epoch_s=time.time() - 1, valid_until_epoch_s=time.time() + 300,
        event_store=EventStore(tmp_path / "actual-web-events"),
        budget_store=TaskBudgetStore(tmp_path / "ledger"),
    )
    engine._event_store = plan.event_store
    engine._task_budget_restricted_session_id = sid
    runner = BackgroundRunner(engine)
    engine.runner = runner

    def finish_run(text):
        handle, bus = runner.start(
            sid, text, ingress=issue_ingress("web"),
            signed_web_canary=WebTaskBudgetCanary(sid, plan),
        )
        assert handle is not None and bus is not None
        for _ in range(15):
            item = bus.get(timeout=5)
            if item["type"] in {"done", "error"}:
                return item
        pytest.fail("no Run terminal")

    first = finish_run("actual approved request")
    assert first["type"] == "error"
    assert "provider_adapter_unqualified" in first["error"]
    assert fake.calls == []
    row = plan.budget_store.read(plan.budget_id)
    assert row["grant"]["limits"]["physical_attempts"] == 1
    assert row["grant"]["human_turn_ref"].startswith("event-")
    assert row["phase"] == "stop_requested"
    # Session was spent even though no Provider POST was attempted.
    second = finish_run("replayed human request")
    assert second["type"] == "error"
    assert "operator_budget_proof_replayed" in second["error"]
    assert fake.calls == []


def test_restricted_session_direct_engine_path_is_not_unlimited(
    build_test_engine,
) -> None:
    engine, fake = build_test_engine([])
    sid = engine.session.create()
    engine._task_budget_restricted_session_id = sid
    with pytest.raises(TaskBudgetDeniedError, match="restricted_web_session_requires_budget_plan"):
        engine.run(sid, "unbound sync call", ingress=issue_ingress("web"))
    assert fake.calls == []


def test_canary_scope_explicitly_binds_and_unbinds(tmp_path: Path) -> None:
    _event, plan = _setup(tmp_path)
    assert active_admin_once_plan() is None
    with bind_web_canary(WebTaskBudgetCanary(plan.session_id, plan)):
        assert active_admin_once_plan() is plan
    assert active_admin_once_plan() is None


def test_admin_config_0600_and_no_symlink_or_relaxed_permissions(tmp_path: Path) -> None:
    config = {
        "schema": "web-task-budget-admin-once/v1",
        "authorization_id": "c" * 32,
        "session_id": "web-session", "workspace_root": str(tmp_path),
        "model_ref": "glm/glm-5.3",
        "valid_from_epoch_s": time.time(),
        "valid_until_epoch_s": time.time() + 300,
    }
    target = tmp_path / "approved.json"
    target.write_text(json.dumps(config))
    target.chmod(0o600)
    assert _read_operator_config(target) == config
    target.chmod(0o644)
    with pytest.raises(TaskBudgetDeniedError):
        _read_operator_config(target)
    target.chmod(0o600)
    symlink = tmp_path / "redirect.json"
    symlink.symlink_to(target)
    with pytest.raises(OSError):
        _read_operator_config(symlink)


def test_real_web_bootstrap_installs_one_session_fence_without_signer(
    build_test_engine, tmp_path: Path, monkeypatch,
) -> None:
    from llm_loop.web import build_app
    from llm_loop.web import task_budget_canary as web_canary

    engine, _fake = build_test_engine([])
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine.set_workspace(str(workspace), "admin-once-ws")
    sid = engine.session.create()
    engine.runner = BackgroundRunner(engine)
    events = EventStore(tmp_path / "app-events")
    engine._event_store = events
    config = {
        "schema": "web-task-budget-admin-once/v1",
        "authorization_id": "d" * 32,
        "session_id": sid,
        "workspace_root": str(workspace),
        "model_ref": "glm/glm-5.3",
        "valid_from_epoch_s": time.time() - 1,
        "valid_until_epoch_s": time.time() + 300,
    }
    path = tmp_path / "admin-setup.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    monkeypatch.setattr(
        web_canary, "business_config_snapshot",
        lambda _service: {"LFL_TASK_BUDGET_WEB_CANARY_CONFIG": str(path)},
    )
    app = build_app(engine=engine)
    pinned = app.state.task_budget_web_canary
    assert isinstance(pinned.plan, AdminOnceEventPlan)
    assert pinned.session_id == sid
    assert engine._task_budget_restricted_session_id == sid
    # The pre-existing synchronous Engine API must also fail closed.
    with pytest.raises(TaskBudgetDeniedError, match="restricted_web_session_requires_budget_plan"):
        engine.run(sid, "unbound request", ingress=issue_ingress("web"))
    assert not list(pinned.plan.budget_store.directory.glob("budget-*.json"))


def test_operator_setup_exclusive_and_fsync_file(tmp_path: Path) -> None:
    from scripts.task_budget_admin_once_setup import _store_exclusive

    path = tmp_path / "one-run.json"
    row = {
        "schema": "web-task-budget-admin-once/v1", "authorization_id": "e" * 32,
        "session_id": "web-session", "workspace_root": str(tmp_path),
        "model_ref": "glm/glm-5.3", "valid_from_epoch_s": time.time(),
        "valid_until_epoch_s": time.time() + 300,
    }
    _store_exclusive(path, row)
    assert _read_operator_config(path) == row
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="must be new"):
        _store_exclusive(path, {**row, "authorization_id": "f" * 32})
    assert _read_operator_config(path) == row
