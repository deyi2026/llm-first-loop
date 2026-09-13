"""Mechanical runtime path resolution for code-bound and persistent state assets.

Mutable knowledge follows persistent state identity, never process cwd.  Tracked
assets (rules/method seeds/skills/docs) follow the exact code root.  Linked Git
worktrees share the primary repository state by default, while an explicit DATA_DIR
is always preserved and merely reported if it points back inside a linked sidecar.
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    code_root: Path
    git_common_root: Path | None
    data_dir: Path
    data_dir_source: str
    data_dir_auto_rebind: bool
    explicit_sidecar_state: bool
    state_root: Path
    experiences_dir: Path
    methods_dir: Path
    method_seed_dir: Path
    skills_dir: Path
    docs_dir: Path
    experiences_source: str
    methods_source: str
    state_root_source: str
    legacy_experiences_dir: Path
    legacy_methods_dir: Path
    auto_rebind_applied: bool

    def binding_summary(self) -> dict[str, object]:
        return {
            "code_root": str(self.code_root),
            "git_common_root": str(self.git_common_root) if self.git_common_root else "",
            "data_dir": str(self.data_dir),
            "data_dir_source": self.data_dir_source,
            "data_dir_auto_rebind": self.data_dir_auto_rebind,
            "explicit_sidecar_state": self.explicit_sidecar_state,
            "state_root": str(self.state_root),
            "state_root_source": self.state_root_source,
            "experiences_dir": str(self.experiences_dir),
            "experiences_source": self.experiences_source,
            "methods_dir": str(self.methods_dir),
            "methods_source": self.methods_source,
            "method_seed_dir": str(self.method_seed_dir),
            "skills_dir": str(self.skills_dir),
            "docs_dir": str(self.docs_dir),
            "legacy_experiences_dir": str(self.legacy_experiences_dir),
            "legacy_methods_dir": str(self.legacy_methods_dir),
            "auto_rebind_applied": self.auto_rebind_applied,
        }


def _resolved(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _explicit(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key, "") or "").strip()


def discover_git_common_root(code_root: str | Path) -> Path | None:
    """Return the primary worktree root for a normal Git repository, if provable."""
    code = _resolved(code_root)
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(code),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    common_dir = _resolved(proc.stdout.strip())
    # LFL uses normal non-bare repositories.  Refuse to infer from an unfamiliar
    # common-dir shape rather than inventing a root.
    return common_dir.parent if common_dir.name == ".git" else None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def infer_state_root(data_dir: str | Path) -> tuple[Path, str]:
    """Infer one persistent state root from the authoritative DATA_DIR."""
    data = _resolved(data_dir)
    if data.name == "data":
        return data.parent, "data_dir_parent"
    return data, "data_dir_bundle"


def resolve_runtime_paths(
    *,
    data_dir: str | Path | None,
    code_root: str | Path,
    env: Mapping[str, str] | None = None,
    data_dir_explicit: bool = False,
) -> RuntimePaths:
    values = os.environ if env is None else env
    code = _resolved(code_root)
    common_root = discover_git_common_root(code)
    linked_worktree = common_root is not None and common_root != code

    if data_dir is None or not str(data_dir).strip():
        if linked_worktree:
            assert common_root is not None
            data = _resolved(common_root / "data")
            data_source = "git_common_root"
            data_auto_rebind = True
        else:
            data = _resolved(code / "data")
            data_source = "code_root_default"
            data_auto_rebind = False
    else:
        data = _resolved(data_dir)
        data_source = "explicit" if data_dir_explicit else "supplied"
        data_auto_rebind = False

    explicit_sidecar_state = bool(
        data_dir_explicit and linked_worktree and _is_within(data, code)
    )
    state_root, state_source = infer_state_root(data)

    exp_raw = _explicit(values, "EXPERIENCES_DIR")
    methods_raw = _explicit(values, "METHODS_DIR")
    seed_raw = _explicit(values, "METHOD_SEED_DIR")
    skills_raw = _explicit(values, "SKILLS_DIR")
    docs_raw = _explicit(values, "DOCS_DIR")

    if exp_raw:
        experiences = _resolved(exp_raw)
        exp_source = "explicit_env"
    else:
        experiences = _resolved(state_root / "experiences")
        exp_source = "data_dir_inferred"

    if methods_raw:
        methods = _resolved(methods_raw)
        methods_source = "explicit_env"
    else:
        methods = _resolved(data / "methods")
        methods_source = "data_dir_inferred"

    method_seed = _resolved(seed_raw) if seed_raw else _resolved(code / "methods")
    skills = _resolved(skills_raw) if skills_raw else _resolved(code / "skills")
    docs = _resolved(docs_raw) if docs_raw else _resolved(code / "docs")

    legacy_experiences = _resolved(code / "experiences")
    legacy_methods = _resolved(code / "data" / "methods")
    mutable_auto_rebind = (
        (not exp_raw and experiences != legacy_experiences)
        or (not methods_raw and methods != legacy_methods)
    )

    return RuntimePaths(
        code_root=code,
        git_common_root=common_root,
        data_dir=data,
        data_dir_source=data_source,
        data_dir_auto_rebind=data_auto_rebind,
        explicit_sidecar_state=explicit_sidecar_state,
        state_root=state_root,
        experiences_dir=experiences,
        methods_dir=methods,
        method_seed_dir=method_seed,
        skills_dir=skills,
        docs_dir=docs,
        experiences_source=exp_source,
        methods_source=methods_source,
        state_root_source=state_source,
        legacy_experiences_dir=legacy_experiences,
        legacy_methods_dir=legacy_methods,
        auto_rebind_applied=data_auto_rebind or mutable_auto_rebind,
    )
