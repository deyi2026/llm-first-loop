"""Web ingress must not invent a character-based model-window hard gate.

Exact provider payload fit belongs to the routing/context layer, which has the real
tokenized system/history/tool payload. The Web adapter only validates request shape.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def _fake_small_window(engine, chars: int = 100) -> None:
    """Expose the old Web preflight trap without changing request-shape validity."""
    engine.llm.model = "fake-model"
    engine._effective_history_budget_detail = lambda _model, **_kwargs: {
        "model_window_budget": chars,
        "effective_budget": chars,
    }


def test_sync_does_not_treat_model_window_tokens_as_message_chars(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok"}])
    _fake_small_window(engine, 100)
    client = _make_client(engine)

    resp = client.post("/api/v1/chat", json={"message": "x" * 101})

    assert resp.status_code == 200
    assert len(fake.calls) == 1


def test_stream_does_not_treat_model_window_tokens_as_message_chars(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok"}])
    _fake_small_window(engine, 100)
    client = _make_client(engine)

    resp = client.post("/api/v1/chat/stream", json={"message": "x" * 101})

    assert resp.status_code == 200
    assert '"type": "done"' in resp.text
    assert len(fake.calls) == 1


def test_history_budget_is_not_a_single_user_message_gate(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok"}])
    object.__setattr__(engine.settings, "history_max_chars", 50)
    client = _make_client(engine)

    resp = client.post("/api/v1/chat", json={"message": "x" * 100})

    assert resp.status_code == 200
    assert len(fake.calls) == 1
