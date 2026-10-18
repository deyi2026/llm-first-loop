#!/usr/bin/env python3
"""Build an *unsigned* Apple Silicon installer from a reviewed local wheel.

Developer-side, offline and isolated. No push, signing, notarization or host
installation. A formal public release requires separate publisher credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, check=True, env=env, capture_output=True, text=True, timeout=300)


def build(*, wheel: Path, expected_sha256: str, out: Path) -> dict[str, str | bool]:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise ValueError("macos_arm64_only")
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or wheel.is_symlink() or not wheel.is_file()):
        raise ValueError("wheel_untrusted_or_invalid")
    found = re.fullmatch(r"llm_first_loop-(\d+\.\d+\.\d+)-py3-none-any\.whl", wheel.name)
    if not found:
        raise ValueError("unsupported_wheel_filename")
    version = found.group(1)
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("wheel_sha_mismatch")
    source_python = Path(sys.base_prefix).resolve()
    if not (source_python / "bin/python3.13").is_file():
        raise ValueError("managed_python313_unavailable")
    if out.is_symlink() or out.exists() or not out.parent.is_dir():
        raise ValueError("out_dir_must_be_new")
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("build_requires_uv")
    environment = dict(os.environ)
    environment["UV_OFFLINE"] = "1"
    environment["UV_LINK_MODE"] = "copy"
    environment["PYTHONNOUSERSITE"] = "1"
    with tempfile.TemporaryDirectory(prefix="lfl-macos-offline-pkg-") as temporary:
        root = Path(temporary)
        app = root / "payload" / "Applications" / "LFL.app"
        resources = app / "Contents" / "Resources"
        bin_dir = app / "Contents" / "MacOS"
        resources.mkdir(parents=True)
        bin_dir.mkdir(parents=True)
        _run(["ditto", str(source_python), str(resources / "python")])
        _run([uv, "venv", "--relocatable", "--python",
              str(resources / "python" / "bin/python3.13"), str(resources / "venv")], env=environment)
        _run([uv, "pip", "install", "--offline", "--link-mode", "copy",
              "--python", str(resources / "venv" / "bin/python"), str(wheel)], env=environment)
        _run([uv, "pip", "check", "--python", str(resources / "venv" / "bin/python")], env=environment)
        # uv --relocatable still writes an absolute interpreter symlink and
        # the builder's temporary path into pyvenv.cfg on this macOS uv build.
        # An archive extract (unlike a same-process ditto clone) then breaks.
        python_link = resources / "venv" / "bin" / "python"
        if not python_link.is_symlink():
            raise ValueError("unexpected_uv_python_layout")
        python_link.unlink()
        python_link.symlink_to("../../python/bin/python3.13")
        venv_config = resources / "venv" / "pyvenv.cfg"
        config = venv_config.read_text(encoding="utf-8")
        if not any(line.startswith("home = ") for line in config.splitlines()):
            raise ValueError("venv_home_missing")
        venv_config.write_text("\n".join(
            "home = ../python/bin" if line.startswith("home = ") else line
            for line in config.splitlines()) + "\n", encoding="utf-8")
        with (app / "Contents" / "Info.plist").open("wb") as stream:
            plistlib.dump({
                "CFBundleIdentifier": "org.llmfirstloop.cli",
                "CFBundleExecutable": "lfl",
                "CFBundleName": "LFL",
                "CFBundleDisplayName": "LFL",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": version,
                "CFBundleShortVersionString": version,
                "LSUIElement": True,
            }, stream)
        launcher = bin_dir / "lfl"
        launcher.write_text(
            '#!/bin/sh\n'
            'BINDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
            'exec "$BINDIR/../Resources/venv/bin/python" -c '
            "'from llm_loop.cli import application_main; raise SystemExit(application_main())' \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        (resources / "README.txt").write_text(
            "LFL 离线安装包；从 /Applications/LFL Start.command 双击启动终端向导。\n"
            "命令行入口：/Applications/LFL.app/Contents/MacOS/lfl。\n"
            "卸载应用不会自动删除用户目录。尚未签名/公证，禁止当作公开可信发行版。\n",
            encoding="utf-8",
        )
        helper = root / "payload" / "Applications" / "LFL Start.command"
        helper.write_text(
            '#!/bin/zsh\n'
            'exec "/Applications/LFL.app/Contents/MacOS/lfl" start\n',
            encoding="utf-8",
        )
        helper.chmod(0o755)

        # Prove relocatability before building the .pkg, without system install.
        relocated = root / "relocated" / "LFL.app"
        relocated.parent.mkdir()
        _run(["ditto", str(app), str(relocated)])
        original = app.with_name("LFL.build-original.app")
        app.rename(original)  # Only relocated files may satisfy the smoke.
        relocated_bin = str(relocated / "Contents" / "MacOS" / "lfl")
        try:
            version_check = subprocess.run([relocated_bin, "--version"],
                                           check=True, capture_output=True, text=True, timeout=30)
            if version_check.stdout.strip() != version:
                raise ValueError("relocated_executable_wrong_version")
            install_check = subprocess.run([relocated_bin, "check-install"],
                                           check=True, capture_output=True, text=True, timeout=60)
            if json.loads(install_check.stdout).get("ok") is not True:
                raise ValueError("relocated_bundle_integrity_failed")
        finally:
            original.rename(app)
        out.mkdir(mode=0o700)
        package = out / f"LFL-{version}-macos-arm64-unsigned.pkg"
        _run(["pkgbuild", "--root", str(root / "payload"),
              "--install-location", "/", "--identifier", "org.llmfirstloop.cli",
              "--version", version, str(package)])
        result: dict[str, str | bool] = {
            "schema": "lfl.macos-installer-candidate/v1",
            "version": version, "architecture": "arm64", "wheel_sha256": expected_sha256,
            "pkg_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
            "pkg_name": package.name,
            "offline_built": True, "relocated_python_self_contained_smoke": True,
            "includes_python_runtime": True, "requires_user_python_or_uv": False,
            "signed": False, "notarized": False, "public_release_eligible": False,
            "host_install_performed": False,
        }
        (out / "provenance.json").write_text(
            json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(wheel=args.wheel, expected_sha256=args.expected_sha256.lower(), out=args.out_dir)
    except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print("macOS installer build failed: " + type(exc).__name__, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
