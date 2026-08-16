"""Web V2 出产物文件预览端点测试（对齐 DSH deliverables 点击打开）.

覆盖：正常读取（相对/工作区根内绝对）/ 根外绝对拒绝 / 越界拒绝 / 不存在 404。
"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _client(build_test_engine):
    engine, _ = build_test_engine([{"content": "ok"}])
    return TestClient(build_app(engine=engine))


def test_preview_normal_file(build_test_engine):
    """项目根内相对路径正常返回内容."""
    client = _client(build_test_engine)
    resp = client.get("/api/v1/files/preview", params={"path": "pyproject.toml"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "pyproject.toml"
    assert "llm-first-loop" in body["content"]
    assert body["truncated"] is False


def test_preview_accepts_absolute_path_in_root(build_test_engine):
    """工作区根内的绝对路径可预览（出产物 chips 用绝对路径）."""
    client = _client(build_test_engine)
    abs_path = os.path.abspath("pyproject.toml")
    resp = client.get("/api/v1/files/preview", params={"path": abs_path})
    assert resp.status_code == 200
    assert "llm-first-loop" in resp.json()["content"]


def test_preview_rejects_absolute_path_outside_root(build_test_engine):
    """根外绝对路径拒绝（resolve 越界校验）."""
    client = _client(build_test_engine)
    resp = client.get("/api/v1/files/preview", params={"path": "/etc/passwd"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "out_of_bounds"


def test_preview_rejects_parent_traversal(build_test_engine):
    client = _client(build_test_engine)
    resp = client.get("/api/v1/files/preview", params={"path": "../.env"})
    assert resp.status_code == 400


def test_preview_missing_file_404(build_test_engine):
    client = _client(build_test_engine)
    resp = client.get("/api/v1/files/preview", params={"path": "no_such_file_xyz.txt"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "file_not_found"
