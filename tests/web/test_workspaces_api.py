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


def test_colliding_workspace_paths_get_distinct_ids_and_sessions(build_test_engine, tmp_path):
    """legacy key碰撞的两个目录仍必须注册为不同workspace并隔离session分区。"""
    from llm_loop.workspace.store import workspace_key

    client = _client(build_test_engine)
    ws_a = tmp_path / "a-b" / "c"
    ws_b = tmp_path / "a" / "b-c"
    ws_a.mkdir(parents=True)
    ws_b.mkdir(parents=True)
    assert workspace_key(ws_a) == workspace_key(ws_b)

    a_resp = client.post("/api/v1/workspaces", json={"path": str(ws_a)})
    assert a_resp.status_code == 200
    a = a_resp.json()
    a_chat = client.post("/api/v1/chat", json={"message": "from-a"})
    assert a_chat.status_code == 200
    a_sid = a_chat.json()["session_id"]

    b_resp = client.post("/api/v1/workspaces", json={"path": str(ws_b)})
    assert b_resp.status_code == 200
    b = b_resp.json()
    assert b["path"] == str(ws_b.resolve())
    assert a["id"] != b["id"]
    b_chat = client.post("/api/v1/chat", json={"message": "from-b"})
    assert b_chat.status_code == 200
    b_sid = b_chat.json()["session_id"]

    a_sessions = client.get(f"/api/v1/workspaces/{a['id']}/sessions").json()["sessions"]
    b_sessions = client.get(f"/api/v1/workspaces/{b['id']}/sessions").json()["sessions"]
    assert any(item["session_id"] == a_sid for item in a_sessions)
    assert all(item["session_id"] != b_sid for item in a_sessions)
    assert any(item["session_id"] == b_sid for item in b_sessions)
    assert all(item["session_id"] != a_sid for item in b_sessions)


def test_register_workspace_persistence_failure_returns_500(
    build_test_engine, tmp_path, monkeypatch
):
    """注册表写盘失败不能返回200/invalid_path；Web必须如实报告持久化失败。"""
    from llm_loop.workspace.store import WorkspaceStore

    client = _client(build_test_engine)
    new_root = tmp_path / "persist-fail"
    new_root.mkdir()
    monkeypatch.setattr(WorkspaceStore, "_save", lambda self: False)

    resp = client.post("/api/v1/workspaces", json={"path": str(new_root)})

    assert resp.status_code == 500
    assert resp.json()["error"] == "workspace_persist_failed"


def test_register_and_switch_is_atomic_when_persistence_fails(
    build_test_engine, tmp_path, monkeypatch
):
    """POST /workspaces失败时注册+current必须整体回滚，不留下半成功workspace。"""
    from llm_loop.workspace.store import WorkspaceStore

    client = _client(build_test_engine)
    before_payload = client.get("/api/v1/workspaces").json()
    before = {item["id"] for item in before_payload["workspaces"]}
    before_current = before_payload["current"]
    new_root = tmp_path / "atomic-new"
    new_root.mkdir()
    calls = 0

    def fail_only_save(self):
        nonlocal calls
        calls += 1
        return False

    monkeypatch.setattr(WorkspaceStore, "_save", fail_only_save)
    resp = client.post("/api/v1/workspaces", json={"path": str(new_root)})

    assert resp.status_code == 500
    assert calls == 1, "原子注册+切换应只尝试一次持久化"
    after_payload = client.get("/api/v1/workspaces").json()
    after = {item["id"] for item in after_payload["workspaces"]}
    assert after == before
    assert after_payload["current"] == before_current


def test_register_and_switch_success_persists_once(build_test_engine, tmp_path, monkeypatch):
    """成功注册+切换也只能提交一次registry，防回退成register+switch两次写。"""
    from llm_loop.workspace.store import WorkspaceStore

    client = _client(build_test_engine)
    new_root = tmp_path / "atomic-success"
    new_root.mkdir()
    real_save = WorkspaceStore._save
    calls = 0

    def count_save(self):
        nonlocal calls
        calls += 1
        return real_save(self)

    monkeypatch.setattr(WorkspaceStore, "_save", count_save)
    resp = client.post("/api/v1/workspaces", json={"path": str(new_root)})

    assert resp.status_code == 200
    assert calls == 1
    payload = client.get("/api/v1/workspaces").json()
    assert payload["current"] == resp.json()["id"]


def test_switch_workspace_with_missing_path_returns_409(build_test_engine, tmp_path):
    client = _client(build_test_engine)
    ws_path = tmp_path / "gone-workspace"
    ws_path.mkdir()
    created = client.post("/api/v1/workspaces", json={"path": str(ws_path)})
    assert created.status_code == 200
    ws_id = created.json()["id"]
    ws_path.rmdir()

    resp = client.post("/api/v1/workspaces/switch", json={"id": ws_id})

    assert resp.status_code == 409
    assert resp.json()["error"] == "workspace_path_unavailable"


