"""M5-D read-only Web recovery: never re-run an uncertain Provider or Tool."""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.core.durable_run_recovery import FENCED, OPENED, SCHEMA
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_contracts import (
    BudgetDimension,
    TaskBudgetGrant,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_store import TaskBudgetStore
from llm_loop.resources.task_budget_t1_web_profile import capabilities, limits
from llm_loop.web import build_app

AUTH = "a" * 32
GEN = "b" * 32
BID = "webt1-" + AUTH


def _fixture(build_test_engine, tmp_path: Path):
    engine, _fake = build_test_engine([])
    sid = engine.session.create()
    state = tmp_path / "state"
    engine.settings = replace(engine.settings, data_dir=str(state))
    events = EventStore(state / "event_logs")
    engine._event_store = events
    engine.session._event_store = events
    budget = TaskBudgetStore(state / "task_budget_t1_web")
    grant = TaskBudgetGrant(
        budget_id=BID, issuer="operator",
        authority_source="admin-once-config-cas-v1",
        workspace_scope=exact_workspace_scope(str(tmp_path)),
        session_id=sid, human_turn_ref="synthetic-human",
        surface="web", profile="web-glm-t1-budgeted-write-v1",
        policy_version="t1-web-v1", deadline_epoch_s=time.time() + 600,
        limits=limits(), capabilities=capabilities(),
        provider_identity="glm", exact_model_ref="glm-5.3",
    )
    row = budget.issue_root(
        grant, root_run_generation=GEN, ingress_kind="web", reject_duplicate=True
    )
    row = budget.activate(BID, expected_revision=row["revision"])
    assert events.append(sid, "session.created", {"session_id": sid})
    return engine, sid, events, budget, row


def _open(sid: str, events: EventStore, row: dict) -> None:
    payload = {
        "schema": SCHEMA, "run_generation": GEN,
        "authorization_id": AUTH, "budget_id": BID,
        "budget_revision": row["revision"],
    }
    events.append_durable_run_fact(sid, OPENED, payload)
    events.append_durable_run_fact(sid, FENCED, payload)


def test_m5d_no_durable_identity_returns_hold_without_dispatch(
    build_test_engine, tmp_path: Path, monkeypatch,
) -> None:
    engine, sid, _events, _budget, _row = _fixture(build_test_engine, tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("read-only recovery must not start a Run")

    if getattr(engine, "runner", None) is not None:
        monkeypatch.setattr(engine.runner, "start", forbidden)
    response = TestClient(build_app(engine=engine)).get(
        f"/api/v1/sessions/{sid}/durable-recovery"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "unknown_HOLD"
    assert body["reason"] == "no_durable_run_identity"
    assert body["auto_resume_allowed"] is False
    assert body["read_only"] is True


def test_m5d_strict_opened_fenced_without_terminal_is_hold(
    build_test_engine, tmp_path: Path,
) -> None:
    engine, sid, events, _budget, row = _fixture(build_test_engine, tmp_path)
    _open(sid, events, row)
    response = TestClient(build_app(engine=engine)).get(
        f"/api/v1/sessions/{sid}/durable-recovery"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["decision"] == "unknown_HOLD"
    assert body["reason"] == "budget_not_stopped"
    assert body["effect_reason"] == "no_external_activity_defer_to_m5a"
    assert body["provider"]["transports_opened"] == 0
    assert body["tool"]["effects_prepared"] == 0
    assert body["auto_resume_allowed"] is False
    assert body["old_run_replay_allowed"] is False
    assert AUTH not in response.text
    assert GEN not in response.text


def test_m5d_provider_dispatched_unknown_stays_hold(
    build_test_engine, tmp_path: Path,
) -> None:
    engine, sid, events, budget, row = _fixture(build_test_engine, tmp_path)
    _open(sid, events, row)
    member = TaskBudgetMember.from_dict(row["members"][BID])
    rid = "dispatch-" + uuid.uuid4().hex
    row = budget.reserve(
        BID, member=member, reservation_id=rid,
        kind=BudgetDimension.PHYSICAL_ATTEMPTS,
        expected_revision=row["revision"],
    )
    budget.mark_dispatched(BID, reservation_id=rid, expected_revision=row["revision"])
    assert events.append(sid, "provider.call.opened", {
        "call_id": "pcall:" + "c" * 32, "origin_run_generation": GEN,
    })
    assert events.append(sid, "provider.transport.opened", {
        "call_id": "pcall:" + "c" * 32, "attempt_id": "pattempt:" + "d" * 32,
    })
    response = TestClient(build_app(engine=engine)).get(
        f"/api/v1/sessions/{sid}/durable-recovery"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "unknown_HOLD"
    assert body["effect_reason"] == "provider_unknown_remote_liability"
    assert body["provider"]["transports_unsettled"] == 1
    assert body["provider"]["budget_unsettled"] == 1
    assert body["remote_provider_settlement_proven"] is False
    assert body["auto_resume_allowed"] is False


def test_m5d_corrupt_event_file_never_claims_recovery(
    build_test_engine, tmp_path: Path,
) -> None:
    engine, sid, events, _budget, row = _fixture(build_test_engine, tmp_path)
    _open(sid, events, row)
    with open(events._path(sid), "ab") as stream:
        stream.write(b"invalid-jsonl\n")
    response = TestClient(build_app(engine=engine)).get(
        f"/api/v1/sessions/{sid}/durable-recovery"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "unknown_HOLD"
    assert body["reason"] == "event_source_unverifiable"
    assert body["auto_resume_allowed"] is False


def test_m5d_multiple_run_identities_are_ambiguous_hold(
    build_test_engine, tmp_path: Path,
) -> None:
    engine, sid, events, _budget, row = _fixture(build_test_engine, tmp_path)
    _open(sid, events, row)
    events.append_durable_run_fact(sid, OPENED, {
        "schema": SCHEMA, "run_generation": "f" * 32,
        "authorization_id": AUTH, "budget_id": BID,
        "budget_revision": row["revision"],
    })
    response = TestClient(build_app(engine=engine)).get(
        f"/api/v1/sessions/{sid}/durable-recovery"
    )
    assert response.status_code == 200
    assert response.json()["reason"] == "ambiguous_durable_run_identity"
    assert response.json()["auto_resume_allowed"] is False


def test_m5d_unknown_session_is_404(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    response = TestClient(build_app(engine=engine)).get(
        "/api/v1/sessions/not-a-session/durable-recovery"
    )
    assert response.status_code == 404
    assert response.json()["error"] == "session_not_found"


def test_m5d_remote_request_requires_existing_web_auth(
    build_test_engine, tmp_path: Path, monkeypatch,
) -> None:
    engine, sid, _events, _budget, _row = _fixture(build_test_engine, tmp_path)
    monkeypatch.setenv("WEB_API_KEY", "m5d-test-key")
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    client = TestClient(build_app(engine=engine), base_url="https://remote.example")
    response = client.get(f"/api/v1/sessions/{sid}/durable-recovery")
    assert response.status_code == 401
    authorized = client.get(
        f"/api/v1/sessions/{sid}/durable-recovery",
        headers={"Authorization": "Bearer m5d-test-key"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["decision"] == "unknown_HOLD"


def test_m5d_restart_with_new_event_store_object_preserves_hold(
    build_test_engine, tmp_path: Path,
) -> None:
    engine, sid, events, _budget, row = _fixture(build_test_engine, tmp_path)
    _open(sid, events, row)
    new_store = EventStore(tmp_path / "state" / "event_logs")
    engine._event_store = new_store
    engine.session._event_store = new_store
    response = TestClient(build_app(engine=engine)).get(
        f"/api/v1/sessions/{sid}/durable-recovery"
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "unknown_HOLD"
    assert response.json()["auto_resume_allowed"] is False


def test_m5d_completed_zero_effect_reports_completion_without_replay(
    build_test_engine, tmp_path: Path,
) -> None:
    from llm_loop.core.durable_run_recovery import TERMINAL

    engine, sid, events, budget, row = _fixture(build_test_engine, tmp_path)
    _open(sid, events, row)
    end = events.append(sid, "run.end", {
        "reason": "completed", "run_generation": GEN,
    })
    assert end is not None
    row = budget.request_stop(
        BID, expected_revision=row["revision"], reason="synthetic_no_effect_terminal"
    )
    events.append_durable_run_fact(sid, TERMINAL, {
        "schema": SCHEMA, "run_generation": GEN,
        "authorization_id": AUTH, "budget_id": BID,
        "budget_revision": row["revision"],
        "outcome": "completed", "run_end_event_id": end.event_id,
    })
    response = TestClient(build_app(engine=engine)).get(
        f"/api/v1/sessions/{sid}/durable-recovery"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "completed_verified"
    assert body["effect_reason"] == "no_external_activity_defer_to_m5a"
    assert body["auto_resume_allowed"] is False
    assert body["old_run_replay_allowed"] is False


def test_m5d_read_only_route_does_not_mutate_event_or_budget_bytes(
    build_test_engine, tmp_path: Path,
) -> None:
    engine, sid, events, _budget, row = _fixture(build_test_engine, tmp_path)
    _open(sid, events, row)
    event_file = Path(events._path(sid))
    budget_file = next((tmp_path / "state" / "task_budget_t1_web").glob("*.json"))
    before = (event_file.read_bytes(), budget_file.read_bytes())
    response = TestClient(build_app(engine=engine)).get(
        f"/api/v1/sessions/{sid}/durable-recovery"
    )
    assert response.status_code == 200
    assert (event_file.read_bytes(), budget_file.read_bytes()) == before


def test_m5d_corrupt_budget_never_claims_completed(
    build_test_engine, tmp_path: Path,
) -> None:
    engine, sid, events, _budget, row = _fixture(build_test_engine, tmp_path)
    _open(sid, events, row)
    budget_file = next((tmp_path / "state" / "task_budget_t1_web").glob("*.json"))
    budget_file.write_text("not-json", encoding="utf-8")
    response = TestClient(build_app(engine=engine)).get(
        f"/api/v1/sessions/{sid}/durable-recovery"
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "unknown_HOLD"
    assert response.json()["auto_resume_allowed"] is False
