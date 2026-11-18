"""Trusted multi-project sandbox *plan* for Task Capability M1.

Not a model-facing tool and NOT an authorization source. The Host must verify
Task Lease signature, parent/Lane scope, OS access, and revocation before calling.
The plan itself never executes a command. Existing sandbox_argv semantics stay
unchanged for sessions without a Task Lease.

Mac Seatbelt limits writes, not reads/network. Linux bwrap does not isolate
network. Docker/none are explicitly unsupported for multi-root task plans.
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Sequence
from dataclasses import dataclass

from llm_loop.tools import sandbox as sbx


@dataclass(frozen=True)
class TaskSandboxPlan:
    backend: str
    argv: tuple[str, ...]
    writable_roots: tuple[str, ...]
    protected_paths: tuple[str, ...]
    note: str


def _canonical_dir(raw: str, *, home: str) -> str:
    if not raw or not os.path.isabs(raw):
        raise ValueError("task root must be an absolute path")
    real = os.path.realpath(raw)
    if real != raw or not os.path.isdir(real) or real in (os.sep, home):
        raise ValueError("task root must be an existing canonical project directory")
    if os.path.islink(raw):
        raise ValueError("symlink task root is not allowed")
    return real


def _git_metadata(project: str) -> tuple[list[str], list[str]]:
    """Find the .git directory or linked-worktree pointer file at project root."""
    marker = os.path.join(project, ".git")
    if not os.path.lexists(marker):
        return [], []
    if os.path.islink(marker):
        raise ValueError("symlink .git marker is not allowed")
    info = os.lstat(marker)
    if stat.S_ISDIR(info.st_mode):
        return [marker], []
    if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
        return [], [marker]
    raise ValueError("unsupported or hardlinked .git marker")


def _task_macos_writable_roots(workdir: str, extra_roots: Sequence[str]) -> list[str]:
    """Only Host-verified roots; never global tmp, HOME caches or env overrides.

    Build/cache directories outside a project must be explicit signed roots in
    the Task Lease, not ambient /tmp or ~/.cache writable exceptions.
    """
    candidates = (workdir, *extra_roots)
    return list(dict.fromkeys(os.path.abspath(path) for path in candidates))


def compile_task_sandbox(
    command: str,
    workdir: str,
    *,
    verified_project_roots: Sequence[str],
    protected_audit_roots: Sequence[str],
    mode: str,
) -> TaskSandboxPlan:
    """Build a fail-closed argv plan from trusted Host-supplied project roots.

    The caller must NOT forward model-supplied roots directly. The plan
    rechecks root identity, prevents workspace-ancestor grants, overlays
    protected audit and .git metadata, and rejects backends lacking equivalent
    multi-root support. Execution requires an independent effect-time check.
    """
    if not command:
        raise ValueError("command required")
    if not protected_audit_roots:
        raise ValueError("Host protected audit roots required")
    home = os.path.realpath(os.path.expanduser("~"))
    cwd = _canonical_dir(workdir, home=home)
    roots: list[str] = [cwd]
    for raw in verified_project_roots:
        root = _canonical_dir(raw, home=home)
        if root == cwd or sbx._inside(root, cwd):
            continue  # already covered by cwd; never widen it
        if sbx._inside(cwd, root):
            raise ValueError("task root would widen writable workspace ancestor")
        if root not in roots:
            roots.append(root)

    audit = sbx._prepare_protected_roots(protected_audit_roots)
    for root in roots:
        if any(sbx._inside(root, p) for p in audit):
            raise ValueError("task root overlaps protected audit authority")

    git_dirs: list[str] = []
    git_files: list[str] = []
    for root in roots:
        dirs, files = _git_metadata(root)
        git_dirs.extend(dirs)
        git_files.extend(files)
    protected_dirs = sbx._prepare_protected_roots([*audit, *git_dirs])
    protected = tuple(dict.fromkeys([*protected_dirs, *git_files]))

    backend = sbx.sandbox_mode(mode)
    if backend == "auto":
        backend, _reasons = sbx.resolve_auto_backend()
    if backend not in ("bwrap", "sandbox-exec"):
        raise RuntimeError(f"task multi-root sandbox unsupported backend: {backend}")
    if backend == "sandbox-exec":
        if not sbx.sandbox_exec_available():
            raise RuntimeError("sandbox-exec not available; no unsandboxed fallback")
        profile = sbx.sandbox_exec_profile(
            _task_macos_writable_roots(cwd, roots[1:]),
            protected_roots=protected_dirs,
        )
        # Linked-worktree .git is a file; directory-only audit compiler cannot
        # accept it, so apply an exact file deny after all allow rules.
        for path in git_files:
            profile += f'(deny file-write* (literal "{sbx._sbx_escape(path)}"))'
        argv = (sbx._SANDBOX_EXEC, "-p", profile, "/bin/bash", "-lc", command)
        note = "macOS Seatbelt task roots; write isolation only; reads/network unrestricted"
    else:
        if shutil.which("bwrap") is None:
            raise RuntimeError("bwrap missing; no unsandboxed fallback")
        base = sbx.bwrap_argv(command, cwd, protected_roots=protected_dirs)
        insert_at = base.index("--chdir")
        extra: list[str] = []
        for root in roots[1:]:
            extra.extend(sbx._bwrap_bind_args(root, root, "rw"))
            for parent in sbx._audit_ancestor_mounts(root, protected_dirs):
                extra.extend(("--bind", parent, parent))
            for protected_dir in sbx._audit_overlay_roots(root, protected_dirs):
                extra.extend(("--ro-bind", protected_dir, protected_dir))
        for path in git_files:
            if any(sbx._inside(path, root) for root in roots):
                extra.extend(("--ro-bind", path, path))
        base[insert_at:insert_at] = extra
        argv = tuple(base)
        note = "Linux bwrap task roots; read-only host system binds; network not isolated"
    return TaskSandboxPlan(
        backend=backend,
        argv=tuple(argv),
        writable_roots=tuple(roots),
        protected_paths=protected,
        note=note,
    )
