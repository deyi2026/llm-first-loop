"""Generation-bound cancel prevents a stale HarmonyOS client stopping another Run."""
import json
import threading
from types import SimpleNamespace

from fastapi import FastAPI, Request

from llm_loop.core.loop.runner import BackgroundRunner, RunHandle
from llm_loop.web.routes import chat_cancel
from llm_loop.web.schemas import ChatCancelRequest


def _backend(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "llm_loop.resources.task_budget_dispatch.cancel_active_task_budget",
        lambda sid, gen, *, reason: captured.append((sid, gen, reason)),
    )
    engine = SimpleNamespace(registry=None)
    runner = BackgroundRunner(engine)
    engine.runner = runner
    runner._registry["sid"] = RunHandle(session_id="sid", run_generation="g-new")
    app = FastAPI()
    app.state.engine = engine
    request = Request({"type": "http", "app": app})
    return runner, request, captured


def test_stale_cancel_must_not_touch_new_run_or_budget(monkeypatch):
    runner, request, captured = _backend(monkeypatch)
    response = chat_cancel(
        ChatCancelRequest(session_id="sid", run_generation="g-old"), request
    )
    assert response.status_code == 409
    assert json.loads(response.body)["error"] == "run_generation_mismatch"
    assert runner.get_handle("sid")["cancelled"] is False
    assert captured == []


def test_exact_cancel_is_acknowledged_once_bound(monkeypatch):
    runner, request, captured = _backend(monkeypatch)
    response = chat_cancel(
        ChatCancelRequest(session_id="sid", run_generation="g-new"), request
    )
    assert response.status_code == 200
    assert json.loads(response.body)["cancelled"] is True
    assert runner.get_handle("sid")["cancelled"] is True
    assert len(captured) == 1
    assert captured[0][0:2] == ("sid", "g-new")


def test_legacy_session_cancel_remains_backward_compatible(monkeypatch):
    runner, request, _ = _backend(monkeypatch)
    response = chat_cancel(ChatCancelRequest(session_id="sid"), request)
    assert response.status_code == 200
    assert json.loads(response.body)["cancelled"] is True
    assert runner.get_handle("sid")["cancelled"] is True


def test_exact_cancel_does_not_apply_to_different_sync_run(monkeypatch):
    engine = SimpleNamespace(
        registry=None,
        _sync_guard=threading.Lock(),
        _sync_active={"sid"},
        session=SimpleNamespace(active_run_generation=lambda sid: "g-sync"),
    )
    runner = BackgroundRunner(engine)
    assert runner.cancel("sid", expected_run_generation="g-old") is False
    assert runner._sync_cancelled == {}
