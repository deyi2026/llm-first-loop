"""Real Web worker -> durable human event -> signed TaskBudget scope."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_dispatch import active_task_budget
from llm_loop.resources.task_budget_event_authority import SignedWebEventPlan
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError
from llm_loop.web import build_app
from llm_loop.web.task_budget_canary import (
    WebTaskBudgetCanary,
    choose_signed_web_canary,
    load_operator_web_canary,
)
from tests.unit.test_task_budget_signed_human_event import _fixture


def _zero_canary(engine: Any, session_id: str, tmp_path: Path):
    events = EventStore(tmp_path / "actual-web-events")
    engine._event_store = events
    _old, _event, issuer, keys, ledger = _fixture(tmp_path / "issuer")

    def after_real_append(event):
        return issuer.approve_zero_web_event(
            event_store=events, event=event, operator_ticket="operator-ok",
            workspace_root=engine.workspace_root or "", session_id=session_id,
        )

    return WebTaskBudgetCanary(
        session_id, SignedWebEventPlan(after_real_append, keys, events, ledger)
    ), ledger


def _request_for(canary: WebTaskBudgetCanary) -> Request:
    app = Starlette()
    app.state.task_budget_web_canary = canary
    return Request({
        "type": "http", "app": app, "method": "POST", "path": "/api/v1/chat/stream",
        "headers": [], "scheme": "http", "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 8903), "query_string": b"",
    })


def test_worker_denies_unqualified_provider_after_durable_signed_human_event(
    build_test_engine: Any, tmp_path: Path,
) -> None:
    engine, fake = build_test_engine([])
    session_id = engine.session.create()
    canary, ledger = _zero_canary(engine, session_id, tmp_path)
    runner = BackgroundRunner(engine)
    engine.runner = runner
    handle, events = runner.start(
        session_id, "actual human request", ingress=issue_ingress("web"),
        signed_web_canary=canary,
    )
    assert handle is not None and events is not None
    terminal = None
    for _ in range(20):
        event = events.get(timeout=5)
        if event["type"] in ("done", "error"):
            terminal = event
            break
    assert terminal is not None and terminal["type"] == "error", terminal
    assert "provider_adapter_unqualified" in terminal["error"]
    assert fake.calls == [], "no model/Provider dispatch behind signed budget"
    human_events = [row for row in canary.plan.event_store.read(session_id)
                    if row.type == "message.appended" and row.payload.get("role") == "user"]
    assert len(human_events) == 1
    budget_id = f"webbudget-event-{human_events[0].event_id.replace('-', '')}"
    root = ledger.read(budget_id)
    assert root["grant"]["human_turn_ref"].startswith("event-")
    assert root["grant"]["limits"]["physical_attempts"] == 0
    assert root["reservations"] == {}
    assert active_task_budget() is None


def test_default_web_remains_off(build_test_engine: Any, monkeypatch) -> None:
    engine, _ = build_test_engine([])
    monkeypatch.delenv("LFL_TASK_BUDGET_WEB_CANARY_CONFIG", raising=False)
    # delenv alone cannot hide a developer .env that pins a real canary config:
    # business_config_snapshot reads dotenv, not just process env. Isolate the
    # snapshot the same way test_real_web_bootstrap does (admin_once tests).
    from llm_loop.web import task_budget_canary as _web_canary

    monkeypatch.setattr(_web_canary, "business_config_snapshot", lambda _s: {})
    assert load_operator_web_canary(engine) is None
    assert build_app(engine=engine).state.task_budget_web_canary is None


def test_sync_route_cannot_bypass_selected_canary(
    build_test_engine: Any, tmp_path: Path, monkeypatch,
) -> None:
    engine, fake = build_test_engine(["should not run"])
    session_id = engine.session.create()
    canary, _ = _zero_canary(engine, session_id, tmp_path)
    monkeypatch.delenv("LFL_TASK_BUDGET_WEB_CANARY_CONFIG", raising=False)
    # delenv alone cannot hide a developer .env that pins a real canary config:
    # business_config_snapshot reads dotenv, not just process env. Isolate the
    # snapshot the same way test_real_web_bootstrap does (admin_once tests).
    from llm_loop.web import task_budget_canary as _web_canary

    monkeypatch.setattr(_web_canary, "business_config_snapshot", lambda _s: {})
    app = build_app(engine=engine)
    app.state.task_budget_web_canary = canary
    response = TestClient(app).post("/api/v1/chat", json={
        "session_id": session_id, "message": "bypass",
        "model": "glm/glm-5.3",
    })
    assert response.status_code == 409
    assert response.json()["error"] == "budget_canary_requires_stream"
    assert fake.calls == []


@pytest.mark.parametrize("model,queue_id,attachments,authenticated", [
    ("glm/glm-5.3", False, False, False),
    ("glm/glm-5.2", False, False, True),
    ("glm/glm-5.3", True, False, True),
    ("glm/glm-5.3", False, True, True),
])
def test_selected_session_denies_untrusted_or_wrong_route(
    build_test_engine: Any, tmp_path: Path, monkeypatch,
    model: str, queue_id: bool, attachments: bool, authenticated: bool,
) -> None:
    from llm_loop.web import auth

    engine, _ = build_test_engine([])
    session_id = engine.session.create()
    canary, ledger = _zero_canary(engine, session_id, tmp_path)
    monkeypatch.setattr(auth, "request_authenticated", lambda _req: authenticated)
    request = _request_for(canary)
    with pytest.raises(TaskBudgetDeniedError):
        choose_signed_web_canary(
            request, session_id, model=model, resume=False,
            queued=queue_id, attachments=attachments,
        )
    assert not list(ledger.directory.glob("budget-*.json"))


def test_other_session_or_resume_never_allocates_a_new_canary_run(
    build_test_engine: Any, tmp_path: Path,
) -> None:
    engine, _ = build_test_engine([])
    session_id = engine.session.create()
    canary, ledger = _zero_canary(engine, session_id, tmp_path)
    request = _request_for(canary)
    for target, resume in (("other-session", False), (session_id, True)):
        assert choose_signed_web_canary(
            request, target, model="glm/glm-5.3", resume=resume,
            queued=False, attachments=False,
        ) is None
    assert not list(ledger.directory.glob("budget-*.json"))


def test_real_web_stream_passes_pinned_plan_to_background_runner(
    build_test_engine: Any, tmp_path: Path, monkeypatch,
) -> None:
    from llm_loop.web import auth

    engine, _ = build_test_engine([])
    session_id = engine.session.create()
    canary, _ = _zero_canary(engine, session_id, tmp_path)
    monkeypatch.delenv("LFL_TASK_BUDGET_WEB_CANARY_CONFIG", raising=False)
    # delenv alone cannot hide a developer .env that pins a real canary config:
    # business_config_snapshot reads dotenv, not just process env. Isolate the
    # snapshot the same way test_real_web_bootstrap does (admin_once tests).
    from llm_loop.web import task_budget_canary as _web_canary

    monkeypatch.setattr(_web_canary, "business_config_snapshot", lambda _s: {})
    monkeypatch.setattr(auth, "request_authenticated", lambda _req: True)
    app = build_app(engine=engine)
    app.state.task_budget_web_canary = canary
    runner = BackgroundRunner(engine)
    engine.runner = runner
    captured = []

    def record(_sid, _text, **kwargs):
        captured.append(kwargs.get("signed_web_canary"))
        return None, None  # no Provider side effect in pre-start route test

    with mock.patch.object(runner, "start", side_effect=record):
        response = TestClient(app).post("/api/v1/chat/stream", json={
            "session_id": session_id, "message": "one limited request",
            "model": "glm/glm-5.3", "model_change": True,
        })
    assert response.status_code == 200
    assert captured == [canary]
