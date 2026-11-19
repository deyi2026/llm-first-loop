#!/usr/bin/env python3
"""Prepare an OFFLINE, relocatable M1 Host bundle; never install it.

The bundle is user-owned and therefore UNTRUSTED until copied into a
root-owned staging directory and checked against the independently reviewed
manifest SHA. No secret key is generated or stored in this bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENDOR_NAMES = (
    "mujoco",
    "numpy",
    "cryptography",
    "OpenGL",
    "glfw",
    "fsspec",
    "etils",
    "absl",
    "cffi",
    "zipp",
    "packaging",
    "typing_extensions.py",
)
SANDBOX_PROFILE = """(version 1)
(allow default)
(deny network*)
(deny file-read* (subpath "/Users") (subpath "/Volumes"))
(deny file-write*)
(allow file-write*
  (subpath "/private/var/run/lfl-m1-oracle")
  (subpath "/private/var/db/lfl-m1-oracle"))
"""


def _copy_runtime(output: Path) -> None:
    base = Path(sys.base_prefix)
    target = output / "runtime"
    (target / "bin").mkdir(parents=True)
    shutil.copy2(base / "bin/python3.13", target / "bin/python3.13")
    shutil.copytree(base / "lib", target / "lib", symlinks=False)
    source_vendor = Path(sys.prefix) / "lib/python3.13/site-packages"
    vendor = output / "vendor"
    vendor.mkdir()
    for name in VENDOR_NAMES:
        source = source_vendor / name
        if not source.exists():
            continue
        if source.is_dir():
            shutil.copytree(source, vendor / name, symlinks=False)
        else:
            shutil.copy2(source, vendor / name)
    for name in ("_cffi_backend*.so", "*dist-info"):
        for source in source_vendor.glob(name):
            if name == "*dist-info" and not any(
                source.name.lower().startswith(n.lower().replace("_", "-")) for n in VENDOR_NAMES
            ):
                continue
            if source.is_dir():
                shutil.copytree(source, vendor / source.name, symlinks=False)
            else:
                shutil.copy2(source, vendor / source.name)


def _copy_code(output: Path) -> None:
    package = output / "src/llm_loop/embodied_sim"
    package.mkdir(parents=True)
    sources = [
        ROOT / "src/llm_loop/__init__.py",
        ROOT / "scripts/embodied/m1_oracle_host_service.py",
        *(ROOT / "src/llm_loop/embodied_sim").glob("*.py"),
    ]
    relative = [str(path.relative_to(ROOT)) for path in sources]
    # Never label a bundle with a frozen SHA while copying untracked or
    # modified service bytes from a concurrent worktree.
    subprocess.run(
        ["/usr/bin/git", "-C", str(ROOT), "ls-files", "--error-unmatch", "--", *relative],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        ["/usr/bin/git", "-C", str(ROOT), "diff", "--quiet", "HEAD", "--", *relative],
        check=True,
    )
    shutil.copy2(sources[0], package.parent / "__init__.py")
    for source in (ROOT / "src/llm_loop/embodied_sim").glob("*.py"):
        shutil.copy2(source, package / source.name)
    shutil.copy2(
        sources[1],
        output / "m1_oracle_host_service.py",
    )
    (output / "oracle.sb").write_text(SANDBOX_PROFILE, encoding="ascii")


def _manifest(output: Path) -> str:
    files = {}
    for path in sorted(output.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"bundle contains symlink: {path}")
        if path.is_file():
            relative = path.relative_to(output).as_posix()
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "schema": "lfl.m1-oracle-host-bundle/v1",
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "git_head": subprocess.check_output(
            ["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip(),
        "files": files,
    }
    raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (output / "manifest.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _relocation_probe(output: Path) -> None:
    code = (
        "import sys;"
        f"sys.path.insert(0,{str(output / 'vendor')!r});"
        f"sys.path.insert(0,{str(output / 'src')!r});"
        "import mujoco,numpy,cryptography;"
        "from llm_loop.embodied_sim import MuJoCoScene;"
        "s=MuJoCoScene(seed=7);s.step(100);"
        "assert s.scene_epoch==1"
    )
    subprocess.run(
        [str(output / "runtime/bin/python3.13"), "-I", "-S", "-B", "-c", code],
        cwd=output,
        check=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "HOME": "/var/empty"},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output
    if not output.is_absolute() or output.exists():
        raise RuntimeError("output must be a new absolute directory")
    if sys.version_info[:2] != (3, 13) or platform.system() != "Darwin":
        raise RuntimeError("macOS Python3.13 required")
    output.mkdir(parents=True, mode=0o700)
    try:
        _copy_runtime(output)
        _copy_code(output)
        _relocation_probe(output)
        digest = _manifest(output)
    except BaseException:
        # Do not erase a partially built bundle silently: it is diagnostic,
        # never eligible for installation without a complete manifest.
        raise
    print(
        json.dumps(
            {
                "status": "BUNDLE_READY_NOT_INSTALLED",
                "path": str(output),
                "manifest_sha256": digest,
                "git_head": json.loads((output / "manifest.json").read_text())["git_head"],
                "file_count": len(json.loads((output / "manifest.json").read_text())["files"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
