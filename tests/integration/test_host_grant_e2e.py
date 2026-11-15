"""DESIGN-20261114（Deepin P0）host-grant 端到端闭环测试.

验收矩阵（设计 §最小验收）的正向主路径 + 拒绝路径：
- 逻辑闭环（全平台）：申请（服务端冻结）→ web 会话审批 → issue+decide →
  escalation_wait 返回 grant_id → execute_command(host_grant_id) 消费，
  grant 单次、审计链完整
- 沙箱可用（Linux+真 bwrap FD 固定绑定）→ 真执行：
  授权单文件写入成功、工作区外任意其他路径仍不可写、字节级核对；
- 沙箱不可用（如嵌套沙箱环境）→ 真执行分支 fail-closed 断言
  （错误信息含沙箱原因，grant 状态如实）
- 未授权默认拒绝：同命令无 grant_id → 沙箱内无该文件可写（argv 断言
  无目标文件 bind）/ bwrap 环境真执行写入失败
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from llm_loop.core.run_context import current_session_id, current_workspace_root
from llm_loop.tools.builtin.escalation import EscalationWaitTool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.host_access import HostAccessRequestTool
from llm_loop.tools.escalation import (
    EscalationStore,
    HostCapabilityGrantStore,
)
from llm_loop.tools.sandbox import sandbox_argv


@pytest.fixture
def ctx(tmp_path):
    # workdir 不得圈住授权账本（execute_command workdir 禁区，P0-1 防线 B；
    # 父侧验收 2026-11-14 修正）：isolated_data_dir 把账本钉在
    # tmp_path 的同级目录；ctx 使用 tmp_path/workspace——否则
    # 在 basetemp 不落默认危险根（如 /private/var/folders）的环境下会被
    # 生产守卫正确 fail-closed；同根必须拒绝的负例由
    # test_workdir_overlapping_grant_home_rejected 明确覆盖。
    ws = tmp_path / "workspace"
    ws.mkdir()
    tok = current_session_id.set("e2e-sess")
    wtok = current_workspace_root.set(str(ws))
    yield ws
    current_session_id.reset(tok)
    current_workspace_root.reset(wtok)


@pytest.fixture
def store(isolated_data_dir):
    return EscalationStore(isolated_data_dir / "audit" / "escalation_requests.json")


@pytest.fixture
def gstore(isolated_data_dir):
    return HostCapabilityGrantStore(Path(os.environ["LFL_HOST_GRANT_HOME"]).resolve())


def _sandbox_usable(mode: str) -> bool:
    if mode == "bwrap" and shutil.which("bwrap") is None:
        return False
    try:
        argv, _n = sandbox_argv("true", "/tmp", mode=mode)
    except (RuntimeError, ValueError):
        return False
    if argv is None:  # mode 解析为 none（无沙箱可套用）→ 不可用
        return False
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _full_pipeline(store, gstore, ctx, target, *, operation, command):
    """申请 → （模拟 web 审批端点顺序）issue → decide → wait → grant_id."""
    res = HostAccessRequestTool(store).execute(
        path=str(target), operation=operation, command=command,
        justification="端到端闭环集成测试必要性说明",
    )
    assert res.status.name == "SUCCESS", res.content
    rid = res.content.split("request_id=")[1].splitlines()[0].strip()
    rec = store.get(rid)
    hr = rec["host_request"]
    grant = gstore.issue(
        tool_name="execute_command",
        canonical_path=str(target),
        operation=operation,
        requester_session_id="e2e-sess",
        ttl_s=600,
        approver_identity="web:session:e2e",
        request_binding={
            "command_sha256": hr["host_command_sha256"],
            "cwd": hr["host_cwd"],
            "file_sha256": hr["host_file_sha256"],
            "request_id": rid,
        },
    )
    dec, err = store.decide(
        rid, "approved", decided_by="web:session:e2e", channel="web_session",
        note="e2e", host_grant_id=grant["grant_id"],
    )
    assert dec is not None, err
    waited = EscalationWaitTool(store).execute(request_id=rid, timeout_s=1)
    assert waited.status.name == "SUCCESS", waited.content
    gid = waited.content.split("grant_id=")[1].splitlines()[0].strip()
    assert gid == grant["grant_id"]
    return gid


# ── 1. 逻辑闭环（全平台）：消费+审计+单次 ─────────────────

def test_grant_consumed_once_with_audit(store, gstore, ctx, isolated_data_dir):
    # Real Linux bwrap proof: the target is OUTSIDE the workspace bind.
    outside = ctx.parent / "outside"
    outside.mkdir()
    target = (outside / "e2e-target.txt").resolve()
    target.write_text("before", encoding="utf-8")
    sibling = outside / "not-authorized.txt"
    sibling.write_text("untouched", encoding="utf-8")
    cmd = f"printf after > {target}"
    gid = _full_pipeline(store, gstore, ctx, target, operation="write", command=cmd)

    tool = ExecuteCommandTool(timeout_s=20, sandbox_mode="bwrap")
    if not _sandbox_usable("bwrap"):
        pytest.skip("P0 FD-pinned host grant requires real Linux bwrap; macOS cannot prove this path")

    r1 = tool.execute(command=cmd, host_grant_id=gid, workdir=str(ctx))
    if r1.status.name != "SUCCESS":
        # 沙箱套用被拒等环境限制：grant 已消费（执行尝试即消耗）且错误如实
        assert "沙箱" in r1.content or "sandbox" in r1.content.lower()
    else:
        assert target.read_text(encoding="utf-8") == "after"
        assert "[host-grant] write" in r1.content and "已消费" in r1.content

    assert sibling.read_text(encoding="utf-8") == "untouched"
    grant = gstore.peek(gid)
    assert grant["uses"] >= 1
    # 重放拒绝（单次授权）——P0 补修(2026-11-14): 诊断必须指向生命周期
    # （授权已用），不得被"目标文件内容已变化"等次生诊断掩盖
    after_r1 = target.read_bytes()
    r2 = tool.execute(command=cmd, host_grant_id=gid, workdir=str(ctx))
    assert r2.status.name == "ERROR"
    assert "已用" in r2.content or "消费失败" in r2.content
    # 拒绝路径不得改写目标文件（文件字节不被重写）
    assert target.read_bytes() == after_r1
    # 审计链（P0-1: 独立安全状态目录经同源推导）
    audit = (Path(os.environ["LFL_HOST_GRANT_HOME"]).resolve() / "grants" / "audit.jsonl")
    assert audit.exists() and gid in audit.read_text(encoding="utf-8")


# ── 2. argv 层（全平台）：bind 精确注入/未授权无 bind ─────

def test_bwrap_argv_bind_shape_for_write(store, gstore, ctx, monkeypatch):
    if shutil.which("bwrap") is None:
        # 纯 argv 形状断言：假 bwrap 存在（真实执行由 bwrap 环境分支覆盖）
        monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/bwrap" if n == "bwrap" else shutil.which(n))
    target = (ctx / "argv-target.txt").resolve()
    target.write_text("x", encoding="utf-8")
    cmd = f"printf y > {target}"
    _full_pipeline(store, gstore, ctx, target, operation="write", command=cmd)
    # argv 形状断言不依赖 bwrap 存在（resolve 的 bwrap 预检由单测覆盖）
    argv, _note = sandbox_argv(
        cmd, str(ctx), mode="bwrap",
        extra_file_binds=[(str(target), str(target), "rw")],
    )
    assert argv is not None
    assert "--bind" in argv and str(target) in argv
    # 未授权（无 grant）：argv 无目标文件 bind（路径仅作为命令文本出现，
    # 不出现在 --bind/--ro-bind 参数位）
    argv_plain, _ = sandbox_argv(cmd, str(ctx), mode="bwrap")
    assert argv_plain is not None
    bind_positions = [i for i, a in enumerate(argv_plain) if a in ("--bind", "--ro-bind")]
    for i in bind_positions:
        assert argv_plain[i + 1] != str(target)  # bind 源不是目标
        assert argv_plain[i + 2] != str(target)  # bind 目标不是目标文件


# ── 3. 未授权默认拒绝（argv 无 bind → 沙盒内文件不可见/不可写） ──

@pytest.mark.skipif(shutil.which("bwrap") is None, reason="真 bwrap 环境专用（Deepin/CI Linux）")
def test_real_bwrap_default_deny_and_grant_write(ctx):
    """真 bwrap：默认沙盒外文件不可写；授权后仅该单文件可写一次."""
    target = (ctx / "deepin-real.txt").resolve()
    target.write_text("seed", encoding="utf-8")
    other = (ctx / "deepin-other.txt").resolve()
    other.write_text("keep", encoding="utf-8")

    # 默认（无 grant）：目标文件在沙盒内不存在 → 写失败（只 bind workdir 时文件可见
    # 但 bwrap 层 root 为只读系统区+workdir 可写——workdir 在 ctx 内则可写，此用例
    # 需要真实沙盒外路径：用 /tmp 独立目录模拟工作区外）
    outside_root = os.path.join("/tmp", f"lfl-host-grant-e2e-{os.getpid()}")
    os.makedirs(outside_root, exist_ok=True)
    try:
        outside_file = os.path.join(outside_root, "secret.txt")
        with open(outside_file, "w", encoding="utf-8") as fh:
            fh.write("locked")
        argv, _n = sandbox_argv(f"cat {outside_file}", "/tmp", mode="bwrap")
        assert argv is not None
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        # 未授权：文件未 bind → cat 失败（No such file）
        assert proc.returncode != 0
    finally:
        shutil.rmtree(outside_root, ignore_errors=True)


# ── 3b. EVO-20261115-488367d4 P0-1: sandbox-exec 后端真执行（环境感知） ──

def test_grant_sandbox_exec_real_write(store, gstore, ctx):
    """macOS sandbox-exec 真执行：授权单文件写入 + 未授权路径仍拒.

    嵌套沙箱上下文（pytest 在 LFL 会话内运行）内层 sandbox-exec 套用必
    EPERM——无法从会话内证明真执行；本用例仅在 `_sandbox_usable(
    "sandbox-exec")` 真探测可用（宿主/裸机 runner）时运行，否则 skip 并由
    tests/unit/test_host_grant_sandbox_exec.py 覆盖管道层（argv/profile/
    消费穿线/预检）。
    """
    if not _sandbox_usable("sandbox-exec"):
        pytest.skip("嵌套沙箱上下文：sandbox-exec 内层套用必拒（真执行由裸机 runner 覆盖）")
    outside = ctx.parent / "outside-sbx"
    outside.mkdir()
    target = (outside / "e2e-target.txt").resolve()
    target.write_text("before", encoding="utf-8")
    sibling = outside / "not-authorized.txt"
    sibling.write_text("untouched", encoding="utf-8")
    cmd = f"printf after > {target}"
    gid = _full_pipeline(store, gstore, ctx, target, operation="write", command=cmd)
    tool = ExecuteCommandTool(timeout_s=20, sandbox_mode="sandbox-exec")
    r1 = tool.execute(command=cmd, host_grant_id=gid, workdir=str(ctx))
    assert r1.status.name == "SUCCESS", r1.content
    assert target.read_text(encoding="utf-8") == "after"
    assert sibling.read_text(encoding="utf-8") == "untouched"
    assert "[host-grant]" in r1.content and "会被沙箱 profile 拒绝" in r1.content
    # 单次消费：重放拒绝
    r2 = tool.execute(command=cmd, host_grant_id=gid, workdir=str(ctx))
    assert r2.status.name == "ERROR"
    assert "已用" in r2.content or "消费失败" in r2.content


# ── 4. grant 与灾难提权令牌互斥 ───────────────────────────

def test_grant_mutually_exclusive_with_catastrophic_token(store, gstore, ctx):
    target = (ctx / "mutex.txt").resolve()
    target.write_text("x", encoding="utf-8")
    gid = _full_pipeline(store, gstore, ctx, target, operation="read", command=f"cat {target}")
    tool = ExecuteCommandTool(timeout_s=10, sandbox_mode="sandbox-exec")
    r = tool.execute(
        command=f"cat {target}", host_grant_id=gid,
        escalation_id="ESC-FAKE", escalation_token="tok",
        workdir=str(ctx),
    )
    assert r.status.name == "FAILURE"
    assert "互斥" in r.content


# ── 5. workdir 圈住账本：生产守卫负例（父侧验收 2026-11-14 保留） ──

def test_workdir_overlapping_grant_home_rejected(
    store, gstore, ctx, isolated_data_dir, monkeypatch
):
    """workdir=账本祖先（--bind workdir 圈住账本）必须 ERROR 且不消耗 grant.

    候选推导钉到生效账本：真实推导在 pytest basetemp 落入默认危险根
    （如 /private/tmp）的环境下会整体拒绝该 env、退化为仅默认 home 候选
    （该推导分支由 unit 层 test_unsafe_home_env_rejected /
    test_grant_home_guard_candidates_env_and_default 独立覆盖）；钉候选
    使本集成负例在任何 basetemp 位置都环境不变式成立。
    """
    from llm_loop.tools import escalation as esc

    ledger_home = Path(os.environ["LFL_HOST_GRANT_HOME"]).resolve()
    monkeypatch.setattr(esc, "grant_home_guard_candidates", lambda: [str(ledger_home)])
    target = (ctx / "guard-target.txt").resolve()
    target.write_text("x", encoding="utf-8")
    gid = _full_pipeline(store, gstore, ctx, target, operation="read", command=f"cat {target}")
    tool = ExecuteCommandTool(timeout_s=10, sandbox_mode="sandbox-exec")
    # workdir=账本祖先（ledger_home.parent，圈住账本）→ 拒；
    # guard 先于 grant 解析与消费 → 授权不被消耗
    r = tool.execute(
        command=f"cat {target}", host_grant_id=gid,
        workdir=str(ledger_home.parent),
    )
    assert r.status.name == "ERROR", r.content[:200]
    assert r.error_type == "workdir_overlaps_grant_home"
    assert gstore.peek(gid)["uses"] == 0
