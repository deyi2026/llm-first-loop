"""SSE multi-tab fingerprint scan deduplication without hiding workspace changes."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import llm_loop.web.routes as routes


def _engine(root):
    return SimpleNamespace(session=SimpleNamespace(root=root))


def test_sse_fingerprint_reuses_same_root_within_ttl_and_refreshes_after(monkeypatch, tmp_path):
    root = tmp_path / "a"
    other = tmp_path / "b"
    root.mkdir()
    other.mkdir()
    calls = []

    def fake_scan(path):
        calls.append(path)
        return f"v{len(calls)}"

    monkeypatch.setattr(routes, "_sessions_fingerprint", fake_scan)
    with routes._SSE_FINGERPRINT_CACHE_LOCK:
        routes._SSE_FINGERPRINT_CACHE.clear()

    assert routes._session_events_fingerprint(_engine(root)) == f"{root}:v1"
    assert routes._session_events_fingerprint(_engine(root)) == f"{root}:v1"
    assert len(calls) == 1
    # A different workspace must never reuse the first workspace's fingerprint.
    assert routes._session_events_fingerprint(_engine(other)) == f"{other}:v2"
    assert len(calls) == 2

    # Force the entry past TTL without sleeping; next request must observe a new scan.
    with routes._SSE_FINGERPRINT_CACHE_LOCK:
        routes._SSE_FINGERPRINT_CACHE[os.fspath(root)] = (0.0, "v1")
    assert routes._session_events_fingerprint(_engine(root)) == f"{root}:v3"
    assert len(calls) == 3


def test_sse_fingerprint_concurrent_clients_share_one_scan(monkeypatch, tmp_path):
    calls = 0
    guard = threading.Lock()

    def slow_scan(_root):
        nonlocal calls
        with guard:
            calls += 1
        time.sleep(0.03)
        return "same"

    monkeypatch.setattr(routes, "_sessions_fingerprint", slow_scan)
    with routes._SSE_FINGERPRINT_CACHE_LOCK:
        routes._SSE_FINGERPRINT_CACHE.clear()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(routes._session_events_fingerprint, [_engine(tmp_path)] * 8))
    assert results == [f"{tmp_path}:same"] * 8
    assert calls == 1


def test_sse_fingerprint_error_not_cached(monkeypatch, tmp_path):
    responses = iter(["err", "recovered"])
    calls = []

    def fake_scan(_root):
        value = next(responses)
        calls.append(value)
        return value

    monkeypatch.setattr(routes, "_sessions_fingerprint", fake_scan)
    with routes._SSE_FINGERPRINT_CACHE_LOCK:
        routes._SSE_FINGERPRINT_CACHE.clear()
    assert routes._session_events_fingerprint(_engine(tmp_path)) == f"{tmp_path}:err"
    assert routes._session_events_fingerprint(_engine(tmp_path)) == f"{tmp_path}:recovered"
    assert calls == ["err", "recovered"]
