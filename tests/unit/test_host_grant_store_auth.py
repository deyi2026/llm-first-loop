"""P0-1（2026-11-14，独立 Reviewer P0）host-grant 账本认证与隔离的攻击链回归.

背景：生产 LFL_DATA_DIR 曾位于 workspace 内，bwrap --bind workdir workdir
下同 UID 模型可改写 grants/audit；伪造 ``status=approved`` + 自洽
request_binding 的 JSON 可被消费，直接获得无人工审批的宿主文件
read/write bind（Reviewer 临时目录 PoC 实证）。本文件覆盖双重防线：

防线 A（MAC，进程内随机 HMAC 密钥）：
- 伪造（含字段全自洽、request_id 指向不存在请求）→ peek/consume/check 拒；
- 篡改已签发文件（保留原 mac）→ 拒；
- 锁内窗口被替换为不可信内容 → 拒，绝不"重签洗白"（revoke 同理）；
- 审计链篡改 → audit_chain_broken 停止签发；
- 服务重启（密钥轮换）→ 旧 grant 失效需重新人工审批；旧审计链按
  epoch 归档保留证据、审批流仍可用；
- 同进程跨 store 对象共享密钥 → 正常签发-消费。

防线 B（home 隔离，独立安全状态目录）：
- LFL_HOST_GRANT_HOME / XDG_STATE_HOME 指向 workspace、LFL_DATA_DIR、
  /tmp、缓存目录、EXEC_SANDBOX_MACOS_WRITABLE → fail-closed 拒；
- symlink 重定向进 workspace → realpath 判定拒；
- execute_command 的 workdir 圈住账本（--bind workdir 攻击面）→ 拒；
- 真实 bwrap 可用时：workdir bind 内不可写账本（结构性证明）。
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from llm_loop.core.run_context import current_session_id
from llm_loop.tools import escalation as esc
from llm_loop.tools.escalation import (
    HostCapabilityGrantStore,
    HostGrantError,
    host_grant_store_home,
)

_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]  # 与 escalation.py parents[3] 同根


def _home() -> Path:
    """正向语境账本 home（conftest 已注入 LFL_HOST_GRANT_HOME 并钉模块属性）.

    注意与负例的区别：负例测试直接调用文件顶部绑定的**真实**
    host_grant_store_home()（不受 conftest patch 影响，走生产校验）。
    """
    return Path(os.environ["LFL_HOST_GRANT_HOME"]).resolve()


@pytest.fixture
def gstore(isolated_data_dir):
    return HostCapabilityGrantStore(_home())


@pytest.fixture
def session_ctx():
    tok = current_session_id.set("p01-auth-unit")
    yield "p01-auth-unit"
    current_session_id.reset(tok)


@pytest.fixture
def target_file(tmp_path):
    f = tmp_path / "target.txt"
    f.write_text("before", encoding="utf-8")
    return f


def _issue_real(gstore, target: Path, *, ttl_s: int = 600) -> dict:
    return gstore.issue(
        tool_name="execute_command",
        canonical_path=str(target.resolve()),
        operation="write",
        requester_session_id="p01-auth-unit",
        ttl_s=ttl_s,
        approver_identity="web:session:p01",
        request_binding={
            "command_sha256": "a" * 64,
            "cwd": "/ws",
            "file_sha256": "b" * 64,
            "request_id": f"ER-{uuid.uuid4().hex[:12]}",
        },
    )


def _forge_grant(home: Path, *, mac: str = "", key_id: str = "", **overrides) -> str:
    """模拟模型在可写目录伪造 grant 文件（schema 自洽、维度全匹配）."""
    grant_id = secrets.token_hex(12)
    now = datetime.now()
    record = {
        "schema": "lfl.host-capability-grant/v1",
        "grant_id": grant_id,
        "tool_name": "execute_command",
        "canonical_path": "/etc/pwned.txt",
        "operation": "write",
        "requester_session_id": "p01-auth-unit",
        "request_binding": {
            "command_sha256": "c" * 64,
            "cwd": "/ws",
            "file_sha256": "d" * 64,
            "request_id": "ER-NOT-EXIST-9999",
        },
        "approver_identity": "web:session:p01",
        "status": "approved",
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=600)).isoformat(),
        "uses": 0,
        "max_uses": 1,
        "version": 1,
    }
    record.update(overrides)
    if mac:
        record["mac"] = mac
    if key_id:
        record["key_id"] = key_id
    grants = home / "grants"
    grants.mkdir(parents=True, exist_ok=True, mode=0o700)  # 精明攻击者: 直击签名防线
    path = grants / f"{grant_id}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # 攻击者也会伪装 0600
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False))
    return grant_id


# ── 防线 A：伪造 / 篡改 / 重启 ─────────────────────────────


def test_forged_approved_grant_without_mac_rejected(gstore, isolated_data_dir):
    gid = _forge_grant(_home())
    snap = gstore.peek(gid)
    assert snap.get("_sig_unverified") is True
    ok, reason = gstore.check(
        gid, tool_name="execute_command", canonical_path="/etc/pwned.txt",
        operation="write", requester_session_id="p01-auth-unit",
    )
    assert not ok and "signature" in reason
    assert gstore.consume(
        gid, tool_name="execute_command", canonical_path="/etc/pwned.txt",
        operation="write", requester_session_id="p01-auth-unit",
    ) is None


def test_forged_grant_with_fake_mac_and_key_id_rejected(gstore, isolated_data_dir):
    # 攻击者无密钥：即使伪造 64-hex mac 与任意 key_id，HMAC 不符即拒。
    gid = _forge_grant(
        _home(), mac=secrets.token_hex(32), key_id=secrets.token_hex(8),
    )
    assert gstore.peek(gid).get("_sig_unverified") is True
    assert gstore.consume(
        gid, tool_name="execute_command", canonical_path="/etc/pwned.txt",
        operation="write", requester_session_id="p01-auth-unit",
    ) is None


def test_forged_fully_selfconsistent_binding_rejected(gstore, isolated_data_dir, session_ctx, target_file):
    # 维度全自洽（tool/path/operation/session 匹配 + request_binding 自洽 +
    # request_id 指向不存在的请求）——无有效签名仍拒（Reviewer PoC 场景）。
    gid = _forge_grant(
        _home(),
        canonical_path=str(target_file.resolve()),
        request_binding={
            "command_sha256": "a" * 64,
            "cwd": "/ws",
            "file_sha256": "b" * 64,
            "request_id": "ER-NOT-EXIST-8888",
        },
    )
    assert gstore.peek(gid).get("_sig_unverified") is True
    assert gstore.consume(
        gid, tool_name="execute_command", canonical_path=str(target_file.resolve()),
        operation="write", requester_session_id="p01-auth-unit",
    ) is None


def test_tampered_issued_grant_rejected(gstore, isolated_data_dir, session_ctx, target_file):
    g = _issue_real(gstore, target_file)
    assert gstore.peek(g["grant_id"]).get("_sig_unverified") is None  # 签发即有效
    # 模型篡改：延长有效期 / 重置使用次数（保留原 mac → 必失配）
    path = _home() / "grants" / f"{g['grant_id']}.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["expires_at"] = (
        datetime.now() + timedelta(days=365)
    ).isoformat()
    rec["uses"] = 0
    path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    assert gstore.peek(g["grant_id"]).get("_sig_unverified") is True
    ok, reason = gstore.check(
        g["grant_id"], tool_name="execute_command",
        canonical_path=str(target_file.resolve()),
        operation="write", requester_session_id="p01-auth-unit",
    )
    assert not ok and "signature" in reason
    assert gstore.consume(
        g["grant_id"], tool_name="execute_command",
        canonical_path=str(target_file.resolve()),
        operation="write", requester_session_id="p01-auth-unit",
    ) is None


def test_audit_tamper_stops_issuance(gstore, isolated_data_dir, session_ctx, target_file):
    _issue_real(gstore, target_file)
    _issue_real(gstore, target_file)  # 链：epoch_start + issue + issue
    audit = _home() / "grants" / "audit.jsonl"
    lines = audit.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 3 and lines[0].startswith('{"event": "epoch_start"') or "epoch_start" in lines[0]
    # 篡改中间行（reason 字段改写，保留原 mac → 链断）
    mid = json.loads(lines[1])
    mid["reason"] = "forged"
    lines[1] = json.dumps(mid, ensure_ascii=False, sort_keys=True)
    audit.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(HostGrantError, match="audit_chain_broken"):
        _issue_real(gstore, target_file)


def test_service_restart_rotates_key_and_invalidates_grants(
    gstore, isolated_data_dir, session_ctx, target_file, monkeypatch
):
    g = _issue_real(gstore, target_file)
    kid_old = g["key_id"]
    # 模拟重启：进程内密钥轮换（密钥从不落盘，重启必然换钥）
    new_key = secrets.token_bytes(32)
    new_kid = hashlib.sha256(b"lfl.host_grant.key_id.v1" + new_key).hexdigest()[:16]
    monkeypatch.setattr(esc, "_GRANT_SIGNING_KEY", new_key)
    monkeypatch.setattr(esc, "_GRANT_KEY_ID", new_kid)
    # 旧 grant：验签失败（不假装仍有效），消费拒绝 → 需重新人工审批
    assert gstore.peek(g["grant_id"]).get("_sig_unverified") is True
    assert gstore.consume(
        g["grant_id"], tool_name="execute_command",
        canonical_path=str(target_file.resolve()),
        operation="write", requester_session_id="p01-auth-unit",
    ) is None
    # 审批流仍可用：旧链按 epoch 归档保留证据，新链开新 epoch
    g2 = _issue_real(gstore, target_file)
    assert g2["key_id"] == new_kid
    grants_dir = _home() / "grants"
    archived = sorted(grants_dir.glob(f"audit.{kid_old}.*.jsonl"))
    assert archived, "旧 epoch 审计链必须归档保留（append-only 证据）"
    audit_lines = (grants_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(audit_lines[0])
    assert first["event"] == "epoch_start" and first["key_id"] == new_kid


def test_revoke_refuses_untrusted_record(gstore, isolated_data_dir, session_ctx, target_file):
    g = _issue_real(gstore, target_file)
    # 锁内窗口替换（模拟攻击者趁隙改文件为无签名内容）→ revoke 拒绝改写，
    # 防止把伪造内容重签成"合法 revoked"记录（洗白）。
    path = _home() / "grants" / f"{g['grant_id']}.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec.pop("mac", None)
    path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(HostGrantError, match="signature verification failed"):
        gstore.revoke(g["grant_id"], revoked_by="web:test")


def test_same_process_cross_store_object_consume(
    isolated_data_dir, session_ctx, target_file
):
    # 同进程两个 store 实例（web 端点与工具侧各自构造）共享进程密钥：
    # A 签发 → B 消费成功；跨对象 CAS 单次语义保持（B 再消费拒）。
    store_a = HostCapabilityGrantStore(_home())
    store_b = HostCapabilityGrantStore(_home())
    g = store_a.issue(
        tool_name="execute_command",
        canonical_path=str(target_file.resolve()),
        operation="write",
        requester_session_id="p01-auth-unit",
        ttl_s=600,
        approver_identity="web:session:p01",
        request_binding={"command_sha256": "a" * 64, "cwd": "/ws",
                         "file_sha256": "b" * 64, "request_id": "ER-X1"},
    )
    gid = g["grant_id"]
    assert store_b.peek(gid).get("_sig_unverified") is None
    consumed = store_b.consume(
        gid, tool_name="execute_command",
        canonical_path=str(target_file.resolve()),
        operation="write", requester_session_id="p01-auth-unit",
    )
    assert consumed is not None and consumed["status"] == "consumed"
    assert store_a.consume(
        gid, tool_name="execute_command",
        canonical_path=str(target_file.resolve()),
        operation="write", requester_session_id="p01-auth-unit",
    ) is None  # 单次：另一对象重放拒


# ── 防线 B：home 隔离 fail-closed ──────────────────────────


def test_unsafe_home_env_rejected(monkeypatch, tmp_path, isolated_data_dir):
    cases = []
    cases.append(("workspace 子目录", str(_WORKSPACE_ROOT / "grant-trap")))
    cases.append(("workspace 本身", str(_WORKSPACE_ROOT)))
    cases.append(("/tmp", "/tmp/lfl-grant-trap"))
    cases.append(("缓存目录", str(Path.home() / ".cache" / "lfl-trap")))
    for _label, value in cases:
        monkeypatch.setenv("LFL_HOST_GRANT_HOME", value)
        with pytest.raises(HostGrantError, match="grant_store_insecure"):
            host_grant_store_home()
    # EXEC_SANDBOX_MACOS_WRITABLE 追加根：显式设置 env 后断言（父侧验收
    # 2026-11-14 修正：原 case 未设该 env，仅当 pytest basetemp 恰落默认
    # 危险根（如 /private/tmp）内才被拒——环境依赖侥幸；显式设置后追加根
    # 及其子路径在任何 basetemp 位置都必须 fail-closed，生产守卫不变）
    monkeypatch.setenv("EXEC_SANDBOX_MACOS_WRITABLE", str(tmp_path / "extra-writable"))
    for value in (
        str(tmp_path / "extra-writable"),
        str(tmp_path / "extra-writable" / "inside"),
    ):
        monkeypatch.setenv("LFL_HOST_GRANT_HOME", value)
        with pytest.raises(HostGrantError, match="grant_store_insecure"):
            host_grant_store_home()
    monkeypatch.delenv("EXEC_SANDBOX_MACOS_WRITABLE")


def test_unsafe_home_via_lfl_data_dir_rejected(monkeypatch, tmp_path, isolated_data_dir):
    # 生产缺陷场景复现：LFL_DATA_DIR 位于 workspace 内 → 账本绝不跟随
    data_in_ws = _WORKSPACE_ROOT / "data-trap"
    monkeypatch.setenv("LFL_DATA_DIR", str(data_in_ws))
    monkeypatch.setenv("LFL_HOST_GRANT_HOME", str(data_in_ws / "grants"))
    with pytest.raises(HostGrantError, match="grant_store_insecure"):
        host_grant_store_home()


def test_xdg_state_home_into_workspace_rejected(monkeypatch, isolated_data_dir):
    monkeypatch.delenv("LFL_HOST_GRANT_HOME", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(_WORKSPACE_ROOT / "xdg-trap"))
    with pytest.raises(HostGrantError, match="grant_store_insecure"):
        host_grant_store_home()


def test_home_symlink_redirect_into_workspace_rejected(monkeypatch, tmp_path, isolated_data_dir):
    link = tmp_path / "state-link"
    os.symlink(_WORKSPACE_ROOT / "symlink-trap", link)
    monkeypatch.setenv("LFL_HOST_GRANT_HOME", str(link))
    with pytest.raises(HostGrantError, match="grant_store_insecure"):
        host_grant_store_home()


def test_default_home_outside_writable_roots(monkeypatch, isolated_data_dir):
    # 无 env：默认 ~/.local/state/lfl-host-grants——与 workspace/缓存/tmp
    # 分离；只读推导不建目录（绝不触碰真实 home 的写）。
    monkeypatch.delenv("LFL_HOST_GRANT_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    home = host_grant_store_home()
    assert home.name == "lfl-host-grants"
    assert "state" in str(home)
    assert not str(home).startswith(str(_WORKSPACE_ROOT))
    assert not str(home).startswith("/tmp")


# ── 工具层：execute_command 拒绝路径 ───────────────────────


def test_execute_command_rejects_forged_grant(gstore, isolated_data_dir, ctx_e2e):
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

    gid = _forge_grant(_home())
    tool = ExecuteCommandTool(timeout_s=10, sandbox_mode="sandbox-exec")
    r = tool.execute(command="true", host_grant_id=gid, workdir=str(ctx_e2e))
    assert r.status.name == "ERROR"
    assert r.error_type == "host_grant_rejected"
    assert "重新" in r.content or "人工审批" in r.content


def test_execute_command_workdir_grant_home_guard(
    isolated_data_dir, tmp_path, monkeypatch
):
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

    tool = ExecuteCommandTool(timeout_s=10, sandbox_mode="sandbox-exec")
    home = _home()
    home.mkdir(parents=True, exist_ok=True)  # workdir 需存在，防先败于存在性检查
    # 钉 guard 候选=生效账本（候选推导的生产校验由下方负例/正例独立覆盖：
    # 测试 basetemp 在 /private/tmp 危险根内，真实推导会拒绝该 env）
    monkeypatch.setattr(esc, "grant_home_guard_candidates", lambda: [str(home)])
    # workdir=账本自身 / 账本祖先（--bind workdir 圈住账本）→ 拒
    for wd in (str(home), str(home.parent)):
        r = tool.execute(command="true", workdir=wd)
        assert r.status.name == "ERROR", r.content[:200]
        assert r.error_type == "workdir_overlaps_grant_home"


def test_grant_home_guard_candidates_env_and_default(monkeypatch, isolated_data_dir):
    # 候选推导正例：env 指向合法位置（真实 home 下独立目录，非危险根）时，
    # 候选=生效 env home + 平台默认 home；env 非法（/tmp）时仅默认 home。
    good = Path.home() / ".local" / "state-guard-unit-probe"
    monkeypatch.setenv("LFL_HOST_GRANT_HOME", str(good))
    cands = esc.grant_home_guard_candidates()
    assert any(c.endswith("state-guard-unit-probe") for c in cands)
    assert any(c.endswith("lfl-host-grants") for c in cands)
    monkeypatch.setenv("LFL_HOST_GRANT_HOME", "/tmp/bad-grant-home")
    cands2 = esc.grant_home_guard_candidates()
    assert cands2 and all(not c.startswith("/tmp") for c in cands2)


@pytest.fixture
def ctx_e2e(tmp_path):
    from llm_loop.core.run_context import current_workspace_root

    ctx = tmp_path / "ctx"
    ctx.mkdir(exist_ok=True)
    tok = current_workspace_root.set(str(tmp_path))
    yield ctx
    current_workspace_root.reset(tok)


# ── 结构性证明（真实 bwrap，Deepin/Linux）─────────────────


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="真实 bwrap 仅 Deepin/Linux 部署可用")
def test_bwrap_cannot_write_grant_home(gstore, isolated_data_dir, session_ctx, target_file):
    """bwrap --bind workdir workdir 下，账本目录不可写（防线 B 结构证明）."""
    _issue_real(gstore, target_file)
    home = host_grant_store_home()
    workdir = home.parent  # tmp 根：账本祖先——最不利情形
    probe = home / "grants" / "pwned.txt"
    argv = [
        "bwrap",
        "--ro-bind", "/", "/",
        "--bind", str(workdir), str(workdir),
        "--dev", "/dev", "--proc", "/proc",
        "--unshare-user",
        "--", "/bin/sh", "-c",
        f"echo pwn > '{probe}' 2>&1; echo rc=$?",
    ]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert not probe.exists(), f"模型经 workdir bind 写入账本: {proc.stdout} {proc.stderr}"
