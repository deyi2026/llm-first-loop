#!/usr/bin/python3
"""Root-staged, manifest-pinned M1-only Host upgrade, refresh and trial switch.

Never run from a user-writable worktree as root. No new key, ledger, sudoers,
robot, or existing LFL Web/Feishu/Learning/WeCom service is touched.
The old v1 bundle and root-owned plist backup remain for rollback.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

LABEL = "com.lfl.m1-oracle"
ROOT = Path("/Library/PrivilegedHelperTools")
OLD = ROOT / "lfl-m1-oracle-v1"
PLIST = Path("/Library/LaunchDaemons/com.lfl.m1-oracle.plist")
TRIAL_CONFIG = Path("/usr/local/etc/lfl-m1-oracle-trial.json")
RUN_INFO = Path("/private/var/run/lfl-m1-oracle/runtime/run.json")
QUEUE = Path("/private/var/run/lfl-m1-oracle")
PRIVATE = Path("/usr/local/etc/lfl-m1-oracle-ed25519.key")
PUBLIC = Path("/usr/local/etc/lfl-m1-oracle-ed25519.pub")
LEDGER = Path("/private/var/db/lfl-m1-oracle/verified-nonces.sqlite3")
STAGE = Path(__file__).absolute().parent
PAIRED_GRANT = Path("/usr/local/etc/lfl-m1-paired-grant.json")
PAIRED_LEDGER_DIR = Path("/usr/local/var/lfl-m1-paired-budget")
PAIRED_LEDGER = PAIRED_LEDGER_DIR / "m1-paired-cost-ledger.jsonl"
PAIRED_ISSUED = Path("/usr/local/etc/lfl-m1-paired-issued.jsonl")
PREREG_SHA256 = "d77a2550b17c71630bee1bdaddaf733cc240ac3bb67c662837d4f5f3b3f163d6"
PAIRED_EXPERIMENT = "M1-SIM-003"
PAIRED_MODEL = "deepseek/deepseek-v4-flash"
BATCH_USD_LIMIT = Decimal("20.00")
CALL_RESERVE_USD_LIMIT = Decimal("0.05")
MIN_INPUT_PER_MILLION_USD = Decimal("0.30")
MIN_OUTPUT_PER_MILLION_USD = Decimal("1.20")
BATCH_REQUIRED = frozenset({
    "schema", "batch_id", "experiment_id", "prereg_sha256", "candidate_sha",
    "model", "currency", "max_episodes", "max_provider_attempts",
    "max_tool_actions", "max_total_usd", "reserve_per_call_usd",
    "input_per_million_usd", "output_per_million_usd", "pricing_source",
    "pricing_checked_at_utc", "expires_at_utc", "ledger_path",
})


def _validate_batch_plan(plan: dict, *, now: datetime | None = None) -> None:
    """Independent root-side frozen identity, USD and expiry validation."""
    if not isinstance(plan, dict) or set(plan) != BATCH_REQUIRED:
        raise RuntimeError("paired grant fields mismatch")
    if (plan["schema"] != "lfl.m1-paired-cost-grant/v1"
            or plan["experiment_id"] != PAIRED_EXPERIMENT
            or plan["model"] != PAIRED_MODEL
            or plan["currency"] != "USD"
            or plan["prereg_sha256"] != PREREG_SHA256
            or re.fullmatch(r"[0-9a-f]{40}", str(plan["candidate_sha"])) is None
            or re.fullmatch(r"[0-9a-f]{32}", str(plan["batch_id"])) is None
            or plan["ledger_path"] != str(PAIRED_LEDGER)):
        raise RuntimeError("paired grant identity mismatch")
    if (type(plan["max_episodes"]) is not int or plan["max_episodes"] != 60
            or type(plan["max_provider_attempts"]) is not int
            or plan["max_provider_attempts"] != 360
            or type(plan["max_tool_actions"]) is not int
            or plan["max_tool_actions"] != 480):
        raise RuntimeError("paired grant frozen limits mismatch")
    try:
        values = [Decimal(plan[k]) for k in (
            "max_total_usd", "reserve_per_call_usd",
            "input_per_million_usd", "output_per_million_usd")]
    except (InvalidOperation, TypeError) as exc:
        raise RuntimeError("paired grant USD tariff invalid") from exc
    cap, reserve, rate_in, rate_out = values
    if (not all(isinstance(plan[k], str) for k in (
            "max_total_usd", "reserve_per_call_usd",
            "input_per_million_usd", "output_per_million_usd"))
            or not all(v.is_finite() for v in values)
            or cap <= 0 or not 0 < reserve <= cap
            or min(rate_in, rate_out) < 0 or max(rate_in, rate_out) == 0):
        raise RuntimeError("paired grant USD limits invalid")
    if (cap > BATCH_USD_LIMIT or reserve > CALL_RESERVE_USD_LIMIT
            or rate_in < MIN_INPUT_PER_MILLION_USD
            or rate_out < MIN_OUTPUT_PER_MILLION_USD):
        raise RuntimeError("paired grant exceeds approved USD ceiling or understates tariff")
    if not isinstance(plan["pricing_source"], str) or not plan["pricing_source"].strip():
        raise RuntimeError("paired grant pricing provenance missing")
    try:
        checked = datetime.fromisoformat(str(plan["pricing_checked_at_utc"]).replace("Z", "+00:00"))
        expiry = datetime.fromisoformat(str(plan["expires_at_utc"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("paired grant timestamp invalid") from exc
    clock = now or datetime.now(UTC)
    if (checked.tzinfo is None or expiry.tzinfo is None
            or checked > clock or expiry <= clock):
        raise RuntimeError("paired grant expired or pricing unqualified")


def _trusted(path: Path, *, owner: int = 0, directory: bool = False) -> bool:
    try:
        info = path.lstat()
        return (
            (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid == owner
            and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            and (directory or info.st_nlink == 1)
        )
    except OSError:
        return False


def _root_stage() -> None:
    if os.getuid() != 0 or os.geteuid() != 0:
        raise RuntimeError("Host administrator/root required")
    if (STAGE.parent != Path("/private/var/db")
            or not STAGE.name.startswith("lfl-m1-oracle-upgrade-")
            or not _trusted(STAGE.parent, directory=True)
            or not _trusted(STAGE, directory=True)
            or stat.S_IMODE(STAGE.stat().st_mode) != 0o700
            or not _trusted(Path(__file__))):
        raise RuntimeError("upgrade must run from root:wheel 0700 staging")


def _manifest(bundle: Path, expected_sha: str) -> dict:
    if not _trusted(bundle, directory=True) or not _trusted(bundle.parent, directory=True):
        raise RuntimeError("untrusted root-owned Host bundle")
    path = bundle / "manifest.json"
    if not _trusted(path):
        raise RuntimeError("untrusted Host manifest")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise RuntimeError("reviewed Host manifest SHA mismatch")
    info = json.loads(raw)
    if (info.get("schema") != "lfl.m1-oracle-host-bundle/v1"
            or not str(info.get("python", "")).startswith("3.13.")
            or info.get("architecture") != "arm64"
            or re.fullmatch(r"[0-9a-f]{40}", str(info.get("git_head"))) is None
            or not isinstance(info.get("files"), dict) or not info["files"]):
        raise RuntimeError("invalid Host bundle identity/runtime")
    found = set()
    for entry in bundle.rglob("*"):
        if not _trusted(entry, directory=entry.is_dir()):
            raise RuntimeError(f"untrusted Host bundle entry: {entry}")
        if entry.is_file():
            name = entry.relative_to(bundle).as_posix()
            found.add(name)
            if name != "manifest.json" and hashlib.sha256(entry.read_bytes()).hexdigest() != info["files"].get(name):
                raise RuntimeError(f"Host bundle content mismatch: {name}")
    if found != set(info["files"]) | {"manifest.json"}:
        raise RuntimeError("Host bundle file set mismatch")
    return info


def _config(phase: str, arm: str, index: int,
            experiment_id: str = "M1-SIM-002") -> tuple[dict, bytes]:
    # The installed Host validates the SAME frozen rules independently.
    if phase not in ("smoke", "paired") or arm not in ("B1", "B2"):
        raise RuntimeError("unknown experiment phase or comparison arm")
    if experiment_id not in ("M1-SIM-002", PAIRED_EXPERIMENT):
        raise RuntimeError("unknown frozen experiment identity")
    count, start = (10, 0) if phase == "smoke" else (30, 20261117)
    if type(index) is not int or not 0 <= index < count:
        raise RuntimeError("trial index outside frozen range")
    trial = {"phase": phase, "arm": arm, "trial_index": index, "seed": start + index}
    payload = {"schema": "lfl.m1-oracle-host-trial/v1",
               "experiment_id": experiment_id, "trial": trial}
    return trial, (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _authorize_batch(expected_run: str, plan_path: Path, expected_sha: str) -> dict:
    """Separate administrator action: stage one root-owned 60-episode grant."""
    _root_stage()
    current = _current(expected_run, experiment=PAIRED_EXPERIMENT)
    if current.get("trial", {}).get("phase") != "smoke":
        raise RuntimeError("batch authorization requires an idle smoke Host")
    if (plan_path.parent != STAGE or not _trusted(plan_path)
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None):
        raise RuntimeError("batch plan must be root-staged and SHA-pinned")
    raw = plan_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise RuntimeError("batch grant SHA mismatch")
    plan = json.loads(raw)
    _validate_batch_plan(plan)
    if any(p.exists() or p.is_symlink() for p in (
            PAIRED_GRANT, PAIRED_ISSUED, PAIRED_LEDGER, PAIRED_LEDGER_DIR)):
        raise RuntimeError("batch grant or ledger already exists; refuse overwrite")
    uid = int(os.environ.get("SUDO_UID", "0"))
    if uid < 500 or uid == 463:
        raise RuntimeError("interactive administrator's non-Oracle UID required")
    PAIRED_LEDGER_DIR.parent.mkdir(mode=0o755, exist_ok=True)
    if not _trusted(PAIRED_LEDGER_DIR.parent, directory=True):
        raise RuntimeError("paired ledger parent not root-controlled")
    PAIRED_LEDGER_DIR.mkdir(mode=0o755)
    try:
        fd = os.open(PAIRED_LEDGER, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.fchown(fd, uid, 0)
            os.fsync(fd)
        finally:
            os.close(fd)
        _atomic(PAIRED_ISSUED, b"", 0o600)
        _atomic(PAIRED_GRANT, raw, 0o644)
    except BaseException:
        if not PAIRED_GRANT.exists():
            PAIRED_ISSUED.unlink(missing_ok=True)
            PAIRED_LEDGER.unlink(missing_ok=True)
            with suppress(OSError):
                PAIRED_LEDGER_DIR.rmdir()
        raise
    return {"HOST_BATCH_AUTH": "READY_NOT_STARTED", "grant_sha256": expected_sha,
            "batch_id": plan["batch_id"], "max_episodes": 60,
            "max_provider_attempts": 360, "max_tool_actions": 480,
            "max_total_usd": plan["max_total_usd"]}


@contextmanager
def _paired_issue(expected_run: str, trial: dict):
    """Root-only, non-replayable paired trial issuance; failure consumes identity."""
    _root_stage()
    _current(expected_run, experiment=PAIRED_EXPERIMENT)
    if (trial.get("phase") != "paired" or trial.get("arm") not in ("B1", "B2")
            or type(trial.get("trial_index")) is not int
            or not 0 <= trial["trial_index"] < 30
            or trial.get("seed") != 20261117 + trial["trial_index"]):
        raise RuntimeError("paired Host trial identity outside frozen range")
    if (not _trusted(PAIRED_GRANT) or not _trusted(PAIRED_ISSUED)
            or stat.S_IMODE(PAIRED_ISSUED.stat().st_mode) != 0o600
            or not _trusted(PAIRED_LEDGER_DIR, directory=True)):
        raise RuntimeError("independent paired Host grant not installed")
    ledger_info = PAIRED_LEDGER.lstat()
    caller_uid = int(os.environ.get("SUDO_UID", "0"))
    if (not stat.S_ISREG(ledger_info.st_mode) or ledger_info.st_uid != caller_uid
            or ledger_info.st_uid < 500
            or ledger_info.st_uid == 463 or ledger_info.st_nlink != 1
            or ledger_info.st_mode & 0o077):
        raise RuntimeError("paired cost ledger not a protected operator file")
    raw = PAIRED_GRANT.read_bytes()
    _validate_batch_plan(json.loads(raw))
    grant_sha = hashlib.sha256(raw).hexdigest()
    with PAIRED_ISSUED.open("r+", encoding="utf-8") as issued:
        fcntl.flock(issued, fcntl.LOCK_EX)
        entries = [json.loads(line) for line in issued if line.strip()]
        if (len(entries) >= 60
                or any(entry.get("grant_sha256") != grant_sha for entry in entries)
                or any(entry.get("arm") == trial["arm"]
                       and entry.get("trial_index") == trial["trial_index"]
                       for entry in entries)):
            raise RuntimeError("paired Host trial replay or batch cap")
        issued.seek(0, os.SEEK_END)
        issued.write(json.dumps({
            "grant_sha256": grant_sha, "arm": trial["arm"],
            "trial_index": trial["trial_index"], "seed": trial["seed"],
            "expected_run": expected_run, "issued_at_utc": datetime.now(UTC).isoformat(),
        }, sort_keys=True) + "\n")
        issued.flush()
        os.fsync(issued.fileno())
        yield


def _atomic(path: Path, data: bytes, mode: int = 0o644) -> None:
    if not _trusted(path.parent, directory=True):
        raise RuntimeError("untrusted Host configuration parent")
    temp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchown(out.fileno(), 0, 0)
            os.fchmod(out.fileno(), mode)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _plist() -> tuple[dict, bytes]:
    if not _trusted(PLIST) or not _trusted(PLIST.parent, directory=True):
        raise RuntimeError("untrusted M1 LaunchDaemon plist")
    raw = PLIST.read_bytes()
    data = plistlib.loads(raw)
    if (data.get("Label") != LABEL or data.get("UserName") != "_lfl_oracle"
            or data.get("GroupName") != "_lfl_oracle"
            or data.get("KeepAlive") is not True
            or data.get("ProgramArguments", [None])[0] != "/usr/bin/sandbox-exec"):
        raise RuntimeError("M1 LaunchDaemon identity mismatch")
    return data, raw


def _current(expected_run: str, *, experiment: str) -> dict:
    if not _trusted(RUN_INFO, owner=463):
        raise RuntimeError("untrusted UID463 run metadata")
    info = json.loads(RUN_INFO.read_text())
    if (info.get("run_id") != expected_run or info.get("experiment_id") != experiment
            or type(info.get("pid")) is not int):
        raise RuntimeError("Host run changed or experiment identity mismatch")
    proc = subprocess.run(["/bin/ps", "-p", str(info["pid"]), "-o", "uid=", "-o", "command="],
                          capture_output=True, text=True, check=True, timeout=10)
    if not proc.stdout.strip().startswith("463 ") or "m1_oracle_host_service.py --serve" not in proc.stdout:
        raise RuntimeError("Host PID is not isolated UID463 service")
    for name in ("jobs", "verify-jobs"):
        directory = QUEUE / name
        if any(directory.iterdir()):
            raise RuntimeError(f"Host {name} queue not idle; refuse restart")
    if (not _trusted(PRIVATE, owner=463) or stat.S_IMODE(PRIVATE.stat().st_mode) != 0o400
            or not _trusted(PUBLIC) or not _trusted(LEDGER, owner=463)):
        raise RuntimeError("existing Host identity or replay ledger untrusted")
    return info


def _new_plist(old: dict, target: Path) -> bytes:
    data = dict(old)
    data["ProgramArguments"] = [
        "/usr/bin/sandbox-exec", "-f", str(target / "oracle.sb"),
        str(target / "runtime/bin/python3.13"), "-I", "-S", "-B",
        str(target / "m1_oracle_host_service.py"), "--serve",
    ]
    data["WorkingDirectory"] = str(target)
    return plistlib.dumps(data)


def _install(bundle: Path, expected_sha: str) -> Path:
    target = ROOT / f"lfl-m1-oracle-v2-{expected_sha[:12]}"
    if not _trusted(ROOT, directory=True) or target.exists() or target.is_symlink():
        raise RuntimeError("new versioned Host target already exists or parent untrusted")
    shutil.copytree(bundle, target, symlinks=False)
    for entry in (target, *target.rglob("*")):
        if entry.is_symlink():
            raise RuntimeError("installed Host symlink rejected")
        os.chown(entry, 0, 0)
        os.chmod(entry, 0o755 if entry.is_dir() or entry == target / "runtime/bin/python3.13" else 0o644)
    _manifest(target, expected_sha)
    return target


def _launch(*args: str) -> None:
    subprocess.run(["/bin/launchctl", *args], check=True, timeout=25)


def _health(previous_run: str, trial: dict | None, target: Path,
            experiment_id: str | None = None) -> dict:
    for _ in range(40):
        try:
            if not _trusted(RUN_INFO, owner=463):
                raise RuntimeError("UID463 run file missing")
            info = json.loads(RUN_INFO.read_text())
            expected_experiment = experiment_id or ("M1-SIM-002" if trial else "M1-SIM-001")
            if (info.get("run_id") == previous_run or info.get("trial") != trial
                    or info.get("experiment_id") != expected_experiment
                    or type(info.get("scene_epoch")) is not int or info["scene_epoch"] != 1):
                raise RuntimeError("Host run identity not yet refreshed")
            proc = subprocess.run(["/bin/ps", "-p", str(info["pid"]), "-o", "uid=", "-o", "command="],
                                  capture_output=True, text=True, timeout=5)
            if (proc.returncode or not proc.stdout.strip().startswith("463 ")
                    or str(target / "m1_oracle_host_service.py") not in proc.stdout):
                raise RuntimeError("new Host PID/path not confirmed")
            return info
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            time.sleep(0.5)
    raise RuntimeError("new Host failed UID463 run/trial health gate")


def _upgrade(bundle: Path, sha: str, expected_run: str, trial: dict, config: bytes) -> dict:
    _root_stage()
    old = _current(expected_run, experiment="M1-SIM-001")
    plist, original = _plist()
    if str(OLD / "m1_oracle_host_service.py") not in plist["ProgramArguments"]:
        raise RuntimeError("existing Host not running original v1")
    if TRIAL_CONFIG.exists() or TRIAL_CONFIG.is_symlink():
        raise RuntimeError("Host trial config already exists; refuse overwrite")
    _manifest(bundle, sha)
    backup = STAGE / "old.plist"
    if backup.exists() or backup.is_symlink():
        raise RuntimeError("upgrade backup already exists")
    public_sha = hashlib.sha256(PUBLIC.read_bytes()).hexdigest()
    target = _install(bundle, sha)
    _atomic(backup, original, 0o600)
    _atomic(TRIAL_CONFIG, config)
    try:
        probe = subprocess.run([
            "/usr/bin/sudo", "-n", "-u", "_lfl_oracle", "/usr/bin/sandbox-exec",
            "-f", str(target / "oracle.sb"), str(target / "runtime/bin/python3.13"),
            "-I", "-S", "-B", str(target / "m1_oracle_host_service.py"), "--probe",
        ], capture_output=True, text=True, timeout=45,
            env={"PATH": "/usr/bin:/bin", "HOME": "/var/empty"})
        if (probe.returncode or json.loads(probe.stdout).get("trial") != trial
                or json.loads(probe.stdout).get("uid") != 463):
            raise RuntimeError(f"new UID463 Seatbelt trial probe failed: exit={probe.returncode}")
    except BaseException:
        # Preflight failure must NOT interrupt the still-running v1 Host.
        TRIAL_CONFIG.unlink(missing_ok=True)
        raise
    try:
        _launch("bootout", f"system/{LABEL}")
        _atomic(PLIST, _new_plist(plist, target))
        _launch("bootstrap", "system", str(PLIST))
        new = _health(expected_run, trial, target)
        if new["pid"] == old["pid"]:
            raise RuntimeError("Host PID unchanged after upgrade")
        if hashlib.sha256(PUBLIC.read_bytes()).hexdigest() != public_sha:
            raise RuntimeError("Host public key changed during upgrade")
    except BaseException:
        subprocess.run(["/bin/launchctl", "bootout", f"system/{LABEL}"], capture_output=True)
        _atomic(PLIST, original)
        TRIAL_CONFIG.unlink(missing_ok=True)
        _launch("bootstrap", "system", str(PLIST))
        _health(expected_run, None, OLD)
        raise
    return {"HOST_UPGRADE": "PASS", "old_run": old["run_id"], "new_run": new["run_id"],
            "uid": 463, "target": str(target), "trial": trial,
            "public_key_sha256": public_sha, "rollback_plist": str(backup)}


def _refresh_bundle(bundle: Path, sha: str, expected_run: str,
                    trial: dict, config: bytes) -> dict:
    """One Host-only v2 refresh from GLM smoke to DeepSeek smoke, with rollback."""
    _root_stage()
    if (json.loads(config)["experiment_id"] != PAIRED_EXPERIMENT
            or trial["phase"] != "smoke"):
        raise RuntimeError("Host refresh requires M1-SIM-003 engineering smoke only")
    old = _current(expected_run, experiment="M1-SIM-002")
    if old.get("trial", {}).get("phase") != "smoke" or not _trusted(TRIAL_CONFIG):
        raise RuntimeError("Host refresh requires trusted idle M1-SIM-002 smoke")
    plist, original_plist = _plist()
    old_target = Path(plist["WorkingDirectory"])
    if (old_target.parent != ROOT or not old_target.name.startswith("lfl-m1-oracle-v2-")
            or not _trusted(old_target, directory=True)
            or str(old_target / "m1_oracle_host_service.py") not in plist["ProgramArguments"]):
        raise RuntimeError("Host refresh requires trusted installed v2")
    old_config = TRIAL_CONFIG.read_bytes()
    if json.loads(old_config) != {"schema": "lfl.m1-oracle-host-trial/v1",
                                  "experiment_id": "M1-SIM-002", "trial": old["trial"]}:
        raise RuntimeError("active Host config mismatch before refresh")
    if any(p.exists() or p.is_symlink() for p in (PAIRED_GRANT, PAIRED_ISSUED, PAIRED_LEDGER)):
        raise RuntimeError("Host refresh refuses existing paired grant/ledger")
    _manifest(bundle, sha)
    backup = STAGE / "old-v2.plist"
    if backup.exists() or backup.is_symlink():
        raise RuntimeError("Host refresh backup already exists")
    public_sha = hashlib.sha256(PUBLIC.read_bytes()).hexdigest()
    target = _install(bundle, sha)
    _atomic(backup, original_plist, 0o600)
    _atomic(TRIAL_CONFIG, config)
    try:
        probe = subprocess.run([
            "/usr/bin/sudo", "-n", "-u", "_lfl_oracle", "/usr/bin/sandbox-exec",
            "-f", str(target / "oracle.sb"), str(target / "runtime/bin/python3.13"),
            "-I", "-S", "-B", str(target / "m1_oracle_host_service.py"), "--probe",
        ], capture_output=True, text=True, timeout=45,
            env={"PATH": "/usr/bin:/bin", "HOME": "/var/empty"})
        result = json.loads(probe.stdout) if probe.returncode == 0 else {}
        if (probe.returncode or result.get("uid") != 463
                or result.get("trial") != trial
                or result.get("experiment_id") != PAIRED_EXPERIMENT):
            raise RuntimeError("new DeepSeek UID463 Seatbelt Host probe failed")
    except BaseException:
        _atomic(TRIAL_CONFIG, old_config)
        raise
    try:
        _launch("bootout", f"system/{LABEL}")
        _atomic(PLIST, _new_plist(plist, target))
        _launch("bootstrap", "system", str(PLIST))
        new = _health(expected_run, trial, target, PAIRED_EXPERIMENT)
        if (new["pid"] == old["pid"]
                or hashlib.sha256(PUBLIC.read_bytes()).hexdigest() != public_sha):
            raise RuntimeError("Host refresh PID or public-key verification failed")
    except BaseException:
        subprocess.run(["/bin/launchctl", "bootout", f"system/{LABEL}"], capture_output=True)
        _atomic(PLIST, original_plist)
        _atomic(TRIAL_CONFIG, old_config)
        _launch("bootstrap", "system", str(PLIST))
        _health(expected_run, old["trial"], old_target, "M1-SIM-002")
        raise
    return {"HOST_REFRESH": "PASS", "old_run": old["run_id"],
            "new_run": new["run_id"], "uid": 463,
            "experiment_id": PAIRED_EXPERIMENT, "trial": trial,
            "target": str(target), "rollback_plist": str(backup),
            "public_key_sha256": public_sha}


def _switch_host_only(expected_run: str, trial: dict, config: bytes) -> dict:
    _root_stage()
    if not _trusted(TRIAL_CONFIG):
        raise RuntimeError("installed Host trial config untrusted")
    new_experiment = json.loads(config)["experiment_id"]
    old_experiment = json.loads(TRIAL_CONFIG.read_bytes())["experiment_id"]
    old = _current(expected_run, experiment=old_experiment)
    plist, _ = _plist()
    target = Path(plist["WorkingDirectory"])
    if (target.parent != ROOT or not target.name.startswith("lfl-m1-oracle-v2-")
            or not _trusted(target, directory=True) or not _trusted(TRIAL_CONFIG)):
        raise RuntimeError("Host v2 target/config untrusted")
    original = TRIAL_CONFIG.read_bytes()
    if (json.loads(original).get("trial") != old.get("trial")
            or old_experiment not in ("M1-SIM-002", PAIRED_EXPERIMENT)
            or new_experiment not in ("M1-SIM-002", PAIRED_EXPERIMENT)):
        raise RuntimeError("installed trial config differs from active Host run")
    if old["trial"] == trial and old_experiment == new_experiment:
        raise RuntimeError("refuse same-trial restart without explicit new identity")
    _atomic(TRIAL_CONFIG, config)
    try:
        _launch("kickstart", "-k", f"system/{LABEL}")
        new = _health(expected_run, trial, target, new_experiment)
        if new["pid"] == old["pid"]:
            raise RuntimeError("Host PID unchanged after trial switch")
    except BaseException:
        _atomic(TRIAL_CONFIG, original)
        _launch("kickstart", "-k", f"system/{LABEL}")
        _health(expected_run, old["trial"], target, old_experiment)
        raise
    return {"HOST_TRIAL_SWITCH": "PASS", "old_run": old["run_id"],
            "new_run": new["run_id"], "uid": 463, "trial": trial}


def _switch(expected_run: str, trial: dict, config: bytes) -> dict:
    if trial["phase"] != "paired":
        return _switch_host_only(expected_run, trial, config)
    if json.loads(config)["experiment_id"] != PAIRED_EXPERIMENT:
        raise RuntimeError("paired Host trial requires DeepSeek frozen experiment")
    with _paired_issue(expected_run, trial):
        return _switch_host_only(expected_run, trial, config)


def _rollback(expected_run: str) -> dict:
    _root_stage()
    old_experiment = json.loads(TRIAL_CONFIG.read_bytes())["experiment_id"]
    _current(expected_run, experiment=old_experiment)
    old_plist = STAGE / "old.plist"
    if not _trusted(old_plist) or stat.S_IMODE(old_plist.stat().st_mode) != 0o600:
        raise RuntimeError("trusted original v1 plist backup missing")
    backup = old_plist.read_bytes()
    if str(OLD / "m1_oracle_host_service.py") not in plistlib.loads(backup)["ProgramArguments"]:
        raise RuntimeError("rollback backup not the original v1 Host")
    _launch("bootout", f"system/{LABEL}")
    _atomic(PLIST, backup)
    TRIAL_CONFIG.unlink(missing_ok=True)
    _launch("bootstrap", "system", str(PLIST))
    new = _health(expected_run, None, OLD)
    return {"HOST_ROLLBACK": "PASS", "new_run": new["run_id"], "uid": 463}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("upgrade", "refresh-bundle", "switch",
                                          "rollback", "authorize-batch"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--batch-plan", type=Path)
    parser.add_argument("--batch-sha256")
    parser.add_argument("--expected-run-id", required=True)
    parser.add_argument("--phase", choices=("smoke", "paired"))
    parser.add_argument("--arm", choices=("B1", "B2"))
    parser.add_argument("--trial-index", type=int)
    parser.add_argument("--experiment-id", choices=("M1-SIM-002", PAIRED_EXPERIMENT),
                        default="M1-SIM-002")
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{32}", args.expected_run_id) is None:
        raise RuntimeError("expected run ID must be exact 32-character hex")
    if args.action == "rollback":
        result = _rollback(args.expected_run_id)
    elif args.action == "authorize-batch":
        if (args.batch_plan is None or not args.batch_plan.is_absolute()
                or re.fullmatch(r"[0-9a-f]{64}", args.batch_sha256 or "") is None
                or any(v is not None for v in (args.phase, args.arm, args.trial_index))):
            raise RuntimeError("separate batch authorization needs pinned root plan only")
        result = _authorize_batch(args.expected_run_id, args.batch_plan,
                                  args.batch_sha256)
    else:
        if args.phase is None or args.arm is None or args.trial_index is None:
            raise RuntimeError("trial phase, arm and index are mandatory")
        trial, config = _config(args.phase, args.arm, args.trial_index,
                                experiment_id=args.experiment_id)
        if args.action in ("upgrade", "refresh-bundle"):
            if (args.bundle is None or not args.bundle.is_absolute()
                    or re.fullmatch(r"[0-9a-f]{64}", args.manifest_sha256 or "") is None):
                raise RuntimeError("upgrade requires root-owned bundle and reviewed manifest SHA")
            if args.action == "refresh-bundle":
                result = _refresh_bundle(args.bundle, args.manifest_sha256,
                                         args.expected_run_id, trial, config)
            else:
                if args.experiment_id != "M1-SIM-002":
                    raise RuntimeError("legacy Host v1 upgrade must retain M1-SIM-002")
                result = _upgrade(args.bundle, args.manifest_sha256, args.expected_run_id,
                                  trial, config)
        else:
            result = _switch(args.expected_run_id, trial, config)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print("HOST_UPGRADE=NO_GO " + str(exc), file=sys.stderr)
        sys.exit(77)
