#!/usr/bin/env python3
"""Build an LFL wheel and sdist exclusively from one Git commit.

Unlike running ``uv build`` in the operator's checkout, this command never
reads uncommitted source modules. It creates its own detached Git worktree,
builds UI assets *from that same snapshot*, and checks wheel Python ownership
against the tracked tree before publishing artifacts to a new output folder.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZipFile


class CommittedBuildError(RuntimeError):
    """A candidate is ineligible for a clean distribution build."""


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode:
        raise CommittedBuildError(f"git {args[0]} rejected candidate")
    return result.stdout


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _check_commit(repo: Path, ref: str) -> str:
    candidate = _git(repo, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
    if re.fullmatch(r"[0-9a-f]{40}", candidate) is None:
        raise CommittedBuildError("invalid Git commit identity")
    return candidate


@contextmanager
def _git_lock(repo: Path) -> Iterator[None]:
    common_dir = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
    with (common_dir / "r9-commit.lock").open("a+") as stream:
        deadline = time.monotonic() + 20
        while True:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise CommittedBuildError("shared Git mutation lock busy") from None
                time.sleep(0.25)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def _frozen_checkout(repo: Path, commit: str, temporary: Path) -> Iterator[Path]:
    checkout = temporary / "source"
    with _git_lock(repo):
        _git(repo, "worktree", "add", "--detach", str(checkout), commit)
    try:
        if _git(checkout, "rev-parse", "HEAD").decode().strip() != commit:
            raise CommittedBuildError("temporary checkout is not the requested commit")
        yield checkout
    finally:
        # Only remove the private path created by this invocation. Never
        # touch the caller's checkout or another Agent's existing worktree.
        with _git_lock(repo):
            _git(repo, "worktree", "remove", "--force", str(checkout))


def _webui_fingerprint(checkout: Path) -> dict[str, object]:
    names = sorted(filter(None, _git(checkout, "ls-files", "-z", "--", "webui").split(b"\0")))
    if not names:
        raise CommittedBuildError("no tracked WebUI sources in candidate")
    hashed = hashlib.sha256()
    for raw in names:
        name = raw.decode("utf-8", errors="strict")
        source = checkout / name
        if not source.is_file() or source.is_symlink():
            raise CommittedBuildError("tracked WebUI input missing or symlinked")
        hashed.update(raw)
        hashed.update(b"\0")
        hashed.update(hashlib.sha256(source.read_bytes()).digest())
        hashed.update(b"\0")
    return {"schema": "lfl-webui-source/v1", "source_sha256": hashed.hexdigest(),
            "tracked_files": len(names)}


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                            timeout=240, check=False)
    if result.returncode:
        # Avoid accidentally dumping environment variables, credentials or
        # local file contents returned by package build subprocesses.
        raise CommittedBuildError(f"{command[0]} build step failed (exit {result.returncode})")


def _build_env() -> dict[str, str]:
    keep = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env.update({"npm_config_offline": "true", "UV_NO_CONFIG": "1", "PYTHONNOUSERSITE": "1"})
    return env


def _check_wheel_python(checkout: Path, wheel: Path) -> int:
    expected = {
        name.removeprefix("src/") for name in
        _git(checkout, "ls-files", "--", "src/llm_loop").decode().splitlines()
        if name.endswith(".py")
    }
    with ZipFile(wheel) as archive:
        actual = {
            name for name in archive.namelist()
            if name.startswith("llm_loop/") and name.endswith(".py")
            and not name.startswith("llm_loop/_bundled/")
        }
    if expected != actual:
        raise CommittedBuildError("wheel Python modules differ from Git tracked snapshot")
    return len(expected)


def build(repo: Path, ref: str, out_dir: Path, node_modules: Path) -> dict[str, object]:
    repo = repo.resolve(strict=True)
    out_dir = out_dir.expanduser().absolute()
    node_modules = node_modules.resolve(strict=True)
    commit = _check_commit(repo, ref)
    if not node_modules.is_dir() or not (node_modules / ".bin" / "vite").is_file():
        raise CommittedBuildError("pinned local WebUI build dependencies are unavailable")
    if out_dir.exists() or out_dir.is_symlink() or not out_dir.parent.is_dir():
        raise CommittedBuildError("output directory must be an unused new directory")
    env = _build_env()
    with tempfile.TemporaryDirectory(prefix="lfl-committed-distribution-") as directory:
        temporary = Path(directory)
        with _frozen_checkout(repo, commit, temporary) as checkout:
            # Reuse only dependency binaries, never caller's generated UI or
            # untracked Python source files.
            (checkout / "webui" / "node_modules").symlink_to(node_modules, target_is_directory=True)
            fingerprint = _webui_fingerprint(checkout)
            _run(["npm", "run", "build"], cwd=checkout / "webui", env=env)
            marker = checkout / "webui" / "dist" / ".lfl-webui-source.json"
            if not marker.is_file() or json.loads(marker.read_text()) != fingerprint:
                raise CommittedBuildError("compiled WebUI is not bound to the frozen Git snapshot")
            staging = temporary / "dist"
            _run(["uv", "build", "--offline", "--out-dir", str(staging)], cwd=checkout, env=env)
            wheels = list(staging.glob("*.whl"))
            sdists = list(staging.glob("*.tar.gz"))
            if len(wheels) != 1 or len(sdists) != 1:
                raise CommittedBuildError("exactly one wheel and sdist are required")
            python_count = _check_wheel_python(checkout, wheels[0])
            if _git(checkout, "rev-parse", "HEAD").decode().strip() != commit:
                raise CommittedBuildError("source commit changed during build")
            if _git(checkout, "status", "--porcelain=v1").strip():
                raise CommittedBuildError("tracked snapshot changed during build")
            artifact = {"schema": "lfl.committed-distribution/v1", "source_commit": commit,
                        "webui_source_sha256": fingerprint["source_sha256"],
                        "webui_tracked_files": fingerprint["tracked_files"],
                        "tracked_python_modules": python_count,
                        "build_source": "detached-clean-git-worktree", "offline_build": True,
                        "node_modules_source": "existing_local_installed_dependencies",
                        "artifacts": {path.name: _sha(path.read_bytes()) for path in (wheels[0], sdists[0])},
                        "publisher_signature_verified": False}
            out_dir.mkdir(mode=0o700)
            try:
                for path in (wheels[0], sdists[0]):
                    shutil.copy2(path, out_dir / path.name)
                (out_dir / "provenance.json").write_text(
                    json.dumps(artifact, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            except (OSError, ValueError):
                shutil.rmtree(out_dir)
                raise
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--node-modules", type=Path)
    args = parser.parse_args()
    try:
        result = build(args.repo, args.ref, args.out_dir,
                       args.node_modules or args.repo / "webui" / "node_modules")
    except (CommittedBuildError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        parser.exit(1, "Committed distribution build rejected: " + str(exc) + "\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
