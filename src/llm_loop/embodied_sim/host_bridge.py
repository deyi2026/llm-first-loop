"""Cross-UID M1 Oracle verification queue; only the Host may sign acceptance.

An unprivileged caller can submit a receipt for checking but cannot mutate the
UID463-owned replay ledger or the Host's verification response directory.
Only a signed, nonce-bound Host response may upgrade to VERIFIED_BY_ORACLE.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
import time
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature

from llm_loop.embodied_sim.attestation import (
    ATTEST_UID,
    PROD_PUBLIC_KEY_PATH,
    PROD_REPLAY_LEDGER_PATH,
    AttestationUnavailableError,
    ReplayLedger,
    _trusted_host_file,
    canonical,
    load_public_key,
    verify_attestation_host,
)
from llm_loop.embodied_sim.contract import VerificationStatus
from llm_loop.embodied_sim.oracle_daemon import PROD_PRIVATE_KEY_PATH, OracleDaemon
from llm_loop.embodied_sim.trial import EXPERIMENT_ID, validate_trial

PROD_VERIFY_JOBS_DIR = "/private/var/run/lfl-m1-oracle/verify-jobs"
PROD_VERIFY_RECEIPTS_DIR = "/private/var/run/lfl-m1-oracle/verify-receipts"
_BINDINGS = (
    "expected_run",
    "expected_epoch",
    "expected_action_seq",
    "expected_nonce",
    "expected_experiment_id",
    "expected_claim_kind",
)
_TRIAL_BINDINGS = _BINDINGS + ("expected_trial",)
_CORE = (
    "request_nonce",
    "receipt_sha256",
    "receipt_nonce",
    "run_id",
    "scene_epoch",
    "action_seq",
    "experiment_id",
    "claim_kind",
    "status",
    "uid",
)
_TRIAL_CORE = _CORE + ("trial",)


def _atomic_publish(path: Path, obj: dict[str, Any]) -> None:
    """Publish a complete, no-overwrite queue message across processes."""
    temp = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(temp, flags, 0o644)
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), 0o644)
            out.write(canonical(obj) + b"\n")
            out.flush()
            os.fsync(out.fileno())
        os.link(temp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()


def _binding_values(receipt: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    values = {
        "receipt_sha256": hashlib.sha256(canonical(receipt)).hexdigest(),
        "receipt_nonce": binding["expected_nonce"],
        "run_id": binding["expected_run"],
        "scene_epoch": binding["expected_epoch"],
        "action_seq": binding["expected_action_seq"],
        "experiment_id": binding["expected_experiment_id"],
        "claim_kind": binding["expected_claim_kind"],
    }
    if "expected_trial" in binding:
        values["trial"] = binding["expected_trial"]
    return values


def _signed_host_result(
    daemon: OracleDaemon,
    request_nonce: str,
    receipt: dict[str, Any],
    binding: dict[str, Any],
    status: VerificationStatus,
) -> dict[str, Any]:
    if (
        os.getuid() != ATTEST_UID
        or daemon._key_path != PROD_PRIVATE_KEY_PATH
        or not _trusted_host_file(daemon._key_path, owner=ATTEST_UID, private_key=True)
    ):
        raise AttestationUnavailableError("Host UID463 private key not trusted")
    core = {
        "request_nonce": request_nonce,
        **_binding_values(receipt, binding),
        "status": str(status.value),
        "uid": ATTEST_UID,
    }
    if daemon.trial is not None and "expected_trial" not in binding:
        raise AttestationUnavailableError("missing signed Host trial binding")
    return {**core, "signature": daemon._key.sign(canonical(core)).hex()}


def verify_host_response(
    response: dict[str, Any],
    *,
    request_nonce: str,
    receipt: dict[str, Any],
    binding: dict[str, Any],
    pubkey_path: str = PROD_PUBLIC_KEY_PATH,
) -> VerificationStatus:
    """No caller-chosen key or receipt can fabricate Host acceptance."""
    core_keys = _TRIAL_CORE if "expected_trial" in binding else _CORE
    if (
        pubkey_path != PROD_PUBLIC_KEY_PATH
        or not _trusted_host_file(pubkey_path, owner=0)
        or set(response) != set(core_keys) | {"signature"}
    ):
        return VerificationStatus.FAILED_CLAIM
    expected = {"request_nonce": request_nonce, **_binding_values(receipt, binding)}
    if any(type(response.get(k)) is not type(v) or response[k] != v for k, v in expected.items()):
        return VerificationStatus.FAILED_CLAIM
    if response.get("uid") != ATTEST_UID or response.get("status") not in {
        VerificationStatus.VERIFIED_BY_ORACLE.value,
        VerificationStatus.FAILED_CLAIM.value,
    }:
        return VerificationStatus.FAILED_CLAIM
    try:
        core = {key: response[key] for key in core_keys}
        load_public_key(pubkey_path).verify(bytes.fromhex(response["signature"]), canonical(core))
    except (InvalidSignature, OSError, ValueError, TypeError):
        return VerificationStatus.FAILED_CLAIM
    return VerificationStatus(response["status"])


def request_host_verification(
    receipt: dict[str, Any],
    *,
    expected_run: str,
    expected_epoch: int,
    expected_action_seq: int,
    expected_nonce: str,
    expected_experiment_id: str,
    expected_claim_kind: str = "place",
    expected_trial: dict[str, Any] | None = None,
    jobs_dir: str = PROD_VERIFY_JOBS_DIR,
    receipts_dir: str = PROD_VERIFY_RECEIPTS_DIR,
    timeout_s: float = 5.0,
) -> VerificationStatus:
    """Wait for a signed Host decision, never for a local self-declared success."""
    if not (Path(jobs_dir).is_dir() and Path(receipts_dir).is_dir()):
        raise AttestationUnavailableError("Host verification queue not installed")
    if not _trusted_host_file(PROD_PUBLIC_KEY_PATH, owner=0):
        raise AttestationUnavailableError("Host public key not trusted")
    binding = {
        "expected_run": expected_run,
        "expected_epoch": expected_epoch,
        "expected_action_seq": expected_action_seq,
        "expected_nonce": expected_nonce,
        "expected_experiment_id": expected_experiment_id,
        "expected_claim_kind": expected_claim_kind,
    }
    if expected_trial is not None:
        try:
            binding["expected_trial"] = validate_trial(expected_trial)
        except (ValueError, TypeError) as exc:
            raise AttestationUnavailableError(f"invalid Host trial binding: {exc}") from None
    elif expected_experiment_id == EXPERIMENT_ID:
        raise AttestationUnavailableError("new Host experiment requires trial binding")
    request_nonce = secrets.token_hex(16)
    job = {"request_nonce": request_nonce, "receipt": receipt, **binding}
    try:
        _atomic_publish(Path(jobs_dir) / f"{request_nonce}.verify.json", job)
    except OSError as exc:
        raise AttestationUnavailableError(f"Host verification submission failed: {exc}") from None
    path = Path(receipts_dir) / f"{request_nonce}.verified.json"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            try:
                response = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(response, dict):
                    raise ValueError("Host response must be object")
                return verify_host_response(
                    response,
                    request_nonce=request_nonce,
                    receipt=receipt,
                    binding=binding,
                    pubkey_path=PROD_PUBLIC_KEY_PATH,
                )
            except (OSError, ValueError, TypeError) as exc:
                raise AttestationUnavailableError(f"unreadable Host verification: {exc}") from None
        time.sleep(0.05)
    raise AttestationUnavailableError("Host verification daemon did not respond")


def process_verification_jobs(
    daemon: OracleDaemon,
    ledger: ReplayLedger,
    jobs_dir: str,
    receipts_dir: str,
) -> int:
    """UID463-only consumer: verify signed physics receipts and consume nonce."""
    if os.getuid() != ATTEST_UID or str(ledger.path) != PROD_REPLAY_LEDGER_PATH:
        raise AttestationUnavailableError("Host UID463 verifier required")
    count = 0
    for job_path in sorted(Path(jobs_dir).glob("*.verify.json")):
        try:
            request_nonce = job_path.name.removesuffix(".verify.json")
            if re.fullmatch(r"[0-9a-f]{32}", request_nonce) is None:
                continue
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(job_path, flags)
            with os.fdopen(fd, "rb") as inp:
                info = os.fstat(inp.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                    continue
                job = json.loads(inp.read(65537).decode("utf-8"))
            keys = _TRIAL_BINDINGS if daemon.trial is not None else _BINDINGS
            if not isinstance(job, dict) or set(job) != set(keys) | {
                "request_nonce",
                "receipt",
            }:
                continue
            if job["request_nonce"] != request_nonce or not isinstance(job["receipt"], dict):
                continue
            binding = {key: job[key] for key in keys}
            if (
                type(binding["expected_epoch"]) is not int
                or type(binding["expected_action_seq"]) is not int
                or binding["expected_run"] != daemon.run_id
                or binding["expected_experiment_id"] != daemon.experiment_id
                or (daemon.trial is not None and binding["expected_trial"] != daemon.trial)
            ):
                status = VerificationStatus.FAILED_CLAIM
            else:
                status = verify_attestation_host(
                    job["receipt"],
                    pubkey_path=PROD_PUBLIC_KEY_PATH,
                    replay_ledger=ledger,
                    **binding,
                )
            result = _signed_host_result(daemon, request_nonce, job["receipt"], binding, status)
            _atomic_publish(Path(receipts_dir) / f"{request_nonce}.verified.json", result)
            count += 1
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            pass  # malformed job cannot crash the daemon or produce acceptance
        finally:
            with contextlib.suppress(OSError):
                job_path.unlink()
    return count
