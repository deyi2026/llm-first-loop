"""Web V2 出产物文件预览端点测试（对齐 DSH deliverables 点击打开）.

覆盖：正常读取（相对/工作区根内绝对）/ 根外绝对拒绝 / 越界拒绝 / 不存在 404。
"""

from __future__ import annotations

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
    # R9-IMM-02 适配：conftest chdir 沙箱后 cwd≠仓库根，锚定 __file__ 取根内文件绝对路径
    from pathlib import Path

    abs_path = str(Path(__file__).resolve().parents[2] / "pyproject.toml")
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


def test_preview_basename_fallback_rejects_symlink_escape(build_test_engine, tmp_path):
    """裸文件名兜底不得把工作区内symlink解析到根外后读取。"""
    root = tmp_path / "workspace"
    docs = root / "docs"
    docs.mkdir(parents=True)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("SECRET-OUTSIDE-WORKSPACE", encoding="utf-8")
    (docs / "secret-link.txt").symlink_to(outside)

    engine, _ = build_test_engine([{"content": "ok"}])
    engine.workspace_root = str(root)
    client = TestClient(build_app(engine=engine))
    resp = client.get("/api/v1/files/preview", params={"path": "secret-link.txt"})

    assert resp.status_code == 400
    assert resp.json()["error"] == "out_of_bounds"
    assert "SECRET-OUTSIDE-WORKSPACE" not in resp.text
