"""Fail-closed M1 paired-call cost gate. No tariff, grant or receipt => no call.

The USD value is a tariff-based estimate, not an account invoice. Unknown
provider usage or a transport timeout leaves the batch on HOLD until an
operator reconciles billing; it is never silently counted as zero.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from llm_loop.embodied_sim.usage import estimate_usd

GRANT_PATH = Path("/usr/local/etc/lfl-m1-paired-grant.json")
LEDGER_DIR = Path("/usr/local/var/lfl-m1-paired-budget")
PREREG_RELATIVE = Path("experiments/embodied/prereg-m1-sim-003.json")
# Operator-selected ceilings for this one M1-SIM-003 batch. They do not issue
# a Host grant or authorize any paired Provider request.
BATCH_USD_LIMIT = Decimal("20.00")
CALL_RESERVE_USD_LIMIT = Decimal("0.05")
MIN_INPUT_PER_MILLION_USD = Decimal("0.30")
MIN_OUTPUT_PER_MILLION_USD = Decimal("1.20")
REQUIRED = frozenset({
    "schema", "batch_id", "experiment_id", "prereg_sha256", "candidate_sha",
    "model", "currency", "max_episodes", "max_provider_attempts",
    "max_tool_actions", "max_total_usd", "reserve_per_call_usd",
    "input_per_million_usd", "output_per_million_usd", "pricing_source",
    "pricing_checked_at_utc", "expires_at_utc", "ledger_path",
})


class PairedCostHold(RuntimeError):  # noqa: N818 - typed HOLD outcome
    """Typed stop; provider_attempted differentiates preflight from wire failure."""

    def __init__(self, code: str, *, provider_attempted: bool = False):
        super().__init__(code)
        self.code = code
        self.provider_attempted = provider_attempted


def _positive_usd(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise PairedCostHold("USD_AMOUNT_NOT_STRING")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise PairedCostHold("USD_AMOUNT_INVALID") from exc
    if not number.is_finite() or number <= 0:
        raise PairedCostHold("USD_AMOUNT_NOT_POSITIVE")
    return number


def validate_plan(plan: Any, *, prereg_sha: str, candidate_sha: str,
                  now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(plan, dict) or set(plan) != REQUIRED:
        raise PairedCostHold("GRANT_SCHEMA_FIELDS")
    if (plan["schema"] != "lfl.m1-paired-cost-grant/v1"
            or plan["experiment_id"] != "M1-SIM-003"
            or plan["model"] != "deepseek/deepseek-v4-flash"
            or plan["currency"] != "USD"
            or plan["prereg_sha256"] != prereg_sha
            or plan["candidate_sha"] != candidate_sha
            or re.fullmatch(r"[0-9a-f]{32}", str(plan["batch_id"])) is None):
        raise PairedCostHold("GRANT_IDENTITY_MISMATCH")
    if (type(plan["max_episodes"]) is not int or plan["max_episodes"] != 60
            or type(plan["max_provider_attempts"]) is not int
            or plan["max_provider_attempts"] != 360
            or type(plan["max_tool_actions"]) is not int
            or plan["max_tool_actions"] != 480):
        raise PairedCostHold("GRANT_FROZEN_LIMITS_MISMATCH")
    cap = _positive_usd(plan["max_total_usd"])
    reserve = _positive_usd(plan["reserve_per_call_usd"])
    if reserve > cap:
        raise PairedCostHold("CALL_RESERVE_EXCEEDS_TOTAL")
    if cap > BATCH_USD_LIMIT or reserve > CALL_RESERVE_USD_LIMIT:
        raise PairedCostHold("PAIRED_APPROVED_USD_CEILING_EXCEEDED")
    try:
        estimate_usd({"usage_status": "reported", "prompt_tokens": 1,
                      "completion_tokens": 1}, input_per_million=plan["input_per_million_usd"],
                     output_per_million=plan["output_per_million_usd"])
    except (ValueError, TypeError) as exc:
        raise PairedCostHold("GRANT_TARIFF_INVALID") from exc
    if (Decimal(plan["input_per_million_usd"]) < MIN_INPUT_PER_MILLION_USD
            or Decimal(plan["output_per_million_usd"]) < MIN_OUTPUT_PER_MILLION_USD):
        raise PairedCostHold("GRANT_TARIFF_UNDER_REFERENCE")
    if not isinstance(plan["pricing_source"], str) or not plan["pricing_source"].strip():
        raise PairedCostHold("GRANT_PRICING_SOURCE_MISSING")
    try:
        expiry = datetime.fromisoformat(str(plan["expires_at_utc"]).replace("Z", "+00:00"))
        checked = datetime.fromisoformat(str(plan["pricing_checked_at_utc"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PairedCostHold("GRANT_TIMESTAMP_INVALID") from exc
    clock = now or datetime.now(UTC)
    if (expiry.tzinfo is None or checked.tzinfo is None
            or expiry <= clock or checked > clock):
        raise PairedCostHold("GRANT_EXPIRED_OR_UNQUALIFIED")
    ledger = Path(str(plan["ledger_path"]))
    if not ledger.is_absolute() or ledger.name != "m1-paired-cost-ledger.jsonl":
        raise PairedCostHold("GRANT_LEDGER_PATH_INVALID")
    return plan


class PairedCostGate:
    """One durable reservation per real Provider request, serialized by flock."""

    def __init__(self, plan: dict[str, Any], ledger_path: Path, plan_sha: str,
                 *, run_id: str = "", trial: dict[str, Any] | None = None):
        self.plan = plan
        self.ledger_path = ledger_path
        self.plan_sha = plan_sha
        self.run_id = run_id
        self.trial = trial

    @classmethod
    def load(cls, repo: Path, *, candidate_sha: str,
             run: dict[str, Any]) -> PairedCostGate:
        trial = run.get("trial", {})
        if (run.get("experiment_id") != "M1-SIM-003"
                or trial.get("phase") != "paired"
                or trial.get("arm") not in ("B1", "B2")
                or type(trial.get("trial_index")) is not int
                or not 0 <= trial["trial_index"] < 30
                or trial.get("seed") != 20261117 + trial["trial_index"]
                or re.fullmatch(r"[0-9a-f]{32}", str(run.get("run_id"))) is None):
            raise PairedCostHold("PAIRED_RUN_IDENTITY_INVALID")
        info = GRANT_PATH.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or info.st_nlink != 1):
            raise PairedCostHold("GRANT_NOT_ROOT_OWNED")
        raw = GRANT_PATH.read_bytes()
        plan = validate_plan(
            json.loads(raw),
            prereg_sha=hashlib.sha256((repo / PREREG_RELATIVE).read_bytes()).hexdigest(),
            candidate_sha=candidate_sha,
        )
        ledger = Path(plan["ledger_path"])
        parent = ledger.parent.lstat()
        if (ledger.parent != LEDGER_DIR or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != 0 or parent.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise PairedCostHold("LEDGER_PARENT_NOT_HOST_CONTROLLED")
        info = ledger.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise PairedCostHold("LEDGER_NOT_TRUSTED")
        return cls(plan, ledger, hashlib.sha256(raw).hexdigest(),
                   run_id=run["run_id"], trial=dict(trial))

    def _read(self, handle: Any) -> tuple[int, Decimal, dict[str, Any]]:
        handle.seek(0)
        attempts, spent, pending = 0, Decimal(0), {}
        for line in handle:
            try:
                event = json.loads(line)
                if event.get("plan_sha256") != self.plan_sha:
                    raise ValueError("plan mismatch")
                call_id = event["call_id"]
                if re.fullmatch(r"[0-9a-f]{32}", str(call_id)) is None:
                    raise ValueError("invalid call identity")
                kind = event["event"]
                if kind == "reserve":
                    if call_id in pending:
                        raise ValueError("duplicate reservation")
                    if event.get("reserve_usd") != self.plan["reserve_per_call_usd"]:
                        raise ValueError("reservation tariff mismatch")
                    pending[call_id] = event
                    attempts += 1
                elif kind == "settle":
                    if call_id not in pending:
                        raise ValueError("orphan settlement")
                    pending.pop(call_id)
                    amount = Decimal(event["estimated_usd"])
                    verified = Decimal(estimate_usd(
                        {"usage_status": "reported",
                         "prompt_tokens": event["prompt_tokens"],
                         "completion_tokens": event["completion_tokens"]},
                        input_per_million=self.plan["input_per_million_usd"],
                        output_per_million=self.plan["output_per_million_usd"]))
                    if (not amount.is_finite() or amount < 0 or amount != verified
                            or amount > _positive_usd(self.plan["reserve_per_call_usd"])):
                        raise ValueError("invalid settled USD")
                    spent += amount
                elif kind == "unknown":
                    raise PairedCostHold("UNRECONCILED_PROVIDER_BILLING")
                else:
                    raise ValueError("unknown event")
            except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                raise PairedCostHold("COST_LEDGER_CORRUPT") from exc
        return attempts, spent, pending

    def _open(self) -> Any:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.ledger_path, os.O_RDWR | os.O_APPEND | os.O_CREAT
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            os.close(fd)
            raise PairedCostHold("COST_LEDGER_UNTRUSTED")
        handle = os.fdopen(fd, "r+", encoding="utf-8")
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle

    def _append(self, handle: Any, event: dict[str, Any]) -> None:
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps({"plan_sha256": self.plan_sha, **event},
                                sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    def reserve(self) -> str:
        with self._open() as handle:
            attempts, spent, pending = self._read(handle)
            if pending:
                raise PairedCostHold("UNSETTLED_PROVIDER_ATTEMPT")
            if attempts >= self.plan["max_provider_attempts"]:
                raise PairedCostHold("PROVIDER_ATTEMPT_CAP")
            if spent + _positive_usd(self.plan["reserve_per_call_usd"]) > _positive_usd(
                    self.plan["max_total_usd"]):
                raise PairedCostHold("TOTAL_USD_STOP_THRESHOLD")
            call_id = secrets.token_hex(16)
            self._append(handle, {"event": "reserve", "call_id": call_id,
                                  "reserve_usd": self.plan["reserve_per_call_usd"],
                                  "run_id": self.run_id, "trial": self.trial})
            return call_id

    def settle(self, call_id: str, usage: dict[str, Any] | None) -> str:
        with self._open() as handle:
            _, spent, pending = self._read(handle)
            if set(pending) != {call_id}:
                raise PairedCostHold("RESERVATION_ID_MISMATCH", provider_attempted=True)
            try:
                cost = Decimal(estimate_usd(
                    usage or {}, input_per_million=self.plan["input_per_million_usd"],
                    output_per_million=self.plan["output_per_million_usd"]))
                if (cost > _positive_usd(self.plan["reserve_per_call_usd"])
                        or spent + cost > _positive_usd(self.plan["max_total_usd"])):
                    raise ValueError("reservation exceeded")
            except (ValueError, TypeError, InvalidOperation):
                self._append(handle, {"event": "unknown", "call_id": call_id})
                raise PairedCostHold("PROVIDER_COST_UNKNOWN_OR_OVER_RESERVE",
                                     provider_attempted=True) from None
            assert usage is not None
            self._append(handle, {"event": "settle", "call_id": call_id,
                                  "estimated_usd": str(cost),
                                  "prompt_tokens": usage["prompt_tokens"],
                                  "completion_tokens": usage["completion_tokens"]})
            return str(cost)

    def mark_unknown(self, call_id: str) -> None:
        with self._open() as handle:
            _, _, pending = self._read(handle)
            if set(pending) != {call_id}:
                raise PairedCostHold("RESERVATION_ID_MISMATCH", provider_attempted=True)
            self._append(handle, {"event": "unknown", "call_id": call_id})
