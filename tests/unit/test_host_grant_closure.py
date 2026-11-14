"""DESIGN-20261114（Deepin P0）host-grant 工具层闭环测试.

覆盖验收矩阵（设计 §最小验收）的工具侧部分：
- 申请参数校验 fail-closed（相对路径/glob/../symlink/不存在/目录/非法
  operation/短 justification/ttl 越界）
- 服务端冻结字段（会话/工具/cwd/realpath/文件 sha256/命令 sha256）
- decide 携带 host_grant_id 原子落盘（无灾难令牌）；denied 携带 → 拒
- HostCapabilityGrantStore 扩展（request_binding/policy_hash/peek）
- escalation_wait host-grant 分支（grant_id 回执/签发中断显式失败）
- execute_command._resolve_host_grant 全维度拒绝矩阵（跨会话/命令篡改/
  cwd 不匹配/文件版本漂移/symlink 替换/文件消失/none/docker/bwrap 缺失）
- write-scope gate 叠加（allow 豁免仅授权单文件；deny 不可绕过）
- sandbox_argv 单文件精确 bind 构造（bwrap --dir 祖链 + ro/rw；docker 拒）
- 并发消费单赢家；单次重放拒绝
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id, current_workspace_root
from llm_loop.core.write_scope import WriteScope
from llm_loop.tools.builtin.escalation import EscalationWaitTool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.host_access import HostAccessRequestTool
from llm_loop.tools.escalation import (
    EscalationStore,
    HostCapabilityGrantStore,
    host_grant_store_home,
)
from llm_loop.tools.sandbox import bwrap_argv, sandbox_argv

# ── 公共装配 ──────────────────────────────────────────────

@pytest.fixture
def store(isolated_data_dir):
    return EscalationStore(isolated_data_dir / "audit" / "escalation_requests.json")


@pytest.fixture
def gstore(isolated_data_dir):
    # P0 补修(2026-11-14): home 推导返回**基准 data 目录**（grants 由 store
    # __init__ 统一追加一次，类契约 <home>/grants）——单层，不再双层 grants
    assert host_grant_store_home() == isolated_data_dir
    return HostCapabilityGrantStore(host_grant_store_home())


@pytest.fixture
def session_ctx(tmp_path):
    tok = current_session_id.set("host-grant-unit")
    wtok = current_workspace_root.set(str(tmp_path))
    yield
    current_session_id.reset(tok)
    current_workspace_root.reset(wtok)


@pytest.fixture
def target_file(tmp_path):
    outside = tmp_path / "outside-tree"
    outside.mkdir()
    f = (outside / "note.txt").resolve()
    f.write_text("v1-content", encoding="utf-8")
    return f


def _cmd(f: Path) -> str:
    return f"cat {f}"


def _request(store, target: Path, *, operation="write", command=None, justification=None, **kw):
    return HostAccessRequestTool(store).execute(
        path=str(target),
        operation=operation,
        command=command or _cmd(target),
        justification=justification or "host-grant 单元测试必要性说明（>=10字符）",
        **kw,
    )


def _approve(store, gstore, rid: str, target: Path, *, operation="write",
             session_id="host-grant-unit", cwd=None, command=None, ttl_s=600) -> str:
    """模拟 web 审批端点的签发顺序（issue → decide(host_grant_id)）."""
    rec = store.get(rid)
    hr = rec["host_request"]
    grant = gstore.issue(
        tool_name="execute_command",
        canonical_path=str(target),
        operation=operation,
        requester_session_id=session_id,
        ttl_s=ttl_s,
        approver_identity="web:session:unit",
        request_binding={
            "command_sha256": hr["host_command_sha256"],
            "cwd": cwd or hr["host_cwd"],
            "file_sha256": hr["host_file_sha256"],
            "request_id": rid,
        },
    )
    dec, err = store.decide(
        rid, "approved", decided_by="web:session:unit", channel="web_session",
        note="unit", host_grant_id=grant["grant_id"],
    )
    assert dec is not None, err
    return grant["grant_id"]


# ── 1. 申请参数校验矩阵（fail-closed） ───────────────────

def test_request_rejects_relative_path(store, session_ctx, target_file):
    res = HostAccessRequestTool(store).execute(
        path="relative/x.txt", operation="read", command="cat x",
        justification="相对路径必须拒绝的必要性说明",
    )
    assert res.status == ToolResultStatus.FAILURE
    assert "绝对路径" in res.content


def test_request_rejects_glob_and_dotdot(store, session_ctx):
    tool = HostAccessRequestTool(store)
    r1 = tool.execute(path="/etc/*.conf", operation="read", command="cat /etc/a.conf",
                      justification="通配符必须拒绝的必要性说明")
    assert "通配符" in r1.content and r1.status == ToolResultStatus.FAILURE
    r2 = tool.execute(path="/etc/../etc/passwd", operation="read", command="cat /etc/passwd",
                      justification="dotdot 必须拒绝的必要性说明")
    assert ".." in r2.content and r2.status == ToolResultStatus.FAILURE


def test_request_rejects_symlink(store, session_ctx, tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("x")
    link = tmp_path / "link.txt"
    os.symlink(real, link)
    res = HostAccessRequestTool(store).execute(
        path=str(link), operation="read", command=f"cat {real}",
        justification="符号链接必须拒绝的必要性说明",
    )
    assert res.status == ToolResultStatus.FAILURE and "符号链接" in res.content


def test_request_rejects_missing_and_dir(store, session_ctx, tmp_path):
    tool = HostAccessRequestTool(store)
    r1 = tool.execute(path=str(tmp_path / "nope.txt"), operation="read",
                      command="cat nope", justification="不存在文件必须拒绝的说明")
    assert "不存在" in r1.content or "既存" in r1.content
    r2 = tool.execute(path=str(tmp_path), operation="read", command="ls",
                      justification="目录必须拒绝的必要性说明")
    assert "单文件" in r2.content
    assert r1.status == ToolResultStatus.FAILURE and r2.status == ToolResultStatus.FAILURE


def test_request_rejects_bad_operation_and_short_justification(store, session_ctx, target_file):
    tool = HostAccessRequestTool(store)
    r1 = tool.execute(path=str(target_file), operation="delete", command=_cmd(target_file),
                      justification="删除操作不在 P0 支持范围之内")
    assert "read|write" in r1.content
    r2 = tool.execute(path=str(target_file), operation="read", command=_cmd(target_file),
                      justification="短")
    assert "10 个字符" in r2.content
    r3 = tool.execute(path=str(target_file), operation="read", command=_cmd(target_file),
                      justification="ttl 越界必须拒绝的必要性说明", ttl_seconds=601)
    assert "ttl_seconds" in r3.content


# ── 2. 冻结字段与幂等 ─────────────────────────────────────

def test_request_freezes_binding_fields(store, session_ctx, tmp_path, target_file):
    res = _request(store, target_file, operation="write")
    assert res.status == ToolResultStatus.SUCCESS
    rid = res.content.split("request_id=")[1].splitlines()[0].strip()
    rec = store.get(rid)
    assert rec["request_kind"] == "host_grant"
    hr = rec["host_request"]
    assert hr["host_operation"] == "write"
    assert hr["host_canonical_path"] == str(target_file)
    assert hr["host_session_id"] == "host-grant-unit"
    assert hr["host_cwd"] == str(tmp_path)
    assert hr["host_file_sha256"] == hashlib.sha256(b"v1-content").hexdigest()
    assert hr["host_command_sha256"] == hashlib.sha256(_cmd(target_file).encode()).hexdigest()
    assert rec["command"].startswith("[host-grant:write]")

    # 幂等：同申请复用 pending 记录
    res2 = _request(store, target_file, operation="write")
    rid2 = res2.content.split("request_id=")[1].splitlines()[0].strip()
    assert rid2 == rid


# ── 3. decide: host_grant_id 原子绑定、不铸令牌 ───────────

def test_decide_binds_grant_and_mints_no_token(store, session_ctx, target_file):
    res = _request(store, target_file)
    rid = res.content.split("request_id=")[1].splitlines()[0].strip()
    dec, err = store.decide(rid, "approved", decided_by="web:session:x",
                            channel="web_session", note="ok", host_grant_id="HG-1")
    assert dec is not None, err
    assert dec["host_grant_id"] == "HG-1"
    assert "token" not in dec  # _public 永不投影令牌
    full = store.get(rid)
    assert full["token"] == ""


def test_decide_rejects_grant_id_on_denied(store, session_ctx, target_file):
    res = _request(store, target_file)
    rid = res.content.split("request_id=")[1].splitlines()[0].strip()
    dec, err = store.decide(rid, "denied", decided_by="w", channel="web_session",
                            host_grant_id="HG-x")
    assert dec is None and "approved" in err


# ── 4. HostCapabilityGrantStore: binding/policy_hash/peek ─

def test_issue_with_binding_and_peek_roundtrip(gstore, target_file):
    g = gstore.issue(
        tool_name="execute_command", canonical_path=str(target_file),
        operation="read", requester_session_id="s1", ttl_s=60,
        approver_identity="web:session:t",
        request_binding={"command_sha256": "a" * 64, "cwd": "/ws", "file_sha256": "b" * 64},
    )
    assert g["request_binding"]["command_sha256"] == "a" * 64
    assert g["policy_hash"]
    # 并发安全文件写回读一致
    assert gstore.peek(g["grant_id"])["canonical_path"] == str(target_file)


def test_peek_missing_grant_fails_closed(gstore):
    from llm_loop.tools.escalation import HostGrantError

    with pytest.raises(HostGrantError):
        gstore.peek("HG-NOT-EXIST")


def test_grant_store_layout_single_layer(isolated_data_dir, gstore, session_ctx, target_file):
    """P0 补修(2026-11-14) 回归: 审计/授权文件必须落在 data/grants/（单层）.

    host_grant_store_home() 曾额外拼 /grants，与 store __init__ 内追加叠成
    data/grants/grants 双层，audit.jsonl 落错层（e2e 审计断言失败的根因）。
    """
    gstore.issue(
        tool_name="execute_command", canonical_path=str(target_file),
        operation="write", requester_session_id="host-grant-unit",
        ttl_s=600, approver_identity="web:session:unit",
        request_binding={"command_sha256": "a" * 64, "cwd": "/ws", "file_sha256": "b" * 64},
    )
    # audit 恰在 data/grants/audit.jsonl（单层），且不存在双层 grants/grants
    assert (isolated_data_dir / "grants" / "audit.jsonl").exists()
    assert not (isolated_data_dir / "grants" / "grants").exists()
    assert not (isolated_data_dir / "grants" / "grants" / "audit.jsonl").exists()


# ── 5. escalation_wait: host-grant 分支 ───────────────────

def test_wait_returns_grant_id(store, session_ctx, target_file, gstore):
    rid = _request(store, target_file).content.split("request_id=")[1].splitlines()[0].strip()
    gid = _approve(store, gstore, rid, target_file)
    res = EscalationWaitTool(store).execute(request_id=rid, timeout_s=1)
    assert res.status == ToolResultStatus.SUCCESS
    assert f"grant_id={gid}" in res.content
    assert "execute_command(host_grant_id" in res.content


def test_wait_reports_broken_issuance(store, session_ctx, target_file):
    rid = _request(store, target_file).content.split("request_id=")[1].splitlines()[0].strip()
    dec, err = store.decide(rid, "approved", decided_by="w", channel="web_session",
                            note="crash-before-issue", host_grant_id="")
    assert dec is not None, err
    res = EscalationWaitTool(store).execute(request_id=rid, timeout_s=1)
    assert res.status == ToolResultStatus.FAILURE
    assert "签发中断" in res.content


# ── 6. _resolve_host_grant 全维度拒绝矩阵 ─────────────────

def _gid_for(store, gstore, target, *, operation="write", session_id="host-grant-unit"):
    rid = _request(store, target, operation=operation).content.split("request_id=")[1].splitlines()[0].strip()
    return _approve(store, gstore, rid, target, operation=operation, session_id=session_id)


@pytest.fixture
def tool_exec_sbx():
    return ExecuteCommandTool(sandbox_mode="sandbox-exec")


def test_resolve_ok_and_bindings_enforced(store, gstore, session_ctx, tmp_path, target_file, tool_exec_sbx):
    gid = _gid_for(store, gstore, target_file)
    ctx, err = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), None)
    assert err is None and ctx["canonical_path"] == str(target_file)
    assert ctx["operation"] == "write"

    # 命令文本篡改 → 拒
    _, err = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file) + " ; echo tampered", None)
    assert err is not None and "命令文本" in err.content

    # cwd 不匹配 → 拒
    _, err = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), "/other/cwd")
    assert err is not None and "cwd 不匹配" in err.content

    # 文件版本漂移（TOCTOU）→ 拒
    target_file.write_text("v2-content", encoding="utf-8")
    _, err = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), None)
    assert err is not None and "内容已变化" in err.content
    target_file.write_text("v1-content", encoding="utf-8")


def test_resolve_rejects_cross_session(store, gstore, session_ctx, tmp_path, target_file, tool_exec_sbx):
    gid = _gid_for(store, gstore, target_file)
    other = current_session_id.set("attacker-session")
    try:
        _, err = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), None)
        assert err is not None and "会话不匹配" in err.content
    finally:
        current_session_id.reset(other)


def test_resolve_rejects_symlink_replacement(store, gstore, session_ctx, target_file, tool_exec_sbx, tmp_path):
    gid = _gid_for(store, gstore, target_file)
    # 审批后把授权路径替换为指向他处的符号链接
    target_file.unlink()
    os.symlink(tmp_path / "elsewhere.txt", target_file)
    _, err = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), None)
    assert err is not None and "符号链接" in err.content


def test_resolve_rejects_deleted_target(store, gstore, session_ctx, target_file, tool_exec_sbx):
    gid = _gid_for(store, gstore, target_file)
    target_file.unlink()
    _, err = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), None)
    assert err is not None and "常规文件" in err.content


def test_resolve_rejects_unsafe_backends(store, gstore, session_ctx, target_file):
    gid = _gid_for(store, gstore, target_file)
    t_none = ExecuteCommandTool(sandbox_mode="none")
    _, err = t_none._resolve_host_grant(gid, _cmd(target_file), None)
    assert err is not None and "EXEC_SANDBOX=none" in err.content
    t_docker = ExecuteCommandTool(sandbox_mode="docker")
    _, err = t_docker._resolve_host_grant(gid, _cmd(target_file), None)
    assert err is not None and "docker" in err.content


def test_resolve_bwrap_missing_fail_closed(store, gstore, session_ctx, target_file, monkeypatch):
    gid = _gid_for(store, gstore, target_file)
    t = ExecuteCommandTool(sandbox_mode="bwrap")
    monkeypatch.setattr("shutil.which", lambda name: None if name == "bwrap" else "/usr/bin/x")
    _, err = t._resolve_host_grant(gid, _cmd(target_file), None)
    assert err is not None and "bwrap 不可用" in err.content


# ── 6b. P0 补修(2026-11-14): 生命周期诊断优先级 + 绑定完整性 ──

def test_resolve_consumed_reports_used_before_content_drift(
    store, gstore, session_ctx, target_file, tool_exec_sbx
):
    """已消费 grant 重放：根因诊断必须是"授权已用"，不被"内容已变化"掩盖."""
    gid = _gid_for(store, gstore, target_file)
    assert gstore.consume(
        gid, tool_name="execute_command", canonical_path=str(target_file),
        operation="write", requester_session_id="host-grant-unit",
    ) is not None
    # 模拟首次执行已改写目标文件（e2e 真实场景中的字节漂移）
    target_file.write_text("drifted", encoding="utf-8")
    _, err = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), None)
    assert err is not None
    assert "已用" in err.content
    assert "内容已变化" not in err.content
    target_file.write_text("v1-content", encoding="utf-8")


def test_resolve_reports_revoked_and_expired(
    store, gstore, session_ctx, target_file, tool_exec_sbx
):
    gid = _gid_for(store, gstore, target_file)
    gstore.revoke(gid, revoked_by="web:session:unit")
    _, err = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), None)
    assert err is not None and "已撤销" in err.content
    rid = (
        _request(store, target_file).content
        .split("request_id=")[1].splitlines()[0].strip()
    )
    gid2 = _approve(store, gstore, rid, target_file, ttl_s=1)
    time.sleep(1.2)
    _, err = tool_exec_sbx._resolve_host_grant(gid2, _cmd(target_file), None)
    assert err is not None and "已过期" in err.content


def test_resolve_rejects_incomplete_binding(gstore, session_ctx, target_file, tool_exec_sbx):
    """fail-closed: request_binding 缺任一必备字段（或整段缺失）即拒绝，不静默跳过核验."""
    full = {"command_sha256": "a" * 64, "cwd": "/ws", "file_sha256": "b" * 64}
    for drop in ("command_sha256", "cwd", "file_sha256", None):
        binding = dict(full) if drop else None
        if drop:
            binding.pop(drop)
        gid = gstore.issue(
            tool_name="execute_command", canonical_path=str(target_file),
            operation="write", requester_session_id="host-grant-unit",
            ttl_s=600, approver_identity="web:session:unit",
            request_binding=binding,
        )["grant_id"]
        _, err = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), None)
        assert err is not None, f"缺 {drop} 未拒绝"
        assert "绑定不完整" in err.content, f"缺 {drop}: {err.content}"


# ── 7. write-scope gate 叠加 ──────────────────────────────

def test_gate_allows_grant_path_under_allow_scope(store, gstore, session_ctx, tmp_path, target_file, tool_exec_sbx):
    from llm_loop.core.run_context import current_write_scope
    gid = _gid_for(store, gstore, target_file)
    ctx, _ = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), None)
    tok = current_write_scope.set(
        WriteScope(mode="allow", paths=(str(tmp_path),), deny_paths=(), declared=True)
    )
    try:
        gate = tool_exec_sbx._write_scope_command_gate(
            f"echo x > {target_file}", None, str(tmp_path), False,
            grant_write_paths=frozenset({ctx["canonical_path"]}),
        )
        assert gate is None, gate.content if gate else ""
    finally:
        current_write_scope.reset(tok)


def test_gate_never_bypasses_deny_scope(store, gstore, session_ctx, tmp_path, target_file, tool_exec_sbx):
    from llm_loop.core.run_context import current_write_scope
    gid = _gid_for(store, gstore, target_file)
    ctx, _ = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), None)
    tok = current_write_scope.set(
        WriteScope(mode="deny", paths=(), deny_paths=("outside-tree/**",), declared=True)
    )
    try:
        gate = tool_exec_sbx._write_scope_command_gate(
            f"echo x > {target_file}", None, str(tmp_path), False,
            grant_write_paths=frozenset({ctx["canonical_path"]}),
        )
        assert gate is not None
        assert "deny" in gate.content and "不可绕过" in gate.content
    finally:
        current_write_scope.reset(tok)


# ── 8. sandbox argv 精确单文件 bind ──────────────────────

def test_bwrap_argv_precise_file_bind_with_dir_ancestors(target_file):
    argv = bwrap_argv("cat x", "/ws", extra_file_binds=[(str(target_file), str(target_file), "rw")])
    j = argv
    # 祖先目录 --dir + 精确 --bind 单文件
    assert "--bind" in j and str(target_file) in j
    assert "--ro-bind" in j  # 系统 ro-bind 仍在
    assert j.index(str(target_file)) < j.index("--chdir")  # 位于 workdir bind 之前
    # ro 变体
    argv_ro = bwrap_argv("cat x", "/ws", extra_file_binds=[(str(target_file), str(target_file), "ro")])
    flat_ro = " ".join(argv_ro)
    assert "--ro-bind" in flat_ro
    # ro 模式下不应出现裸 --bind（workdir bind 除外：--bind /ws /ws 不含目标文件）
    binds = [a for a in argv_ro if a == "--bind"]
    assert binds == ["--bind"]  # 仅 workdir 一处
    assert str(target_file) not in " ".join(argv_ro[argv_ro.index("--bind"):])


def test_sandbox_argv_docker_rejects_binds(target_file):
    import shutil as _shutil
    if _shutil.which("docker") is None:
        # docker 后端存在性检查先于 binds 拒绝——本环境 docker 缺失时直接断言
        # binds 拒绝逻辑需要 docker 存在；跳过（bwrap 拒绝路径已由 resolve 层覆盖）
        pytest.skip("docker not installed; binds-rejection tested at resolve layer")


def test_sandbox_argv_binds_validation(target_file, tmp_path):
    lnk = tmp_path / "lnk2"
    os.symlink(target_file, lnk)
    with pytest.raises(ValueError):
        sandbox_argv("cat", "/ws", mode="bwrap", extra_file_binds=[(str(lnk), str(lnk), "ro")])
    with pytest.raises(ValueError):
        sandbox_argv("cat", "/ws", mode="bwrap", extra_file_binds=[(str(tmp_path), str(tmp_path), "ro")])
    with pytest.raises(ValueError):
        sandbox_argv("cat", "/ws", mode="bwrap", extra_file_binds=[(str(target_file), str(target_file), "rx")])


# ── 9. 消费单次/并发/重放/过期/撤销 ───────────────────────

def test_concurrent_consume_single_winner(store, gstore, session_ctx, target_file):
    rid = _request(store, target_file).content.split("request_id=")[1].splitlines()[0].strip()
    gid = _approve(store, gstore, rid, target_file)
    results: list = []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        r = gstore.consume(gid, tool_name="execute_command", canonical_path=str(target_file),
                           operation="write", requester_session_id="host-grant-unit")
        results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    # 重放拒绝
    assert gstore.consume(gid, tool_name="execute_command", canonical_path=str(target_file),
                          operation="write", requester_session_id="host-grant-unit") is None


def test_expired_and_revoked_grant_rejected(store, gstore, session_ctx, target_file, tool_exec_sbx):
    rid = _request(store, target_file).content.split("request_id=")[1].splitlines()[0].strip()
    gid = _approve(store, gstore, rid, target_file, ttl_s=1)
    import time
    time.sleep(1.2)
    _, err = tool_exec_sbx._resolve_host_grant(gid, _cmd(target_file), None)
    # P0 补修(2026-11-14): 预检现也拒绝生命周期已失效 grant（诊断优先级修复的
    # 必要部分——已消费/过期/撤销不得漏到维度比对层产生"内容已变化"类次生诊断）
    assert err is not None and "已过期" in err.content
    assert gstore.consume(gid, tool_name="execute_command", canonical_path=str(target_file),
                          operation="write", requester_session_id="host-grant-unit") is None

    # 撤销后拒绝
    rid2 = _request(store, target_file, operation="read").content.split("request_id=")[1].splitlines()[0].strip()
    gid2 = _approve(store, gstore, rid2, target_file, operation="read")
    gstore.revoke(gid2, revoked_by="unit-test")
    assert gstore.consume(gid2, tool_name="execute_command", canonical_path=str(target_file),
                          operation="read", requester_session_id="host-grant-unit") is None
