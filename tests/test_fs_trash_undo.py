"""P2-4：删除默认进回收站 + undo 窗口（10 分钟、单次、绑定原路径）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from llm_loop.web import build_app, fs_tree


@pytest.fixture()
def client(tmp_path):
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMClient
    from llm_loop.tools.registry import ToolRegistry

    data_dir = tmp_path / "data"
    settings = Settings(
        llm_api_key="k", llm_base_url="http://t", llm_model="m", data_dir=str(data_dir)
    )
    (tmp_path / "ws").mkdir(exist_ok=True)
    engine = LoopEngine(
        llm_client=LLMClient(api_key="k", base_url="http://t", model="m"),
        registry=ToolRegistry(),
        memory=None,
        session=SessionStore(data_dir / "sessions"),
        settings=settings,
    )
    engine.workspace_root = str(tmp_path / "ws")
    app = build_app(engine=engine)
    app.state.engine = engine
    fs_tree.reset_delete_tokens_for_tests()
    fs_tree.reset_undo_tokens_for_tests()
    yield TestClient(app), engine, tmp_path
    fs_tree.reset_delete_tokens_for_tests()
    fs_tree.reset_undo_tokens_for_tests()


def _delete(cli, path: str, *, hard: bool = False):
    tok = cli.get("/api/v1/fs/delete-token", params={"path": path})
    assert tok.status_code == 200, tok.text
    params = {"path": path, "confirm": "true", "token": tok.json()["token"]}
    if hard:
        params["hard"] = "true"
    return cli.delete("/api/v1/fs/delete", params=params)


def test_delete_moves_to_trash_and_restore_roundtrip(client):
    cli, _, tmp = client
    target = tmp / "ws" / "note.txt"
    target.write_text("keep me", encoding="utf-8")

    body = _delete(cli, "note.txt").json()
    assert body["status"] == "trashed" and body["hard"] is False
    assert not target.exists()
    trashed = tmp / "ws" / ".trash"
    assert trashed.is_dir() and any(p.name.endswith("note.txt") for p in trashed.iterdir())

    r = cli.post("/api/v1/fs/restore", params={"token": body["undo_token"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "restored"
    assert target.read_text(encoding="utf-8") == "keep me"


def test_undo_token_is_single_use(client):
    cli, _, tmp = client
    (tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
    token = _delete(cli, "a.txt").json()["undo_token"]
    assert cli.post("/api/v1/fs/restore", params={"token": token}).status_code == 200
    again = cli.post("/api/v1/fs/restore", params={"token": token})
    assert again.status_code == 409
    assert again.json()["error"] == "undo_token_invalid"


def test_undo_token_expiry_rejected(client, monkeypatch):
    cli, _, tmp = client
    (tmp / "ws" / "b.txt").write_text("x", encoding="utf-8")
    token = _delete(cli, "b.txt").json()["undo_token"]
    # 把窗口推进到过期之后（只改本进程令牌表，不动系统时钟）
    with fs_tree._UNDO_TOKENS_LOCK:
        fs_tree._UNDO_TOKENS[token]["expires_at"] = 0
    r = cli.post("/api/v1/fs/restore", params={"token": token})
    assert r.status_code == 409
    assert "过期" in r.json()["detail"]


def test_restore_refuses_to_overwrite(client):
    cli, _, tmp = client
    target = tmp / "ws" / "c.txt"
    target.write_text("old", encoding="utf-8")
    token = _delete(cli, "c.txt").json()["undo_token"]
    target.write_text("new", encoding="utf-8")  # 同路径被重新创建
    r = cli.post("/api/v1/fs/restore", params={"token": token})
    assert r.status_code == 409
    assert r.json()["error"] == "restore_conflict"
    assert target.read_text(encoding="utf-8") == "new"  # 不覆盖用户新内容


def test_hard_delete_skips_trash(client):
    cli, _, tmp = client
    target = tmp / "ws" / "d.txt"
    target.write_text("x", encoding="utf-8")
    body = _delete(cli, "d.txt", hard=True).json()
    assert body["status"] == "deleted" and body["hard"] is True
    assert not target.exists()
    trash = tmp / "ws" / ".trash"
    assert not trash.exists() or not any(p.name.endswith("d.txt") for p in trash.iterdir())


def test_trash_itself_cannot_be_deleted(client):
    cli, _, tmp = client
    (tmp / "ws" / ".trash").mkdir()
    r = cli.get("/api/v1/fs/delete-token", params={"path": ".trash"})
    assert r.status_code == 409
    assert r.json()["error"] == "protected_dir"


def test_restore_requires_token(client):
    cli, _, _ = client
    r = cli.post("/api/v1/fs/restore", params={"token": ""})
    assert r.status_code == 400
    assert r.json()["error"] == "token_required"
