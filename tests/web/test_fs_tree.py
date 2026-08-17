"""文件树/会话树 API 测试（EVO-20260818 DSH 064）.

覆盖:
- A 文件树: GET tree（目录+文件）；mkdir/rename/delete（confirm 两步 + 越界拒绝）
- B 会话树: GET agents/tree（会话→子代理层级）
- 安全: 越界路径拒绝、危险路径拒绝、confirm_required
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_loop.web import build_app


@pytest.fixture()
def client(tmp_path):
    """构造隔离工作区引擎的测试客户端."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMClient
    from llm_loop.tools.registry import ToolRegistry

    data_dir = tmp_path / "data"
    # data_dir 由 Settings 构造时自动 mkdir；sessions/audit 从 data_dir 派生
    settings = Settings(
        llm_api_key="k", llm_base_url="http://t", llm_model="m",
        data_dir=str(data_dir),
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
    return TestClient(app), engine


# ── A 文件树 ──
def test_fs_tree_lists_dirs_and_files(client, tmp_path):
    cli, engine = client
    ws = tmp_path / "ws"
    (ws / "sub").mkdir()
    (ws / "file.txt").write_text("hi", encoding="utf-8")
    (ws / ".hidden").write_text("x", encoding="utf-8")
    r = cli.get("/api/v1/fs/tree", params={"path": ""})
    assert r.status_code == 200
    d = r.json()
    assert "sub" in d["dirs"]
    assert any(f["name"] == "file.txt" for f in d["files"])
    assert ".hidden" not in [f["name"] for f in d["files"]]  # 忽略隐藏


def test_fs_tree_out_of_bounds(client):
    cli, _ = client
    r = cli.get("/api/v1/fs/tree", params={"path": "/etc/passwd"})
    assert r.status_code == 400
    assert r.json()["error"] == "out_of_bounds"


def test_fs_mkdir(client, tmp_path):
    cli, _ = client
    r = cli.post("/api/v1/fs/mkdir", params={"path": "new_dir"})
    assert r.status_code == 200
    assert (tmp_path / "ws" / "new_dir").is_dir()


def test_fs_rename(client, tmp_path):
    cli, _ = client
    (tmp_path / "ws" / "a.txt").write_text("x", encoding="utf-8")
    r = cli.put("/api/v1/fs/rename", params={"path": "a.txt", "new_name": "b.txt"})
    assert r.status_code == 200
    assert (tmp_path / "ws" / "b.txt").exists()
    assert not (tmp_path / "ws" / "a.txt").exists()


def test_fs_delete_requires_confirm(client, tmp_path):
    cli, _ = client
    (tmp_path / "ws" / "del.txt").write_text("x", encoding="utf-8")
    # 无 confirm → 409
    r = cli.delete("/api/v1/fs/delete", params={"path": "del.txt"})
    assert r.status_code == 409
    assert r.json()["error"] == "confirm_required"
    assert (tmp_path / "ws" / "del.txt").exists()  # 未删除


def test_fs_delete_with_confirm(client, tmp_path):
    cli, _ = client
    (tmp_path / "ws" / "del.txt").write_text("x", encoding="utf-8")
    r = cli.delete("/api/v1/fs/delete", params={"path": "del.txt", "confirm": "true"})
    assert r.status_code == 200
    assert not (tmp_path / "ws" / "del.txt").exists()


def test_fs_delete_dangerous_denied(client):
    cli, _ = client
    r = cli.delete("/api/v1/fs/delete", params={"path": ".git", "confirm": "true"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_path"


def test_fs_audit_written(client, tmp_path):
    cli, _ = client
    cli.post("/api/v1/fs/mkdir", params={"path": "audited"})
    # audit 落在 data_dir/audit（settings.audit_dir 属性派生）
    audit = tmp_path / "data" / "audit" / "fs_operations.jsonl"
    assert audit.exists()
    assert "mkdir" in audit.read_text(encoding="utf-8")


# ── B 会话树 ──
def test_agents_tree_lists_sessions(client):
    cli, engine = client
    sid = engine.session.create()
    # 造一个子代理会话（带 parent_id，模拟 fork/子代理）
    sub = engine.session.create()
    try:
        sess = engine.session.load(sub)
        sess.parent_id = sid
        engine.session.save(sess)
    except Exception:
        pass
    r = cli.get("/api/v1/agents/tree")
    assert r.status_code == 200
    nodes = {n["id"]: n for n in r.json()["nodes"]}
    assert sid in nodes
    assert sub in nodes
    assert nodes[sub]["parent_id"] == sid


def test_agents_tree_empty(client):
    cli, _ = client
    r = cli.get("/api/v1/agents/tree")
    assert r.status_code == 200
    assert r.json()["nodes"] == []
