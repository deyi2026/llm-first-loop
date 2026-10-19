#!/usr/bin/env python3
"""Run a real user-level Linux install/upgrade-safe/uninstall smoke in an isolated HOME.

This verifier is intended for a non-root glibc Linux CI runner. It installs the supplied
wheel through the same shell installer that users run, verifies the installed CLI and
resource manifest, proves a bad digest cannot change the active version, then uninstalls
only the managed application files and confirms that user configuration/data survive.
"""

from __future__ import annotations

import argparse
import base64
import csv
import email
import hashlib
import io
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


def run(
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    check: bool = True,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-4000:]
        raise RuntimeError(f"command failed ({completed.returncode}): {argv!r}\n{detail}")
    return completed


def wheel_identity(wheel: Path) -> tuple[str, str]:
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with zipfile.ZipFile(wheel) as archive:
        metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise RuntimeError("wheel must contain exactly one dist-info/METADATA")
        metadata = email.message_from_bytes(archive.read(metadata_paths[0]))
    name = (metadata.get("Name") or "").lower().replace("_", "-")
    version = metadata.get("Version") or ""
    if name != "llm-first-loop":
        raise RuntimeError(f"unexpected wheel distribution: {name!r}")
    return version, digest


def wheel_version_variant(source: Path, target: Path, version: str) -> str:
    """Create a valid same-code wheel with a different metadata version for upgrade tests."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise RuntimeError(f"invalid test wheel version: {version}")
    with zipfile.ZipFile(source) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    metadata_paths = [name for name in members if name.endswith(".dist-info/METADATA")]
    if len(metadata_paths) != 1:
        raise RuntimeError("wheel must contain exactly one dist-info/METADATA")
    old_metadata = metadata_paths[0]
    old_prefix = old_metadata.rsplit("/", 1)[0]
    old_version_match = re.search(r"llm_first_loop-([0-9]+\.[0-9]+\.[0-9]+)\.dist-info$", old_prefix)
    if not old_version_match:
        raise RuntimeError("wheel dist-info path has an unexpected name")
    old_version = old_version_match.group(1)
    new_prefix = f"llm_first_loop-{version}.dist-info"
    renamed: dict[str, bytes] = {}
    for name, content in members.items():
        new_name = new_prefix + name[len(old_prefix):] if name.startswith(old_prefix + "/") else name
        if name == old_metadata:
            old_text = content.decode("utf-8")
            old_text, count = re.subn(
                rf"(?m)^Version: {re.escape(old_version)}$", f"Version: {version}", old_text, count=1,
            )
            if count != 1:
                raise RuntimeError("wheel METADATA did not contain the expected Version field")
            content = old_text.encode("utf-8")
        elif name == "llm_loop/_bundled/manifest.json":
            manifest = json.loads(content)
            if manifest.get("schema") != "lfl.application-bundle/v1":
                raise RuntimeError("wheel bundle manifest has an unexpected schema")
            manifest["version"] = version
            content = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        renamed[new_name] = content

    record_path = f"{new_prefix}/RECORD"
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name in sorted(renamed):
        content = renamed[name]
        if name == record_path:
            writer.writerow((name, "", ""))
        else:
            digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode("ascii").rstrip("=")
            writer.writerow((name, f"sha256={digest}", str(len(content))))
    renamed[record_path] = record.getvalue().encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(renamed.items()):
            archive.writestr(name, content)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def verify(wheel: Path, installer: Path, uninstaller: Path) -> dict[str, Any]:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("native Linux installer verification must run on Linux")
    if os.geteuid() == 0:
        raise RuntimeError("native Linux installer verification must run as a non-root user")
    if platform.machine() not in {"x86_64", "aarch64"}:
        raise RuntimeError(f"unsupported CI architecture: {platform.machine()}")
    libc, _ = platform.libc_ver()
    if libc.lower() != "glibc":
        raise RuntimeError(f"glibc Linux is required; detected libc={libc!r}")

    version, digest = wheel_identity(wheel)
    if not version:
        raise RuntimeError("wheel version is empty")
    result: dict[str, Any] = {
        "ok": False,
        "platform": sys.platform,
        "architecture": platform.machine(),
        "libc": libc,
        "version": version,
        "wheel_sha256": digest,
        "provider_invocations": 0,
    }

    with tempfile.TemporaryDirectory(prefix="lfl-linux-installer-smoke-") as temporary:
        temp = Path(temporary).resolve()
        home = temp / "home"
        scratch = temp / "tmp"
        home.mkdir(mode=0o700)
        scratch.mkdir(mode=0o700)
        data_home = home / ".local" / "share"
        app_home = data_home / "lfl"
        bin_home = home / ".local" / "bin"
        launcher = bin_home / "lfl"
        active = app_home / ".LFL-active-version"
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "TMPDIR": str(scratch),
            "XDG_DATA_HOME": str(data_home),
            "LFL_HOME": str(app_home),
            "PYTHONNOUSERSITE": "1",
            "UV_CACHE_DIR": str(temp / "uv-cache"),
            "UV_PYTHON_INSTALL_DIR": str(home / ".local" / "share" / "uv" / "python"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "SSL_CERT_FILE": os.environ.get("SSL_CERT_FILE", ""),
            "SSL_CERT_DIR": os.environ.get("SSL_CERT_DIR", ""),
        }
        env = {key: value for key, value in env.items() if value}
        cwd = temp

        run(
            ["bash", str(installer), "--candidate", str(wheel), "--expected-sha256", digest],
            env=env,
            cwd=cwd,
        )
        if not active.is_file() or active.read_text(encoding="ascii").strip() != version:
            raise RuntimeError("installer did not atomically activate the candidate version")
        if not launcher.is_file() or not os.access(launcher, os.X_OK):
            raise RuntimeError("user-level lfl launcher was not created")

        version_output = run([str(launcher), "--version"], env=env, cwd=cwd).stdout.strip()
        if version not in version_output:
            raise RuntimeError(f"installed CLI reported the wrong version: {version_output!r}")
        integrity = json.loads(run([str(launcher), "check-install"], env=env, cwd=cwd).stdout)
        if integrity.get("ok") is not True:
            raise RuntimeError(f"installed resource integrity failed: {integrity!r}")
        paths = json.loads(run([str(launcher), "paths"], env=env, cwd=cwd).stdout)
        if Path(paths["DATA_DIR"]) != app_home / "data":
            raise RuntimeError("installed DATA_DIR escaped the isolated LFL_HOME")
        if not Path(paths["SKILLS_DIR"]).is_relative_to(app_home / "releases" / f"LFL-{version}" / "venv"):
            raise RuntimeError("bundled resources are not isolated inside the installed environment")

        doctor = run([str(launcher), "doctor", "--json"], env=env, cwd=cwd, check=False)
        if doctor.returncode not in {0, 1}:
            raise RuntimeError(f"offline doctor returned unexpected exit code {doctor.returncode}")
        doctor_json = json.loads(doctor.stdout)
        if doctor_json.get("read_only") is not True:
            raise RuntimeError("doctor did not report read_only=true")

        repeated = run(
            ["bash", str(installer), "--candidate", str(wheel), "--expected-sha256", digest],
            env=env,
            cwd=cwd,
        )
        if active.read_text(encoding="ascii").strip() != version:
            raise RuntimeError("idempotent install changed the active version")
        if "already installed and active" not in repeated.stdout:
            raise RuntimeError("same-version reinstall did not take the idempotent path")

        wrong_digest = "0" * 64 if digest != "0" * 64 else "1" * 64
        bad = run(
            ["bash", str(installer), "--candidate", str(wheel), "--expected-sha256", wrong_digest],
            env=env,
            cwd=cwd,
            check=False,
        )
        if bad.returncode == 0 or active.read_text(encoding="ascii").strip() != version:
            raise RuntimeError("bad candidate digest was not rejected without changing the active version")

        major, minor, patch = (int(part) for part in version.split("."))
        upgrade_version = f"{major}.{minor}.{patch + 1}"
        upgrade_wheel = temp / f"llm_first_loop-{upgrade_version}-py3-none-any.whl"
        upgrade_digest = wheel_version_variant(wheel, upgrade_wheel, upgrade_version)
        upgraded = run(
            ["bash", str(installer), "--candidate", str(upgrade_wheel), "--expected-sha256", upgrade_digest],
            env=env,
            cwd=cwd,
        )
        if f"LFL {upgrade_version} is installed and active" not in upgraded.stdout:
            raise RuntimeError("upgrade did not report successful activation")
        previous = app_home / ".LFL-previous-version"
        if active.read_text(encoding="ascii").strip() != upgrade_version:
            raise RuntimeError("upgrade did not atomically activate the new version")
        if previous.read_text(encoding="ascii").strip() != version:
            raise RuntimeError("upgrade did not retain the previous version pointer")
        upgraded_version_output = run([str(launcher), "--version"], env=env, cwd=cwd).stdout.strip()
        if upgrade_version not in upgraded_version_output:
            raise RuntimeError("upgraded launcher did not execute the new version")

        rollback = run(["bash", str(installer), "--rollback"], env=env, cwd=cwd)
        if f"LFL rolled back: {upgrade_version} -> {version}" not in rollback.stdout:
            raise RuntimeError("rollback did not report the expected version transition")
        if active.read_text(encoding="ascii").strip() != version:
            raise RuntimeError("rollback did not restore the original active version")
        if previous.read_text(encoding="ascii").strip() != upgrade_version:
            raise RuntimeError("rollback did not retain the version it rolled back from")
        rolled_back_version_output = run([str(launcher), "--version"], env=env, cwd=cwd).stdout.strip()
        if version not in rolled_back_version_output:
            raise RuntimeError("launcher did not execute the rolled-back version")

        failed_version = f"{major}.{minor}.{patch + 2}"
        failed_wheel = temp / f"llm_first_loop-{failed_version}-py3-none-any.whl"
        failed_digest = wheel_version_variant(wheel, failed_wheel, failed_version)
        real_uv = shutil.which("uv", path=env["PATH"])
        if not real_uv:
            raise RuntimeError("uv is required for the native failed-upgrade acceptance")
        fail_bin = temp / "fail-uv-bin"
        fail_bin.mkdir(mode=0o700)
        uv_wrapper = fail_bin / "uv"
        uv_wrapper.write_text(
            "#!/bin/sh\n"
            "if [ \"${1:-}\" = pip ] && [ \"${2:-}\" = install ]; then\n"
            f"  case \"${{@}}\" in *{failed_wheel.name}*) exit 73 ;; esac\n"
            "fi\n"
            f"exec {shlex.quote(real_uv)} \"$@\"\n",
            encoding="utf-8",
        )
        uv_wrapper.chmod(0o755)
        failed_env = {**env, "PATH": f"{fail_bin}:{env['PATH']}"}
        failed_upgrade = run(
            ["bash", str(installer), "--candidate", str(failed_wheel), "--expected-sha256", failed_digest],
            env=failed_env,
            cwd=cwd,
            check=False,
        )
        if failed_upgrade.returncode == 0:
            raise RuntimeError("injected dependency-install failure unexpectedly succeeded")
        if active.read_text(encoding="ascii").strip() != version:
            raise RuntimeError("failed upgrade changed the active version pointer")
        if previous.read_text(encoding="ascii").strip() != upgrade_version:
            raise RuntimeError("failed upgrade changed the previous version pointer")
        if (app_home / "releases" / f"LFL-{failed_version}").exists():
            raise RuntimeError("failed upgrade left an incomplete release directory behind")
        if (app_home / ".linux-install.lock").exists():
            raise RuntimeError("failed upgrade left the install lock behind")

        config = app_home / ".env"
        session = app_home / "data" / "sessions" / "keep.jsonl"
        method = app_home / "data" / "methods" / "keep.json"
        config.write_text("LLM_MODEL=installer-smoke-only\n", encoding="utf-8")
        session.parent.mkdir(parents=True, exist_ok=True)
        session.write_text('{"session":"preserve"}\n', encoding="utf-8")
        method.parent.mkdir(parents=True, exist_ok=True)
        method.write_text('{"method":"preserve"}\n', encoding="utf-8")

        removed = run(["bash", str(uninstaller), "--yes"], env=env, cwd=cwd)
        if launcher.exists() or (app_home / "releases").exists():
            raise RuntimeError("uninstaller left managed application files behind")
        if active.exists() or (app_home / ".LFL-previous-version").exists():
            raise RuntimeError("uninstaller left active/previous version pointers behind")
        if not config.is_file() or not session.is_file() or not method.is_file():
            raise RuntimeError("uninstaller deleted user configuration or data")
        result.update(
            {
                "ok": True,
                "fresh_venv": True,
                "source_checkout_on_pythonpath": False,
                "resource_integrity": integrity,
                "doctor_read_only": True,
                "idempotent_reinstall": True,
                "bad_digest_rejected": True,
                "upgrade_switched_and_retained_previous": True,
                "rollback_restored_previous_version": True,
                "failed_upgrade_preserved_active_and_previous": True,
                "uninstall_preserved_user_data": True,
                "uninstall_summary": removed.stdout.strip(),
                "provider_invocations": 0,
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result: dict[str, Any]
    try:
        result = verify(
            args.wheel.resolve(strict=True),
            Path(__file__).with_name("install_linux.sh").resolve(strict=True),
            Path(__file__).with_name("uninstall_linux.sh").resolve(strict=True),
        )
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "provider_invocations": 0}
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
