"""工作区管理 API 测试（列表/注册切换/切换/注销 + 会话按工作区分区）."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.web import build_app
from llm_loop.workspace.store import WorkspaceStore


def _client(build_test_engine):
    engine, _ = build_test_engine([{"content": "ok"}])
    # 测试装配不走 factory：手动挂工作区（默认工作区 = 当前 cwd）
    store = WorkspaceStore(str(engine.settings.data_dir))
    ws = store.register(os.getcwd())
    store.switch(ws.id)
    engine.set_workspace(ws.path)
    engine.workspace_store = store
    return TestClient(build_app(engine=engine))


def test_workspaces_list_and_register_switch(build_test_engine, tmp_path):
    client = _client(build_test_engine)
    # 初始：默认工作区已注册
    resp = client.get("/api/v1/workspaces")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current"]
    assert any(w["id"] == body["current"] for w in body["workspaces"])

    # 注册新工作区（Open 语义：注册即切换）
    proj = Path(tmp_path / "proj-b")
    proj.mkdir()
    resp = client.post("/api/v1/workspaces", json={"path": str(proj)})
    assert resp.status_code == 200
    ws = resp.json()
    assert ws["current"] is True
    resp = client.get("/api/v1/workspaces")
    assert resp.json()["current"] == ws["id"]
    assert len(resp.json()["workspaces"]) == 2

    # 切换回默认
    default_id = None
    resp = client.get("/api/v1/workspaces")
    for w in resp.json()["workspaces"]:
        if w["id"] != ws["id"]:
            default_id = w["id"]
    resp = client.post("/api/v1/workspaces/switch", json={"id": default_id})
    assert resp.status_code == 200
    assert client.get("/api/v1/workspaces").json()["current"] == default_id

    # 注销新工作区（须先切回默认；当前工作区不可注销）
    resp = client.post("/api/v1/workspaces/switch", json={"id": default_id})
    assert resp.status_code == 200
    resp = client.delete(f"/api/v1/workspaces/{ws['id']}")
    assert resp.status_code == 200
    # 已注销 → 再删 404 语义（remove 返回 False → 409）
    resp = client.delete(f"/api/v1/workspaces/{ws['id']}")
    assert resp.status_code == 409
    # 当前工作区不可注销
    resp = client.delete(f"/api/v1/workspaces/{default_id}")
    assert resp.status_code == 409


def test_register_invalid_path(build_test_engine, tmp_path):
    client = _client(build_test_engine)
    resp = client.post("/api/v1/workspaces", json={"path": str(tmp_path / "missing")})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_workspace"


def test_switch_unknown_workspace(build_test_engine):
    client = _client(build_test_engine)
    resp = client.post("/api/v1/workspaces/switch", json={"id": "no-such"})
    assert resp.status_code == 400


def test_workspace_sessions_isolated_by_workspace(build_test_engine, tmp_path):
    """会话按工作区分区：A 工作区会话不出现在 B 工作区列表中."""
    client = _client(build_test_engine)
    # 当前工作区发一条消息 → 默认工作区有 1 会话
    r = client.post("/api/v1/chat", json={"message": "hi"})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    resp = client.get("/api/v1/workspaces")
    current = resp.json()["current"]
    # 默认工作区列表含该会话
    resp = client.get(f"/api/v1/workspaces/{current}/sessions")
    assert resp.status_code == 200
    assert any(s["session_id"] == sid for s in resp.json()["sessions"])
    # 新工作区列表为空（分区隔离）
    proj = Path(tmp_path / "proj-c")
    proj.mkdir()
    resp = client.post("/api/v1/workspaces", json={"path": str(proj)})
    ws = resp.json()
    resp = client.get(f"/api/v1/workspaces/{ws['id']}/sessions")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_workspace_sessions_unknown_404(build_test_engine):
    client = _client(build_test_engine)
    resp = client.get("/api/v1/workspaces/no-such/sessions")
    assert resp.status_code == 404
