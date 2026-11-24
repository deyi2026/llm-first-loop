"""Bounded isolated 4/8-run read-path load probe (fake provider, real Web routes)."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from statistics import median
from threading import Event, Lock
from time import perf_counter, process_time

import pytest
from fastapi.testclient import TestClient

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.web import build_app


@pytest.mark.parametrize("workers", [4, 8])
def test_presentation_reads_during_parallel_runs(build_test_engine, workers):
    import sys

    resource = pytest.importorskip("resource")

    entered: Queue[int] = Queue()
    release = Event()
    lock = Lock()
    active = 0

    def hold(_calls):
        nonlocal active
        with lock:
            active += 1
            entered.put(active)
        assert release.wait(45), "isolated load probe release timed out"

    engine, fake = build_test_engine([{"content": "isolated load probe"}] * workers)
    fake.enable_stream({"deltas": ["first", "last"], "on_delta_n": {1: hold}})
    engine.runner = BackgroundRunner(engine, enabled=True)
    app = build_app(engine=engine)
    client = TestClient(app)
    ids = [engine.session.create() for _ in range(workers)]
    for _ in range(32):
        engine.session.create()

    def run(sid):
        return client.post("/api/v1/chat/stream", json={"session_id": sid, "message": "isolated probe"})

    def read(path):
        start = perf_counter()
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        return (perf_counter() - start) * 1000

    with ThreadPoolExecutor(max_workers=workers) as run_pool:
        futures = []
        try:
            # Admit each exact session after the previous one has emitted its first
            # delta; all remain live together while the second delta is held.
            for index, sid in enumerate(ids, 1):
                futures.append(run_pool.submit(run, sid))
                assert entered.get(timeout=10) == index
            assert active == workers
            wall = perf_counter()
            cpu = process_time()
            results = {}
            with ThreadPoolExecutor(max_workers=workers) as read_pool:
                for label, path in [
                    ("sessions", "/api/v1/sessions"),
                    ("board", "/api/v1/coordination/board"),
                    ("queue", f"/api/v1/chat/queue?session_id={ids[0]}"),
                    ("health", "/health"),
                ]:
                    samples = list(read_pool.map(read, [path] * (workers * 2)))
                    results[label] = (round(median(samples), 1), round(max(samples), 1))
            elapsed = perf_counter() - wall
            cpu_pct = (process_time() - cpu) / elapsed * 100
            peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak_mib = peak_rss / (1024**2 if sys.platform == "darwin" else 1024)
            print(f"LOAD_PROBE runs={workers} provider_overlap={active} "
                  f"requests={workers * 8} wall_s={elapsed:.3f} cpu_one_core_pct={cpu_pct:.1f} "
                  f"process_peak_rss_mib={peak_mib:.1f} median_max_ms={results}", flush=True)
        finally:
            release.set()
        for future in futures:
            response = future.result(timeout=30)
            assert response.status_code == 200, response.status_code
            assert '"type": "done"' in response.text or '"type":"done"' in response.text
    assert len(fake.calls) == workers
