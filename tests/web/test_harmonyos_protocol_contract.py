"""Provider-free native bridge integration against real LFL FastAPI routes.

No live provider, tunnel, credentials, external HTTP or real user sessions are used.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from llm_loop.core.loop.runner import BackgroundRunner, RunHandle
from llm_loop.web import build_app
from tests.unit.test_stream_equivalence import StreamingFakeLLM


def _events(raw: str) -> list[dict]:
    return [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]


def test_api26_native_stream_receipt_and_history_provider_free(build_test_engine):
    artifact = "artifact://v1/" + "a" * 32
    answer = "原生回执，测试用途 " + artifact
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM(answer)
    engine.runner = BackgroundRunner(engine, enabled=True)
    client = TestClient(build_app(engine=engine))

    response = client.post(
        "/api/v1/chat/stream", json={"message": "offline-fixture", "new_session": True}
    )
    assert response.status_code == 200
    events = _events(response.text)
    assert events[0]["type"] == "run_started"
    assert events[-1]["type"] == "done"
    sid = events[0]["data"]["session_id"]
    generation = events[0]["data"]["run_generation"]
    assert sid and generation
    assert events[-1]["data"]["session_id"] == sid
    assert events[-1]["data"]["final_answer"] == answer
    assert events[-1]["data"]["run_incomplete"] is False

    status = client.get("/api/v1/chat/stream/status", params={"session_id": sid})
    assert status.status_code == 200
    assert status.json()["running"] is False
    history = client.get(f"/api/v1/sessions/{sid}/messages", params={"limit": 20, "offset": 0})
    assert history.status_code == 200
    assert history.json()["session_id"] == sid
    assert any(row["role"] == "assistant" and artifact in row["content"]
               for row in history.json()["messages"])


def test_resume_identity_and_stale_cancel_rejected_by_real_routes(build_test_engine):
    engine, fake = build_test_engine([{"content": "must-not-call"}])
    sid = engine.session.create()
    runner = BackgroundRunner(engine, enabled=True)
    engine.runner = runner
    runner._registry[sid] = RunHandle(session_id=sid, run_generation="current-g")
    client = TestClient(build_app(engine=engine))

    snap = client.get("/api/v1/chat/stream/status", params={"session_id": sid})
    assert snap.status_code == 200
    assert snap.json()["running"] is True
    assert snap.json()["run_generation"] == "current-g"

    wrong = client.post("/api/v1/chat/stream", json={
        "message": "resume", "session_id": sid, "resume": True,
        "run_generation": "stale-g"
    })
    assert wrong.status_code == 409
    assert wrong.json()["error"] == "run_generation_mismatch"

    cancel = client.post("/api/v1/chat/cancel",
                         json={"session_id": sid, "run_generation": "stale-g"})
    assert cancel.status_code == 409
    assert runner.get_handle(sid)["cancelled"] is False
    assert len(fake.calls) == 0


def test_real_loopback_tcp_sse_against_fake_lfl_backend(build_test_engine):
    """Actual TCP/ASGI transport, but LFL FakeLLM only; never production/provider."""
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    engine, fake = build_test_engine([{"content": "loopback-completed"}])
    # Use the existing real LFL router and isolated engine from test fixture.
    engine.runner = BackgroundRunner(engine, enabled=True)
    app = build_app(engine=engine)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, "local fake backend failed to start"
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False,
                          timeout=8) as client:
            with client.stream("POST", "/api/v1/chat/stream",
                               json={"message": "loopback", "new_session": True}) as reply:
                assert reply.status_code == 200
                assert "text/event-stream" in reply.headers["content-type"]
                received = b"".join(reply.iter_bytes()).decode("utf-8")
            events = _events(received)
            assert [events[0]["type"], events[-1]["type"]] == ["run_started", "done"]
            assert events[-1]["data"]["final_answer"] == "loopback-completed"
            sid = events[0]["data"]["session_id"]
            status = client.get("/api/v1/chat/stream/status", params={"session_id": sid})
            assert status.status_code == 200 and status.json()["running"] is False
            assert len(fake.calls) == 1, "only the single explicit fake human turn"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive(), "fake server thread leaked"
