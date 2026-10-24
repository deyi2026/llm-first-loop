"""fs 删除两步令牌 + 根/符号链接/内部目录保护 + S2-7 根语义/审计 fail-closed.

对齐《安全审查与修复建议书 2026-10-25》:
- A (P0-2): 删除两步令牌——未带 token / 错路径 / 重放 / 过期 / 身份不符全拒绝
- B (P0-2/S1-2): 根保护——工作区根/项目根/家目录/文件系统根/系统目录/
  符号链接（含路径中段）/内部目录（.git 等）/敏感文件（.env 等）
- D (S2-7): workspace_root 缺失 → 503 workspace_unconfigured（不回退项目根）；
  通配元字符路径拒绝（本模块无任何 glob 展开）；破坏性操作审计 fail-closed
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from llm_loop.web import build_app, fs_tree


@pytest.fixture()
def client(tmp_path):
    """构造隔离工作区引擎的测试客户端（与 tests/web/test_fs_tree.py 同模式）."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMClient
    from llm_loop.tools.registry import ToolRegistry

    data_dir = tmp_path / "data"
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
    fs_tree.reset_delete_tokens_for_tests()
    yield TestClient(app), engine, tmp_path
    fs_tree.reset_delete_tokens_for_tests()


def _issue_token(cli, path: str) -> str:
    r = cli.get("/api/v1/fs/delete-token", params={"path": path})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _del(cli, path: str, token: str = "", hard: bool = False):
    params = {"path": path, "confirm": "true", "token": token}
    if hard:
        params["hard"] = "true"
    return cli.delete("/api/v1/fs/delete", params=params)


def _fake_request(engine):
    class _App:
        state = SimpleNamespace(engine=engine)

    return SimpleNamespace(app=_App())


