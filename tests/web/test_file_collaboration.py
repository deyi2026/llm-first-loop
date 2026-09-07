from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_loop.factory import build_engine
from llm_loop.web import build_app


def _client(fake_settings, tmp_path: Path):
    engine = build_engine(fake_settings)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine.set_workspace(str(workspace), workspace_id="p3test")
    sid = engine.session.create()
    return TestClient(build_app(engine=engine)), engine, workspace, sid


def test_file_observe_edit_operations_api_no_model_run(fake_settings, tmp_path, monkeypatch) -> None:
    client, engine, workspace, sid = _client(fake_settings, tmp_path)
    target = workspace / "notes.txt"
    target.write_bytes(b"draft\r\n")

    def forbidden_run(*_args, **_kwargs):
        raise AssertionError("human file API must never call engine.run")

    monkeypatch.setattr(engine, "run", forbidden_run)
    observed = client.post(
        f"/api/v1/sessions/{sid}/files/observe",
        json={"path": "notes.txt", "offset": 0, "limit": 100},
    )
    assert observed.status_code == 200
    baseline = observed.json()
    assert baseline["content"] == "draft\r\n"
    assert baseline["file_contract_version"] == 1

    saved = client.post(
        f"/api/v1/sessions/{sid}/files/edit",
        json={
            "request_id": "web-request-0001",
            "path": "notes.txt",
            "expected_snapshot_ref": baseline["snapshot_ref"],
            "content": "human note\r\n",
            "file_contract_version": 1,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["origin"] == "authenticated_user"
    assert target.read_bytes() == b"human note\r\n"

    ops = client.get(f"/api/v1/sessions/{sid}/files/operations?limit=10")
    assert ops.status_code == 200
    assert ops.json()["receipts"][0]["operation_id"] == saved.json()["operation_id"]
    assert all(msg.role not in {"user", "assistant", "tool"} for msg in engine.session.load(sid).messages)


def test_file_api_rejects_foreign_origin_and_out_of_scope_path(fake_settings, tmp_path) -> None:
    client, _engine, workspace, sid = _client(fake_settings, tmp_path)
    (workspace / "a.txt").write_text("x", encoding="utf-8")
    blocked = client.post(
        f"/api/v1/sessions/{sid}/files/observe",
        json={"path": "a.txt"},
        headers={"Origin": "https://evil.example"},
    )
    assert blocked.status_code == 403
    escaped = client.post(
        f"/api/v1/sessions/{sid}/files/observe",
        json={"path": "../escape.txt"},
    )
    assert escaped.status_code == 400


def test_file_edit_version_conflict_keeps_human_draft_source_unchanged(fake_settings, tmp_path) -> None:
    client, _engine, workspace, sid = _client(fake_settings, tmp_path)
    target = workspace / "a.txt"
    target.write_text("base\n", encoding="utf-8")
    baseline = client.post(
        f"/api/v1/sessions/{sid}/files/observe", json={"path": "a.txt"}
    ).json()
    target.write_text("external\n", encoding="utf-8")
    response = client.post(
        f"/api/v1/sessions/{sid}/files/edit",
        json={
            "request_id": "web-request-0002",
            "path": "a.txt",
            "expected_snapshot_ref": baseline["snapshot_ref"],
            "content": "stale draft\n",
            "file_contract_version": 1,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"] == "version_conflict"
    assert target.read_text(encoding="utf-8") == "external\n"


def test_file_collaboration_routes_inherit_existing_web_auth(fake_settings, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WEB_API_KEY", "test-only-key")
    monkeypatch.setenv("WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    engine = build_engine(fake_settings)
    workspace = tmp_path / "auth-workspace"
    workspace.mkdir()
    engine.set_workspace(str(workspace), workspace_id="p3auth")
    sid = engine.session.create()
    (workspace / "a.txt").write_text("x\n", encoding="utf-8")
    client = TestClient(build_app(engine=engine))

    assert client.post(
        f"/api/v1/sessions/{sid}/files/observe", json={"path": "a.txt"}
    ).status_code == 401
    allowed = client.post(
        f"/api/v1/sessions/{sid}/files/observe",
        json={"path": "a.txt"},
        headers={"Authorization": "Bearer test-only-key"},
    )
    assert allowed.status_code == 200


def test_file_edit_route_holds_workspace_snapshot_and_session_lease_together(
    fake_settings, tmp_path, monkeypatch
) -> None:
    import threading

    client, engine, workspace, sid = _client(fake_settings, tmp_path)
    target = workspace / "a.txt"
    target.write_text("base\n", encoding="utf-8")
    baseline_response = client.post(
        f"/api/v1/sessions/{sid}/files/observe", json={"path": "a.txt"}
    )
    assert baseline_response.status_code == 200
    baseline = baseline_response.json()

    entered = threading.Event()
    release = threading.Event()
    service = engine.human_file_operations
    assert service is not None
    original_edit = service.file_service.edit

    def blocking_file_edit(**kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return original_edit(**kwargs)

    monkeypatch.setattr(service.file_service, "edit", blocking_file_edit)
    responses: list[int] = []

    def call_edit() -> None:
        response = client.post(
            f"/api/v1/sessions/{sid}/files/edit",
            json={
                "request_id": "workspace-lock-request",
                "path": "a.txt",
                "expected_snapshot_ref": baseline["snapshot_ref"],
                "content": "after\n",
                "file_contract_version": 1,
            },
        )
        responses.append(response.status_code)

    thread = threading.Thread(target=call_edit, daemon=True)
    thread.start()
    assert entered.wait(timeout=5)

    # The actual human edit already owns the session run lease here.
    with engine.session.run_lease(sid) as acquired:
        assert acquired is False

    other = tmp_path / "other-workspace"
    other.mkdir()
    from llm_loop.workspace.store import WorkspaceBusyError

    with pytest.raises(WorkspaceBusyError):
        engine.set_workspace(str(other), workspace_id="p3other")
    assert Path(engine.workspace_root).resolve() == workspace.resolve()
    assert target.read_text(encoding="utf-8") == "base\n"

    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert responses == [200]
    assert target.read_text(encoding="utf-8") == "after\n"
