"""SSE generator finalization must not deadlock the background run registry."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("query", ["cancel_reason", "get_handle"])
def test_sse_gc_cleanup_during_registry_query_remains_responsive(query: str) -> None:
    # Keep a broken non-reentrant lock in a bounded subprocess: a regression must
    # fail this test, rather than strand pytest's own request/worker threads.
    script = r'''
import gc
import sys
from types import SimpleNamespace
from unittest.mock import patch

from llm_loop.core.loop.runner import BackgroundRunner, EventBus, RunHandle
from llm_loop.web.routes import _stream_background

gc.disable()
runner = BackgroundRunner(SimpleNamespace())
bus = EventBus()
sid = "gc-sse-session"
handle = RunHandle(session_id=sid, _bus=bus)
q = bus.subscribe()
remaining = bus.subscribe()

class CollectOnLookup(dict):
    armed = False

    def get(self, key, default=None):
        if self.armed:
            self.armed = False
            # Deterministically place real cyclic GC at the production incident's
            # lookup, while cancel_reason/get_handle owns the registry guard.
            gc.collect()
        return super().get(key, default)

registry = CollectOnLookup({sid: handle})
runner._registry = registry
q.put({"type": "delta", "delta": SimpleNamespace(text="first", reasoning="")})
with patch.object(runner, "start", return_value=(handle, q)):
    stream = _stream_background(runner, sid, "hi", None)
    assert "run_started" in next(stream)
    assert "first" in next(stream)
    unreachable = [stream]
    unreachable.append(unreachable)
    del stream, unreachable

registry.armed = True
print("collecting SSE under registry guard", flush=True)
result = getattr(runner, sys.argv[1])(sid)
if sys.argv[1] == "cancel_reason":
    assert result == ""
else:
    assert result["run_generation"] == handle.run_generation

# The disconnected subscription is gone; another subscriber and the run survive.
event = {"type": "delta", "delta": SimpleNamespace(text="after", reasoning="")}
bus.emit(event)
assert q.empty()
assert remaining.get_nowait() is event
assert runner.is_running(sid)
assert not handle.cancelled
assert runner.get_handle(sid)["status"] == "running"
runner.unsubscribe(sid, remaining)
bus.close()
print("SSE_GC_REENTRY_OK", flush=True)
'''
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, query],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{query}: cyclic SSE cleanup deadlocked the run registry")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SSE_GC_REENTRY_OK" in result.stdout
