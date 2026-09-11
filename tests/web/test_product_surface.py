"""Web V2 product surfaces expose mechanical facts and explicit user actions only."""

from __future__ import annotations

from fastapi.testclient import TestClient

from llm_loop.event_log.store import EventStore
from llm_loop.tools.builtin.job_registry import JobRegistry
from llm_loop.web import build_app


class _KillableProc:
    stdout = None
    stderr = None

    def __init__(self) -> None:
        self.terminated = False
        self.returncode = 0

    def terminate(self) -> None:
        self.terminated = True

    def wait(self) -> int:
        return self.returncode


def _client(engine) -> TestClient:
    return TestClient(build_app(engine=engine))


def test_job_web_surface_is_owner_scoped_and_explicit_kill(
    build_test_engine, monkeypatch
) -> None:
    engine, _ = build_test_engine([])
    sid = engine.session.create()
    other_sid = engine.session.create()
    reg = JobRegistry(event_store=None)
    JobRegistry._instance = reg
    proc = _KillableProc()
    job_id = reg.create(proc, "sleep-like", session_id=sid)
    reg.create(_KillableProc(), "other", session_id=other_sid)
    client = _client(engine)

    listed = client.get(f"/api/v1/sessions/{sid}/jobs")
    assert listed.status_code == 200
    jobs = listed.json()["jobs"]
    assert [row["job_id"] for row in jobs] == [job_id]
    assert "workspace_root" not in jobs[0]

    # Cross-session kill must never succeed: ownership is hard-scoped.
    cross = client.post(f"/api/v1/sessions/{other_sid}/jobs/{job_id}/kill")
    assert cross.status_code == 409
    assert proc.terminated is False

    killed = client.post(f"/api/v1/sessions/{sid}/jobs/{job_id}/kill")
    assert killed.status_code == 200
    assert proc.terminated is True
    second = client.post(f"/api/v1/sessions/{sid}/jobs/{job_id}/kill")
    assert second.status_code == 409


def test_continuity_status_never_returns_model_text_or_reasoning(
    build_test_engine, tmp_path
) -> None:
    engine, _ = build_test_engine([])
    sid = engine.session.create()
    events = EventStore(tmp_path / "events", enabled=True)
    engine.session._event_store = events
    events.append(sid, "request.meta", {"model": "m"})
    events.append(
        sid,
        "llm.partial_checkpoint",
        {
            "provider": "provider-a",
            "model": "model-a",
            "text_tail": "SECRET TEXT",
            "reasoning_tail": "SECRET REASONING",
            "text_chars": 11,
            "reasoning_chars": 16,
            "partial_sha256": "a" * 64,
        },
    )

    resp = _client(engine).get(f"/api/v1/sessions/{sid}/continuity")
    assert resp.status_code == 200
    body = resp.json()
    assert body["open"] is True
    assert body["provider"] == "provider-a"
    assert body["model"] == "model-a"
    assert body["text_chars"] == 11
    assert body["reasoning_chars"] == 16
    serialized = resp.text
    assert "SECRET TEXT" not in serialized
    assert "SECRET REASONING" not in serialized


def test_capability_manifest_reflects_registered_routes(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    resp = _client(engine).get("/api/v1/capabilities")
    assert resp.status_code == 200
    caps = resp.json()["capabilities"]
    for key in ("attachments", "fsTree", "pin", "archive", "delete", "fork", "feedback", "jobs", "continuity", "providerAdmin"):
        assert caps.get(key) is True


def test_capability_manifest_reports_false_when_route_missing(build_test_engine) -> None:
    from llm_loop.web import routes as routes_mod

    engine, _ = build_test_engine([])
    original = routes_mod._CAPABILITY_ROUTES["jobs"]
    routes_mod._CAPABILITY_ROUTES["jobs"] = (("GET", "/api/v1/definitely/not/registered"),)
    try:
        caps = _client(engine).get("/api/v1/capabilities").json()["capabilities"]
        assert caps["jobs"] is False
        assert caps["attachments"] is True
    finally:
        routes_mod._CAPABILITY_ROUTES["jobs"] = original
