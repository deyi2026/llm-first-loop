"""2026-08-20（镜像）: 会话统计面板按模型分桶——跨模型交替时总口径被稀释, 分桶归因."""

from __future__ import annotations


def test_by_model_bucketing_separates_models(monkeypatch):
    """聚合 request.usage 事件 → by_model 分桶（minimax 高命中 / deepseek 冷启动）."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import llm_loop.web.routes as routes

    events = [
        SimpleNamespace(type="request.usage", payload={
            "model": "minimax/MiniMax-M3", "tokens_in": 100000, "tokens_out": 100,
            "cache_hit": 98000, "llm_ms": 500, "tool_ms": 0, "ttft_ms": 100,
        }),
        SimpleNamespace(type="request.usage", payload={
            "model": "deepseek/deepseek-v4-flash", "tokens_in": 100000, "tokens_out": 100,
            "cache_hit": 0, "llm_ms": 500, "tool_ms": 0, "ttft_ms": 100,
        }),
    ]
    store = MagicMock()
    store.enabled = True
    store.read.return_value = events
    engine = MagicMock()
    engine.session._event_store = store
    engine.session.load.return_value = SimpleNamespace(messages=[SimpleNamespace(role="assistant")] * 2)

    request = MagicMock()
    monkeypatch.setattr(routes, "_engine_from", lambda req: engine)
    out = routes.session_stats("sid", request)
    assert out["by_model"]["minimax/MiniMax-M3"]["cache_hit_rate"] == 98.0
    assert out["by_model"]["deepseek/deepseek-v4-flash"]["cache_hit_rate"] == 0.0
    # 总口径被稀释（98K/200K = 49%）, 分桶揭示真相
    assert out["cache_hit_rate"] == 49.0
