"""Workspace Identity Guard（RUNTIME-SOT-WIRE R1）。

任何 LFL 进程启动时都能机械证明：

    resolve(llm_loop.__file__) ∈ resolve(workspace_root/src)

否则 FATAL_RUNTIME_IDENTITY_MISMATCH，拒绝启动（enforce 模式）。

背景（2026-08-29 实测事故）：
  - 主区 .venv 在 shell 残留 PYTHONPATH=mirror/src 时加载 mirror 代码
    （PYTHONPATH 优先级高于 editable .pth，venv 隔离可被静默劫持）；
  - 生产 feishu 进程实际运行于 mirror/.venv 而无任何记录。
本守卫把"我以为跑的是哪份代码"变成可机械核验的事实。

模式（RUNTIME_IDENTITY_MODE）：
  shadow  — 只记录告警，不阻断（默认，观察期）
  enforce — 违规即 raise RuntimeIdentityError（FATAL_RUNTIME_IDENTITY_MISMATCH）

workspace_root 判定优先级：
  1. LFL_WORKSPACE_ROOT 环境变量（显式）
  2. cwd 向上查找最近含 pyproject.toml 的目录（启动目录即 workspace）
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

FATAL_TAG = "FATAL_RUNTIME_IDENTITY_MISMATCH"


class RuntimeIdentityError(RuntimeError):
    """enforce 模式下 identity 违规。message 为完整 fatal 报文。"""

    def __init__(self, report: IdentityReport) -> None:
        self.report = report
        super().__init__(report.to_fatal_text())


@dataclass(frozen=True)
class IdentityReport:
    workspace_root: str
    git_head: str
    python_executable: str
    venv_root: str
    llm_loop_module: str
    data_dir: str
    config_file: str
    providers_file: str
    mode: str
    ok: bool
    detail: dict = field(default_factory=dict)

    def to_fatal_text(self) -> str:
        return (
            f"{FATAL_TAG}\n"
            f"  workspace:     {self.workspace_root}\n"
            f"  loaded module: {self.llm_loop_module}\n"
            f"  python:        {self.python_executable}\n"
            f"  venv:          {self.venv_root}\n"
            f"  detail:        {self.detail}\n"
            f"refusing to start (RUNTIME_IDENTITY_MODE={self.mode})"
        )


def _git_head(workspace: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _find_workspace_root(env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    root = values.get("LFL_WORKSPACE_ROOT")
    if root:
        return Path(root).expanduser().resolve()
    p = Path.cwd().resolve()
    for cand in (p, *p.parents):
        if (cand / "pyproject.toml").is_file():
            return cand
    return p


def _find_runtime_root(workspace: Path, env: Mapping[str, str] | None = None) -> Path:
    """Return the operational CWD/config root, distinct from source workspace when explicit.

    Normal launches keep the historical single-root contract.  Gate-E canaries may
    load an exact clean source worktree while retaining the canonical mirror CWD/data
    root; that split is authorized only by an explicit ``LFL_RUNTIME_ROOT``.
    """
    values = os.environ if env is None else env
    runtime_root = (values.get("LFL_RUNTIME_ROOT") or "").strip()
    return Path(runtime_root).expanduser().resolve() if runtime_root else workspace


def _mode(env: Mapping[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    m = (values.get("RUNTIME_IDENTITY_MODE") or "shadow").strip().lower()
    return m if m in ("shadow", "enforce") else "shadow"


def compute_identity(
    mode: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    workspace_root: str | Path | None = None,
) -> IdentityReport:
    """机械计算当前进程 runtime 身份。纯事实，无副作用。"""
    import llm_loop

    values = os.environ if env is None else env
    mode = mode or _mode(values)
    workspace = (
        Path(workspace_root).expanduser().resolve()
        if workspace_root is not None
        else (_find_workspace_root() if env is None else _find_workspace_root(values))
    )
    runtime_root = _find_runtime_root(workspace, values)
    module = Path(llm_loop.__file__).resolve()
    expected_src = (workspace / "src").resolve()
    ok = expected_src == module.parent or expected_src in module.parents

    from .paths import resolve_runtime_paths

    data_dir_raw = str(values.get("DATA_DIR", "") or "").strip()
    runtime_paths = resolve_runtime_paths(
        data_dir=data_dir_raw or None,
        code_root=workspace,
        env=values,
        data_dir_explicit=bool(data_dir_raw),
    )
    data_dir = str(runtime_paths.data_dir)
    config_candidates = [
        runtime_root / "runtime.toml",
        runtime_root / ".env",
        Path.home() / ".llm_loop" / ".env",
    ]
    providers_candidates = [
        Path(data_dir) / "providers.local.json",
        Path(data_dir) / "providers.json",
        runtime_root / "data" / "providers.local.json",
        runtime_root / "data" / "providers.json",
        workspace / "data" / "providers.local.json",
        workspace / "data" / "providers.json",
    ]

    return IdentityReport(
        workspace_root=str(workspace),
        git_head=_git_head(workspace),
        python_executable=sys.executable,
        venv_root=sys.prefix,
        llm_loop_module=str(module),
        data_dir=data_dir,
        config_file=next((str(p) for p in config_candidates if p.is_file()), ""),
        providers_file=next((str(p) for p in providers_candidates if p.is_file()), ""),
        mode=mode,
        ok=ok,
        detail={
            "expected_src": str(expected_src),
            "runtime_root": str(runtime_root),
            "pythonpath_set": bool(values.get("PYTHONPATH")),
            "pythonpath": values.get("PYTHONPATH", ""),
        },
    )


def check_identity(
    mode: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    workspace_root: str | Path | None = None,
) -> IdentityReport:
    """启动守卫入口：shadow 记录告警；enforce 违规即抛。"""
    report = compute_identity(mode=mode, env=env, workspace_root=workspace_root)
    if not report.ok:
        if report.mode == "enforce":
            raise RuntimeIdentityError(report)
        # shadow：只打告警，不阻断（观察期）
        print(f"[runtime-identity][shadow][WARN] {FATAL_TAG}: {report.detail}", file=sys.stderr)
    return report


def enforce_identity(
    workspace: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    mode: str | None = None,
) -> IdentityReport:
    """R1 服务入口严格守卫（2026-08-30 重写——半改工作区丢失的未提交 API）.

    与 check_identity 的差异：除模块归属核验（resolve(llm_loop) ∈ workspace/src）
    外，追加 CWD 锚定核验。默认单根模式下 runtime root=workspace root；显式
    ``LFL_RUNTIME_ROOT`` 时允许 source workspace 与运行/配置 CWD 分离，但传入的
    启动目录仍必须精确等于 runtime root。共享 venv/PYTHONPATH 串区仍会被捕获。

    - shadow（默认）: stderr 告警不阻断，返回 ok=False 的 report
    - enforce: 违规 raise RuntimeIdentityError（拒绝启动）
    """
    import dataclasses

    report = compute_identity(mode=mode, env=env)
    expected = (workspace if workspace is not None else Path.cwd()).resolve()
    runtime_root = Path(
        str(report.detail.get("runtime_root") or report.workspace_root)
    ).resolve()
    cwd_match = runtime_root == expected
    if report.ok and cwd_match:
        return report
    detail = dict(report.detail)
    detail["expected_workspace"] = str(expected)
    detail["runtime_root"] = str(runtime_root)
    detail["cwd_match"] = cwd_match
    bad = dataclasses.replace(report, ok=False, detail=detail)
    if report.mode == "enforce":
        raise RuntimeIdentityError(bad)
    print(f"[runtime-identity][shadow][WARN] {bad.to_fatal_text()}", file=sys.stderr)
    return bad