# ── A. 两步令牌（P0-2）──
def test_delete_without_confirm_rejected(client):
    cli, _, tmp = client
    (tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
    r = cli.delete("/api/v1/fs/delete", params={"path": "a.txt", "token": "whatever"})
    assert r.status_code == 409
    assert r.json()["error"] == "confirm_required"
    assert (tmp / "ws" / "a.txt").exists()


def test_delete_confirm_without_token_rejected(client):
    cli, _, tmp = client
    (tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
    r = cli.delete("/api/v1/fs/delete", params={"path": "a.txt", "confirm": "true"})
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "confirm_token_required"
    assert "delete-token" in body["detail"]  # 引导先申请令牌
    assert (tmp / "ws" / "a.txt").exists()


def test_delete_token_happy_path(client):
    cli, _, tmp = client
    (tmp / "ws" / "del.txt").write_text("x", encoding="utf-8")
    r = cli.get("/api/v1/fs/delete-token", params={"path": "del.txt"})
    assert r.status_code == 200
    d = r.json()
    assert d["expires_in"] == 300
    assert len(d["token"]) >= 12  # ≥24bit 随机（6 hex）；实现 128bit/32 hex
    assert d["path"].endswith("del.txt")
    r2 = _del(cli, "del.txt", d["token"])
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "trashed"  # P2-4：默认先进回收站
    assert r2.json()["undo_token"]
    assert not (tmp / "ws" / "del.txt").exists()


def test_delete_token_replay_rejected(client):
    cli, _, tmp = client
    (tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
    t = _issue_token(cli, "a.txt")
    assert _del(cli, "a.txt", t).status_code == 200
    r = _del(cli, "a.txt", t)  # 单次使用：重放拒绝
    assert r.status_code == 409
    assert r.json()["error"] == "token_invalid"


def test_delete_token_wrong_path_rejected(client):
    cli, _, tmp = client
    (tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
    (tmp / "ws" / "b.txt").write_text("y", encoding="utf-8")
    t = _issue_token(cli, "a.txt")  # 为 a 签发
    r = _del(cli, "b.txt", t)  # 却删 b
    assert r.status_code == 409
    assert r.json()["error"] == "token_invalid"
    assert (tmp / "ws" / "b.txt").exists()
    assert (tmp / "ws" / "a.txt").exists()


def test_delete_token_expired_rejected(client):
    cli, _, tmp = client
    (tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
    t = _issue_token(cli, "a.txt")
    with fs_tree._DELETE_TOKENS_LOCK:
        fs_tree._DELETE_TOKENS[t]["expires_at"] = time.time() - 1
    r = _del(cli, "a.txt", t)
    assert r.status_code == 409
    assert r.json()["error"] == "token_invalid"
    assert (tmp / "ws" / "a.txt").exists()


def test_delete_token_reissue_invalidates_previous(client):
    cli, _, tmp = client
    (tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
    t1 = _issue_token(cli, "a.txt")
    t2 = _issue_token(cli, "a.txt")  # 同身份+路径重复申请
    assert t1 != t2
    r = _del(cli, "a.txt", t1)
    assert r.status_code == 409 and r.json()["error"] == "token_invalid"
    assert _del(cli, "a.txt", t2).status_code == 200  # 新令牌有效
    assert not (tmp / "ws" / "a.txt").exists()


def test_delete_token_identity_bound(client):
    cli, _, tmp = client
    (tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
    t = _issue_token(cli, "a.txt")  # 默认身份（客户端 IP）
    # 换 Bearer 身份使用 → 身份不匹配拒绝
    r2 = cli.delete(
        "/api/v1/fs/delete",
        params={"path": "a.txt", "confirm": "true", "token": t},
        headers={"Authorization": "Bearer other-identity"},
    )
    assert r2.status_code == 409 and r2.json()["error"] == "token_invalid"
    assert (tmp / "ws" / "a.txt").exists()
    # 同一 Bearer 身份签发+使用 → 成功
    hdr = {"Authorization": "Bearer k1"}
    rt = cli.get("/api/v1/fs/delete-token", params={"path": "a.txt"}, headers=hdr)
    assert rt.status_code == 200
    rd = cli.delete(
        "/api/v1/fs/delete",
        params={"path": "a.txt", "confirm": "true", "token": rt.json()["token"]},
        headers=hdr,
    )
    assert rd.status_code == 200, rd.text
    assert not (tmp / "ws" / "a.txt").exists()


def test_delete_token_issue_writes_audit(client):
    cli, _, tmp = client
    (tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
    _issue_token(cli, "a.txt")
    audit = tmp / "data" / "audit" / "fs_operations.jsonl"
    assert audit.exists()
    assert "delete_token_issue" in audit.read_text(encoding="utf-8")


# ── B. 根保护（P0-2/S1-2）──
def test_delete_workspace_root_denied(client):
    cli, _, tmp = client
    r = cli.get("/api/v1/fs/delete-token", params={"path": "."})
    assert r.status_code == 409 and r.json()["error"] == "protected_root"
    r2 = _del(cli, ".", token="x")
    assert r2.status_code == 409 and r2.json()["error"] == "protected_root"
    assert (tmp / "ws").is_dir()  # 工作区根未动


def test_delete_project_root_denied(client):
    cli, engine, _ = client
    old = engine.workspace_root
    engine.workspace_root = str(fs_tree._PROJECT_ROOT.parent)  # 让项目根落入界内
    try:
        r = _del(cli, str(fs_tree._PROJECT_ROOT), token="x")
        assert r.status_code == 409 and r.json()["error"] == "protected_root"
    finally:
        engine.workspace_root = old


def test_delete_home_denied(client):
    cli, engine, _ = client
    old = engine.workspace_root
    engine.workspace_root = str(Path.home())
    try:
        r = cli.get("/api/v1/fs/delete-token", params={"path": "."})
        assert r.status_code == 409 and r.json()["error"] == "protected_root"
        r2 = _del(cli, ".", token="x")
        assert r2.status_code == 409 and r2.json()["error"] == "protected_root"
    finally:
        engine.workspace_root = old


def test_delete_filesystem_root_and_system_dirs_denied(client):
    cli, engine, _ = client
    old = engine.workspace_root
    engine.workspace_root = "/"
    try:
        r = _del(cli, "/", token="x")
        assert r.status_code == 409 and r.json()["error"] == "protected_root"
        r2 = _del(cli, "/etc", token="x")
        assert r2.status_code == 409 and r2.json()["error"] == "protected_root"
    finally:
        engine.workspace_root = old


def test_root_guard_reason_unit(client):
    _, engine, tmp = client
    ws = (tmp / "ws").resolve()
    g = fs_tree._delete_root_guard_reason
    assert g(ws, engine) == "workspace_root_or_ancestor"  # 工作区根本身
    # 任意父目录拒绝（tmp 在 macOS /private/var 下时先命中 system_dir，同为拒绝）
    assert g(ws.parent, engine) in {"workspace_root_or_ancestor", "system_dir"}
    assert g(ws / "src", engine) is None  # 正常子路径放行
    assert g(Path("/"), engine) == "filesystem_root"
    assert g(Path("/etc/ssh").resolve(), engine) == "system_dir"
    assert g(Path("/usr/bin").resolve(), engine) == "system_dir"


# ── B. 符号链接（逐段 lstat，不依赖 resolve）──
def test_delete_symlink_pointing_outside_rejected(client):
    cli, _, tmp = client
    (tmp / "outside.txt").write_text("secret", encoding="utf-8")
    (tmp / "ws" / "leak.txt").symlink_to(tmp / "outside.txt")
    # resolve 后越界 → 400
    r = cli.get("/api/v1/fs/delete-token", params={"path": "leak.txt"})
    assert r.status_code == 400 and r.json()["error"] == "out_of_bounds"
    r2 = _del(cli, "leak.txt", token="x")
    assert r2.status_code == 400
    assert (tmp / "outside.txt").exists()  # 真实目标未动


def test_delete_symlink_alias_rejected(client):
    """目标自身是 symlink（即使指向工作区内）→ 409 symlink_rejected."""
    cli, _, tmp = client
    (tmp / "ws" / "real.txt").write_text("x", encoding="utf-8")
    (tmp / "ws" / "alias.txt").symlink_to(tmp / "ws" / "real.txt")
    r = cli.get("/api/v1/fs/delete-token", params={"path": "alias.txt"})
    assert r.status_code == 409 and r.json()["error"] == "symlink_rejected"
    r2 = _del(cli, "alias.txt", token="x")
    assert r2.status_code == 409 and r2.json()["error"] == "symlink_rejected"
    assert (tmp / "ws" / "real.txt").exists()  # 未借道 symlink 删真身


def test_delete_symlink_midpath_component_rejected(client):
    """路径中段是 symlink（dirlink→realdir）→ 409 symlink_rejected."""
    cli, _, tmp = client
    (tmp / "ws" / "realdir").mkdir()
    (tmp / "ws" / "realdir" / "f.txt").write_text("x", encoding="utf-8")
    (tmp / "ws" / "dirlink").symlink_to(tmp / "ws" / "realdir")
    r = _del(cli, "dirlink/f.txt", token="x")  # resolve 在界内，但词法路径含 symlink
    assert r.status_code == 409 and r.json()["error"] == "symlink_rejected"
    assert (tmp / "ws" / "realdir" / "f.txt").exists()


# ── B. 内部目录 / 敏感文件 / 扫描上限 ──
@pytest.mark.parametrize("name", [".git", ".lfs_checkpoints", ".trash", ".worktrees"])
def test_delete_protected_dir_requires_hard(client, name):
    cli, _, tmp = client
    proj = tmp / "ws" / "proj"
    (proj / name).mkdir(parents=True)
    (proj / name / "HEAD").write_text("x", encoding="utf-8")
    t = _issue_token(cli, "proj")
    r = _del(cli, "proj", t)
    assert r.status_code == 409 and r.json()["error"] == "protected_dir"
    assert (proj / name).exists()  # 未删
    # 被拒不消费令牌；hard=true 才允许（仍受根/符号链接/令牌约束）
    r2 = _del(cli, "proj", t, hard=True)
    assert r2.status_code == 200, r2.text
    assert not proj.exists()


@pytest.mark.parametrize(
    "name",
    [".env", "cert.pem", "server.key", "id_ed25519", "backup_rsa", "credentials.json"],
)
def test_delete_sensitive_file_requires_hard(client, name):
    cli, _, tmp = client
    app_dir = tmp / "ws" / "app"
    app_dir.mkdir()
    (app_dir / name).write_text("secret", encoding="utf-8")
    t = _issue_token(cli, "app")
    r = _del(cli, "app", t)
    assert r.status_code == 409 and r.json()["error"] == "sensitive_file_requires_hard"
    assert (app_dir / name).exists()
    r2 = _del(cli, "app", t, hard=True)
    assert r2.status_code == 200, r2.text
    assert not app_dir.exists()


def test_delete_scan_limit_requires_hard(client, monkeypatch):
    cli, _, tmp = client
    big = tmp / "ws" / "big"
    big.mkdir()
    for i in range(6):
        (big / f"f{i}.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(fs_tree, "_SENSITIVE_SCAN_MAX_ENTRIES", 3)
    t = _issue_token(cli, "big")
    r = _del(cli, "big", t)
    assert r.status_code == 409 and r.json()["error"] == "scan_limit_requires_hard"
    assert big.exists()
    r2 = _del(cli, "big", t, hard=True)
    assert r2.status_code == 200 and not big.exists()


def test_delete_hard_does_not_bypass_root_or_token(client):
    """hard=true 不豁免根保护/符号链接/令牌（A/B 全部约束仍生效）."""
    cli, _, tmp = client
    r = _del(cli, ".", token="x", hard=True)
    assert r.status_code == 409 and r.json()["error"] == "protected_root"
    r2 = _del(cli, "whatever.txt", token="x", hard=True)  # 无有效令牌
    assert r2.status_code == 409 and r2.json()["error"] == "token_invalid"
    assert (tmp / "ws").is_dir()


# ── D. S2-7: 根语义 503 + 字面量路径 + 审计 fail-closed ──
def test_workspace_unconfigured_returns_503(client):
    cli, engine, _ = client
    engine.workspace_root = ""
    r1 = cli.get("/api/v1/fs/tree", params={"path": ""})
    assert r1.status_code == 503 and r1.json()["error"] == "workspace_unconfigured"
    r2 = cli.post("/api/v1/fs/mkdir", params={"path": "x"})
    assert r2.status_code == 503 and r2.json()["error"] == "workspace_unconfigured"
    r3 = cli.put("/api/v1/fs/rename", params={"path": "a.txt", "new_name": "b.txt"})
    assert r3.status_code == 503 and r3.json()["error"] == "workspace_unconfigured"
    r4 = cli.delete("/api/v1/fs/delete", params={"path": "a.txt", "confirm": "true", "token": "x"})
    assert r4.status_code == 503 and r4.json()["error"] == "workspace_unconfigured"
    r5 = cli.get("/api/v1/fs/delete-token", params={"path": "a.txt"})
    assert r5.status_code == 503 and r5.json()["error"] == "workspace_unconfigured"


def test_workspace_root_nonexistent_returns_503(client):
    cli, engine, tmp = client
    engine.workspace_root = str(tmp / "no-such-dir")
    r = cli.get("/api/v1/fs/tree", params={"path": ""})
    assert r.status_code == 503 and r.json()["error"] == "workspace_unconfigured"


def test_tree_rejects_glob_meta_and_never_expands(client):
    """S2-7: pattern=* / [a-z]* 不得展开为枚举（本端点只接受字面量路径）."""
    cli, _, tmp = client
    (tmp / "ws" / "d1").mkdir()
    (tmp / "ws" / "d1" / "deep.txt").write_text("x", encoding="utf-8")
    for pat in ("*", "[a-z]*", "d1/*"):
        r = cli.get("/api/v1/fs/tree", params={"path": pat})
        assert r.status_code == 400, pat
        assert r.json()["error"] == "glob_meta_rejected"
        assert "dirs" not in r.json()  # 未返回任何枚举结果
    r2 = cli.post("/api/v1/fs/mkdir", params={"path": "a*b"})
    assert r2.status_code == 400 and r2.json()["error"] == "glob_meta_rejected"
    r3 = _del(cli, "*.txt", token="x")
    assert r3.status_code == 400 and r3.json()["error"] == "glob_meta_rejected"


def test_tree_is_single_level_only(client):
    """tree 只做单层 iterdir：深层文件不得出现在父层结果里."""
    cli, _, tmp = client
    (tmp / "ws" / "d1" / "d2").mkdir(parents=True)
    (tmp / "ws" / "d1" / "d2" / "deep.txt").write_text("x", encoding="utf-8")
    r = cli.get("/api/v1/fs/tree", params={"path": "d1"})
    assert r.status_code == 200
    d = r.json()
    assert d["dirs"] == ["d2"]
    assert d["files"] == []
    assert "deep.txt" not in str(d)


def test_delete_audit_fail_closed(client):
    """S2-7: 破坏性操作审计写失败 → 拒绝执行；令牌不燃烧（修复后可重试）."""
    cli, engine, tmp = client
    (tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
    t = _issue_token(cli, "a.txt")
    blocker = tmp / "audit_blocker"  # 用文件冒充审计目录 → 写入必败
    blocker.write_text("not-a-dir", encoding="utf-8")
    real_settings = engine.settings
    engine.settings = SimpleNamespace(audit_dir=str(blocker))
    try:
        r = _del(cli, "a.txt", t)
        assert r.status_code == 500 and r.json()["error"] == "audit_write_failed"
        assert (tmp / "ws" / "a.txt").exists()  # 未执行删除
    finally:
        engine.settings = real_settings
    # 审计恢复后同令牌重试成功（审计失败未消费令牌）
    r2 = _del(cli, "a.txt", t)
    assert r2.status_code == 200, r2.text
    assert not (tmp / "ws" / "a.txt").exists()


def test_rename_audit_fail_closed(client):
    cli, engine, tmp = client
    (tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
    blocker = tmp / "audit_blocker"
    blocker.write_text("not-a-dir", encoding="utf-8")
    real_settings = engine.settings
    engine.settings = SimpleNamespace(audit_dir=str(blocker))
    try:
        r = cli.put("/api/v1/fs/rename", params={"path": "a.txt", "new_name": "b.txt"})
        assert r.status_code == 500 and r.json()["error"] == "audit_write_failed"
        assert (tmp / "ws" / "a.txt").exists()  # 未执行重命名
        assert not (tmp / "ws" / "b.txt").exists()
    finally:
        engine.settings = real_settings


def test_audit_helpers_unit(tmp_path):
    """_audit_destructive 对写失败返回 False（fail-closed）；_audit 吞异常（fail-open）."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not-a-dir", encoding="utf-8")
    engine = SimpleNamespace(settings=SimpleNamespace(audit_dir=str(blocker)))
    assert fs_tree._audit_destructive(_fake_request(engine), "delete", "x") is False
    fs_tree._audit(_fake_request(engine), "mkdir", "x")  # fail-open：不抛
    ok_dir = tmp_path / "audit-ok"
    engine2 = SimpleNamespace(settings=SimpleNamespace(audit_dir=str(ok_dir)))
    assert fs_tree._audit_destructive(_fake_request(engine2), "delete", "y") is True
    assert (ok_dir / "fs_operations.jsonl").exists()
