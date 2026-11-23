"""M1 safety contracts (fail-closed), aligned with frozen M0 contract style.

- scene_epoch: increments on every reset; observation refs are epoch-bound.
- observation_ref TTL: expired refs are rejected, never silently accepted.
- grant_version: skill grants carry monotonically increasing versions; revoke
  invalidates all prior versions.
- intent_key: idempotent action submission.
- UNKNOWN: frozen append-only ledger (sha-chained); read-only reconciliation.
- stop: request and confirmation are separate, explicit steps.
- success claims: only Oracle receipts can produce VERIFIED_BY_ORACLE; a
  success claim without a valid Oracle receipt is FAILED_CLAIM, never VERIFIED.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any

from llm_loop.embodied_sim.goal_binding import goal_digest

DEFAULT_OBSERVATION_TTL_S = 1.0


class ContractViolationError(Exception):
    """Base class; fail-closed callers must catch and surface, not swallow."""


class ObservationExpiredError(ContractViolationError):
    pass


class EpochMismatchError(ContractViolationError):
    pass


class GrantRevokedError(ContractViolationError):
    pass


class DuplicateIntentError(ContractViolationError):
    pass


class StopNotRequestedError(ContractViolationError):
    pass


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_ORACLE = "PENDING_ORACLE"
    VERIFIED_BY_ORACLE = "VERIFIED_BY_ORACLE"
    FAILED_CLAIM = "FAILED_CLAIM"


class ObservationTicket:
    __slots__ = ("ref", "scene_epoch", "issued_at", "expires_at")

    def __init__(self, ref: str, scene_epoch: int, issued_at: float, ttl_s: float):
        self.ref = ref
        self.scene_epoch = int(scene_epoch)
        self.issued_at = float(issued_at)
        self.expires_at = float(issued_at) + float(ttl_s)

    def expired(self, now: float) -> bool:
        return now >= self.expires_at


class ContractKernel:
    """Epoch + observation-ref TTL."""

    def __init__(self, clock: Callable[[], float] | None = None,
                 observation_ttl_s: float = DEFAULT_OBSERVATION_TTL_S):
        self._clock = clock or time.monotonic
        self.observation_ttl_s = float(observation_ttl_s)
        self._seq = 0

    def issue_observation_ref(self, scene_epoch: int) -> ObservationTicket:
        self._seq += 1
        now = self._clock()
        ref = f"obs-epoch{scene_epoch}-{self._seq:08d}"
        return ObservationTicket(ref, scene_epoch, now, self.observation_ttl_s)

    def check_observation(self, ticket: ObservationTicket, current_epoch: int,
                          now: float | None = None) -> str:
        n = self._clock() if now is None else now
        if int(current_epoch) != ticket.scene_epoch:
            raise EpochMismatchError(f"observation {ticket.ref} bound to epoch {ticket.scene_epoch}, scene at {current_epoch}")
        if ticket.expired(n):
            raise ObservationExpiredError(f"observation {ticket.ref} expired at {ticket.expires_at:.3f}")
        return ticket.ref


class GrantRegistry:
    """skill -> {version, revoked}. revoke bumps version; all prior versions invalid."""

    def __init__(self) -> None:
        self._grants: dict[str, dict[str, Any]] = {}

    def grant(self, skill: str) -> int:
        rec = self._grants.setdefault(skill, {"version": 1, "revoked": False})
        if rec["revoked"]:
            rec["version"] += 1
            rec["revoked"] = False
        return int(rec["version"])

    def revoke(self, skill: str) -> int:
        rec = self._grants.get(skill)
        if rec is None:
            raise KeyError(f"no grant for skill {skill}")
        rec["revoked"] = True
        rec["version"] += 1
        return int(rec["version"])

    def check(self, skill: str, version: int) -> bool:
        rec = self._grants.get(skill)
        if rec is None or rec["revoked"]:
            return False
        return int(version) == int(rec["version"])


class IntentLedger:
    """intent_key -> action_id; exactly-once submission."""

    def __init__(self) -> None:
        self._map: dict[str, str] = {}

    def submit(self, intent_key: str, factory: Callable[[], str]) -> tuple[str, bool]:
        existing = self._map.get(intent_key)
        if existing is not None:
            return existing, False
        action_id = factory()
        self._map[str(intent_key)] = action_id
        return action_id, True


class FrozenLedger:
    """Append-only sha-chained JSONL; read-only reconcile. UNKNOWN facts land here."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        prev_sha = self._last_sha()
        body = dict(record)
        body["prev_sha256"] = prev_sha
        blob = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        body["sha256"] = hashlib.sha256(blob).hexdigest()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n")
        return body

    def _last_sha(self) -> str:
        if not self.path.exists():
            return "GENESIS"
        last = self.path.read_text(encoding="utf-8").strip().splitlines()
        if not last:
            return "GENESIS"
        return json.loads(last[-1]).get("sha256", "GENESIS")

    def reconcile(self) -> dict[str, Any]:
        """Read-only integrity check over the whole chain."""
        if not self.path.exists():
            return {"records": 0, "chain_ok": True}
        prev = "GENESIS"
        count = 0
        broken_at = None
        for line in self.path.read_text(encoding="utf-8").strip().splitlines():
            rec = json.loads(line)
            body = {k: v for k, v in rec.items() if k != "sha256"}
            blob = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if rec.get("prev_sha256") != prev or hashlib.sha256(blob).hexdigest() != rec.get("sha256"):
                broken_at = count
                break
            prev = rec["sha256"]
            count += 1
        return {"records": count, "chain_ok": broken_at is None, "broken_at": broken_at}


