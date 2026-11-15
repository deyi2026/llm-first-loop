"""sandbox-exec 后端 host-grant（EVO-20261115-488367d4 P0-1）单元覆盖。

证明目标（不 spawn 真沙箱——嵌套沙箱内 sandbox-exec 内层套用必 EPERM，
真执行证明由 tests/integration/test_host_grant_e2e.py 的环境感知分支覆盖）：
1. 前置预检：sandbox-exec 不可用 → 提前拒绝不消耗人工审批（fail-closed，
   语义与 bwrap 预检一致）；auto 解析非白名单后端 → 同样提前拒绝；
   auto 解析 sandbox-exec 且可用 → 通过。
2. argv/profile 构造：rw bind → sandbox-exec argv + profile 可写根含目标
   路径（deny file-write* 之外唯一放行）；banner note 含已知降级提示
   （P1-1/P2：ps=setuid exec 拒、launchctl list 空输出）。
3. 消费穿线：_apply_sandbox_policy seam 捕获——extra_file_binds 正确穿参、
   不走 FD 固定（sandbox-exec 无通道）、write note 为 sandbox-exec 语义
   （profile 拒绝非零退出，非 bwrap tmpfs 静默）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from llm_loop.core.run_context import current_session_id, current_workspace_root
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.host_access import HostAccessRequestTool
from llm_loop.tools.escalation import (
    EscalationStore,
    HostCapabilityGrantStore,
)
from llm_loop.tools.sandbox import sandbox_argv


@pytest.fixture
def store(isolated_data_dir):
    return EscalationStore(isolated_data_dir / "audit" / "escalation_requests.json")


@pytest.fixture
def gstore(isolated_data_dir):
    return HostCapabilityGrantStore(Path(os.environ["LFL_HOST_GRANT_HOME"]).resolve())


@pytest.fixture
def session_ctx(tmp_path):
    tok = current_session_id.set("sbx-exec-unit")
    wtok = current_workspace_root.set(str(tmp_path))
    yield tmp_path
    current_session_id.reset(tok)
    current_workspace_root.reset(wtok)


@pytest.fixture
def target_file(tmp_path):
    outside = tmp_path / "outside-tree"
    outside.mkdir()
    f = (outside / "note.txt").resolve()
    f.write_text("v1-content", encoding="utf-8")
    return f


def _gid_for(store, gstore, target, *, operation="write"):
    res = HostAccessRequestTool(store).execute(
        path=str(target), operation=operation,
        command=f"cat {target}",
        justification="sandbox-exec 后端单元测试必要性说明",
    )
    assert res.status.name == "SUCCESS", res.content
    rid = res.content.split("request_id=")[1].splitlines()[0].strip()
    rec = store.get(rid)
    hr = rec["host_request"]
    grant = gstore.issue(
        tool_name="execute_command",
        canonical_path=str(target),
        operation=operation,
        requester_session_id="sbx-exec-unit",
        ttl_s=600,
        approver_identity="web:session:unit",
        request_binding={
            "command_sha256": hr["host_command_sha256"],
            "cwd": hr["host_cwd"],
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


# ── 1. 前置预检（fail-closed，不消耗人工审批） ─────────────

def test_resolve_sandbox_exec_missing_fail_closed(store, gstore, session_ctx, target_file, monkeypatch):
    monkeypatch.setattr("llm_loop.tools.sandbox._probe_sandbox_exec", lambda: False)
    gid = _gid_for(store, gstore, target_file)
    tool = ExecuteCommandTool(timeout_s=10, sandbox_mode="sandbox-exec")
    _, err = tool._resolve_host_grant(gid, f"cat {target_file}", None)
    assert err is not None
    assert "sandbox-exec 不可用" in err.content
    assert "不消耗人工审批" in err.content


def test_resolve_auto_non_whitelisted_backend_fail_closed(store, gstore, session_ctx, target_file, monkeypatch):
    monkeypatch.setattr(
        "llm_loop.tools.sandbox.resolve_auto_backend",
        lambda: ("docker", ["bwrap 缺失", "sandbox-exec 缺失"]),
    )
    gid = _gid_for(store, gstore, target_file)
    tool = ExecuteCommandTool(timeout_s=10, sandbox_mode="auto")
    _, err = tool._resolve_host_grant(gid, f"cat {target_file}", None)
    assert err is not None
    assert "auto 后端解析为 docker" in err.content
    # 预检失败不消耗 grant
    assert gstore.peek(gid)["uses"] == 0


def test_resolve_auto_sandbox_exec_ok(store, gstore, session_ctx, target_file, monkeypatch):
    monkeypatch.setattr(
        "llm_loop.tools.sandbox.resolve_auto_backend",
        lambda: ("sandbox-exec", ["bwrap 缺失"]),
    )
    monkeypatch.setattr("llm_loop.tools.sandbox._probe_sandbox_exec", lambda: True)
    gid = _gid_for(store, gstore, target_file)
    tool = ExecuteCommandTool(timeout_s=10, sandbox_mode="auto")
    ctx, err = tool._resolve_host_grant(gid, f"cat {target_file}", None)
    assert err is None and ctx["canonical_path"] == str(target_file)


# ── 2. argv/profile 构造 + banner 降级提示 ────────────────

def test_sandbox_exec_argv_profile_contains_grant_root(target_file, tmp_path, monkeypatch):
    monkeypatch.setattr("llm_loop.tools.sandbox._probe_sandbox_exec", lambda: True)
    argv, note = sandbox_argv(
        f"cat {target_file}", str(tmp_path), mode="sandbox-exec",
        extra_file_binds=[(str(target_file), str(target_file), "rw")],
    )
    assert argv is not None
    assert argv[0] == "/usr/bin/sandbox-exec"
    if "-p" in argv:
        profile = argv[argv.index("-p") + 1]
    else:
        profile = Path(argv[argv.index("-f") + 1]).read_text(encoding="utf-8")
    # 授权文件作为唯一新增可写根出现在 profile
    assert str(target_file) in profile
    assert "file-write" in profile
    # 未授权（无 extra_file_binds）：profile 不含目标路径
    argv_plain, _ = sandbox_argv(f"cat {target_file}", str(tmp_path), mode="sandbox-exec")
    if "-p" in argv_plain:
        prof_plain = argv_plain[argv_plain.index("-p") + 1]
    else:
        prof_plain = Path(argv_plain[argv_plain.index("-f") + 1]).read_text(encoding="utf-8")
    assert str(target_file) not in prof_plain
    # P1-1/P2：banner 含已知静默降级提示
    assert "已知降级" in note and "ps" in note and "launchctl" in note


# ── 3. 消费穿线（_apply_sandbox_policy seam，不 spawn 沙箱） ──

def test_consume_threading_and_write_note_for_sandbox_exec(
    store, gstore, session_ctx, target_file, monkeypatch
):
    monkeypatch.setattr("llm_loop.tools.sandbox._probe_sandbox_exec", lambda: True)
    captured: dict = {}

    def fake_apply(self, spec, workdir, wt_note_in, extra_file_binds):
        captured["extra_file_binds"] = extra_file_binds
        return (["/usr/bin/true"], "（sandbox-exec stub note）")

    monkeypatch.setattr(ExecuteCommandTool, "_apply_sandbox_policy", fake_apply)

    cmd = f"cat {target_file}"
    gid = _gid_for(store, gstore, target_file)
    tool = ExecuteCommandTool(timeout_s=10, sandbox_mode="sandbox-exec")
    r1 = tool.execute(command=cmd, host_grant_id=gid, workdir=str(session_ctx))
    assert r1.status.name == "SUCCESS", r1.content
    # 穿参：授权单文件 rw bind 到达沙箱策略层
    assert captured["extra_file_binds"] == [(str(target_file), str(target_file), "rw")]
    # write note 为 sandbox-exec 语义（profile 拒绝，非 tmpfs 静默）
    assert "[host-grant]" in r1.content
    assert "会被沙箱 profile 拒绝" in r1.content
    assert "tmpfs" not in r1.content
    # grant 单次：重放拒绝
    assert gstore.peek(gid)["uses"] >= 1
    r2 = tool.execute(command=cmd, host_grant_id=gid, workdir=str(session_ctx))
    assert r2.status.name == "ERROR"
    assert "已用" in r2.content or "消费失败" in r2.content


def test_consume_verify_rejects_sha_drift(store, gstore, session_ctx, target_file, monkeypatch):
    """审批后目标文件被改写（sha 漂移）→ spawn 前复验拒绝，不产写效果."""
    monkeypatch.setattr("llm_loop.tools.sandbox._probe_sandbox_exec", lambda: True)

    def fake_apply(self, spec, workdir, wt_note_in, extra_file_binds):
        raise AssertionError("sha 漂移应在复验层被拒，不应到达沙箱策略层")

    monkeypatch.setattr(ExecuteCommandTool, "_apply_sandbox_policy", fake_apply)
    gid = _gid_for(store, gstore, target_file)
    target_file.write_text("tampered", encoding="utf-8")
    try:
        tool = ExecuteCommandTool(timeout_s=10, sandbox_mode="sandbox-exec")
        r = tool.execute(command=f"cat {target_file}", host_grant_id=gid, workdir=str(session_ctx))
        assert r.status.name == "ERROR"
        # resolve 层（file_sha256 绑定）或复验层拒绝——任一均可，但必须拒绝
        assert "内容已变化" in r.content or "固定失败" in r.content
    finally:
        target_file.write_text("v1-content", encoding="utf-8")


# ── 4. read grant 合同（审查 rev1 P1：ro 不得新增可写根） ──

def test_read_grant_adds_no_writable_root(target_file, tmp_path, monkeypatch):
    """ro bind 在 sandbox-exec 是 no-op：profile 不得出现授权路径的 file-write 放行.

    sandbox_argv 仅把 access=="rw" 的 bind 追加进可写根；read-only 审批若
    意外流入可写根追加，等于把 read 合同突破为 write——本用例钉死该边界。
    """
    monkeypatch.setattr("llm_loop.tools.sandbox._probe_sandbox_exec", lambda: True)

    def _profile(argv):
        if "-p" in argv:
            return argv[argv.index("-p") + 1]
        return Path(argv[argv.index("-f") + 1]).read_text(encoding="utf-8")

    # ro bind 与完全无 bind 的 profile 一致：授权路径不出现
    for binds in ([(str(target_file), str(target_file), "ro")], None):
        argv, _ = sandbox_argv(
            f"cat {target_file}", str(tmp_path), mode="sandbox-exec",
            extra_file_binds=binds,
        )
        profile = _profile(argv)
        assert str(target_file) not in profile, binds
    # 对照：rw bind 才进入可写根
    argv_rw, _ = sandbox_argv(
        f"cat {target_file}", str(tmp_path), mode="sandbox-exec",
        extra_file_binds=[(str(target_file), str(target_file), "rw")],
    )
    assert str(target_file) in _profile(argv_rw)


def test_consume_read_grant_threads_ro_and_has_no_write_note(store, gstore, session_ctx, target_file, monkeypatch):
    """read grant 消费穿线：access=ro 到达策略层，且不携带写语义回执注."""
    monkeypatch.setattr("llm_loop.tools.sandbox._probe_sandbox_exec", lambda: True)
    captured: dict = {}

    def fake_apply(self, spec, workdir, wt_note_in, extra_file_binds):
        captured["extra_file_binds"] = extra_file_binds
        return (["/usr/bin/true"], "（sandbox-exec stub note）")

    monkeypatch.setattr(ExecuteCommandTool, "_apply_sandbox_policy", fake_apply)
    cmd = f"cat {target_file}"
    gid = _gid_for(store, gstore, target_file, operation="read")
    tool = ExecuteCommandTool(timeout_s=10, sandbox_mode="sandbox-exec")
    r1 = tool.execute(command=cmd, host_grant_id=gid, workdir=str(session_ctx))
    assert r1.status.name == "SUCCESS", r1.content
    assert captured["extra_file_binds"] == [(str(target_file), str(target_file), "ro")]
    assert "[host-grant] read" in r1.content
    assert "会被沙箱 profile 拒绝" not in r1.content
    assert gstore.peek(gid)["uses"] >= 1
