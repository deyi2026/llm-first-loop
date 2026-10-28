#!/usr/bin/env python3
"""Inspect an unsigned macOS .pkg in quarantine; never install to the host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def _run(*args: str, cwd: Path | None = None,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, timeout=130,
                          check=True, cwd=cwd, env=env)


def verify(*, package: Path, expected_sha256: str) -> dict[str, object]:
    if (sys.platform != "darwin" or platform.machine() != "arm64"
            or package.is_symlink() or not package.is_file()
            or hashlib.sha256(package.read_bytes()).hexdigest() != expected_sha256):
        raise ValueError("package_identity_or_platform_invalid")
    with tempfile.TemporaryDirectory(prefix="lfl-macos-pkg-verify-") as temporary:
        root = Path(temporary)
        expanded = root / "extracted"
        _run("pkgutil", "--expand-full", str(package), str(expanded))
        payload = expanded / "Payload" / "Applications"
        if {path.name for path in payload.iterdir()} != {"LFL.app", "LFL Start.command"}:
            raise ValueError("unexpected_installer_payload")
        shell = payload / "LFL Start.command"
        if not shell.is_file() or not os.access(shell, os.X_OK):
            raise ValueError("startup_shortcut_missing")
        lfl = str(payload / "LFL.app" / "Contents" / "MacOS" / "lfl")
        if not os.access(lfl, os.X_OK):
            raise ValueError("installed_entrypoint_missing")
        # Test after archive extraction, with no developer Python or uv on PATH.
        # HOME itself is forbidden as a workspace; use an isolated child directory.
        workspace = root / "workspace"
        workspace.mkdir(mode=0o700)
        env = {"HOME": str(root), "PATH": "/usr/bin:/bin", "LFL_HOME": str(root / "user-state"),
               "PYTHONNOUSERSITE": "1", "LFL_LEARNING_ENABLED": "false",
               "LFL_REFLECTION_ENABLED": "false", "LLM_MODEL": "glm-5.3",
               "LLM_API_KEY": "fake-smoke-only", "LLM_BASE_URL": "https://example.invalid/v1"}
        version = _run(lfl, "--version", cwd=workspace, env=env).stdout.strip()
        install = json.loads(_run(lfl, "check-install", cwd=workspace, env=env).stdout)
        start_plan = json.loads(_run(lfl, "start", "--plan", "--json", cwd=workspace, env=env).stdout)
        if (not install.get("ok") or not start_plan["read_only"] or start_plan["will_start_web"]):
            raise ValueError("bundled_cli_install_or_start_plan_failed")
        port_socket = socket.socket()
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
        port_socket.close()
        env.update({"WEB_HOST": "127.0.0.1", "WEB_PORT": str(port)})
        # No provider access: fake credentials, disable learning/reflection;
        # request only localhost and stop only our newly spawned Web process.
        with (root / "server.log").open("w") as log:
            proc = subprocess.Popen([lfl, "web"], cwd=workspace, env=env, stdout=log, stderr=log)
            try:
                ready = False
                until = time.monotonic() + 38
                while time.monotonic() < until:
                    if proc.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.2) as response:
                            ready = response.status == 200
                    except (OSError, urllib.error.URLError):
                        time.sleep(0.25)
                    if ready:
                        break
                if not ready:
                    raise ValueError("bundled_web_not_ready")
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/ui/v2/", timeout=3) as response:
                    if response.status != 200:
                        raise ValueError("bundled_web_ui_not_ready")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=4)

        # Notarization and Developer ID signing must be verified independently.
        signature = subprocess.run(["pkgutil", "--check-signature", str(package)],
                                   capture_output=True, text=True, timeout=30)
        signed = "no signature" not in (signature.stdout + signature.stderr).lower() and signature.returncode == 0
        return {
            "schema": "lfl.macos-installer-quarantine-smoke/v1",
            "pkg_sha256": expected_sha256, "package_version": version,
            "pkg_extracted_without_system_install": True,
            "app_has_bundled_python_and_dependencies": True,
            "no_host_python_or_uv_needed_at_runtime": True,
            "installed_entrypoint_check_install": True,
            "start_plan_read_only": True,
            "web_health": 200, "web_ui": 200,
            "developer_id_signature_verified": False if not signed else "unverified_developer_identity",
            "notarization_verified": False,
            "public_release_qualified": False,
            "system_install_performed": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pkg", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify(package=args.pkg, expected_sha256=args.expected_sha256)
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print("macOS installer quarantine verification failed: " + type(exc).__name__, file=sys.stderr)
        return 1
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
