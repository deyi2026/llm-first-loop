"""会话统计端点测试（M59，对齐 DSH 统计栏）."""

from __future__ import annotations

from fastapi.testclient import TestClient

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
