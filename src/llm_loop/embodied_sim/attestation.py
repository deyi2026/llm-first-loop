"""Trusted Host attestation client for M1 oracle verdicts (fail-closed).

Trust boundary (re-designed after P0 review):
- The oracle daemon (oracle_daemon.py) must run as a HOST-OWNED separate
  process: it owns the live MuJoCoScene, executes ONLY whitelisted action
  commands, takes its own snapshots, and signs with an Ed25519 private key that
  callers cannot read or write (production path: UID463-owned, mode 0400
  /usr/local/etc/lfl-m1-oracle-ed25519.key).
- Clients hold at most the PUBLIC key. Verification is asymmetric; a locally
  forged receipt can never verify.
- The only client input channel is a strict action-command whitelist
  (move_to/grasp/release/observe/verify_grasp/verify_place). Snapshots, file paths, stdin JSON and
  arbitrary scripts are not an input surface anywhere.
- Receipts bind run_id, scene_epoch, action_seq, nonce and snapshot_hash.
  Verification checks expected bindings and a PERSISTENT replay ledger.
- If no Host-owned daemon is reachable (current sandbox: true), every request
  raises AttestationUnavailable and the caller must stay HOLD / PENDING_ORACLE.
- The public verifier is ADVISORY and never upgrades a claim to VERIFIED.
  Only the Host-owned verifier may consume the nonce and upgrade. Any local
  Python return value is untrusted until the Host acceptance is independently
  checked across the OS process boundary.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import secrets
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from llm_loop.embodied_sim.contract import VerificationStatus
from llm_loop.embodied_sim.trial import EXPERIMENT_ID, validate_trial

PROD_JOBS_DIR = "/private/var/run/lfl-m1-oracle/jobs"
PROD_RECEIPTS_DIR = "/private/var/run/lfl-m1-oracle/receipts"
PROD_PUBLIC_KEY_PATH = "/usr/local/etc/lfl-m1-oracle-ed25519.pub"
# macOS /private/var/run is root:daemon 0775. It cannot satisfy the
# trusted-host-file ancestor rule (no group-writable ancestors). Persist the
# single-use ledger under root-owned /private/var/db instead.
PROD_REPLAY_LEDGER_PATH = "/private/var/db/lfl-m1-oracle/verified-nonces.sqlite3"
ATTEST_UID = 463
ALLOWED_COMMANDS = {"move_to", "grasp", "release", "observe", "verify_grasp", "verify_place"}
WORKSPACE_BOUNDS = {"x": (-0.25, 0.35), "y": (-0.25, 0.35), "z": (0.005, 0.30)}


class AttestationUnavailableError(Exception):
    """No Host-owned oracle daemon reachable, or malformed client input."""


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(snapshot)).hexdigest()


def validate_command(command: dict[str, Any]) -> str:
    """Return the canonical skill name or raise AttestationUnavailable.

    Strict whitelist: skill in {move_to, grasp, release, observe,
    verify_grasp, verify_place}; move_to
    params must be numeric and inside the frozen workspace; grasp/release
    take no params; file paths, shell, python, snapshots are not accepted.
    """
    skill = command.get("skill")
    if skill not in ALLOWED_COMMANDS:
        raise AttestationUnavailableError(f"command not whitelisted: {skill!r}")
    if set(command) - {"skill", "params"}:
        raise AttestationUnavailableError("unexpected command fields")
    params = command.get("params", {})
    if not isinstance(params, dict):
        raise AttestationUnavailableError("params must be an object")
    if skill == "move_to":
        if set(params) != {"x", "y", "z"}:
            raise AttestationUnavailableError("move_to requires exactly x,y,z")
        for axis in ("x", "y", "z"):
            v = params.get(axis)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise AttestationUnavailableError(f"move_to param {axis} missing/non-numeric")
            try:
                numeric = float(v)
                valid = math.isfinite(numeric)
            except (OverflowError, ValueError):
                valid = False
            if not valid:
                raise AttestationUnavailableError(f"move_to param {axis} missing/non-numeric")
            lo, hi = WORKSPACE_BOUNDS[axis]
            if not (lo <= numeric <= hi):
                raise AttestationUnavailableError(f"move_to {axis}={v} outside workspace")
    else:
        if params:
            raise AttestationUnavailableError(f"{skill} takes no params")
    return str(skill)


class ReplayLedger:
    """Atomic, persistent single-use nonce store (SQLite UNIQUE constraint)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=3) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS consumed "
                "(nonce TEXT PRIMARY KEY, receipt_sha256 TEXT NOT NULL)"
            )

    def seen(self, nonce: str) -> bool:
        with sqlite3.connect(self.path, timeout=3) as db:
            return (
                db.execute("SELECT 1 FROM consumed WHERE nonce=?", (nonce,)).fetchone() is not None
            )

    def record(self, nonce: str, receipt_hash: str) -> bool:
        """True only for the first consumer, atomically across processes."""
        try:
            with sqlite3.connect(self.path, timeout=3) as db:
                db.execute(
                    "INSERT INTO consumed(nonce, receipt_sha256) VALUES (?, ?)",
                    (nonce, receipt_hash),
                )
            return True
        except sqlite3.IntegrityError:
            return False


