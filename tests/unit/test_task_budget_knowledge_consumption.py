"""Bounded consumption preparation; zero public Provider traffic."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import replace
from pathlib import Path
from unittest import mock

import httpx
import pytest

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMClient
from llm_loop.resources.task_budget_dispatch import bind_task_budget, checked_provider_attempt
from llm_loop.resources.task_budget_process_transport import (
    IsolatedTransportProfile,
    bind_isolated_provider_transport,
    isolated_provider_stream,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore
from llm_loop.tools.registry import ToolRegistry
from llm_loop.web.task_budget_canary import _read_operator_config, bind_web_canary
from tests.unit.test_task_budget_admin_once import _open, _setup
from tests.unit.test_task_budget_physical_dispatch import _SideEffectTool

PROFILE = "web-glm-knowledge-consumption-v1"
URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def _consumption(tmp_path):
    event, plan = _setup(tmp_path)
    plan = replace(plan, profile=PROFILE)
    return event, plan, _open(plan, event, tmp_path)


def test_four_attempts_include_retries_and_fifth_is_not_dispatched(tmp_path):
    _, plan, execution = _consumption(tmp_path)
    row = plan.budget_store.read(plan.budget_id)
    assert row["grant"]["profile"] == PROFILE
    assert row["grant"]["limits"]["physical_attempts"] == 4
    assert row["grant"]["limits"]["tool_invocations"] == 8
    assert row["grant"]["limits"]["rounds"] is None
    assert row["grant"]["deadline_epoch_s"] <= time.time() + 180
    with bind_task_budget(execution), bind_isolated_provider_transport(IsolatedTransportProfile()):
        for i in range(4):
            if i == 0:
                with pytest.raises(RuntimeError, match="offline retry"), checked_provider_attempt(
                    provider_id="glm", model_id="glm-5.3", wire_protocol="openai", target_url=URL,
                ):
                    raise RuntimeError("offline retry")
            else:
                with checked_provider_attempt(
                    provider_id="glm", model_id="glm-5.3", wire_protocol="openai", target_url=URL,
                ):
                    pass
        with pytest.raises(TaskBudgetDeniedError, match="budget_exhausted:physical_attempts"), checked_provider_attempt(
            provider_id="glm", model_id="glm-5.3", wire_protocol="openai", target_url=URL,
        ):
            pytest.fail("fifth attempt dispatched")
    report = plan.budget_store.report(plan.budget_id)
    assert report["used_or_reserved"]["physical_attempts"] == 4
    assert report["physical_quiescence_verified"] is False


@pytest.mark.parametrize("name,action", [
    ("method_manage", "save_candidate"), ("method_manage", "record_qualification"),
    ("method_manage", "refine"), ("method_manage", "annotate_freshness"),
    ("refine_experience", "archive"), ("refine_experience", "invalidate"),
    ("refine_experience", "restore"), ("method_manage", None),
    ("execute_command", "record_use"), ("schedule", "record_use"),
    ("spawn_subagent", "record_use"), ("save_experience", "record_use"),
    ("search_records", None),
])
def test_real_registry_denies_mutations_before_tool_side_effect(tmp_path, name, action):
    _, plan, execution = _consumption(tmp_path)
    effects = []
    registry = ToolRegistry()
    registry.register(_SideEffectTool(name, effects))
    with bind_task_budget(execution):
        result = registry.execute(ToolCall(id="blocked", name=name, arguments={"action": action}))
    assert result.status is ToolResultStatus.BLOCKED
    assert effects == []
    assert plan.budget_store.read(plan.budget_id)["reservations"] == {}


def test_real_registry_reads_and_use_declarations_share_eight_tool_ceiling(tmp_path):
    _, plan, execution = _consumption(tmp_path)
    effects = []
    registry = ToolRegistry()
    for name in ("search_records", "method_manage", "refine_experience"):
        registry.register(_SideEffectTool(name, effects))
    calls = [
        ToolCall(id=str(i), name=name, arguments={"action": "record_use", "kind": "method"})
        for i, name in enumerate(["search_records"] * 6 + ["method_manage", "refine_experience"])
    ]
    with bind_task_budget(execution):
        results = registry.execute_many(calls)
        extra = registry.execute(ToolCall(id="ninth", name="search_records", arguments={"kind": "method"}))
    assert all(r.status is ToolResultStatus.SUCCESS for r in results)
    assert extra.status is ToolResultStatus.BLOCKED
    assert len(effects) == 8
    assert plan.budget_store.report(plan.budget_id)["used_or_reserved"]["tool_invocations"] == 8


@pytest.mark.parametrize("kind", ["memory", "all", "archive", None, {}, []])
def test_search_cannot_trigger_other_stores_or_memory_query_rewriter(tmp_path, kind):
    _, plan, execution = _consumption(tmp_path)
    effects = []
    registry = ToolRegistry()
    registry.register(_SideEffectTool("search_records", effects))
    with bind_task_budget(execution):
        result = registry.execute(ToolCall(id="no-rewrite", name="search_records", arguments={"kind": kind}))
    assert result.status is ToolResultStatus.BLOCKED
    assert effects == []
    assert plan.budget_store.read(plan.budget_id)["reservations"] == {}


def test_profile_cannot_reissue_spent_admin_authorization_after_restart(tmp_path):
    event, plan, _ = _consumption(tmp_path)
    recovered = replace(plan, budget_store=TaskBudgetStore(plan.budget_store.directory))
    with pytest.raises(TaskBudgetDeniedError, match="operator_budget_proof_replayed"):
        _open(recovered, event, tmp_path, generation="run-2")
    # Changing the profile cannot turn the same authorization ID into a new grant.
    with pytest.raises(TaskBudgetDeniedError, match="operator_budget_proof_replayed"):
        _open(replace(recovered, profile="web-glm-one-physical-attempt-v3"), event, tmp_path)


@pytest.mark.parametrize("target", [
    "http://127.0.0.1:8903/api/chat", "https://fixture.invalid/api/chat",
    "https://open.bigmodel.cn/api/chat?redirect=1",
])
def test_unqualified_endpoint_has_zero_provider_reservations(tmp_path, target):
    _, plan, execution = _consumption(tmp_path)
    with (
        bind_task_budget(execution), bind_isolated_provider_transport(IsolatedTransportProfile()),
        pytest.raises(TaskBudgetDeniedError), checked_provider_attempt(
            provider_id="glm", model_id="glm-5.3", wire_protocol="openai", target_url=target,
        ),
    ):
        pytest.fail("invalid endpoint dispatched")
    assert plan.budget_store.read(plan.budget_id)["reservations"] == {}


def test_consumption_requires_verified_isolate_and_denies_proxy(tmp_path):
    event, plan = _setup(tmp_path)
    with pytest.raises(TaskBudgetDeniedError):
        replace(plan, profile=PROFILE, provider_proxy="http://127.0.0.1:6152")
    execution = _open(replace(plan, profile=PROFILE), event, tmp_path)
    with bind_task_budget(execution), pytest.raises(TaskBudgetDeniedError), checked_provider_attempt(
        provider_id="glm", model_id="glm-5.3", wire_protocol="openai", target_url=URL,
    ):
        pytest.fail("no isolated transport")


def test_final_transport_rechecks_url_and_dispatched_reservation(tmp_path):
    _, plan, execution = _consumption(tmp_path)
    with (
        bind_task_budget(execution), bind_isolated_provider_transport(IsolatedTransportProfile()),
        httpx.Client() as client,
        mock.patch("llm_loop.resources.task_budget_process_transport._Attempt") as child,
    ):
        with pytest.raises(TaskBudgetDeniedError, match="positive_send_without_dispatched"), isolated_provider_stream(
            client, "POST", URL, json={"model": "glm-5.3"}, headers={}, timeout=2,
        ):
            pytest.fail("unreserved POST")
        with checked_provider_attempt(
            provider_id="glm", model_id="glm-5.3", wire_protocol="openai", target_url=URL,
        ), pytest.raises(TaskBudgetDeniedError), isolated_provider_stream(
            client, "POST", "https://fixture.invalid/api/chat",
            json={"model": "glm-5.3"}, headers={}, timeout=2,
        ):
            pytest.fail("redirected POST")
        child.assert_not_called()
    assert plan.budget_store.report(plan.budget_id)["used_or_reserved"]["physical_attempts"] == 1


def test_new_schema_is_closed_and_old_schema_cannot_expand(tmp_path: Path):
    config = {
        "schema": "web-task-budget-knowledge-consumption/v1", "profile": PROFILE,
        "authorization_id": "c" * 32, "session_id": "web-session",
        "workspace_root": str(tmp_path), "model_ref": "glm/glm-5.3",
        "valid_from_epoch_s": time.time(), "valid_until_epoch_s": time.time() + 300,
    }
    path = tmp_path / "approved.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    assert _read_operator_config(path) == config
    for bad in (
        {**config, "physical_attempts": 500}, {**config, "profile": "arbitrary"},
        {**config, "schema": "web-task-budget-admin-once/v1"},
        {**config, "provider_proxy": "http://127.0.0.1:6152"},
    ):
        path.write_text(json.dumps(bad))
        with pytest.raises(TaskBudgetDeniedError):
            _read_operator_config(path)


def test_real_client_four_decisions_use_reserved_isolated_transport(tmp_path):
    _, plan, execution = _consumption(tmp_path)
    payloads = []

    def local_attempt(**kwargs):
        payloads.append(kwargs["payload"])
        body = b'data: {"choices":[{"delta":{"content":"offline"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        attempt = mock.Mock()
        attempt.next_frame.side_effect = [
            {"event": "headers", "status": 200,
             "headers": [["content-type", "text/event-stream"]], "http_version": "HTTP/1.1"},
            {"event": "body", "data": base64.b64encode(body).decode()}, {"event": "end"},
        ]
        return attempt

    client = LLMClient(
        api_key="fixture-key", base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-5.3", provider="glm", guard_enabled=False, retry_disconnect=0,
    )
    try:
        with (
            bind_task_budget(execution), bind_isolated_provider_transport(IsolatedTransportProfile()),
            mock.patch("llm_loop.resources.task_budget_process_transport._Attempt", side_effect=local_attempt),
        ):
            for i in range(4):
                response = client.chat([{"role": "user", "content": f"decision-{i}"}], tools=[])
                assert response.content == "offline"
            with pytest.raises(TaskBudgetDeniedError, match="budget_exhausted:physical_attempts"):
                client.chat([{"role": "user", "content": "forbidden-fifth"}], tools=[])
    finally:
        client.close()
    assert len(payloads) == 4
    assert [p["messages"][-1]["content"] for p in payloads] == [f"decision-{i}" for i in range(4)]
    assert all(p["model"] == "glm-5.3" for p in payloads)
    assert plan.budget_store.report(plan.budget_id)["used_or_reserved"]["physical_attempts"] == 4


def test_web_bootstrap_consumption_schema_binds_only_existing_session(build_test_engine, tmp_path, monkeypatch):
    from llm_loop.core.loop.runner import BackgroundRunner
    from llm_loop.resources.task_budget_admin_once import active_admin_once_plan
    from llm_loop.web import build_app
    from llm_loop.web import task_budget_canary as canary

    engine, _ = build_test_engine([])
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine.set_workspace(str(workspace), "consumption-workspace")
    sid = engine.session.create()
    engine.runner = BackgroundRunner(engine)
    engine._event_store = EventStore(tmp_path / "test-events")
    config = {
        "schema": "web-task-budget-knowledge-consumption/v1", "profile": PROFILE,
        "authorization_id": "d" * 32, "session_id": sid,
        "workspace_root": str(workspace), "model_ref": "glm/glm-5.3",
        "valid_from_epoch_s": time.time() - 1, "valid_until_epoch_s": time.time() + 300,
    }
    path = tmp_path / "not-production.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    monkeypatch.setattr(canary, "business_config_snapshot",
                        lambda _: {"LFL_TASK_BUDGET_WEB_CANARY_CONFIG": str(path)})
    app = build_app(engine=engine)
    selected = app.state.task_budget_web_canary
    assert selected.session_id == sid and selected.plan.profile == PROFILE
    assert engine._task_budget_restricted_session_id == sid
    with bind_web_canary(selected):
        assert active_admin_once_plan() is selected.plan
    assert active_admin_once_plan() is None
    assert not list(selected.plan.budget_store.directory.glob("budget-*.json"))
