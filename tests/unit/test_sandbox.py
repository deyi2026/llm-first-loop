"""bash 沙箱后端测试（P3-3：EXEC_SANDBOX=bwrap|none）.

- 未启用 → 走既有 shell=True 路径（零回归）
- bwrap 启用且可用 → argv 含 bwrap 前缀（只读系统目录/独立命名空间/工作区可写），
  shell=False；回执如实标注"已启用 bwrap 沙箱"
- bwrap 启用但缺失 → fail-closed ERROR（命令不执行）
"""

from __future__ import annotations

from unittest import mock

import pytest

from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.registry import ToolResultStatus
from llm_loop.tools.sandbox import bwrap_argv, sandbox_argv, sandbox_mode


def test_sandbox_mode_default_none():
    assert sandbox_mode() == "none"


def test_bwrap_argv_structure():
    argv = bwrap_argv("echo hi", "/tmp/work")
    assert argv[0] == "bwrap"
    assert "--unshare-pid" in argv and "--unshare-uts" in argv and "--unshare-ipc" in argv
    assert "--ro-bind" in argv and "/usr" in argv and "/etc" in argv
    assert "--tmpfs" in argv and "/tmp" in argv
    assert "--bind" in argv and "/tmp/work" in argv
    assert argv[-3:] == ["/bin/sh", "-c", "echo hi"]


def test_sandbox_argv_disabled():
    argv, note = sandbox_argv("cmd", ".", mode="none")
    assert argv is None and note == ""


def test_sandbox_argv_bwrap_ok(monkeypatch):
    with mock.patch("llm_loop.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap"):
        argv, note = sandbox_argv("echo hi", "/w", mode="bwrap")
    assert argv is not None and argv[0] == "bwrap"
    assert note == "（已启用 bwrap 沙箱：只读系统目录/工作区可写/未隔离网络）"


def test_sandbox_argv_bwrap_missing_fail_closed(monkeypatch):
    with (
        mock.patch("llm_loop.tools.sandbox.shutil.which", return_value=None),
        pytest.raises(RuntimeError) as ei,
    ):
        sandbox_argv("echo hi", "/w", mode="bwrap")
    assert "fail-closed" in str(ei.value)
    assert "bwrap" in str(ei.value)


def test_execute_bwrap_uses_argv_and_marks_receipt(monkeypatch, tmp_path):
    """启用 bwrap：Popen 收 argv（shell=False），回执含沙箱标注."""
    with (
        mock.patch("llm_loop.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap"),
        mock.patch("subprocess.Popen") as popen,
    ):
        fake = mock.MagicMock()
        fake.communicate.return_value = ("输出内容", "")
        fake.returncode = 0
        popen.return_value = fake
        tool = ExecuteCommandTool(sandbox_mode="bwrap")
        r = tool.execute(command="echo hi", workdir=str(tmp_path))
    assert r.status == ToolResultStatus.SUCCESS
    assert "已启用 bwrap 沙箱" in r.content
    kwargs = popen.call_args
    assert kwargs.kwargs["shell"] is False
    argv = kwargs.args[0]
    assert argv[0] == "bwrap" and "/bin/sh" in argv and "-c" in argv


def test_execute_bwrap_missing_fail_closed(monkeypatch, tmp_path):
    """显式 bwrap 而缺失：命令不执行，ERROR 如实（fail-closed）."""
    with (
        mock.patch("llm_loop.tools.sandbox.shutil.which", return_value=None),
        mock.patch("subprocess.Popen") as popen,
    ):
        tool = ExecuteCommandTool(sandbox_mode="bwrap")
        r = tool.execute(command="echo hi", workdir=str(tmp_path))
    assert r.status == ToolResultStatus.ERROR
    assert "沙箱不可用" in r.content
    popen.assert_not_called()


def test_execute_default_none_zero_regression(monkeypatch, tmp_path):
    """未启用：shell=True 路径不变（零回归）."""
    with mock.patch("subprocess.Popen") as popen:
        fake = mock.MagicMock()
        fake.communicate.return_value = ("ok", "")
        fake.returncode = 0
        popen.return_value = fake
        tool = ExecuteCommandTool()
        r = tool.execute(command="echo hi", workdir=str(tmp_path))
    assert r.status == ToolResultStatus.SUCCESS
    assert popen.call_args.kwargs["shell"] is True
    assert "已启用 bwrap 沙箱" not in r.content


# ---- docker 后端（2026-09-12）----

def test_sandbox_mode_docker():
    assert sandbox_mode("docker") == "docker"


def test_docker_argv_structure():
    from llm_loop.tools.sandbox import docker_argv
    argv = docker_argv("echo hi", "/tmp/w")
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in argv
    assert "--read-only" in argv
    assert "--cap-drop" in argv and "ALL" in argv
    assert "--tmpfs" in argv and "/tmp:rw,size=64m" in argv
    assert "--volume" in argv and "/tmp/w:/tmp/w:rw" in argv
    assert argv[-3:] == ["sh", "-c", "echo hi"]


def test_docker_argv_explicit_image():
    from llm_loop.tools.sandbox import docker_argv
    argv = docker_argv("true", "/w", image="alpine:3.20")
    assert "alpine:3.20" in argv


def test_sandbox_argv_docker_ok(monkeypatch):
    with mock.patch("llm_loop.tools.sandbox.shutil.which", return_value="/usr/local/bin/docker"):
        argv, note = sandbox_argv("echo hi", "/w", mode="docker")
    assert argv is not None and argv[0] == "docker"
    assert "docker" in note


