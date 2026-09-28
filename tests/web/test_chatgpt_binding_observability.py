from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.llm.chatgpt_surface import ChatGPTSessionBindingStore
from llm_loop.web import build_app

PROJECT_REF = "g-p-binding-test"


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def _store(engine) -> ChatGPTSessionBindingStore:
    return ChatGPTSessionBindingStore(
        Path(engine.settings.data_dir) / "chatgpt-web-provider" / "sessions"
    )


def test_provider_binding_endpoint_reports_active_segment_and_history(build_test_engine):
    engine, _ = build_test_engine([])
    sid = engine.session.create(model_override="chatgpt-web/web-gpt")
    store = _store(engine)
    binding = store.get_or_create(session_id=sid, project_ref=PROJECT_REF)
    binding = store.record_exchange(
        binding,
        conversation_id="conv-1",
        conversation_url=f"https://chatgpt.com/g/{PROJECT_REF}/c/conv-1",
        request_chars=12_345,
    )
    binding = store.rollover(binding, reason="cumulative_request_chars")
    binding = store.record_exchange(
        binding,
        conversation_id="conv-2",
        conversation_url=f"https://chatgpt.com/g/{PROJECT_REF}/c/conv-2",
        request_chars=456,
    )

    response = _make_client(engine).get(
        f"/api/v1/sessions/{sid}/provider-binding"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "chatgpt-web"
    assert body["bound"] is True
    assert body["binding"]["conversation_id"] == "conv-2"
    assert body["binding"]["segment_seq"] == 2
    assert body["binding"]["segment_request_count"] == 1
    assert body["binding"]["total_request_count"] == 2
    assert body["history"][0]["conversation_id"] == "conv-1"
    assert body["history"][0]["reason"] == "cumulative_request_chars"
    assert body["lifecycle"]["session_exists"] is True
    assert body["lifecycle"]["gc_eligible"] is False
    assert body["gc_policy"]["automatic_gc"] is False


def test_provider_binding_endpoint_returns_unbound_for_existing_session(build_test_engine):
    engine, _ = build_test_engine([])
    sid = engine.session.create()

    response = _make_client(engine).get(
        f"/api/v1/sessions/{sid}/provider-binding"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["bound"] is False
    assert body["history"] == []
    assert body["lifecycle"]["gc_reason"] == "session_exists"


def test_binding_health_endpoint_reports_recent_restore_alert(build_test_engine):
    engine, _ = build_test_engine([])
    sid = engine.session.create(model_override="chatgpt-web/web-gpt")
    store = _store(engine)
    binding = store.get_or_create(session_id=sid, project_ref=PROJECT_REF)
    binding = store.record_exchange(
        binding,
        conversation_id="conv-1",
        conversation_url=f"https://chatgpt.com/g/{PROJECT_REF}/c/conv-1",
        request_chars=1_000,
    )
    store.record_transport_event(
        binding,
        event="restore_failed",
        error_type="BrowserSurfaceLeaseError",
    )

    response = _make_client(engine).get(
        "/api/v1/chatgpt-web/bindings/health"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "lfl.chatgpt_binding_health.v1"
    assert body["status"] == "warning"
    assert body["metrics"]["bindings_total"] == 1
    assert body["metrics"]["restore_failures_24h"] == 1
    assert body["telemetry"]["coverage"] == "event_log_only"
    alert = next(row for row in body["alerts"] if row["code"] == "restore_failures_recent")
    assert alert["severity"] == "warning"


def test_gc_plan_never_marks_existing_or_archived_session_eligible(build_test_engine):
    engine, _ = build_test_engine([])
    active_sid = engine.session.create()
    archived_sid = engine.session.create()
    assert engine.session.archive(archived_sid) is True
    store = _store(engine)
    for sid in (active_sid, archived_sid):
        binding = store.get_or_create(session_id=sid, project_ref=PROJECT_REF)
        store.save(replace(binding, updated_at="2020-01-01T00:00:00+00:00"))

    body = _make_client(engine).get(
        "/api/v1/chatgpt-web/bindings/gc-plan?min_age_days=1"
    ).json()
    rows = {item["session_id"]: item for item in body["items"]}

    assert body["eligible_count"] == 0
    assert rows[active_sid]["gc_eligible"] is False
    assert rows[active_sid]["gc_reason"] == "session_exists"
    assert rows[archived_sid]["gc_eligible"] is False
    assert rows[archived_sid]["session_status"] == "archived"


def test_gc_requires_aged_orphan_confirmation_and_fresh_plan(build_test_engine):
    engine, _ = build_test_engine([])
    store = _store(engine)
    deleted_sid = engine.session.create()
    binding = store.get_or_create(session_id=deleted_sid, project_ref=PROJECT_REF)
    assert engine.session.delete(deleted_sid) is True
    binding = store.save(
        replace(binding, updated_at="2020-01-01T00:00:00+00:00")
    )
    client = _make_client(engine)

    plan = client.get(
        "/api/v1/chatgpt-web/bindings/gc-plan?min_age_days=30"
    )
    assert plan.status_code == 200
    item = next(
        row
        for row in plan.json()["items"]
        if row["session_id"] == deleted_sid
    )
    assert item["gc_eligible"] is True
    assert item["gc_reason"] == "orphan_aged"
    assert item["global_presence_state"] == "deleted"

    no_confirm = client.post(
        "/api/v1/chatgpt-web/bindings/gc",
        json={
            "session_id": deleted_sid,
            "expected_updated_at": binding.updated_at,
            "min_age_days": 30,
            "confirm": False,
        },
    )
    assert no_confirm.status_code == 400
    assert store.load(deleted_sid) is not None

    stale = client.post(
        "/api/v1/chatgpt-web/bindings/gc",
        json={
            "session_id": deleted_sid,
            "expected_updated_at": "stale-plan",
            "min_age_days": 30,
            "confirm": True,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "binding_changed"
    assert store.load(deleted_sid) is not None

    deleted = client.post(
        "/api/v1/chatgpt-web/bindings/gc",
        json={
            "session_id": deleted_sid,
            "expected_updated_at": binding.updated_at,
            "min_age_days": 30,
            "confirm": True,
        },
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert store.load(deleted_sid) is None


def test_gc_plan_fail_closes_binding_without_deleted_session_tombstone(build_test_engine):
    engine, _ = build_test_engine([])
    store = _store(engine)
    binding = store.get_or_create(
        session_id="never-was-an-lfs-session",
        project_ref=PROJECT_REF,
    )
    store.save(replace(binding, updated_at="2020-01-01T00:00:00+00:00"))

    body = _make_client(engine).get(
        "/api/v1/chatgpt-web/bindings/gc-plan?min_age_days=1"
    ).json()
    item = next(
        row
        for row in body["items"]
        if row["session_id"] == "never-was-an-lfs-session"
    )
    assert item["gc_eligible"] is False
    assert item["gc_reason"] == "no_deleted_tombstone"
    assert item["global_presence_state"] == "missing"
