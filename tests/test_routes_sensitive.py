"""Web 文件面敏感清单 + 根语义 + 路径校验（安全建议书 P1-3 剩余 / S3-7）.

被测对象：routes.py 的 `_resolve_workspace_file` 收口（import-workspace 端点为其
唯一调用方，行为矩阵经该端点全量生效）与工作区注册/切换端点的
WorkspaceNotAllowedError 映射。security_guard 名单本身的覆盖在其单测里，
这里只测 Web 接线语义（状态码 / 错误码 / 内容不外泄）。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_loop.web import build_app
from llm_loop.workspace.store import WorkspaceNotAllowedError, WorkspaceStore

SECRET = "SUPER-SECRET-DO-NOT-LEAK-9f3a"


def _client(engine) -> TestClient:
    return TestClient(build_app(engine=engine))


def _import(client: TestClient, path: str):
    return client.post("/api/v1/attachments/import-workspace", json={"path": path})


def _ws_engine(build_test_engine, root) -> object:
    engine, _ = build_test_engine([])
    engine.workspace_root = str(root)
    return engine


# ── 根语义：未配置工作区不再回退项目根 ──────────────────────────────────


def test_import_workspace_unconfigured_engine_returns_503(build_test_engine):
    """workspace_root 为空（LoopEngine 默认）→ 503，而非回退项目根后 404/200."""
    engine, _ = build_test_engine([])
    assert engine.workspace_root == ""
    resp = _import(_client(engine), "notes.txt")
    assert resp.status_code == 503
    assert resp.json()["error"] == "workspace_unconfigured"


def test_import_workspace_missing_root_returns_503(build_test_engine, tmp_path):
    """配置了但目录不存在 → 同样 503（显式失败，不做静默回退）."""
    engine = _ws_engine(build_test_engine, tmp_path / "no-such-root")
    resp = _import(_client(engine), "notes.txt")
    assert resp.status_code == 503
    assert resp.json()["error"] == "workspace_unconfigured"


# ── 敏感名单（P1-3）：403 且内容不外泄 ────────────────────────────────


@pytest.mark.parametrize("name", [".env", "cert.pem", "id_ed25519"])
def test_import_workspace_blocks_sensitive_names(build_test_engine, tmp_path, name):
    engine = _ws_engine(build_test_engine, tmp_path)
    (tmp_path / name).write_text(SECRET, encoding="utf-8")
    resp = _import(_client(engine), name)
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "sensitive_file_blocked"
    assert body.get("reason")  # dir:<name> / name:<pattern>
    assert SECRET not in resp.text


def test_import_workspace_rejects_home_credentials_path(
    build_test_engine, tmp_path, monkeypatch
):
    """绝对路径 ~/.ssh/id_ed25519（根外+敏感）→ 403，不读取不复制."""
    engine = _ws_engine(build_test_engine, tmp_path)
    fake_home = tmp_path / "fake-home"
    (fake_home / ".ssh").mkdir(parents=True)
    (fake_home / ".ssh" / "id_ed25519").write_text(SECRET, encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    resp = _import(_client(engine), "~/.ssh/id_ed25519")
    assert resp.status_code == 403
    assert resp.json()["error"] == "sensitive_file_blocked"
    assert SECRET not in resp.text


def test_import_workspace_sensitive_named_symlink_alias_blocked(
    build_test_engine, tmp_path
):
    """敏感名只是 symlink 别名（leaked.env → notes.txt）也拒绝：按用户给的路径名判."""
    engine = _ws_engine(build_test_engine, tmp_path)
    real = tmp_path / "notes.txt"
    real.write_text(SECRET, encoding="utf-8")
    (tmp_path / "leaked.env").symlink_to(real)
    resp = _import(_client(engine), "leaked.env")
    assert resp.status_code == 403
    assert resp.json()["error"] == "sensitive_file_blocked"
    assert SECRET not in resp.text


def test_import_workspace_template_and_normal_files_still_pass(
    build_test_engine, tmp_path
):
    """非敏感文件正常导入；模板（.env.example）不被敏感名单拦截.

    模板的"豁免"指不返回 403 sensitive_file_blocked——上传层按扩展名白名单
    （.example 不支持）仍会 400 invalid_upload，那是另一层既有策略，与本名单无关。
    """
    engine = _ws_engine(build_test_engine, tmp_path)
    (tmp_path / ".env.example").write_text("PLACEHOLDER=1", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("WORKSPACE-BYTES", encoding="utf-8")
    client = _client(engine)
    ok = _import(client, "notes.txt")
    assert ok.status_code == 200, ok.text
    assert ok.json()["attachment_ref"].startswith("attachment://")
    template = _import(client, ".env.example")
    assert template.status_code != 403
    assert template.json().get("error") != "sensitive_file_blocked"


# ── 路径校验（S3-7 + 越界原语义） ────────────────────────────────────


def test_import_workspace_nul_byte_returns_400(build_test_engine, tmp_path):
    """NUL 字节 → 400 invalid_path（此前 ValueError 逃逸为 500）."""
    engine = _ws_engine(build_test_engine, tmp_path)
    resp = _import(_client(engine), "notes\x00.txt")
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_path"


def test_import_workspace_traversal_outside_root_blocked(build_test_engine, tmp_path):
    """../../etc/passwd → 越界维持原语义 404 workspace_file_not_found."""
    engine = _ws_engine(build_test_engine, tmp_path)
    resp = _import(_client(engine), "../../etc/passwd")
    assert resp.status_code == 404
    assert resp.json()["error"] == "workspace_file_not_found"


def test_import_workspace_symlink_to_outside_target_not_copied(
    build_test_engine, tmp_path
):
    """工作区内 symlink 指向根外真实文件 → resolve 后越界，404 且不复制内容."""
    engine = _ws_engine(build_test_engine, tmp_path)
    outside = tmp_path.parent / "routes-sensitive-outside.txt"
    outside.write_text(SECRET, encoding="utf-8")
    (tmp_path / "leak.txt").symlink_to(outside)
    try:
        resp = _import(_client(engine), "leak.txt")
        assert resp.status_code == 404
        assert resp.json()["error"] == "workspace_file_not_found"
        assert SECRET not in resp.text
    finally:
        outside.unlink(missing_ok=True)


# ── 工作区注册/切换：白名单外 → 403 workspace_not_allowed ─────────────


def _store_engine(build_test_engine):
    engine, _ = build_test_engine([])
    engine.workspace_store = WorkspaceStore(str(engine.settings.data_dir))
    return engine


def test_register_workspace_filesystem_root_returns_403(build_test_engine):
    engine = _store_engine(build_test_engine)
    resp = _client(engine).post("/api/v1/workspaces", json={"path": "/"})
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "workspace_not_allowed"
    assert "LFL_WORKSPACE_ALLOWED_ROOTS" in body["detail"]


def test_register_workspace_outside_allowed_roots_returns_403(build_test_engine):
    """真实存在、但不在允许根（cwd/仓库根/data/workspace）下的目录 → 403."""
    engine = _store_engine(build_test_engine)
    outside = Path(tempfile.mkdtemp(prefix="routes-sensitive-outside-ws-"))
    try:
        resp = _client(engine).post("/api/v1/workspaces", json={"path": str(outside)})
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"] == "workspace_not_allowed"
        assert "LFL_WORKSPACE_ALLOWED_ROOTS" in body["detail"]
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def test_switch_workspace_not_allowed_maps_to_403(build_test_engine, monkeypatch):
    """switch 端点对 WorkspaceNotAllowedError 同映射 403（非笼统 400）."""
    engine = _store_engine(build_test_engine)
    store = engine.workspace_store

    def deny_switch(_workspace_id, **_kwargs):
        raise WorkspaceNotAllowedError(
            "工作区路径不在允许根之下；如需扩展允许范围，设置环境变量 "
            "LFL_WORKSPACE_ALLOWED_ROOTS（os.pathsep 分隔的绝对路径列表）。"
        )

    monkeypatch.setattr(store, "switch", deny_switch)
    resp = _client(engine).post("/api/v1/workspaces/switch", json={"id": "any-id"})
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "workspace_not_allowed"
    assert "LFL_WORKSPACE_ALLOWED_ROOTS" in body["detail"]