class StopController:
    """stop request and confirmation are separate explicit steps."""

    def __init__(self) -> None:
        self._requested: dict[str, str] = {}
        self._confirmed: set[str] = set()
        self._seq = 0

    def request(self, reason: str) -> dict[str, str]:
        self._seq += 1
        stop_id = f"stop-{self._seq:06d}"
        self._requested[stop_id] = str(reason)
        return {"stop_id": stop_id, "state": "requested", "reason": str(reason)}

    def confirm(self, stop_id: str) -> dict[str, str]:
        if stop_id not in self._requested:
            raise StopNotRequestedError(f"cannot confirm unknown stop {stop_id}")
        self._confirmed.add(stop_id)
        return {"stop_id": stop_id, "state": "confirmed"}

    def is_confirmed(self, stop_id: str) -> bool:
        return stop_id in self._confirmed


class ClaimGuard:
    """Success claims: VERIFIED_BY_ORACLE only via valid Oracle receipt."""

    def __init__(self) -> None:
        self._receipts: dict[str, dict[str, Any]] = {}

    def register_receipt(self, claim_key: str, receipt: dict[str, Any]) -> None:
        self._receipts[str(claim_key)] = dict(receipt)

    def evaluate_claim(self, claim_key: str, claimed_success: bool,
                       expected_scene_epoch: int, *,
                       expected_goal_digest: str | None = None) -> VerificationStatus:
        receipt = self._receipts.get(str(claim_key))
        if not claimed_success:
            return VerificationStatus.UNVERIFIED
        if receipt is None:
            # A success claim without any Oracle receipt is a FAILED_CLAIM, never VERIFIED.
            return VerificationStatus.FAILED_CLAIM
        return verify_receipt_fields(receipt, expected_scene_epoch,
                                     expected_goal_digest=expected_goal_digest)


# Marker for the future Host-managed independent channel. Gate B callers can
# NEVER reach VERIFIED_BY_ORACLE from verify_receipt_fields: every field in a
# caller-supplied dict (including oracle_execution and any host_acceptance
# block) is model-editable and untrusted. Promotion to VERIFIED happens only in
# the Gate C dedicated Host verifier, which checks a real signature over the
# receipt and the independent UID-463 execution channel; it must NOT reuse this
# dict-based function. In-process physical success therefore caps at
# PENDING_ORACLE here, with FAILED_CLAIM reserved for integrity tampering.
INDEPENDENT_ORACLE_EXECUTION = "host_uid_463_managed"


def _goal_block_matches(goal: Any, expected_goal_digest: str | None) -> bool:
    """A `goal` block is self-consistent and (when given) matches the expected goal."""
    if not isinstance(goal, dict):
        return False
    kind = goal.get("kind")
    pos = goal.get("pos")
    digest = goal.get("digest")
    if not isinstance(kind, str) or not isinstance(digest, str):
        return False
    if not isinstance(pos, (list, tuple)) or len(pos) < 3:
        return False
    try:
        recomputed = goal_digest(kind, pos)
    except (TypeError, ValueError):
        return False
    if recomputed != digest:
        return False
    return expected_goal_digest is None or digest == str(expected_goal_digest)


def verify_receipt_fields(receipt: dict[str, Any], expected_scene_epoch: int, *,
                          expected_goal_digest: str | None = None) -> VerificationStatus:
    """Fail-closed receipt validation. Anything missing/stale/mismatched is FAILED_CLAIM.

    Otherwise the result is at most PENDING_ORACLE: caller-supplied dicts cannot
    prove independence, so VERIFIED_BY_ORACLE is unreachable from this function
    by construction (see INDEPENDENT_ORACLE_EXECUTION note above).

    `expected_goal_digest` binds the receipt to the goal observed for THIS claim
    (M2). A `goal` block is validated whenever it is present — a block whose
    digest does not match its own pose, or a block for a different goal than the
    one the caller observed, is FAILED_CLAIM. A receipt that carries no goal block
    is FAILED_CLAIM as soon as the caller supplies an expected digest; only the
    legacy M1 shape (no block, no expectation) keeps its old epoch/verdict path.
    """
    required = ("experiment_id", "scene_epoch", "verdict", "oracle_impl", "oracle_execution",
                "snapshot_sha256", "evidence")
    if any(k not in receipt for k in required):
        return VerificationStatus.FAILED_CLAIM
    goal = receipt.get("goal")
    if goal is None:
        if expected_goal_digest is not None:
            return VerificationStatus.FAILED_CLAIM
    elif not _goal_block_matches(goal, expected_goal_digest):
        # Fail closed even when the caller passed no expectation: a tampered block
        # must never be waved through by the absence of an expected digest.
        return VerificationStatus.FAILED_CLAIM
    elif goal.get("scene_epoch") is not None:
        # The block claims a scene epoch; it must agree with the receipt's own.
        block_epoch = goal.get("scene_epoch")
        receipt_epoch = receipt.get("scene_epoch")
        if block_epoch is not None:
            if not isinstance(block_epoch, int) or not isinstance(receipt_epoch, int):
                return VerificationStatus.FAILED_CLAIM
            if block_epoch != receipt_epoch:
                return VerificationStatus.FAILED_CLAIM
    if int(receipt["scene_epoch"]) != int(expected_scene_epoch):
        return VerificationStatus.FAILED_CLAIM
    if str(receipt["verdict"]).lower() != "success":
        return VerificationStatus.FAILED_CLAIM
    return VerificationStatus.PENDING_ORACLE