def request_attestation(
    command: dict[str, Any],
    *,
    run_id: str,
    action_seq: int,
    jobs_dir: str = PROD_JOBS_DIR,
    receipts_dir: str = PROD_RECEIPTS_DIR,
    timeout_s: float = 5.0,
    poll_interval_s: float = 0.05,
) -> tuple[str, dict[str, Any]]:
    """Drop a whitelisted action command as a job file for the Host-owned daemon.

    Pure file IPC (no sockets): jobs/{nonce}.job -> receipts/{nonce}.receipt.json.
    Return the client-issued nonce SEPARATELY from the untrusted receipt.
    The daemon executes the action on ITS OWN live scene and returns a signed
    receipt binding run_id/scene_epoch/action_seq/nonce/snapshot_hash/uid463.
    Missing managed directories (any sandbox without the Host deployment)
    => AttestationUnavailableError, i.e. the caller must stay HOLD/PENDING.
    """
    validate_command(command)
    if not (Path(jobs_dir).is_dir() and Path(receipts_dir).is_dir()):
        raise AttestationUnavailableError(
            f"host oracle queue not present: {jobs_dir} / {receipts_dir}"
        )
    nonce = secrets.token_hex(16)
    job = {"command": command, "run_id": str(run_id), "action_seq": int(action_seq), "nonce": nonce}
    dest = Path(jobs_dir) / f"{nonce}.job"
    temp = Path(jobs_dir) / f".{nonce}.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        # The Host must never observe a partially written job. Publish the
        # complete payload with an atomic, no-overwrite hard link, just as the
        # daemon does for receipts. Directory ACLs govern cross-UID access.
        try:
            fd = os.open(temp, flags, 0o644)
            with os.fdopen(fd, "wb") as out:
                os.fchmod(out.fileno(), 0o644)
                out.write(canonical(job) + b"\n")
                out.flush()
                os.fsync(out.fileno())
            os.link(temp, dest)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temp.unlink()
    except OSError as exc:
        raise AttestationUnavailableError(f"host job submission failed: {exc}") from None
    receipt_path = Path(receipts_dir) / f"{nonce}.receipt.json"
    deadline = time.monotonic() + float(timeout_s)
    while time.monotonic() < deadline:
        if receipt_path.exists():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if not isinstance(receipt, dict):
                    raise ValueError("receipt must be an object")
                return nonce, receipt
            except (OSError, ValueError) as exc:
                raise AttestationUnavailableError(f"unreadable Host receipt: {exc}") from None
        time.sleep(poll_interval_s)
    raise AttestationUnavailableError("daemon did not process the request in time")


def load_public_key(pubkey_path: str) -> Ed25519PublicKey:
    raw = bytes.fromhex(Path(pubkey_path).read_text().strip())
    return Ed25519PublicKey.from_public_bytes(raw)


