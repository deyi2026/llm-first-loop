"""沙箱后端 auto 解析 / sandbox-exec / note 如实标注测试（P2-1、S2-6，2026-10-25）.

覆盖：
- auto 解析矩阵（monkeypatch shutil.which / subprocess.run / sys.platform）
- EXEC_SANDBOX_STRICT=1 且全无后端 → RuntimeError（fail-closed）
- sandbox-exec profile 生成：默认可写根 + EXEC_SANDBOX_MACOS_WRITABLE 追加 + S 表达式转义
- darwin 真实执行：工作区可写、~/Documents 写被拒
- note 文案与后端一一对应（S2-6：不得夸大隔离范围；none 不加"已隔离"措辞）
- sandbox-exec 可用性实跑探测（2026-11-09：套用被拒/execvp 失败/异常三路分类）
- worktree 隔离语义如实标注（S2-6：isolation=true 非系统沙箱从句）
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.tools import sandbox as sbx
from tests import env_channel

BWRAP_NOTE = "（已启用 bwrap 沙箱：只读系统目录/工作区可写/未隔离网络）"
DOCKER_NOTE = "（已启用 docker 沙箱：断网/只读 rootfs/工作区可写）"
SBX_NOTE = "（已启用 macOS sandbox-exec 沙箱：仅允许写工作区与缓存目录/未隔离网络）"


@pytest.fixture(autouse=True)
def _fresh_auto_cache():
    sbx.reset_auto_cache()
    yield
    sbx.reset_auto_cache()


def _patch_backends(
    monkeypatch,
    *,
    platform: str = "linux",
    which: dict[str, str] | None = None,
    docker_ok: bool | None = None,
    sandbox_exec_ok: bool | None = None,
) -> None:
    """矩阵测试补丁：which 映射 + docker info 探测 + 平台 + sandbox-exec 可执行性."""
    monkeypatch.setattr(sys, "platform", platform)
    table = dict(which or {})
    monkeypatch.setattr(sbx.shutil, "which", lambda name: table.get(name))

    def fake_run(cmd, **kwargs):
        assert list(cmd)[:2] == ["docker", "info"]
        return SimpleNamespace(returncode=0 if docker_ok else 1)

    if docker_ok is None:
        monkeypatch.setattr(
            sbx.subprocess,
            "run",
            lambda cmd, **kw: pytest.fail("docker 探测不应被触达（CLI 缺失时短路）"),
        )
    else:
        monkeypatch.setattr(sbx.subprocess, "run", fake_run)
    if sandbox_exec_ok is not None:
        monkeypatch.setattr(
            sbx.os.path, "isfile", lambda p: bool(sandbox_exec_ok) if p == sbx._SANDBOX_EXEC else False
        )
        monkeypatch.setattr(sbx.os, "access", lambda p, m: bool(sandbox_exec_ok))
        # 2026-11-09：可用性改由"实跑套用"判定；矩阵测试不真起 sandbox-exec，
        # 这里直接给出探测结论，探测本身的分类逻辑由专门的用例覆盖。
        monkeypatch.setattr(
            sbx,
            "_sandbox_exec_applicable",
            lambda ok=sandbox_exec_ok: (
                (True, f"{sbx._SANDBOX_EXEC} 可套用 profile（实跑探测通过）", "")
                if ok
                else (False, f"{sbx._SANDBOX_EXEC} 不存在或不可执行", "")
            ),
        )
    monkeypatch.delenv("EXEC_SANDBOX_STRICT", raising=False)


# ---- auto 解析矩阵 ----


def test_auto_linux_prefers_bwrap(monkeypatch):
    _patch_backends(
        monkeypatch,
        platform="linux",
        which={"bwrap": "/usr/bin/bwrap", "docker": "/usr/bin/docker"},
        docker_ok=True,
    )
    backend, _ = sbx.resolve_auto_backend()
    assert backend == "bwrap"


def test_auto_no_bwrap_uses_docker(monkeypatch):
    _patch_backends(
        monkeypatch, platform="linux", which={"docker": "/usr/local/bin/docker"}, docker_ok=True
    )
    backend, reasons = sbx.resolve_auto_backend()
    assert backend == "docker"


def test_auto_darwin_no_docker_uses_sandbox_exec(monkeypatch):
    _patch_backends(monkeypatch, platform="darwin", which={}, sandbox_exec_ok=True)
    backend, _ = sbx.resolve_auto_backend()
    assert backend == "sandbox-exec"


def test_auto_all_missing_resolves_none_and_warns(monkeypatch, caplog):
    _patch_backends(monkeypatch, platform="linux", which={})
    with caplog.at_level(logging.WARNING, logger="llm_loop.tools.sandbox"):
        backend, reasons = sbx.resolve_auto_backend()
        sbx.resolve_auto_backend()  # 缓存命中：不得重复告警
    assert backend == "none"
    assert len(reasons) == 3
    warnings = [r for r in caplog.records if "未启用沙箱" in r.getMessage()]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert all(k in msg for k in ("bwrap", "docker", "sandbox-exec"))


def test_docker_daemon_probe_cached_in_process(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sbx.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sbx.shutil, "which", lambda n: "/usr/bin/docker" if n == "docker" else None
    )
    assert sbx._probe_docker() is True
    assert sbx._probe_docker() is True
    assert len(calls) == 1  # docker info 只探测一次


# ---- strict 模式 ----


def test_auto_none_strict_fail_closed(monkeypatch):
    _patch_backends(monkeypatch, platform="linux", which={})
    monkeypatch.setenv("EXEC_SANDBOX_STRICT", "1")
    with pytest.raises(RuntimeError, match="fail-closed"):
        sbx.sandbox_argv("echo hi", "/w", mode="auto")


def test_auto_none_non_strict_falls_back_to_plain_shell(monkeypatch):
    _patch_backends(monkeypatch, platform="linux", which={})
    argv, note = sbx.sandbox_argv("echo hi", "/w", mode="auto")
    assert argv is None and note == ""


def test_strict_does_not_bind_explicit_none(monkeypatch):
    _patch_backends(monkeypatch, platform="linux", which={})
    monkeypatch.setenv("EXEC_SANDBOX_STRICT", "1")
    argv, note = sbx.sandbox_argv("echo hi", "/w", mode="none")
    assert argv is None and note == ""  # 显式 none 是明确意图，strict 只约束 auto


# ---- sandbox_mode 归一化 ----


def test_sandbox_mode_accepts_auto_and_sandbox_exec():
    assert sbx.sandbox_mode("auto") == "auto"
    assert sbx.sandbox_mode("AUTO") == "auto"
    assert sbx.sandbox_mode("sandbox-exec") == "sandbox-exec"
    assert sbx.sandbox_mode("bwrap") == "bwrap"
    assert sbx.sandbox_mode("docker") == "docker"
    assert sbx.sandbox_mode("none") == "none"
    assert sbx.sandbox_mode() == "none"


def test_sandbox_mode_invalid_falls_back_none_with_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="llm_loop.tools.sandbox"):
        assert sbx.sandbox_mode("kvm") == "none"
    assert any("非法" in r.getMessage() for r in caplog.records)


# ---- note 文案与后端一一对应（S2-6）----


def test_notes_match_backend_semantics(monkeypatch):
    # bwrap
    monkeypatch.setattr(
        sbx.shutil, "which", lambda n: "/usr/bin/bwrap" if n == "bwrap" else None
    )
    argv, note = sbx.sandbox_argv("echo hi", "/w", mode="bwrap")
    assert argv is not None and argv[0] == "bwrap" and note == BWRAP_NOTE
    # docker
    monkeypatch.setattr(
        sbx.shutil, "which", lambda n: "/usr/bin/docker" if n == "docker" else None
    )
    argv, note = sbx.sandbox_argv("echo hi", "/w", mode="docker")
    assert argv is not None and argv[0] == "docker" and note == DOCKER_NOTE
    # sandbox-exec
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sbx.os.path, "isfile", lambda p: p == sbx._SANDBOX_EXEC)
    monkeypatch.setattr(sbx.os, "access", lambda p, m: True)
    monkeypatch.setattr(
        sbx,
        "_sandbox_exec_applicable",
        lambda: (True, f"{sbx._SANDBOX_EXEC} 可套用 profile（实跑探测通过）", ""),
    )
    argv, note = sbx.sandbox_argv("echo hi", "/w", mode="sandbox-exec")
    assert argv is not None and argv[0] == "/usr/bin/sandbox-exec" and note == SBX_NOTE
    # none：不加任何"已隔离"措辞
    argv, note = sbx.sandbox_argv("echo hi", "/w", mode="none")
    assert argv is None and note == ""


def test_auto_dispatch_note_follows_resolved_backend(monkeypatch):
    _patch_backends(monkeypatch, platform="darwin", which={}, sandbox_exec_ok=True)
    argv, note = sbx.sandbox_argv("echo hi", "/w", mode="auto")
    assert argv is not None and argv[0] == "/usr/bin/sandbox-exec" and note == SBX_NOTE

    sbx.reset_auto_cache()
    _patch_backends(
        monkeypatch, platform="linux", which={"docker": "/usr/bin/docker"}, docker_ok=True
    )
    argv, note = sbx.sandbox_argv("echo hi", "/w", mode="auto")
    assert argv is not None and argv[0] == "docker" and note == DOCKER_NOTE


def test_sandbox_exec_missing_on_linux_fail_closed(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="fail-closed"):
        sbx.sandbox_argv("echo hi", "/w", mode="sandbox-exec")


# ---- sandbox-exec 实跑探测（2026-11-09：二进制存在 ≠ 可套用）----


def _stub_probe_process(monkeypatch, *, returncode: int, stderr: str = "", exc=None) -> list[list[str]]:
    """伪 sandbox-exec 探测：记录 argv，按需返回退出码/stderr/异常；宿主二进制视为存在."""
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if exc is not None:
            raise exc
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        sbx.os.path, "isfile", lambda p: p in {sbx._SANDBOX_EXEC, "/usr/bin/true"}
    )
    monkeypatch.setattr(sbx.os, "access", lambda p, m: True)
    monkeypatch.setattr(sbx.subprocess, "run", fake_run)
    return calls


def test_probe_apply_refused_is_not_available(monkeypatch):
    calls = _stub_probe_process(
        monkeypatch,
        returncode=71,
        stderr="sandbox-exec: sandbox_apply: Operation not permitted\n",
    )
    assert sbx._probe_sandbox_exec() is False
    assert "套用被拒" in sbx._sandbox_exec_detail
    assert "套用被拒" in sbx._sandbox_exec_nested_note()
    # 探测体必须是确定存在的可执行文件：不得回落到历史 /bin/true（本机不存在）
    assert calls and "/bin/true" not in calls[0]
    assert calls[0][3] == "/usr/bin/true"


def test_probe_available_only_on_real_apply(monkeypatch):
    calls = _stub_probe_process(monkeypatch, returncode=0)
    assert sbx._probe_sandbox_exec() is True
    assert "实跑探测通过" in sbx._sandbox_exec_detail
    assert sbx._sandbox_exec_nested_note() == ""
    assert sbx._probe_sandbox_exec() is True
    assert len(calls) == 1  # 进程内缓存：只实跑一次


def test_probe_execvp_failure_not_misread_as_nested(monkeypatch):
    _stub_probe_process(
        monkeypatch,
        returncode=71,
        stderr=(
            "sandbox-exec: execvp() of '/usr/bin/true' failed: "
            "No such file or directory\n"
        ),
    )
    assert sbx._probe_sandbox_exec() is False
    assert "套用被拒" not in sbx._sandbox_exec_detail
    assert sbx._sandbox_exec_nested_note() == ""


def test_probe_exception_unavailable_and_not_nested(monkeypatch):
    _stub_probe_process(
        monkeypatch, returncode=0, exc=PermissionError(1, "Operation not permitted")
    )
    assert sbx._probe_sandbox_exec() is False
    assert "探测无法执行" in sbx._sandbox_exec_detail
    assert sbx._sandbox_exec_nested_note() == ""


def test_auto_nested_degrade_note_is_honest(monkeypatch):
    _stub_probe_process(
        monkeypatch,
        returncode=71,
        stderr="sandbox-exec: sandbox_apply: Operation not permitted\n",
    )
    monkeypatch.setattr(sbx.shutil, "which", lambda name: None)
    backend, reasons = sbx.resolve_auto_backend()
    assert backend == "none"
    assert any("套用被拒" in r for r in reasons)

    argv, note = sbx.sandbox_argv("echo hi", "/w", mode="auto")
    assert argv is None
    assert "未套内层沙箱" in note
    assert "已隔离" not in note


def test_explicit_sandbox_exec_nested_fail_closed(monkeypatch):
    _stub_probe_process(
        monkeypatch,
        returncode=71,
        stderr="sandbox-exec: sandbox_apply: Operation not permitted\n",
    )
    with pytest.raises(RuntimeError, match="套用被拒"):
        sbx.sandbox_argv("echo hi", "/w", mode="sandbox-exec")


def test_reset_auto_cache_clears_apply_probe(monkeypatch):
    calls = _stub_probe_process(monkeypatch, returncode=0)
    assert sbx._probe_sandbox_exec() is True
    sbx.reset_auto_cache()
    assert sbx._probe_sandbox_exec() is True
    assert len(calls) == 2


@pytest.mark.skipif(sys.platform != "darwin", reason="需要 macOS sandbox-exec")
def test_live_probe_matches_real_apply():
    """双向实测（可用侧）：探测结论必须与真实套用结果一致，且真实主机解析到 sandbox-exec."""
    sbx.reset_auto_cache()
    proc = subprocess.run(
        sbx._sandbox_exec_probe_argv(), capture_output=True, text=True, timeout=30
    )
    applicable = sbx._probe_sandbox_exec()
    assert applicable is (proc.returncode == 0)
    if applicable:
        backend, _ = sbx.resolve_auto_backend()
        assert backend == "sandbox-exec"


# ---- sandbox-exec profile 生成与转义 ----


def test_profile_contains_workdir_and_cache_roots(tmp_path):
    workdir = str(tmp_path / "ws")
    roots = sbx.macos_writable_roots(workdir)
    home = os.path.expanduser("~")
    for expected in (
        workdir,
        "/tmp",
        "/private/tmp",
        "/dev",
        os.path.join(home, ".cache"),
        os.path.join(home, "Library", "Caches"),
        os.path.join(home, ".npm"),
    ):
        assert os.path.abspath(expected) in roots
    profile = sbx.sandbox_exec_profile(roots)
    assert profile.startswith("(version 1)(allow default)(deny file-write*)")
    assert f'(allow file-write* (subpath "{os.path.abspath(workdir)}"))' in profile


def test_profile_env_extra_roots(monkeypatch, tmp_path):
    monkeypatch.setenv("EXEC_SANDBOX_MACOS_WRITABLE", "/opt/a" + os.pathsep + "/opt/b c")
    roots = sbx.macos_writable_roots(str(tmp_path))
    assert "/opt/a" in roots
    assert "/opt/b c" in roots


def test_profile_escapes_quotes_and_backslashes():
    profile = sbx.sandbox_exec_profile(['/tmp/ws "q"', "/tmp/back\\slash"])
    assert '(subpath "/tmp/ws \\"q\\"")' in profile
    assert '(subpath "/tmp/back\\\\slash")' in profile


def test_sandbox_exec_argv_shape(tmp_path):
    argv = sbx.sandbox_exec_argv("echo hi", str(tmp_path))
    assert argv[0] == "/usr/bin/sandbox-exec"
    assert argv[1] == "-p"
    assert argv[3:] == ["/bin/bash", "-lc", "echo hi"]
    assert "(deny file-write*)" in argv[2]
    assert f'(subpath "{os.path.abspath(str(tmp_path))}")' in argv[2]


# ---- darwin 真实执行：写域约束 ----


@pytest.mark.skipif(sys.platform != "darwin", reason="需要 macOS sandbox-exec 真实写域")
@pytest.mark.skipif(
    env_channel.nested_sandbox_exec(),
    reason="环境受限：测试自起 sandbox-exec 与工具层沙箱嵌套——sandbox_apply Operation not permitted【RED-08】",
)
def test_sandbox_exec_real_write_domain(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ok_target = ws / "sb_ok.txt"
    argv = sbx.sandbox_exec_argv(f"echo x > {shlex.quote(str(ok_target))}", str(ws))
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert ok_target.read_text().strip() == "x"

    denied = Path.home() / "Documents" / f"lfl_sb_probe_{os.getpid()}.txt"
    argv2 = sbx.sandbox_exec_argv(f"echo x > {shlex.quote(str(denied))}", str(ws))
    proc2 = subprocess.run(argv2, capture_output=True, text=True, timeout=60)
    assert proc2.returncode != 0, "写 ~/Documents 应被 sandbox-exec 拒绝"
    assert not denied.exists()
    denied.unlink(missing_ok=True)


# ---- worktree 隔离语义如实标注（S2-6）----


def test_worktree_semantics_labeled_non_system_sandbox(monkeypatch):
    from llm_loop.tools.builtin import execute_command as ec

    desc = ec.ExecuteCommandTool.parameters["properties"]["isolation"]["description"]
    assert "（worktree 隔离，非系统沙箱）" in desc

    lease = SimpleNamespace(parent_root="/w", path="/w/.worktrees/x")
    monkeypatch.setattr(ec, "release_worktree", lambda root, path: object())
    monkeypatch.setattr(ec, "format_release_note", lambda report, path: "[worktree] 干净树已删除")
    assert "（worktree 隔离，非系统沙箱）" in ec._release_cmd_worktree_note(lease)

    def boom(root, path):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ec, "release_worktree", boom)
    err_note = ec._release_cmd_worktree_note(lease)
    assert "（worktree 隔离，非系统沙箱）" in err_note
    assert "释放异常" in err_note
