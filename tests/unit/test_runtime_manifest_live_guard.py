"""runtime_manifest service-specific 身份活进程守卫（2026-09-24 面板误报实证）.

场景：restart 探测路径上的短命进程在真实 web 之后执行 web 启动路径，
覆盖 runtime_manifest.web.json 的 pid → status/面板按已死 pid 误报
restart_required。守卫：specific 身份只允许被"旧持有者已死/就是自己"刷新。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from llm_loop.runtime.manifest import write_manifest


def _write_specific(rt_dir: Path, service: str, pid: int) -> None:
    rt_dir.mkdir(parents=True, exist_ok=True)
    (rt_dir / f"runtime_manifest.{service}.json").write_text(
        json.dumps({"service": service, "pid": pid}), encoding="utf-8"
    )


def test_live_same_service_pid_not_overwritten(tmp_path: Path, monkeypatch) -> None:
    """旧持有者 pid 存活且 argv 属 llm_loop 进程族 → 短命写入者不覆盖 specific.

    模拟 ps 返回真实 web 服务形态的 command（.venv/bin/python -m llm_loop.web）
    ——测试进程自身 argv（pytest）不含 llm_loop，不能作为持有者模拟。
    """
    rt_dir = tmp_path / "runtime"
    _write_specific(rt_dir, "web", 4194303)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=a,
            returncode=0,
            stdout="/.venv/bin/python -m llm_loop.web",
        ),
    )
    new_manifest = {
        "service": "web",
        "pid": os.getpid(),  # 与持有者不同的写入者（短命探测进程）
    }
    write_manifest(new_manifest, tmp_path)
    kept = json.loads((rt_dir / "runtime_manifest.web.json").read_text())
    assert kept["pid"] == 4194303, "存活持有者的 specific 身份不得被覆盖"
    # merged last-writer 兼容文件不受守卫影响
    merged = json.loads((rt_dir / "runtime_manifest.json").read_text())
    assert merged["pid"] == os.getpid()


def test_dead_old_pid_allows_overwrite(tmp_path: Path, monkeypatch) -> None:
    """旧持有者已死（ps 无输出）→ 允许正常覆盖（真实重启路径）。"""
    rt_dir = tmp_path / "runtime"
    _write_specific(rt_dir, "web", 4194303)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(args=a, returncode=0, stdout=""),
    )
    write_manifest({"service": "web", "pid": os.getpid()}, tmp_path)
    now = json.loads((rt_dir / "runtime_manifest.web.json").read_text())
    assert now["pid"] == os.getpid()


def test_non_llm_loop_old_pid_allows_overwrite(tmp_path: Path, monkeypatch) -> None:
    """旧 pid 存活但 argv 非 llm_loop 本服务（pid 复用给无关进程）→ 放行。"""
    rt_dir = tmp_path / "runtime"
    _write_specific(rt_dir, "web", 4194303)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=a, returncode=0, stdout="/usr/sbin/cfprefsd agent"
        ),
    )
    write_manifest({"service": "web", "pid": os.getpid()}, tmp_path)
    now = json.loads((rt_dir / "runtime_manifest.web.json").read_text())
    assert now["pid"] == os.getpid()


def test_ps_failure_fails_open(tmp_path: Path, monkeypatch) -> None:
    """ps 异常 → fail-open 放行（保持历史 last-writer 语义）。"""

    def _boom(*a, **k):
        raise OSError("ps unavailable")

    rt_dir = tmp_path / "runtime"
    _write_specific(rt_dir, "feishu", 4194303)
    monkeypatch.setattr(subprocess, "run", _boom)
    write_manifest({"service": "feishu", "pid": os.getpid()}, tmp_path)
    now = json.loads((rt_dir / "runtime_manifest.feishu.json").read_text())
    assert now["pid"] == os.getpid()