def _trusted_host_file(path: str, *, owner: int, private_key: bool = False) -> bool:
    """Reject caller-created trust anchors, symlinks, and writable parents."""
    try:
        p = Path(path)
        if p.is_symlink() or not p.is_file():
            return False
        st = p.stat()
        forbidden_mode = 0o077 if private_key else (stat.S_IWGRP | stat.S_IWOTH)
        if st.st_uid != owner or st.st_mode & forbidden_mode:
            return False
        parent = p.parent
        while parent != parent.parent:
            pst = parent.stat()
            # The nonce DB directory must be writable by the isolated Oracle
            # UID, never by the caller. All ancestors remain root-owned.
            # The private key lives in a root-owned directory so UID463 can
            # read but cannot replace the trust key. Only the SQLite ledger
            # needs a UID463-writable immediate parent for journal files.
            isolated_dir = owner == ATTEST_UID and parent == p.parent and not private_key
            allowed_owner = ATTEST_UID if isolated_dir else 0
            if (
                parent.is_symlink()
                or pst.st_uid != allowed_owner
                or pst.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            ):
                return False
            parent = parent.parent
        return True
    except OSError:
        return False


def _verify_attestation_impl(
    receipt: dict[str, Any],
    *,
    pubkey_path: str = PROD_PUBLIC_KEY_PATH,
    expected_run: str,
    expected_epoch: int,
    expected_action_seq: int,
    expected_nonce: str,
    expected_experiment_id: str,
    replay_ledger: ReplayLedger,
    expected_claim_kind: str = "place",
    host_authority: bool = False,
    expected_trial: dict[str, Any] | None = None,
) -> VerificationStatus:
    """Asymmetric verification with strict binding + persistent replay defence.

    Any mismatch is FAILED_CLAIM. There is no client-side path to VERIFIED:
    only a daemon-signed (uid 463) receipt with a valid Ed25519 signature and
    fresh nonce verifies; missing daemon => PENDING_ORACLE at request time.
    """
    required = {
        "claim_kind",
        "run_id",
        "scene_epoch",
        "action_seq",
        "nonce",
        "snapshot_hash",
        "oracle_execution",
        "verdict",
        "uid",
        "signature",
        "experiment_id",
        "oracle_impl",
        "evidence",
    }
    trial_bound = expected_experiment_id == EXPERIMENT_ID
    if trial_bound:
        try:
            if validate_trial(receipt.get("trial")) != validate_trial(expected_trial):
                return VerificationStatus.FAILED_CLAIM
        except (ValueError, TypeError):
            return VerificationStatus.FAILED_CLAIM
        required.add("trial")
    elif expected_trial is not None:
        return VerificationStatus.FAILED_CLAIM
    if any(k not in receipt for k in required):
        return VerificationStatus.FAILED_CLAIM
    if set(receipt) - required - {"daemon_public_key"}:
        return VerificationStatus.FAILED_CLAIM
    # Only the Host-installed, root-owned key is an identity. A caller-chosen
    # Ed25519 key is not a Host signature, even when the cryptography verifies.
    if pubkey_path != PROD_PUBLIC_KEY_PATH or not _trusted_host_file(pubkey_path, owner=0):
        return VerificationStatus.FAILED_CLAIM
    # Replay state must be Host-owned, not a user-resettable temporary file.
    if str(replay_ledger.path) != PROD_REPLAY_LEDGER_PATH or not _trusted_host_file(
        str(replay_ledger.path), owner=ATTEST_UID
    ):
        return VerificationStatus.FAILED_CLAIM
    if (
        receipt["claim_kind"] != expected_claim_kind
        or expected_claim_kind not in ("grasp", "place")
        or receipt["oracle_execution"] != "host_uid463_managed"
        or receipt.get("oracle_impl") != "embodied-m1-oracle-daemon-v0"
    ):
        return VerificationStatus.FAILED_CLAIM
    if str(receipt["run_id"]) != str(expected_run):
        return VerificationStatus.FAILED_CLAIM  # cross-run
    if str(receipt["experiment_id"]) != str(expected_experiment_id):
        return VerificationStatus.FAILED_CLAIM
    try:
        if int(receipt["scene_epoch"]) != int(expected_epoch):
            return VerificationStatus.FAILED_CLAIM
        if int(receipt["action_seq"]) != int(expected_action_seq):
            return VerificationStatus.FAILED_CLAIM
        if int(receipt["uid"]) != ATTEST_UID:
            return VerificationStatus.FAILED_CLAIM
    except (TypeError, ValueError):
        return VerificationStatus.FAILED_CLAIM
    if str(receipt["nonce"]) != str(expected_nonce):
        return VerificationStatus.FAILED_CLAIM  # nonce binding
    try:
        if replay_ledger.seen(str(receipt["nonce"])):
            return VerificationStatus.FAILED_CLAIM
    except (OSError, sqlite3.DatabaseError):
        return VerificationStatus.FAILED_CLAIM
    try:
        pubkey = load_public_key(pubkey_path)
        core = {
            k: receipt[k]
            for k in (
                "claim_kind",
                "run_id",
                "scene_epoch",
                "action_seq",
                "nonce",
                "snapshot_hash",
                "oracle_execution",
                "verdict",
                "uid",
                "experiment_id",
                "oracle_impl",
                "evidence",
            ) + (("trial",) if trial_bound else ())
        }
        pubkey.verify(bytes.fromhex(str(receipt["signature"])), canonical(core))
    except (InvalidSignature, ValueError, OSError):
        return VerificationStatus.FAILED_CLAIM  # forged/tampered/wrong key
    # A genuine daemon-signed failure is not a success claim.
    if str(receipt["verdict"]).lower() != "success":
        return VerificationStatus.FAILED_CLAIM
    if not host_authority:
        return VerificationStatus.PENDING_ORACLE
    receipt_sha = hashlib.sha256(canonical(receipt)).hexdigest()
    try:
        if not replay_ledger.record(str(receipt["nonce"]), receipt_sha):
            return VerificationStatus.FAILED_CLAIM
    except (OSError, sqlite3.DatabaseError):
        return VerificationStatus.FAILED_CLAIM
    return VerificationStatus.VERIFIED_BY_ORACLE


