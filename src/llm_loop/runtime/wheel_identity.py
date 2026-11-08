"""Read installed wheel facts without borrowing identity from the task workspace."""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from llm_loop.runtime.package_identity import installed_identity


def read_release_identity(release: Path, *, package_root: Path | None = None) -> dict[str, str]:
    """Verify the retained wheel and, when supplied, its installed package bytes."""
    match = re.fullmatch(r"LFL-([0-9]+\.[0-9]+\.[0-9]+)", release.name)
    if not match or release.is_symlink() or not release.is_dir():
        raise ValueError("wheel release directory missing or unsafe")
    version = match[1]
    if (release / ".installer-incomplete").exists():
        raise ValueError("wheel release installation is incomplete")
    record = release / ".installer-wheel.sha256"
    if record.is_symlink() or not record.is_file():
        raise ValueError("wheel integrity record missing or unsafe")
    lines = [line.split() for line in record.read_text(encoding="ascii").splitlines() if line.strip()]
    name = f"llm_first_loop-{version}-py3-none-any.whl"
    if len(lines) != 1 or len(lines[0]) != 2 or lines[0][1] != name:
        raise ValueError("wheel integrity record must name exactly the release wheel")
    wheel = release / name
    if wheel.is_symlink() or not wheel.is_file():
        raise ValueError("release wheel missing or unsafe")
    sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", lines[0][0]) or sha != lines[0][0].lower():
        raise ValueError("release wheel checksum mismatch")
    if package_root is not None:
        verify_installed_package(wheel, package_root)
    return {"artifact_kind": "wheel_release", "release_version": version,
            "wheel_sha256": sha, "release_dir": str(release.resolve())}


def verify_installed_package(wheel: Path, package_root: Path) -> None:
    """Same-version substitution or modified site-packages must remain visible."""
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError("duplicate wheel members")
        checked = 0
        for name in names:
            path = PurePosixPath(name)
            if not path.parts or path.parts[0] != "llm_loop" or name.endswith("/"):
                continue
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe wheel member")
            target = package_root.joinpath(*path.parts[1:])
            if not target.resolve().is_relative_to(package_root.resolve()):
                raise ValueError("installed package member escapes package root")
            if target.is_symlink() or not target.is_file() or target.read_bytes() != archive.read(name):
                raise ValueError(f"installed wheel member mismatch: {name}")
            checked += 1
        if not checked:
            raise ValueError("wheel has no llm_loop package")


def installed_build_identity() -> dict[str, Any] | None:
    """Use this process's package location, never the active-version pointer."""
    module = Path(__file__).resolve().parents[1] / "__init__.py"
    installed = installed_identity(module)
    if installed is None:
        return None
    version = installed["version"]
    facts: dict[str, Any] = {
        "release_version": version, "artifact_kind": "installed_wheel",
        "expected_release_tag": f"v{version}", "nearest_release_tag": "",
        "commits_since_release_tag": None, "git_available": False,
        "git_head": "", "git_short": "", "git_dirty": False,
        "release_exact": False, "git_describe": "", "display": f"v{version} (wheel)",
        "package_root": installed["package_root"],
    }
    package = Path(installed["package_root"]).resolve()
    release = next((p.parent for p in package.parents if p.name == "venv"), None)
    if release is None or release.parent.name != "releases":
        return facts
    try:
        verified = read_release_identity(release, package_root=package)
        if verified["release_version"] != version:
            raise ValueError("installed distribution and release directory version differ")
        facts.update(verified)
        facts["display"] = f"v{version} wheel@{verified['wheel_sha256'][:12]}"
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        facts["identity_error"] = str(exc)
    return facts


def manifest_identity_problems(raw: dict[str, Any], desired: Any) -> list[str]:
    """One comparison for both the panel and the controlled restart verifier."""
    build = raw.get("build_identity") or {}
    if not isinstance(build, dict):
        return ["build_identity_invalid"]
    problems: list[str] = []
    for key, expected in (("release_version", desired.version),
                          ("wheel_sha256", desired.wheel_sha256),
                          ("release_dir", desired.release_dir)):
        actual = str(build.get(key) or "")
        if not actual:
            problems.append(f"{key}_missing")
        elif actual != str(expected):
            problems.append(f"{key}_mismatch live={actual} desired={expected}")
    if build.get("identity_error"):
        problems.append("installed_package_integrity_failed")
    if build.get("artifact_kind") != "wheel_release":
        problems.append("artifact_kind_mismatch")
    package = str(build.get("package_root") or "")
    expected_venv = Path(desired.release_dir) / "venv"
    executable = Path(str(raw.get("python_executable") or ""))
    if not executable.is_absolute() or not executable.is_relative_to(expected_venv):
        problems.append("python_executable_mismatch")
    if not package or not Path(package).is_relative_to(expected_venv):
        problems.append("package_root_mismatch")
    if str(raw.get("data_dir") or "") != str(desired.data_dir):
        problems.append("data_dir_mismatch")
    return problems
