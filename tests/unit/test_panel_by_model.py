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
    store.read_usage_events.return_value = events  # 2026-11-26 起优先走 usage-only 读取
    engine = MagicMock()
    engine.session._event_store = store
    engine.session.load.return_value = SimpleNamespace(messages=[SimpleNamespace(role="assistant")] * 2)

    request = MagicMock()
    monkeypatch.setattr(routes, "_engine_from", lambda req: engine)
    # P0 projection（2026-11-26）接入后：注入直通 projection，绕过缓存层，
    # 保持本测试对聚合逻辑（loader 路径）的原语义验证。
    from llm_loop.web import session_stats_cache as _ssc

    class _PassthroughProjection:
        def compute_and_store(self, engine_arg, session_id, loader):
            return loader()

    monkeypatch.setattr(_ssc, "projection_for_engine", lambda eng: _PassthroughProjection())
    out = routes.session_stats("sid", request)
    assert out["by_model"]["minimax/MiniMax-M3"]["cache_hit_rate"] == 98.0
    assert out["by_model"]["deepseek/deepseek-v4-flash"]["cache_hit_rate"] == 0.0
    # 总口径被稀释（98K/200K = 49%）, 分桶揭示真相
    assert out["cache_hit_rate"] == 49.0
