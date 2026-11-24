"""Read-only CLI startup artifact evidence; not a Run admission grant.

The source of truth is the loaded package, not the task workspace or its HEAD.
Capture once at startup; compare that frozen evidence to deployment snapshots
without invoking Git or hashing a wheel again on the comparison path.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llm_loop.runtime.service_control import ManagedServiceDeployment


@dataclass(frozen=True)
class StartupArtifactIdentity:
    pid: int
    artifact_kind: str
    module_path: str
    python_executable: str
    code_root: str = ""
    git_head: str = ""
    version: str = ""
    wheel_sha256: str = ""
    release_dir: str = ""
    reason: str = ""


def capture_startup_artifact() -> StartupArtifactIdentity:
    """Capture actual loaded source/wheel facts, once per CLI startup.

    A source snapshot is observational, not proof of immutable file contents.
    Dirty or unverified artifacts cannot be reported as matching the target.
    """
    import llm_loop
    from llm_loop.runtime.wheel_identity import installed_build_identity

    module = Path(llm_loop.__file__).resolve()
    common = {"pid": os.getpid(), "module_path": str(module),
              "python_executable": sys.executable}
    if module.parent.name == "llm_loop" and module.parent.parent.name == "src":
        root = module.parents[2]
        if (root / "pyproject.toml").is_file() and (root / ".git").exists():
            try:
                head = subprocess.run(
                    ["git", "-C", str(root), "rev-parse", "HEAD"],
                    check=True, capture_output=True, text=True, timeout=5,
                ).stdout.strip()
                dirty = subprocess.run(
                    ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
                    check=True, capture_output=True, text=True, timeout=5,
                ).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                return StartupArtifactIdentity(**common, artifact_kind="source_checkout",
                                               code_root=str(root), reason="source_identity_unavailable")
            reason = "source_dirty" if dirty else ""
            if not re.fullmatch(r"[0-9a-f]{40}", head):
                reason = "source_head_invalid"
            return StartupArtifactIdentity(**common, artifact_kind="source_checkout",
                                           code_root=str(root), git_head=head, reason=reason)
    try:
        build = installed_build_identity()
    except (OSError, ValueError):
        build = None
    if build is not None:
        verified = (build.get("artifact_kind") == "wheel_release"
                    and not build.get("identity_error"))
        return StartupArtifactIdentity(
            **common, artifact_kind="wheel_release" if verified else "installed_wheel",
            version=str(build.get("release_version") or ""),
            wheel_sha256=str(build.get("wheel_sha256") or ""),
            release_dir=str(build.get("release_dir") or ""),
            reason="" if verified else "wheel_identity_unverified",
        )
    return StartupArtifactIdentity(**common, artifact_kind="unknown", reason="module_origin_unverified")


def compare_startup_artifact(
    startup: StartupArtifactIdentity, desired: ManagedServiceDeployment | None,
) -> dict[str, Any]:
    """Pure comparison. Matching desired is not stable/live or admission proof."""
    state, reason = "unverified", startup.reason or "deployment_not_registered"
    if desired is not None and not startup.reason:
        if startup.artifact_kind != desired.artifact_kind:
            state, reason = "update_required", "artifact_kind_mismatch"
        elif desired.artifact_kind == "source_checkout":
            if startup.code_root != desired.code_root:
                state, reason = "update_required", "code_root_mismatch"
            elif startup.git_head != desired.git_head:
                state, reason = "update_required", "git_head_mismatch"
            else:
                state, reason = "identity_matches_target", "source_identity_matches"
        elif desired.artifact_kind == "wheel_release":
            if (startup.version, startup.wheel_sha256, startup.release_dir) != (
                desired.version, desired.wheel_sha256, desired.release_dir,
            ):
                state, reason = "update_required", "wheel_identity_mismatch"
            else:
                venv = Path(desired.release_dir) / "venv"
                if (not Path(startup.module_path).is_relative_to(venv)
                        or not Path(startup.python_executable).is_relative_to(venv)):
                    state, reason = "unverified", "wheel_runtime_path_mismatch"
                else:
                    state, reason = "identity_matches_target", "wheel_identity_matches"
    return {
        "entrypoint": "cli", "state": state, "reason": reason,
        "startup_artifact": asdict(startup),
        "desired_generation": desired.generation if desired is not None else None,
        "desired_artifact_kind": desired.artifact_kind if desired is not None else None,
        "desired_git_head": desired.git_head if desired is not None else None,
        "desired_version": desired.version if desired is not None else None,
        "admission_verified": False,
    }
