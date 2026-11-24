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



def test_sse_shared_probe_eight_clients_one_read_and_cache(monkeypatch, tmp_path):
    import asyncio

    calls = 0
    engine = _engine(tmp_path)

    async def read(_engine):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return f"v{calls}"

    async def scenario():
        probe = routes._SSESharedProbe(read, lambda value: value != "err", "err")
        assert await asyncio.gather(*(probe.read(engine) for _ in range(8))) == ["v1"] * 8
        assert calls == 1
        assert await probe.read(engine) == "v1"
        assert calls == 1
        monkeypatch.setattr(routes, "_SSE_FINGERPRINT_CACHE_TTL_S", 0)
        assert await asyncio.gather(*(probe.read(engine) for _ in range(8))) == ["v2"] * 8
        assert calls == 2

    asyncio.run(scenario())


def test_sse_shared_probe_cancelled_client_does_not_cancel_other_readers(tmp_path):
    import asyncio

    engine = _engine(tmp_path)

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def read(_engine):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return "v1"

        probe = routes._SSESharedProbe(read, lambda value: value != "err", "err")
        first = asyncio.create_task(probe.read(engine))
        await started.wait()
        second = asyncio.create_task(probe.read(engine))
        first.cancel()
        from contextlib import suppress

        with suppress(asyncio.CancelledError):
            await first
        release.set()
        assert await second == "v1"
        assert calls == 1

    asyncio.run(scenario())


def test_sse_shared_probe_discards_old_workspace_and_does_not_cache_errors(tmp_path):
    import asyncio

    engine = _engine(tmp_path)

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def read(_engine):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await release.wait()
                return "old"
            if calls == 2:
                return "err"
            return "new"

        probe = routes._SSESharedProbe(read, lambda value: value != "err", "err")
        first = asyncio.create_task(probe.read(engine))
        await started.wait()
        engine._workspace_epoch = 1
        second = asyncio.create_task(probe.read(engine))
        await asyncio.sleep(0)
        release.set()
        assert await first == "err"
        assert await second == "err"
        assert calls == 1
        assert await probe.read(engine) == "err"
        assert await probe.read(engine) == "new"
        assert calls == 3

    asyncio.run(scenario())


def test_sse_shared_probes_are_app_local_and_share_provider_reads(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    calls = 0
    engine = _engine(tmp_path)

    async def provider(_engine):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return "provider-v1", {"type": "providers_updated"}

    monkeypatch.setattr(routes, "_providers_events_fingerprint_async", provider)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))
    other = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))

    async def scenario():
        session_probe, provider_probe = routes._sse_shared_probes(request)
        assert routes._sse_shared_probes(request) == (session_probe, provider_probe)
        assert routes._sse_shared_probes(other)[1] is not provider_probe
        values = await asyncio.gather(*(provider_probe.read(engine) for _ in range(8)))
        assert values == [("provider-v1", {"type": "providers_updated"})] * 8
        assert calls == 1
        assert await routes._sse_shared_probes(other)[1].read(engine) == values[0]
        assert calls == 2

    asyncio.run(scenario())



def test_sse_initial_provider_probe_does_not_block_event_loop(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    engine = _engine(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_provider(_engine):
        started.set()
        assert release.wait(timeout=1.0)
        return "provider-v1", {"type": "providers_updated"}

    monkeypatch.setattr(routes, "_providers_events_fingerprint", slow_provider)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))

    async def scenario():
        task = asyncio.create_task(routes.stream_session_events(request))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.001)
            assert started.is_set()
            assert not task.done()
            release.set()
            response = await asyncio.wait_for(task, timeout=1.0)
            assert response.media_type == "text/event-stream"
        finally:
            release.set()

    asyncio.run(scenario())



def test_sse_shared_probe_timeout_does_not_duplicate_slow_worker(monkeypatch, tmp_path):
    import asyncio

    engine = _engine(tmp_path)
    monkeypatch.setattr(routes, "_SSE_SHARED_PROBE_WAIT_S", 0.01)

    async def scenario():
        release = asyncio.Event()
        calls = 0

        async def read(_engine):
            nonlocal calls
            calls += 1
            await release.wait()
            return "recovered"

        probe = routes._SSESharedProbe(read, lambda value: value != "err", "err")
        assert await asyncio.gather(*(probe.read(engine) for _ in range(8))) == ["err"] * 8
        assert await probe.read(engine) == "err"
        assert calls == 1
        release.set()
        assert await probe.read(engine) == "recovered"
        assert calls == 1

    asyncio.run(scenario())


def test_sse_provider_and_session_changes_both_delivered_in_one_tick(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    engine = _engine(tmp_path)
    version = 0
    checks = 0

    async def session(_engine):
        return f"session:{version}"

    async def provider(_engine):
        return f"provider:{version}", {"type": "providers_updated"}

    async def tick(_seconds):
        nonlocal version
        version += 1

    async def disconnected():
        nonlocal checks
        checks += 1
        return checks > 1

    monkeypatch.setattr(routes, "_SSE_FINGERPRINT_CACHE_TTL_S", 0)
    monkeypatch.setattr(routes, "_session_events_fingerprint_async", session)
    monkeypatch.setattr(routes, "_providers_events_fingerprint_async", provider)
    monkeypatch.setattr(routes.asyncio, "sleep", tick)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(engine=engine)),
        is_disconnected=disconnected,
    )

    async def scenario():
        response = await routes.stream_session_events(request)
        frames = [str(frame) async for frame in response.body_iterator]
        assert any("event: providers_updated" in frame for frame in frames)
        assert any("event: sessions_updated" in frame for frame in frames)

    asyncio.run(scenario())