def test_sandbox_argv_docker_missing_fail_closed(monkeypatch):
    with (
        mock.patch("llm_loop.tools.sandbox.shutil.which", return_value=None),
        pytest.raises(RuntimeError) as ei,
    ):
        sandbox_argv("echo hi", "/w", mode="docker")
    assert "fail-closed" in str(ei.value) and "docker" in str(ei.value)


def test_sandbox_argv_workdir_made_absolute(monkeypatch):
    import os as _os
    with mock.patch("llm_loop.tools.sandbox.shutil.which", return_value="/usr/local/bin/docker"):
        argv, _ = sandbox_argv("true", "rel/dir", mode="docker")
    vol_i = argv.index("--volume") + 1
    assert _os.path.isabs(argv[vol_i].split(":")[0])


# ---- auto 解析平台顺序（P1-1，Rule28 修复轮：darwin 上 sandbox-exec 优先）----

import logging  # noqa: E402
import sys  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from llm_loop.tools import sandbox as sbx  # noqa: E402


@pytest.fixture()
def _fresh_auto_cache():
    """auto 解析/docker 探测缓存逐用例隔离（生产进程只解析一次）。"""
    sbx.reset_auto_cache()
    yield
    sbx.reset_auto_cache()


def _patch_platform_backends(
    monkeypatch,
    *,
    platform: str,
    bwrap: bool = False,
    docker_ok: bool | None = None,
    sandbox_exec_ok: bool | None = None,
) -> None:
    """monkeypatch sys.platform + bwrap/docker/sandbox-exec 三探测."""
    monkeypatch.setattr(sys, "platform", platform)
    table = {"bwrap": "/usr/bin/bwrap"} if bwrap else {}
    if docker_ok is not None:
        table["docker"] = "/usr/local/bin/docker"
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
            sbx.os.path,
            "isfile",
            lambda p: bool(sandbox_exec_ok) if p == sbx._SANDBOX_EXEC else False,
        )
        monkeypatch.setattr(sbx.os, "access", lambda p, m: bool(sandbox_exec_ok))
    monkeypatch.delenv("EXEC_SANDBOX_STRICT", raising=False)


def test_auto_darwin_prefers_sandbox_exec_over_docker(monkeypatch, _fresh_auto_cache):
    """P1-1：darwin + 两者可用 → 选 sandbox-exec（不再被 docker 抢走）。"""
    _patch_platform_backends(
        monkeypatch,
        platform="darwin",
        docker_ok=True,
        sandbox_exec_ok=True,
    )
    backend, _ = sbx.resolve_auto_backend()
    assert backend == "sandbox-exec"


def test_auto_darwin_docker_fallback_warns(monkeypatch, _fresh_auto_cache, caplog):
    """P1-1：darwin + sandbox-exec 不可用 + docker 可用 → 落 docker 且打 warning。"""
    _patch_platform_backends(monkeypatch, platform="darwin", docker_ok=True, sandbox_exec_ok=False)
    with caplog.at_level(logging.WARNING, logger="llm_loop.tools.sandbox"):
        backend, _ = sbx.resolve_auto_backend()
    assert backend == "docker"
    hits = [
        r
        for r in caplog.records
        if "docker on darwin runs linux images" in r.getMessage()
    ]
    assert len(hits) == 1
    assert "set EXEC_SANDBOX=none/docker consciously" in hits[0].getMessage()


def test_auto_linux_keeps_bwrap_first(monkeypatch, _fresh_auto_cache):
    """P1-1：linux + bwrap/docker 都可用 → 仍选 bwrap（其余平台顺序不变）。"""
    _patch_platform_backends(
        monkeypatch, platform="linux", bwrap=True, docker_ok=True, sandbox_exec_ok=True
    )
    backend, _ = sbx.resolve_auto_backend()
    assert backend == "bwrap"


def test_auto_linux_no_bwrap_docker_beats_sandbox_exec(monkeypatch, _fresh_auto_cache):
    """P1-1：linux + 无 bwrap → docker 优先于 sandbox-exec（维持既有链序）.

    linux 上 `_probe_sandbox_exec` 被平台门直接拒绝，故此处直接 patch 探测函数为
    True（模拟"假想可用"），验证链序本身仍是 docker 在 sandbox-exec 之前。
    """
    _patch_platform_backends(monkeypatch, platform="linux", docker_ok=True)
    monkeypatch.setattr(sbx, "_probe_sandbox_exec", lambda: True)
    backend, _ = sbx.resolve_auto_backend()
    assert backend == "docker"


def test_explicit_mode_bypasses_auto_chain(monkeypatch, _fresh_auto_cache):
    """P1-1：显式 EXEC_SANDBOX=none/docker 不经 auto 解析（auto 被引爆也不受影响）。"""
    monkeypatch.setattr(
        sbx, "resolve_auto_backend", lambda: pytest.fail("显式模式不得触发 auto 解析")
    )
    argv, note = sandbox_argv("cmd", ".", mode="none")
    assert argv is None and note == ""
    with mock.patch(
        "llm_loop.tools.sandbox.shutil.which", return_value="/usr/local/bin/docker"
    ):
        argv, note = sandbox_argv("cmd", ".", mode="docker")
    assert argv is not None and argv[0] == "docker"