def verify_attestation(
    receipt: dict[str, Any],
    *,
    pubkey_path: str = PROD_PUBLIC_KEY_PATH,
    expected_run: str,
    expected_epoch: int,
    expected_action_seq: int,
    expected_nonce: str,
    expected_experiment_id: str,
    replay_ledger: ReplayLedger,
    expected_claim_kind: str = "place",
    expected_trial: dict[str, Any] | None = None,
) -> VerificationStatus:
    """Unprivileged advisory check. Never grants VERIFIED_BY_ORACLE."""
    return _verify_attestation_impl(
        receipt,
        pubkey_path=pubkey_path,
        expected_run=expected_run,
        expected_epoch=expected_epoch,
        expected_action_seq=expected_action_seq,
        expected_nonce=expected_nonce,
        expected_experiment_id=expected_experiment_id,
        replay_ledger=replay_ledger,
        expected_claim_kind=expected_claim_kind,
        expected_trial=expected_trial,
    )


def verify_attestation_host(
    receipt: dict[str, Any],
    *,
    pubkey_path: str = PROD_PUBLIC_KEY_PATH,
    expected_run: str,
    expected_epoch: int,
    expected_action_seq: int,
    expected_nonce: str,
    expected_experiment_id: str,
    replay_ledger: ReplayLedger,
    expected_claim_kind: str = "place",
    expected_trial: dict[str, Any] | None = None,
) -> VerificationStatus:
    """Host-only verifier. The consuming safety gate MUST run out of process."""
    if os.getuid() != ATTEST_UID:
        return VerificationStatus.FAILED_CLAIM
    return _verify_attestation_impl(
        receipt,
        pubkey_path=pubkey_path,
        expected_run=expected_run,
        expected_epoch=expected_epoch,
        expected_action_seq=expected_action_seq,
        expected_nonce=expected_nonce,
        expected_experiment_id=expected_experiment_id,
        replay_ledger=replay_ledger,
        expected_claim_kind=expected_claim_kind,
        host_authority=True,
        expected_trial=expected_trial,
    )
