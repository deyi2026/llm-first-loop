#!/usr/bin/python3
"""Root-only, exact-manifest macOS installer for M1 UID463 Oracle.

Never run this file as root from a user-writable worktree. An operator must
first copy the reviewed installer and bundle into a root:wheel 0700 staging
directory, then supply the reviewed manifest SHA256. No existing LFL service,
sudoers rule, key, or previous oracle-worker installation is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import pwd
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path

TARGET = Path("/Library/PrivilegedHelperTools/lfl-m1-oracle-v1")
PYTHON = TARGET / "runtime/bin/python3.13"
SERVICE = TARGET / "m1_oracle_host_service.py"
KEY = Path("/usr/local/etc/lfl-m1-oracle-ed25519.key")
PUB = Path("/usr/local/etc/lfl-m1-oracle-ed25519.pub")
QUEUE = Path("/private/var/run/lfl-m1-oracle")
STATE = Path("/private/var/db/lfl-m1-oracle")
PLIST = Path("/Library/LaunchDaemons/com.lfl.m1-oracle.plist")
LABEL = "com.lfl.m1-oracle"
UID = 463
GID = 463
CLIENT_UID = 501
CLIENT_GID = 20


def _root_only() -> None:
    if os.getuid() != 0 or os.geteuid() != 0:
        raise RuntimeError("Host administrator/root required; no sudo bypass")


def _trusted(path: Path, *, owner: int = 0, directory: bool = False) -> bool:
    try:
        st = path.lstat()
        return (
            (stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode))
            and st.st_uid == owner
            and not st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        )
    except OSError:
        return False


def _check_account() -> None:
    oracle = pwd.getpwnam("_lfl_oracle")
    client = pwd.getpwnam("yyj")
    if (oracle.pw_uid, oracle.pw_gid) != (UID, GID):
        raise RuntimeError("Oracle account UID/GID mismatch")
    if (client.pw_uid, client.pw_gid) != (CLIENT_UID, CLIENT_GID):
        raise RuntimeError("client account UID/GID mismatch")
    if oracle.pw_shell != "/usr/bin/false" or oracle.pw_dir != "/var/empty":
        raise RuntimeError("Oracle account must not have login shell/home")


def _manifest(bundle: Path, expected_sha: str) -> dict:
    if not _trusted(bundle, directory=True) or not _trusted(bundle.parent, directory=True):
        raise RuntimeError("bundle and staging parent must be root-owned nonwritable")
    path = bundle / "manifest.json"
    if not _trusted(path):
        raise RuntimeError("manifest not root-owned")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise RuntimeError("reviewed manifest SHA256 mismatch")
    data = json.loads(raw)
    if data.get("schema") != "lfl.m1-oracle-host-bundle/v1":
        raise RuntimeError("unknown bundle schema")
    if not data.get("python", "").startswith("3.13.") or data.get("architecture") != "arm64":
        raise RuntimeError("wrong runtime version or architecture")
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("empty manifest")
    actual = set()
    for path in bundle.rglob("*"):
        if path.is_symlink() or not _trusted(path, directory=path.is_dir()):
            raise RuntimeError(f"untrusted bundle entry: {path}")
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise RuntimeError("hardlinked bundle file rejected")
            relative = path.relative_to(bundle).as_posix()
            actual.add(relative)
            if relative != "manifest.json" and hashlib.sha256(
                path.read_bytes()
            ).hexdigest() != files.get(relative):
                raise RuntimeError(f"bundle content mismatch: {relative}")
    if actual != set(files) | {"manifest.json"}:
        raise RuntimeError("bundle file set differs from reviewed manifest")
    return data


def _install_bundle(bundle: Path) -> None:
    if TARGET.exists() or TARGET.is_symlink():
        raise RuntimeError("refuse to overwrite an existing M1 Oracle installation")
    if not _trusted(TARGET.parent, directory=True):
        raise RuntimeError("untrusted privileged helper parent")
    shutil.copytree(bundle, TARGET, symlinks=False)
    for path in [TARGET, *TARGET.rglob("*")]:
        if path.is_symlink():
            raise RuntimeError("installed symlink rejected")
        os.chown(path, 0, 0)
        os.chmod(path, 0o755 if path.is_dir() or path == PYTHON else 0o644)


def _directory(path: Path, uid: int, gid: int, mode: int) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"refuse to reuse Host state path: {path}")
    path.mkdir(mode=mode)
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def _prepare_state() -> None:
    # /private/var/run is root:daemon 0775 on macOS. It is not a trust
    # anchor for signatures, only a parent of strictly owned queue dirs.
    if not _trusted(QUEUE.parent, directory=True) and (
        QUEUE.parent.stat().st_uid != 0 or QUEUE.parent.is_symlink()
    ):
        raise RuntimeError("untrusted queue parent")
    if not _trusted(STATE.parent, directory=True):
        raise RuntimeError("untrusted persistent ledger parent")
    _directory(QUEUE, 0, 0, 0o755)
    _directory(QUEUE / "jobs", CLIENT_UID, GID, 0o770)
    _directory(QUEUE / "verify-jobs", CLIENT_UID, GID, 0o770)
    for name in ("receipts", "verify-receipts"):
        _directory(QUEUE / name, UID, CLIENT_GID, 0o750)
    # run.json is discovery metadata, not an authorization secret. UID463
    # cannot chgrp it to staff (not a member), so expose it read-only.
    _directory(QUEUE / "runtime", UID, GID, 0o755)
    _directory(STATE, UID, GID, 0o700)
    dbpath = STATE / "verified-nonces.sqlite3"
    with sqlite3.connect(str(dbpath)) as db:
        db.execute("CREATE TABLE consumed (nonce TEXT PRIMARY KEY, receipt_sha256 TEXT NOT NULL)")
    os.chown(dbpath, UID, GID)
    os.chmod(dbpath, 0o600)


def _init_key() -> None:
    if not KEY.parent.exists():
        if not _trusted(KEY.parent.parent, directory=True):
            raise RuntimeError("untrusted /usr/local parent")
        _directory(KEY.parent, 0, 0, 0o755)
    if not _trusted(KEY.parent, directory=True):
        raise RuntimeError("untrusted Host key parent")
    if any(path.exists() or path.is_symlink() for path in (KEY, PUB)):
        raise RuntimeError("refuse to replace existing Host key")
    proc = subprocess.run(
        [str(PYTHON), "-I", "-S", "-B", str(SERVICE), "--init-key"],
        text=True,
        capture_output=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "HOME": "/var/empty"},
    )
    if proc.returncode or "HOST_KEY_INITIALIZED=PASS" not in proc.stdout:
        raise RuntimeError(f"Host key initialization failed: exit={proc.returncode}")


def _probe_isolated_runtime() -> None:
    command = [
        "/usr/bin/sudo",
        "-n",
        "-u",
        "_lfl_oracle",
        "/usr/bin/sandbox-exec",
        "-f",
        str(TARGET / "oracle.sb"),
        str(PYTHON),
        "-I",
        "-S",
        "-B",
        str(SERVICE),
        "--probe",
    ]
    proc = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=45,
        env={"PATH": "/usr/bin:/bin", "HOME": "/var/empty"},
    )
    if proc.returncode:
        raise RuntimeError(f"UID463 Seatbelt/Python3.13 preflight failed: exit={proc.returncode}")
    result = json.loads(proc.stdout)
    if result.get("HOST_ORACLE_PROBE") != "PASS" or result.get("uid") != UID:
        raise RuntimeError("UID463 preflight did not prove isolated runtime")


def _write_plist() -> None:
    if PLIST.exists() or PLIST.is_symlink():
        raise RuntimeError("refuse to overwrite existing LaunchDaemon")
    data = {
        "Label": LABEL,
        "ProgramArguments": [
            "/usr/bin/sandbox-exec",
            "-f",
            str(TARGET / "oracle.sb"),
            str(PYTHON),
            "-I",
            "-S",
            "-B",
            str(SERVICE),
            "--serve",
        ],
        "UserName": "_lfl_oracle",
        "GroupName": "_lfl_oracle",
        "WorkingDirectory": str(TARGET),
        "EnvironmentVariables": {"HOME": "/var/empty", "PATH": "/usr/bin:/bin"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(STATE / "daemon.out"),
        "StandardErrorPath": str(STATE / "daemon.err"),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(PLIST, flags, 0o644)
    with os.fdopen(fd, "wb") as out:
        os.fchmod(out.fileno(), 0o644)
        out.write(plistlib.dumps(data))
        out.flush()
        os.fsync(out.fileno())


def _service_health() -> dict:
    proc = subprocess.run(
        ["/bin/launchctl", "print", f"system/{LABEL}"],
        text=True,
        capture_output=True,
        timeout=10,
    )
    runfile = QUEUE / "runtime/run.json"
    if proc.returncode or not runfile.is_file() or runfile.is_symlink():
        raise RuntimeError("LaunchDaemon not running or no independent run metadata")
    if runfile.stat().st_uid != UID:
        raise RuntimeError("run metadata not owned by isolated UID463")
    info = json.loads(runfile.read_text())
    pid = info.get("pid")
    if type(pid) is not int or pid < 1:
        raise RuntimeError("invalid Host daemon PID")
    proc = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "uid=", "-o", "command="],
        text=True,
        capture_output=True,
        timeout=10,
    )
    fields = proc.stdout.strip().split(None, 1)
    if (
        proc.returncode
        or len(fields) != 2
        or fields[0] != str(UID)
        or str(SERVICE) not in fields[1]
        or "--serve" not in fields[1]
    ):
        raise RuntimeError("Host daemon PID not running as UID463")
    if (
        not isinstance(info.get("run_id"), str)
        or len(info["run_id"]) != 32
        or info.get("experiment_id") != "M1-SIM-001"
    ):
        raise RuntimeError("invalid Host run identity")
    return {"pid": pid, "uid": UID, "run_id": info.get("run_id")}


def _apply(bundle: Path, expected_sha: str) -> None:
    _root_only()
    if not _trusted(Path(__file__)) or not _trusted(Path(__file__).parent, directory=True):
        raise RuntimeError("installer must run from root-owned 0700 staging")
    _check_account()
    _manifest(bundle, expected_sha)
    if any(p.exists() or p.is_symlink() for p in (TARGET, QUEUE, STATE, KEY, PUB, PLIST)):
        raise RuntimeError("M1 Oracle paths already exist; refusing overwrite")
    _install_bundle(bundle)
    _manifest(TARGET, expected_sha)  # verify the root-owned copy before key creation
    _prepare_state()
    _init_key()
    _probe_isolated_runtime()
    _write_plist()
    subprocess.run(
        ["/bin/launchctl", "bootstrap", "system", str(PLIST)],
        check=True,
        timeout=20,
    )
    for _ in range(30):
        try:
            health = _service_health()
            print(json.dumps({"HOST_INSTALL": "PASS", "health": health}, sort_keys=True))
            return
        except (OSError, RuntimeError, ValueError):
            time.sleep(1)
    raise RuntimeError("Host service failed health check; preserve state for diagnosis")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("apply", "check", "stop"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    if args.action == "apply":
        if not args.bundle or not args.manifest_sha256:
            raise RuntimeError("apply requires root-owned bundle and reviewed manifest SHA")
        _apply(args.bundle, args.manifest_sha256)
    elif args.action == "check":
        print(json.dumps({"HOST_CHECK": "PASS", "health": _service_health()}, sort_keys=True))
    else:
        _root_only()
        subprocess.run(["/bin/launchctl", "bootout", f"system/{LABEL}"], check=True, timeout=20)
        print("HOST_STOP=PASS (keys and audit state preserved)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print("HOST_INSTALL=NO_GO " + str(exc), file=sys.stderr)
        sys.exit(77)
