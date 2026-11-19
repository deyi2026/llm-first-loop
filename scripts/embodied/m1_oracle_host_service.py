#!/usr/bin/env python3
"""Fixed root-owned entrypoint for the independent macOS M1 Oracle.

Installed at /Library/PrivilegedHelperTools/lfl-m1-oracle-v2-<manifest>. Never run from
the project worktree as a privileged service. Only --init-key runs as root;
--probe/--serve require the isolated _lfl_oracle UID/GID 463.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import sys
import time
from pathlib import Path

ROOT = Path(__file__).absolute().parent
PYTHON = ROOT / "runtime/bin/python3.13"
VENDOR = ROOT / "vendor"
SRC = ROOT / "src"
PRIVATE = Path("/usr/local/etc/lfl-m1-oracle-ed25519.key")
PUBLIC = Path("/usr/local/etc/lfl-m1-oracle-ed25519.pub")
QUEUE_ROOT = Path("/private/var/run/lfl-m1-oracle")
STATE_ROOT = Path("/private/var/db/lfl-m1-oracle")
TRIAL_CONFIG = Path("/usr/local/etc/lfl-m1-oracle-trial.json")


def _trusted(path: Path, *, uid: int = 0, directory: bool = False) -> bool:
    try:
        st = path.lstat()
        return (
            (stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode))
            and st.st_uid == uid
            and not st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        )
    except OSError:
        return False


def _bootstrap() -> None:
    if Path(sys.executable) != PYTHON or sys.flags.isolated != 1 or sys.flags.no_site != 1:
        raise RuntimeError("fixed Python3.13 -I -S entrypoint required")
    if (ROOT.parent != Path("/Library/PrivilegedHelperTools")
            or re.fullmatch(r"lfl-m1-oracle-v2-[0-9a-f]{12}", ROOT.name) is None
            or not _trusted(ROOT.parent, directory=True)):
        raise RuntimeError("untrusted versioned Host installation path")
    for directory in (ROOT, ROOT / "runtime", VENDOR, SRC, SRC / "llm_loop"):
        if not _trusted(directory, directory=True):
            raise RuntimeError(f"untrusted root-owned runtime directory: {directory}")
    for file in (PYTHON, Path(__file__), SRC / "llm_loop/embodied_sim/oracle_daemon.py"):
        if not _trusted(file):
            raise RuntimeError(f"untrusted root-owned runtime file: {file}")
    sys.path.insert(0, str(VENDOR))
    sys.path.insert(0, str(SRC))


def _load_trial() -> dict:
    """Read a bounded root-owned config; client queues cannot choose seeds."""
    from llm_loop.embodied_sim.trial import validate_host_config

    if not _trusted(TRIAL_CONFIG.parent, directory=True):
        raise RuntimeError("untrusted Host trial configuration parent")
    fd = os.open(TRIAL_CONFIG, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as inp:
        info = os.fstat(inp.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) != 0o644 or info.st_nlink != 1
                or not 0 < info.st_size <= 512):
            raise RuntimeError("Host trial configuration ownership/mode/size invalid")
        return validate_host_config(json.loads(inp.read(513)))


def _write_key(path: Path, raw: bytes, uid: int, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, mode)
    with os.fdopen(fd, "wb") as out:
        os.fchmod(out.fileno(), mode)
        os.fchown(out.fileno(), uid, 0)
        out.write(raw.hex().encode("ascii") + b"\n")
        out.flush()
        os.fsync(out.fileno())


def _init_key() -> int:
    if os.getuid() != 0 or os.geteuid() != 0:
        raise RuntimeError("root required to create Host identity")
    if not _trusted(PRIVATE.parent, directory=True):
        raise RuntimeError("private-key parent must be root-owned and nonwritable")
    if PRIVATE.exists() or PRIVATE.is_symlink() or PUBLIC.exists() or PUBLIC.is_symlink():
        raise RuntimeError("refuse to overwrite an existing Host key")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    key = Ed25519PrivateKey.generate()
    raw_private = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw_public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    try:
        _write_key(PRIVATE, raw_private, 463, 0o400)
        _write_key(PUBLIC, raw_public, 0, 0o644)
    except BaseException:
        PRIVATE.unlink(missing_ok=True)
        PUBLIC.unlink(missing_ok=True)
        raise
    print("HOST_KEY_INITIALIZED=PASS public_sha256=" + hashlib.sha256(raw_public).hexdigest())
    return 0


def _check_host_state() -> None:
    from llm_loop.embodied_sim.attestation import (
        PROD_PUBLIC_KEY_PATH,
        PROD_REPLAY_LEDGER_PATH,
        _trusted_host_file,
    )
    from llm_loop.embodied_sim.oracle_daemon import PROD_PRIVATE_KEY_PATH

    if os.getuid() != 463 or os.geteuid() != 463 or os.getgid() != 463:
        raise RuntimeError("UID/GID 463 required")
    if (
        str(PRIVATE) != PROD_PRIVATE_KEY_PATH
        or str(PUBLIC) != PROD_PUBLIC_KEY_PATH
        or str(STATE_ROOT / "verified-nonces.sqlite3") != PROD_REPLAY_LEDGER_PATH
    ):
        raise RuntimeError("installed Host trust paths differ from code")
    if not _trusted_host_file(str(PRIVATE), owner=463, private_key=True):
        raise RuntimeError("private key ownership or ancestor invalid")
    if not _trusted_host_file(str(PUBLIC), owner=0):
        raise RuntimeError("public key ownership or ancestor invalid")
    if not _trusted_host_file(PROD_REPLAY_LEDGER_PATH, owner=463):
        raise RuntimeError("replay ledger ownership or ancestor invalid")
    expected_dirs = {
        "jobs": (501, 463, 0o770),
        "verify-jobs": (501, 463, 0o770),
        "receipts": (463, 20, 0o750),
        "verify-receipts": (463, 20, 0o750),
        "runtime": (463, 463, 0o755),
    }
    if not _trusted(QUEUE_ROOT, directory=True):
        raise RuntimeError("untrusted root-owned Host queue directory")
    for name, (uid, gid, mode) in expected_dirs.items():
        path = QUEUE_ROOT / name
        try:
            st = path.lstat()
        except OSError as exc:
            raise RuntimeError(f"Host queue missing: {name}: {exc}") from None
        if (
            not stat.S_ISDIR(st.st_mode)
            or st.st_uid != uid
            or st.st_gid != gid
            or stat.S_IMODE(st.st_mode) != mode
        ):
            raise RuntimeError(f"Host queue ownership/mode mismatch: {name}")


def _publish_run_info(run_id: str, scene_epoch: int, trial: dict) -> None:
    from llm_loop.embodied_sim.trial import EXPERIMENT_ID

    directory = QUEUE_ROOT / "runtime"
    if not _trusted(directory, uid=463, directory=True):
        raise RuntimeError("untrusted runtime metadata directory")
    path = directory / "run.json"
    temp = directory / f".run.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp, flags, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        os.fchmod(out.fileno(), 0o644)
        out.write(
            json.dumps(
                {
                    "run_id": run_id,
                    "scene_epoch": scene_epoch,
                    "experiment_id": EXPERIMENT_ID,
                    "pid": os.getpid(),
                    "trial": trial,
                },
                sort_keys=True,
            )
            + "\n"
        )
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)


def _run(*, serve: bool) -> int:
    _check_host_state()
    from llm_loop.embodied_sim.attestation import ReplayLedger
    from llm_loop.embodied_sim.host_bridge import process_verification_jobs
    from llm_loop.embodied_sim.oracle_daemon import build_daemon_from_scene_seed
    from llm_loop.embodied_sim.trial import EXPERIMENT_ID

    trial = _load_trial()
    run_id = secrets.token_hex(16)
    daemon = build_daemon_from_scene_seed(trial["seed"], run_id, str(PRIVATE), trial=trial)
    ledger = ReplayLedger(STATE_ROOT / "verified-nonces.sqlite3")
    if not serve:
        print(
            json.dumps(
                {
                    "HOST_ORACLE_PROBE": "PASS",
                    "uid": os.getuid(),
                    "scene_epoch": daemon.scene.scene_epoch,
                    "experiment_id": EXPERIMENT_ID,
                    "trial": trial,
                    "public_sha256": hashlib.sha256(
                        bytes.fromhex(daemon.public_key_hex)
                    ).hexdigest(),
                },
                sort_keys=True,
            )
        )
        return 0
    _publish_run_info(run_id, daemon.scene.scene_epoch, trial)
    while True:
        daemon.process_pending(str(QUEUE_ROOT / "jobs"), str(QUEUE_ROOT / "receipts"))
        process_verification_jobs(
            daemon,
            ledger,
            str(QUEUE_ROOT / "verify-jobs"),
            str(QUEUE_ROOT / "verify-receipts"),
        )
        time.sleep(0.25)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("--init-key", "--probe", "--serve"):
        raise RuntimeError("fixed --init-key / --probe / --serve only")
    _bootstrap()
    if sys.argv[1] == "--init-key":
        return _init_key()
    return _run(serve=sys.argv[1] == "--serve")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print("HOST_ORACLE=NO_GO " + str(exc), file=sys.stderr)
        sys.exit(77)