def test_register_workspace_runtime_switch_failure_rolls_back_registry_and_engine(
    build_test_engine, tmp_path, monkeypatch
):
    """registry已提交后若session根切换失败，请求不能留下current/engine半成功。"""
    client = _client(build_test_engine)
    engine = client.app.state.engine
    before_payload = client.get("/api/v1/workspaces").json()
    before_ids = {item["id"] for item in before_payload["workspaces"]}
    before_current = before_payload["current"]
    before_root = engine.workspace_root
    before_session_dir = engine.session._dir
    new_root = tmp_path / "runtime-fail"
    new_root.mkdir()

    def fail_prepare_root(_path):
        raise OSError("sessions root unavailable")

    monkeypatch.setattr(engine.session, "prepare_root", fail_prepare_root)
    resp = client.post("/api/v1/workspaces", json={"path": str(new_root)})

    assert resp.status_code == 500
    assert resp.json()["error"] == "workspace_runtime_prepare_failed"
    after_payload = client.get("/api/v1/workspaces").json()
    assert {item["id"] for item in after_payload["workspaces"]} == before_ids
    assert after_payload["current"] == before_current
    assert engine.workspace_root == before_root
    assert engine.session._dir == before_session_dir


def test_switch_workspace_runtime_prepare_failure_keeps_current_and_engine(
    build_test_engine, tmp_path, monkeypatch
):
    """已有workspace切换也必须先prepare，失败时registry current与engine都不变。"""
    client = _client(build_test_engine)
    engine = client.app.state.engine
    store = engine.workspace_store
    before_payload = client.get("/api/v1/workspaces").json()
    before_current = before_payload["current"]
    before_root = engine.workspace_root
    before_session_dir = engine.session._dir

    target_root = tmp_path / "switch-runtime-fail"
    target_root.mkdir()
    target = store.register(target_root)
    assert target.id != before_current

    def fail_prepare_root(_path):
        raise OSError("sessions root unavailable")

    monkeypatch.setattr(engine.session, "prepare_root", fail_prepare_root)
    resp = client.post("/api/v1/workspaces/switch", json={"id": target.id})

    assert resp.status_code == 500
    assert resp.json()["error"] == "workspace_runtime_prepare_failed"
    after_payload = client.get("/api/v1/workspaces").json()
    assert after_payload["current"] == before_current
    assert engine.workspace_root == before_root
    assert engine.session._dir == before_session_dir


def test_session_events_follow_workspace_switch(build_test_engine, tmp_path, monkeypatch):
    """SSE长连接必须跟随当前workspace session分区；切换本身也应触发刷新事件。"""
    import asyncio
    from types import SimpleNamespace

    import llm_loop.web.routes as routes

    client = _client(build_test_engine)
    engine = client.app.state.engine
    target_root = tmp_path / "sse-target"
    target_root.mkdir()
    target = engine.workspace_store.register(target_root)

    disconnect_checks = 0
    switched = False

    async def is_disconnected():
        nonlocal disconnect_checks
        disconnect_checks += 1
        return disconnect_checks >= 2

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(engine=engine)),
        is_disconnected=is_disconnected,
    )

    async def fake_sleep(_seconds):
        nonlocal switched
        if switched:
            return
        engine.workspace_store.switch(target.id)
        engine.set_workspace(target.path, target.id)
        switched = True

    monkeypatch.setattr(routes.asyncio, "sleep", fake_sleep)

    async def collect_frames():
        response = await routes.stream_session_events(request)
        frames: list[str] = []
        async for chunk in response.body_iterator:
            if isinstance(chunk, bytes):
                frames.append(chunk.decode("utf-8"))
            else:
                frames.append(str(chunk))
        return frames

    frames = asyncio.run(collect_frames())

    assert switched is True
    assert any("event: sessions_updated" in frame for frame in frames)


def test_workspace_mutations_reject_active_sync_run_without_partial_commit(
    build_test_engine, tmp_path
):
    """active run期间register/switch都必须409，registry current与runtime根完全不动。"""
    from llm_loop.llm.client import LLMResponse, StreamDelta

    client = _client(build_test_engine)
    engine = client.app.state.engine
    store = engine.workspace_store
    assert store is not None

    target_root = tmp_path / "busy-target"
    target_root.mkdir()
    target = store.register(target_root)
    new_root = tmp_path / "busy-register"
    new_root.mkdir()

    before_current = store.get_current()
    assert before_current is not None
    before_root = engine.workspace_root
    before_session_root = engine.session.root
    before_ids = {w.id for w in store.list()}

    def slow_stream(**_kwargs):
        yield StreamDelta(text="A")
        yield StreamDelta(text="B")
        return LLMResponse(content="AB", tool_calls=[], provider="fake")

    engine.llm_pool.default_client.chat_stream = slow_stream
    sid = engine.session.create()
    stream = engine.run_stream(sid, "hello")
    try:
        assert next(stream).text == "A"

        register_resp = client.post("/api/v1/workspaces", json={"path": str(new_root)})
        switch_resp = client.post("/api/v1/workspaces/switch", json={"id": target.id})

        assert register_resp.status_code == 409
        assert register_resp.json()["error"] == "workspace_busy"
        assert switch_resp.status_code == 409
        assert switch_resp.json()["error"] == "workspace_busy"
        assert {w.id for w in store.list()} == before_ids
        assert store.get_current() is not None
        assert store.get_current().id == before_current.id
        assert engine.workspace_root == before_root
        assert engine.session.root == before_session_root
    finally:
        stream.close()
