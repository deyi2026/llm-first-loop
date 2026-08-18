"""EVO-20260818 cache_window_converge: architecture_status 缓存快照注入测试（spec §5.4.1-2）.

覆盖: cache_health/cache_guard 字段注入、session 透传、回调异常 fail-open、未注入 None。
"""

from llm_loop.introspection.status import ArchitectureStatusProvider


def _provider(**kw) -> ArchitectureStatusProvider:
    return ArchitectureStatusProvider(audit_dir=None, **kw)


def test_status_no_injection_fields_none():
    """未注入回调 → context_usage.cache_health/cache_guard 为 None（零回归）."""
    sp = _provider()
    snap = sp.snapshot()
    assert snap["context_usage"]["cache_health"] is None
    assert snap["context_usage"]["cache_guard"] is None


def test_status_injects_cache_health_field():
    """注入 cache_health 回调 → 字段填充."""
    sp = _provider()
    sp.set_cache_health_fn(lambda: {"win_in": 100, "win_hit": 90, "win_runs": 5})
    snap = sp.snapshot()
    ch = snap["context_usage"]["cache_health"]
    assert ch == {"win_in": 100, "win_hit": 90, "win_runs": 5}


def test_status_injects_cache_guard_field_with_session():
    """cache_guard 回调透传 session_id（grill-me Q11）."""
    sp = _provider()
    seen = []
    sp.set_cache_guard_fn(lambda sid: seen.append(sid) or {"recent_hit_rate": 0.92})
    snap = sp.snapshot(session_id="sess-abc")
    assert snap["context_usage"]["cache_guard"] == {"recent_hit_rate": 0.92}
    assert seen == ["sess-abc"]  # session 透传


def test_status_cache_callback_exception_fail_open():
    """回调抛异常 → 字段 None 不抛穿 architecture_status."""
    sp = _provider()
    sp.set_cache_health_fn(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    sp.set_cache_guard_fn(lambda _sid: (_ for _ in ()).throw(RuntimeError("boom")))
    snap = sp.snapshot()
    assert snap["context_usage"]["cache_health"] is None
    assert snap["context_usage"]["cache_guard"] is None
