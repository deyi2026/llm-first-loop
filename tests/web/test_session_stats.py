"""会话统计端点测试（M59，对齐 DSH 统计栏）."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import Session
from llm_loop.event_log.store import EventStore
from llm_loop.web import build_app


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def test_session_stats_aggregates(build_test_engine):
    """统计端点聚合轮/步/tokens/缓存命中/耗时."""
    engine, _ = build_test_engine([{"content": "回答"}])
    sid = engine.session.create()
    # 构造两条 run：assistant（tokens+缓存+耗时）+ tool（步+工具耗时）
    from llm_loop.core.message import Message, MessageSource

    sess = engine.session.load(sid)
    sess.messages.append(Message(
        role="assistant", content="回答", source=MessageSource.USER,
        tokens_in=1000, tokens_out=200, tokens_cache_hit=700, llm_ms=3000.0, ttft_ms=800.0,
    ))
    sess.messages.append(Message(
        role="tool", content="[状态: success] ok", tool_call_id="t1", tool_name="read_file",
        source=MessageSource.USER, duration_ms=500.0,
    ))
    engine.session.save(sess)
    client = _make_client(engine)
    resp = client.get(f"/api/v1/sessions/{sid}/stats")
    assert resp.status_code == 200
    d = resp.json()
    assert d["turns"] == 1
    assert d["steps"] == 1
    assert d["tokens_in"] == 1000
    assert d["cache_hit"] == 700
    assert d["cache_hit_rate"] == 70.0
    assert d["llm_ms"] == 3000.0
    assert d["tool_ms"] == 500.0
    assert d["ttft_avg_ms"] == 800.0
    assert d["tok_s"] == round(200.0 / 3.0, 1)


def test_session_stats_empty(build_test_engine):
    """无消息会话 → 全零统计."""
    engine, _ = build_test_engine([{"content": "回答"}])
    sid = engine.session.create()
    client = _make_client(engine)
    resp = client.get(f"/api/v1/sessions/{sid}/stats")
    assert resp.status_code == 200
    d = resp.json()
    assert d["turns"] == 0 and d["tokens_in"] == 0 and d["cache_hit_rate"] == 0.0


def test_child_stats_use_physical_settlement_and_keep_parent_separate(
    build_test_engine, tmp_path,
):
    engine, _ = build_test_engine([])
    engine.session._event_store = EventStore(tmp_path / "event_logs")
    parent_id = engine.session.create()
    parent = engine.session.load(parent_id)
    parent.messages.append(Message(
        role="assistant", content="父会话", source=MessageSource.USER,
        tokens_in=1000, tokens_out=90, tokens_cache_hit=600, llm_ms=2000.0,
    ))
    engine.session.save(parent)
    child_id = "subagent_" + uuid4().hex[:12]
    engine.session.save(Session(session_id=child_id, parent_id=parent_id))
    store = engine.session._event_store
    assert store is not None and store.enabled
    # Same logical call, two actual Provider sends. Do not lose hidden retry.
    for i, cached in enumerate((10, 90)):
        result = store.append(child_id, "provider.transport.settled", {
            "call_id": "pcall:one",
            "attempt_id": f"pattempt:{i}",
            "provider_id": "minimax", "model_id": "MiniMax-M3.1",
            "started_at": 10.0 + i, "settled_at": 10.4 + i,
            "outcome": "success",
            "usage": {
                "input_tokens": 100, "output_tokens": 8,
                "cached_input_tokens": cached,
            },
        })
        assert result is not None

    client = _make_client(engine)
    parent_stats = client.get(f"/api/v1/sessions/{parent_id}/stats").json()
    assert parent_stats["tokens_in"] == 1000
    assert parent_stats["cache_hit"] == 600
    assert "agent_comparison" not in parent_stats
    child_stats = client.get(f"/api/v1/sessions/{child_id}/stats").json()
    assert child_stats["agent_scope"] == {
        "kind": "subagent", "parent_session_id": parent_id,
    }
    assert child_stats["tokens_in"] == 200
    assert child_stats["tokens_out"] == 16
    assert child_stats["cache_hit"] == 100
    assert child_stats["cache_hit_rate"] == 50.0
    assert child_stats["llm_ms"] == 800.0
    assert child_stats["usage_source"] == "provider.transport.settled"
    assert child_stats["physical_provider_usage"]["physical_attempts"] == 2
    assert child_stats["physical_provider_usage"]["logical_calls_observed"] == 1
    assert child_stats["physical_provider_usage"]["uncached_input_tokens"] == 100
    assert child_stats["physical_provider_usage"]["cache_usage_complete"] is True

    comparison = client.get(
        f"/api/v1/sessions/{parent_id}/stats", params={"child_id": child_id},
    )
    assert comparison.status_code == 200
    d = comparison.json()["agent_comparison"]
    assert "agent_comparison" not in client.get(f"/api/v1/sessions/{parent_id}/stats").json()
    assert d["parent"]["tokens_in"] == 1000
    assert d["child"]["tokens_in"] == 200
    assert d["reviewer_role"] == "unverified"


def test_child_comparison_refuses_unrelated_parent_and_unknown_cache(build_test_engine):
    engine, _ = build_test_engine([])
    parent_id = engine.session.create()
    other_id = engine.session.create()
    child_id = "subagent_" + uuid4().hex[:12]
    engine.session.save(Session(session_id=child_id, parent_id=other_id))
    client = _make_client(engine)
    assert client.get(
        f"/api/v1/sessions/{parent_id}/stats", params={"child_id": child_id},
    ).status_code == 404
    # No transport receipts exist: empty child must not report a 0%-hit rate.
    child_stats = client.get(f"/api/v1/sessions/{child_id}/stats").json()
    assert child_stats["cache_hit_rate"] is None
    assert child_stats["usage_source"] == "unavailable"


def test_child_opened_without_settlement_is_not_a_zero_hit_sample(
    build_test_engine, tmp_path,
):
    engine, _ = build_test_engine([])
    engine.session._event_store = EventStore(tmp_path / "events")
    parent_id = engine.session.create()
    child_id = "subagent_" + uuid4().hex[:12]
    engine.session.save(Session(session_id=child_id, parent_id=parent_id))
    assert engine.session._event_store.append(child_id, "provider.transport.opened", {
        "call_id": "pcall:pending", "attempt_id": "pattempt:pending",
        "provider_id": "glm", "model_id": "glm-5.3",
        "started_at": 20.0,
    }) is not None
    d = _make_client(engine).get(f"/api/v1/sessions/{child_id}/stats").json()
    assert d["usage_source"] == "provider.transport.settled+opened"
    assert d["cache_hit_rate"] is None
    assert d["physical_provider_usage"]["physical_attempts"] == 0
    assert d["physical_provider_usage"]["opened_unsettled_attempts"] == 1


def test_stats_uses_usage_projection_without_full_event_replay(build_test_engine, tmp_path, monkeypatch):
    engine, _ = build_test_engine([])
    engine.session._event_store = EventStore(tmp_path / "events")
    sid = engine.session.create()
    store = engine.session._event_store
    store.append(sid, "message.appended", {"content": "x" * 100000})
    store.append(sid, "request.usage", {"tokens_in": 100, "tokens_out": 10, "cache_hit": 50})

    def unexpected_replay(_session_id):
        raise AssertionError("statistics must not replay full event payloads")

    monkeypatch.setattr(store, "read", unexpected_replay)
    client = _make_client(engine)
    for expected in (100, 150):
        response = client.get(f"/api/v1/sessions/{sid}/stats")
        assert response.status_code == 200
        assert response.json()["tokens_in"] == expected
        assert response.json()["usage_source"] == "request.usage"
        if expected == 100:
            store.append(sid, "request.usage", {"tokens_in": 50, "tokens_out": 5})


def test_stats_warm_poll_skips_session_load_and_invalidates_on_transcript_change(
    build_test_engine, tmp_path, monkeypatch,
):
    from llm_loop.core.message import Message, MessageSource

    engine, _ = build_test_engine([])
    engine.session._event_store = EventStore(tmp_path / "events")
    sid = engine.session.create()
    engine.session._event_store.append(sid, "request.usage", {"tokens_in": 100})
    client = _make_client(engine)
    assert client.get(f"/api/v1/sessions/{sid}/stats").json()["turns"] == 0
    original = engine.session.load
    calls = []

    def count_load(session_id):
        calls.append(session_id)
        return original(session_id)

    monkeypatch.setattr(engine.session, "load", count_load)
    assert client.get(f"/api/v1/sessions/{sid}/stats").json()["tokens_in"] == 100
    assert calls == []
    sess = original(sid)
    sess.messages.append(Message(role="assistant", content="new", source=MessageSource.USER))
    engine.session.save(sess)
    assert client.get(f"/api/v1/sessions/{sid}/stats").json()["turns"] == 1
    assert calls == [sid]


def test_child_stats_reject_old_parent_after_transcript_only_change(
    build_test_engine, tmp_path,
):
    engine, _ = build_test_engine([])
    store = EventStore(tmp_path / "events")
    engine.session._event_store = store
    old_parent = engine.session.create()
    new_parent = engine.session.create()
    child_id = "subagent_" + uuid4().hex[:12]
    engine.session.save(Session(session_id=child_id, parent_id=old_parent))
    store.append(child_id, "request.usage", {"tokens_in": 7})
    client = _make_client(engine)
    child_url = f"/api/v1/sessions/{child_id}/stats"
    first = client.get(child_url).json()
    assert first["agent_scope"]["parent_session_id"] == old_parent
    assert client.get(
        f"/api/v1/sessions/{old_parent}/stats", params={"child_id": child_id},
    ).status_code == 200
    stamp = store.history_source_stamp(child_id)
    child = engine.session.load(child_id)
    child.parent_id = new_parent
    engine.session.save(child)
    assert store.history_source_stamp(child_id) == stamp
    assert client.get(
        f"/api/v1/sessions/{old_parent}/stats", params={"child_id": child_id},
    ).status_code == 404
    assert client.get(child_url).json()["agent_scope"]["parent_session_id"] == new_parent
    comparison = client.get(
        f"/api/v1/sessions/{new_parent}/stats", params={"child_id": child_id},
    )
    assert comparison.status_code == 200
    assert comparison.json()["agent_comparison"]["child"]["agent_scope"]["parent_session_id"] == new_parent
