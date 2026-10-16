"""I1 durable root-budget CAS, intentionally NOT connected to provider/tools.

The file is a strict source-of-truth; no in-memory balance or RG-3D projection
can grant execution. All mutations: per-root flock, re-read, revision CAS,
O_EXCL temp + file fsync + replace + directory fsync. On uncertainty, the
caller must reconcile the exact reservation id, never blindly replay effects.

This is an offline accounting primitive, NOT an ingress-signature verifier,
provider physical-attempt gate, cancellation controller, or cost limit.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import replace
from pathlib import Path
from typing import Any

from llm_loop.resources.task_budget_contracts import (
    ACTION_DIMENSIONS,
    MEASURE_DIMENSIONS,
    BudgetDimension,
    BudgetPhase,
    ReservationPhase,
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
    _identifier,
)

SCHEMA = "task-budget-root/v1"
_MAX_RESERVATIONS = 1024
_MAX_MEMBERS = 128
_DIR_FSYNC_ATTEMPTS = 2


class TaskBudgetConflictError(RuntimeError):
    """Stale CAS, duplicate identity with different payload, or bad transition."""


class TaskBudgetDeniedError(PermissionError):
    """Budget enforcement denial; never fail open to an external side effect."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"task budget denied: {reason}")
        self.reason = reason


class TaskBudgetCorruptError(RuntimeError):
    """Authoritative file is missing, corrupt or schema-incompatible."""


class TaskBudgetPersistError(OSError):
    """Mutation definitely did not replace the authoritative root file."""

    retry_safe = True


class TaskBudgetCommitUncertainError(TaskBudgetPersistError):
    """Replace succeeded, directory durability fence could not be confirmed."""

    retry_safe = False

    def __init__(
        self, budget_id: str, expected_sha256: str, visible_state: str
    ) -> None:
        super().__init__(
            f"task budget commit outcome uncertain: budget={budget_id}, "
            f"visible_state={visible_state}, no blind mutation replay"
        )
        self.budget_id = budget_id
        self.expected_sha256 = expected_sha256
        self.visible_state = visible_state


def _write_temp_exclusive(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _visible_state(path: Path, expected: bytes) -> str:
    try:
        return "matches" if path.read_bytes() == expected else "differs"
    except OSError:
        return "unknown"


def _finite_time(now: float) -> float:
    if not isinstance(now, (int, float)) or isinstance(now, bool):
        raise TaskBudgetDeniedError("clock_unavailable")
    from math import isfinite

    if not isfinite(now) or now <= 0:
        raise TaskBudgetDeniedError("clock_unavailable")
    return float(now)


def _valid_reservations(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or len(value) > _MAX_RESERVATIONS:
        raise ValueError("invalid reservation collection")
    expected = {
        "reservation_id", "member_id", "run_generation", "ingress_ref",
        "kind", "tool_id", "allocations", "phase", "receipt_ref", "outcome",
        "policy_generation",
    }
    for ident, row in value.items():
        _identifier("reservation id", ident)
        if not isinstance(row, dict) or set(row) != expected:
            raise ValueError("invalid reservation fields")
        if row["reservation_id"] != ident:
            raise ValueError("reservation id mismatch")
        if type(row["policy_generation"]) is not int or row["policy_generation"] < 1:
            raise ValueError("invalid reservation policy generation")
        _identifier("member id", row["member_id"])
        if not isinstance(row["run_generation"], str) or not row["run_generation"]:
            raise ValueError("missing reservation generation")
        if not isinstance(row["ingress_ref"], str) or not row["ingress_ref"]:
            raise ValueError("missing ingress ref")
        dimension = BudgetDimension(row["kind"])
        phase = ReservationPhase(row["phase"])
        if dimension not in ACTION_DIMENSIONS:
            raise ValueError("reservation kind must be a physical action")
        if not isinstance(row["tool_id"], str) or not isinstance(row["receipt_ref"], str):
            raise ValueError("invalid receipt/tool id")
        if not isinstance(row["outcome"], str):
            raise ValueError("invalid outcome")
        if dimension == BudgetDimension.TOOL_INVOCATIONS:
            _identifier("tool id", row["tool_id"])
        elif row["tool_id"]:
            raise ValueError("tool id on non-tool reservation")
        alloc = row["allocations"]
        if not isinstance(alloc, dict) or not alloc:
            raise ValueError("allocations must be a non-empty mapping")
        for name, count in alloc.items():
            BudgetDimension(name)
            if type(count) is not int or count < 0:
                raise ValueError("invalid allocation amount")
        if alloc.get(row["kind"]) != 1:
            raise ValueError("one action reservation must allocate exactly 1")
        if set(alloc) - ({row["kind"]} | {d.value for d in MEASURE_DIMENSIONS}):
            raise ValueError("only physical measure dimensions can accompany action")
        if phase in {ReservationPhase.RESERVED, ReservationPhase.DISPATCHED} and (
            row["receipt_ref"] or row["outcome"]
        ):
            raise ValueError("open reservation has terminal evidence")
        if phase in {
            ReservationPhase.SETTLED,
            ReservationPhase.UNKNOWN,
            ReservationPhase.ABORTED_BEFORE_DISPATCH,
        } and not row["receipt_ref"]:
            raise ValueError("terminal reservation requires receipt ref")
        if phase == ReservationPhase.ABORTED_BEFORE_DISPATCH and row["outcome"] != "proven_unsent":
            raise ValueError("abort must be a proven pre-dispatch")
        if phase in {ReservationPhase.SETTLED, ReservationPhase.UNKNOWN} and row["outcome"] not in {
            "success", "failure", "cancelled", "interrupted"
        }:
            raise ValueError("settlement requires terminal outcome")
    return value


class TaskBudgetStore:
    """One authoritative snapshot per root, with a lock shared by processes.

    Missing/corrupt state never resets spent counters. The store deliberately
    provides NO API to close as physically verified in I1.
    """

    def __init__(
        self, directory: str | Path, *, clock: Callable[[], float] = time.time
    ) -> None:
        self.directory = Path(directory).expanduser().resolve()
        self._clock = clock

    def _paths(self, budget_id: str) -> tuple[Path, Path]:
        _identifier("budget id", budget_id)
        digest = hashlib.sha256(budget_id.encode("utf-8")).hexdigest()
        return (
            self.directory / f"budget-{digest}.json",
            self.directory / f"budget-{digest}.lock",
        )

    @contextmanager
    def _lock(self, budget_id: str) -> Iterator[Path]:
        path, lock = self._paths(budget_id)
        try:
            with suppress(FileExistsError):
                self.directory.mkdir(mode=0o700, parents=True)
            # The root directory entry is part of first-write durability.
            # Always fence its parent: an earlier first-use attempt may have
            # created the directory but failed that exact durability fence.
            _fsync_directory(self.directory.parent)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(lock, flags, 0o600)
        except OSError as exc:
            raise TaskBudgetPersistError(f"task-budget storage lock failed: {exc}") from exc
        with os.fdopen(fd, "rb") as guard:
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
            try:
                yield path
            finally:
                fcntl.flock(guard.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _validate(data: Any, budget_id: str) -> dict[str, Any]:
        if not isinstance(data, dict) or set(data) != {
            "schema", "revision", "phase", "grant", "members", "reservations",
            "stop_reason",
        }:
            raise ValueError("invalid root schema")
        if data["schema"] != SCHEMA:
            raise ValueError("unrecognized root schema")
        if type(data["revision"]) is not int or data["revision"] < 1:
            raise ValueError("invalid budget revision")
        BudgetPhase(data["phase"])
        grant = TaskBudgetGrant.from_dict(data["grant"])
        if grant.budget_id != budget_id:
            raise ValueError("root id mismatch")
        members = data["members"]
        if not isinstance(members, dict) or len(members) > _MAX_MEMBERS:
            raise ValueError("invalid members")
        for key, value in members.items():
            member = TaskBudgetMember.from_dict(value)
            if member.member_id != key or member.workspace_scope != grant.workspace_scope:
                raise ValueError("member identity or workspace mismatch")
            if member.session_id != grant.session_id:
                from llm_loop.resources import task_budget_subagent_profile as subagent_profile

                if not (
                    grant.profile == subagent_profile.PROFILE
                    and key != budget_id
                    and member.member_id == member.session_id
                    and member.session_id.startswith("subagent_")
                    and member.parent_id == budget_id
                    and member.ingress_kind == "subagent"
                    and not member.schedule_sid
                    and member.ingress_ref == f"delegated-{members[budget_id]['run_generation']}"
                ):
                    raise ValueError("member session mismatch")
            if key == budget_id:
                if member.parent_id != budget_id or member.ingress_ref != grant.human_turn_ref:
                    raise ValueError("root member mismatch")
            elif member.parent_id not in members or member.parent_id == key:
                raise ValueError("orphaned or self-parented member")
        if budget_id not in members:
            raise ValueError("missing root member")
        for member_id in members:
            seen: set[str] = set()
            current = member_id
            while current != budget_id:
                if current in seen:
                    raise ValueError("cyclic member lineage")
                seen.add(current)
                current = members[current]["parent_id"]
        if grant.profile == "web-glm-direct-subagent-canary-v1":
            # Durable freeze: one direct child, no chained member, no hidden
            # capability escalation by JSON substitution after an approval.
            if len(members) > 2:
                raise ValueError("subagent canary member capacity exceeded")
            from llm_loop.resources import task_budget_subagent_profile as subagent_profile

            if (
                grant.capabilities != subagent_profile.capabilities()
                or grant.limits != subagent_profile.limits()
                or grant.policy_version != subagent_profile.POLICY
                or grant.authority_source != "admin-once-config-cas-v1"
                or grant.surface != "web"
                or grant.provider_identity != "glm"
                or grant.exact_model_ref != "glm-5.3"
            ):
                raise ValueError("subagent canary grant authority drift")
        reservations = _valid_reservations(data["reservations"])
        for row in reservations.values():
            binding = members.get(row["member_id"])
            if binding is None or row["run_generation"] != binding["run_generation"] or row["ingress_ref"] != binding["ingress_ref"]:
                raise ValueError("orphan or drifted reservation owner")
            if row["policy_generation"] > grant.generation:
                raise ValueError("reservation from future policy generation")
        if not isinstance(data["stop_reason"], str):
            raise ValueError("stop reason not a string")
        if BudgetPhase(data["phase"]) in {BudgetPhase.ISSUED, BudgetPhase.ACTIVE}:
            if data["stop_reason"]:
                raise ValueError("active root cannot carry a stop reason")
        elif not data["stop_reason"]:
            raise ValueError("stopped root must carry a reason")
        return data

    def _read_path(self, path: Path, budget_id: str) -> dict[str, Any]:
        try:
            if path.is_symlink():
                raise ValueError("authoritative snapshot must not be symlinked")
            raw = path.read_bytes()
            value = json.loads(raw)
            return self._validate(value, budget_id)
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise TaskBudgetCorruptError(
                f"unavailable or corrupt task budget root: {budget_id}"
            ) from exc

    def read(self, budget_id: str) -> dict[str, Any]:
        path, _ = self._paths(budget_id)
        # JSON is atomically replaced; read never trusts a cached copy.
        return self._read_path(path, budget_id)

    def _write(self, path: Path, budget_id: str, row: dict[str, Any]) -> None:
        self._validate(row, budget_id)
        payload = (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        temp = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            _write_temp_exclusive(temp, payload)
            os.replace(temp, path)
        except OSError as exc:
            raise TaskBudgetPersistError(
                f"task budget snapshot definitely not replaced: {budget_id}: {exc}"
            ) from exc
        finally:
            with suppress(FileNotFoundError):
                temp.unlink()
        for _ in range(_DIR_FSYNC_ATTEMPTS):
            try:
                _fsync_directory(path.parent)
                return
            except OSError:
                continue
        raise TaskBudgetCommitUncertainError(
            budget_id, hashlib.sha256(payload).hexdigest(), _visible_state(path, payload)
        )

    @staticmethod
    def _cas(row: dict[str, Any], expected_revision: int) -> None:
        if type(expected_revision) is not int or expected_revision != row["revision"]:
            raise TaskBudgetConflictError("stale budget revision CAS")

    def issue_root(
        self,
        grant: TaskBudgetGrant,
        *,
        root_run_generation: str,
        ingress_kind: str,
        reject_duplicate: bool = False,
    ) -> dict[str, Any]:
        """Create a root; an operator-signed one-time proof cannot be replayed.

        Existing offline callers retain idempotent issue semantics. An I5-A
        proof instead opts into an atomic reject of every duplicate, even if
        all identifiers match; a caller cannot spend the approval twice.
        """
        root = TaskBudgetMember(
            member_id=grant.budget_id,
            parent_id=grant.budget_id,  # explicit root-self sentinel; never traversed
            workspace_scope=grant.workspace_scope,
            session_id=grant.session_id,
            run_generation=root_run_generation,
            ingress_ref=grant.human_turn_ref,
            ingress_kind=ingress_kind,
        )
        template = {
            "schema": SCHEMA,
            "revision": 1,
            "phase": BudgetPhase.ISSUED.value,
            "grant": grant.to_dict(),
            "members": {grant.budget_id: root.to_dict()},
            "reservations": {},
            "stop_reason": "",
        }
        with self._lock(grant.budget_id) as path:
            if path.exists() or path.is_symlink():
                old = self._read_path(path, grant.budget_id)
                if reject_duplicate:
                    raise TaskBudgetDeniedError("operator_budget_proof_replayed")
                if old["grant"] == template["grant"] and old["members"][grant.budget_id] == root.to_dict():
                    return old  # no reissue, no increase
                raise TaskBudgetConflictError("budget root id already bound to different identity")
            self._write(path, grant.budget_id, template)
            return template

    def _mutate(
        self,
        budget_id: str,
        expected_revision: int,
        mutate: Callable[[dict[str, Any]], bool],
    ) -> dict[str, Any]:
        with self._lock(budget_id) as path:
            row = self._read_path(path, budget_id)
            self._cas(row, expected_revision)
            changed = mutate(row)
            if not changed:
                return row
            row["revision"] += 1
            self._write(path, budget_id, row)
            return row

    def activate(self, budget_id: str, *, expected_revision: int) -> dict[str, Any]:
        def apply(row: dict[str, Any]) -> bool:
            if row["phase"] != BudgetPhase.ISSUED:
                raise TaskBudgetConflictError("budget root cannot be reactivated")
            if _finite_time(self._clock()) >= row["grant"]["deadline_epoch_s"]:
                raise TaskBudgetDeniedError("deadline_expired")
            row["phase"] = BudgetPhase.ACTIVE
            return True

        return self._mutate(budget_id, expected_revision, apply)

    def bind_member(
        self,
        budget_id: str,
        member: TaskBudgetMember,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        def apply(row: dict[str, Any]) -> bool:
            if row["phase"] != BudgetPhase.ACTIVE:
                raise TaskBudgetDeniedError("budget_not_active")
            if _finite_time(self._clock()) >= row["grant"]["deadline_epoch_s"]:
                raise TaskBudgetDeniedError("deadline_expired")
            members, cap = row["members"], row["grant"]["capabilities"]
            if member.member_id == budget_id or member.parent_id not in members:
                raise TaskBudgetDeniedError("unknown_parent_or_member")
            if member.workspace_scope != row["grant"]["workspace_scope"]:
                raise TaskBudgetDeniedError("scope_mismatch")
            from llm_loop.resources import task_budget_subagent_profile as subagent_profile

            if row["grant"]["profile"] == subagent_profile.PROFILE:
                root = members[budget_id]
                if (
                    member.ingress_kind != "subagent"
                    or member.parent_id != budget_id
                    or member.session_id != member.member_id
                    or not member.session_id.startswith("subagent_")
                    or member.ingress_ref != f"delegated-{root['run_generation']}"
                    or len(members) != 1
                    or not any(
                        entry["member_id"] == budget_id
                        and entry["tool_id"] == "spawn_subagent"
                        and entry["phase"] in {"dispatched", "settled", "unknown"}
                        for entry in row["reservations"].values()
                    )
                ):
                    raise TaskBudgetDeniedError("subagent_canary_member_not_authorized")
            elif member.session_id != row["grant"]["session_id"]:
                raise TaskBudgetDeniedError("scope_mismatch")
            if member.ingress_kind == "scheduled:schedule_wake" and not cap["allow_wake"]:
                raise TaskBudgetDeniedError("wake_not_allowed")
            if member.ingress_kind == "subagent" and not cap["allow_subagents"]:
                raise TaskBudgetDeniedError("subagent_not_allowed")
            old = members.get(member.member_id)
            if old is not None:
                if old == member.to_dict():
                    return False
                raise TaskBudgetConflictError("member id reused with different authority")
            if len(members) >= _MAX_MEMBERS:
                raise TaskBudgetDeniedError("member_capacity_reached")
            members[member.member_id] = member.to_dict()
            return True

        return self._mutate(budget_id, expected_revision, apply)

    def reserve(
        self,
        budget_id: str,
        *,
        member: TaskBudgetMember,
        reservation_id: str,
        kind: BudgetDimension,
        expected_revision: int,
        measures: Mapping[BudgetDimension, int] | None = None,
        tool_id: str = "",
    ) -> dict[str, Any]:
        """Atomically consume counts; reservation id is idempotent across restarts.

        This reserves *declared numeric allocations*, not proven GLM token usage.
        The physical network/tool gate and true measurement authority are I2/I3.
        """
        _identifier("reservation id", reservation_id)
        if kind not in ACTION_DIMENSIONS:
            raise ValueError("one action kind required")
        if kind == BudgetDimension.TOOL_INVOCATIONS:
            _identifier("tool id", tool_id)
        elif tool_id:
            raise ValueError("tool id only valid for tool reservations")
        allocations = {kind.value: 1}
        for dimension, amount in dict(measures or {}).items():
            if dimension not in MEASURE_DIMENSIONS:
                raise ValueError("only physical measurement dimensions are additional")
            if type(amount) is not int or amount < 0:
                raise ValueError("measure must be a non-negative integer")
            allocations[dimension.value] = amount
        descriptor = {
            "reservation_id": reservation_id,
            "member_id": member.member_id,
            "run_generation": member.run_generation,
            "ingress_ref": member.ingress_ref,
            "kind": kind.value,
            "tool_id": tool_id,
            "allocations": allocations,
            "policy_generation": 0,  # replaced atomically from current policy below
            "phase": ReservationPhase.RESERVED.value,
            "receipt_ref": "",
            "outcome": "",
        }

        def apply(row: dict[str, Any]) -> bool:
            matching = row["members"].get(member.member_id)
            if matching != member.to_dict():
                raise TaskBudgetDeniedError("member_identity_mismatch")
            reserved = row["reservations"]
            existing = reserved.get(reservation_id)
            if existing is not None:
                # A retry after post-replace durability uncertainty must NEVER
                # debit twice or reset the current phase of the same request.
                if all(existing[k] == descriptor[k] for k in (
                    "reservation_id", "member_id", "run_generation", "ingress_ref",
                    "kind", "tool_id", "allocations",
                )):
                    return False
                raise TaskBudgetConflictError("reservation id reused with changed request")
            if row["phase"] != BudgetPhase.ACTIVE:
                raise TaskBudgetDeniedError("budget_not_active")
            if _finite_time(self._clock()) >= row["grant"]["deadline_epoch_s"]:
                raise TaskBudgetDeniedError("deadline_expired")
            if kind == BudgetDimension.TOOL_INVOCATIONS:
                names = row["grant"]["capabilities"]["allowed_tools"]
                if names is not None and tool_id not in names:
                    raise TaskBudgetDeniedError("tool_not_allowed")
            if row["grant"]["profile"] == "web-glm-direct-subagent-canary-v1":
                if kind == BudgetDimension.TOOL_INVOCATIONS:
                    if member.member_id != budget_id or tool_id not in {
                        "spawn_subagent", "subagent_result"
                    }:
                        raise TaskBudgetDeniedError("subagent_canary_child_tools_denied")
                    seen = sum(1 for entry in reserved.values()
                        if entry["kind"] == BudgetDimension.TOOL_INVOCATIONS.value
                        and entry["tool_id"] == tool_id
                        and entry["phase"] != ReservationPhase.ABORTED_BEFORE_DISPATCH.value)
                    if seen >= (1 if tool_id == "spawn_subagent" else 2):
                        raise TaskBudgetDeniedError("subagent_canary_tool_once_limit")
                elif kind == BudgetDimension.PHYSICAL_ATTEMPTS:
                    if member.member_id != budget_id and member.ingress_kind != "subagent":
                        raise TaskBudgetDeniedError("subagent_canary_member_role_invalid")
                    # A real transport failure/interruption, or an attempt
                    # still pending/uncertain of physical dispatch, is NOT a
                    # license to send the next call. A successfully returned
                    # response with unknown *usage* is charged in full but
                    # may continue within the frozen root allowance.
                    if any(
                        entry["kind"] == BudgetDimension.PHYSICAL_ATTEMPTS.value
                        and (
                            entry["phase"] in {"reserved", "dispatched"}
                            or entry["outcome"] in {"failure", "interrupted", "cancelled"}
                        )
                        for entry in reserved.values()
                    ):
                        raise TaskBudgetDeniedError("subagent_canary_provider_retry_denied")
            descriptor["policy_generation"] = row["grant"]["generation"]
            if len(reserved) >= _MAX_RESERVATIONS:
                raise TaskBudgetDeniedError("reservation_capacity_reached")
            existing_units: dict[str, int] = {d.value: 0 for d in BudgetDimension}
            for r in reserved.values():
                if r["phase"] != ReservationPhase.ABORTED_BEFORE_DISPATCH:
                    for name, amount in r["allocations"].items():
                        existing_units[name] += amount
            for name, amount in allocations.items():
                ceiling = row["grant"]["limits"][name]
                if ceiling is None:
                    raise TaskBudgetDeniedError(f"dimension_unqualified:{name}")
                if existing_units[name] + amount > ceiling:
                    raise TaskBudgetDeniedError(f"budget_exhausted:{name}")
            reserved[reservation_id] = descriptor
            return True

        return self._mutate(budget_id, expected_revision, apply)

    def mark_dispatched(
        self, budget_id: str, reservation_id: str, *, expected_revision: int
    ) -> dict[str, Any]:
        def apply(row: dict[str, Any]) -> bool:
            reservation = row["reservations"].get(reservation_id)
            if reservation is None:
                raise TaskBudgetDeniedError("reservation_missing")
            if reservation["phase"] == ReservationPhase.DISPATCHED:
                return False
            if reservation["phase"] != ReservationPhase.RESERVED:
                raise TaskBudgetConflictError("cannot dispatch terminal reservation")
            if row["phase"] != BudgetPhase.ACTIVE or _finite_time(self._clock()) >= row["grant"]["deadline_epoch_s"]:
                raise TaskBudgetDeniedError("dispatch_forbidden_after_stop_or_deadline")
            if reservation["policy_generation"] != row["grant"]["generation"]:
                raise TaskBudgetDeniedError("dispatch_forbidden_after_policy_change")
            reservation["phase"] = ReservationPhase.DISPATCHED
            return True

        return self._mutate(budget_id, expected_revision, apply)

    def abort_before_dispatch(
        self,
        budget_id: str,
        reservation_id: str,
        *,
        expected_revision: int,
        proof_ref: str,
    ) -> dict[str, Any]:
        """Refund ONLY a reservation with no dispatch fact and explicit proof ref."""
        _identifier("proof ref", proof_ref)

        def apply(row: dict[str, Any]) -> bool:
            entry = row["reservations"].get(reservation_id)
            if entry is None:
                raise TaskBudgetDeniedError("reservation_missing")
            if entry["phase"] == ReservationPhase.ABORTED_BEFORE_DISPATCH:
                if entry["receipt_ref"] == proof_ref:
                    return False
                raise TaskBudgetConflictError("abort evidence changed")
            if entry["phase"] != ReservationPhase.RESERVED:
                raise TaskBudgetDeniedError("cannot_refund_dispatched_or_unknown")
            entry["phase"] = ReservationPhase.ABORTED_BEFORE_DISPATCH
            entry["receipt_ref"] = proof_ref
            entry["outcome"] = "proven_unsent"
            return True

        return self._mutate(budget_id, expected_revision, apply)

    def settle(
        self,
        budget_id: str,
        reservation_id: str,
        *,
        expected_revision: int,
        receipt_ref: str,
        outcome: str,
        usage_complete: bool,
    ) -> dict[str, Any]:
        _identifier("receipt ref", receipt_ref)
        if outcome not in {"success", "failure", "cancelled", "interrupted"}:
            raise ValueError("outcome must be an explicit terminal code")
        if type(usage_complete) is not bool:
            raise ValueError("usage completeness must be a boolean fact")
        desired = ReservationPhase.SETTLED if usage_complete else ReservationPhase.UNKNOWN

        def apply(row: dict[str, Any]) -> bool:
            entry = row["reservations"].get(reservation_id)
            if entry is None:
                raise TaskBudgetDeniedError("reservation_missing")
            if entry["phase"] == desired:
                if entry["receipt_ref"] == receipt_ref and entry["outcome"] == outcome:
                    return False
                raise TaskBudgetConflictError("settlement evidence changed")
            if entry["phase"] != ReservationPhase.DISPATCHED:
                raise TaskBudgetDeniedError("only dispatched work can be settled")
            entry["phase"] = desired
            entry["receipt_ref"] = receipt_ref
            entry["outcome"] = outcome
            return True

        return self._mutate(budget_id, expected_revision, apply)

    def tighten(
        self,
        budget_id: str,
        *,
        expected_revision: int,
        expected_generation: int,
        limits: TaskBudgetLimits,
        capabilities: TaskBudgetCapabilities,
        deadline_epoch_s: float,
    ) -> dict[str, Any]:
        def apply(row: dict[str, Any]) -> bool:
            old = TaskBudgetGrant.from_dict(row["grant"])
            if old.generation != expected_generation:
                raise TaskBudgetConflictError("stale policy generation")
            if row["phase"] not in {BudgetPhase.ISSUED, BudgetPhase.ACTIVE}:
                raise TaskBudgetDeniedError("budget_cannot_be_relaxed_or_reactivated")
            if (
                not limits.tighter_than(old.limits)
                or not capabilities.tighter_than(old.capabilities)
                or deadline_epoch_s > old.deadline_epoch_s
            ):
                raise TaskBudgetDeniedError("policy_relaxation_forbidden")
            # Revalidate all fields including numeric finiteness.
            tightened = replace(
                old,
                generation=old.generation + 1,
                deadline_epoch_s=deadline_epoch_s,
                limits=limits,
                capabilities=capabilities,
            )
            if (
                tightened.limits == old.limits
                and tightened.capabilities == old.capabilities
                and tightened.deadline_epoch_s == old.deadline_epoch_s
            ):
                raise TaskBudgetConflictError("no-op policy generation change")
            row["grant"] = tightened.to_dict()
            return True

        return self._mutate(budget_id, expected_revision, apply)

    def request_stop(
        self, budget_id: str, *, expected_revision: int, reason: str
    ) -> dict[str, Any]:
        if not reason or len(reason) > 128:
            raise ValueError("bounded stop reason is required")

        def apply(row: dict[str, Any]) -> bool:
            if row["phase"] == BudgetPhase.STOP_REQUESTED and row["stop_reason"] == reason:
                return False
            if row["phase"] not in {BudgetPhase.ISSUED, BudgetPhase.ACTIVE}:
                raise TaskBudgetConflictError("root already stopped")
            row["phase"] = BudgetPhase.STOP_REQUESTED
            row["stop_reason"] = reason
            return True

        return self._mutate(budget_id, expected_revision, apply)

    def mark_settling(self, budget_id: str, *, expected_revision: int) -> dict[str, Any]:
        def apply(row: dict[str, Any]) -> bool:
            if row["phase"] != BudgetPhase.STOP_REQUESTED:
                raise TaskBudgetConflictError("settling needs a stop request")
            row["phase"] = BudgetPhase.SETTLING
            return True

        return self._mutate(budget_id, expected_revision, apply)

    def close_uncertain(self, budget_id: str, *, expected_revision: int) -> dict[str, Any]:
        """I1 cannot attest physical quiescence; never emit CLOSED_VERIFIED."""
        def apply(row: dict[str, Any]) -> bool:
            if row["phase"] != BudgetPhase.SETTLING:
                raise TaskBudgetConflictError("closure requires settling")
            row["phase"] = BudgetPhase.CLOSED_UNCERTAIN
            return True

        return self._mutate(budget_id, expected_revision, apply)

    def report(self, budget_id: str) -> dict[str, Any]:
        row = self.read(budget_id)
        used = {d.value: 0 for d in BudgetDimension}
        liability: list[str] = []
        for rid, reservation in row["reservations"].items():
            if reservation["phase"] == ReservationPhase.ABORTED_BEFORE_DISPATCH:
                continue
            for field, amount in reservation["allocations"].items():
                used[field] += amount
            if reservation["phase"] in {
                ReservationPhase.RESERVED, ReservationPhase.DISPATCHED, ReservationPhase.UNKNOWN
            }:
                liability.append(rid)
        return {
            "budget_id": budget_id,
            "phase": row["phase"],
            "revision": row["revision"],
            "generation": row["grant"]["generation"],
            "used_or_reserved": used,
            "outstanding_or_unknown": sorted(liability),
            "over_limit_dimensions": [
                d.value for d in BudgetDimension
                if row["grant"]["limits"][d.value] is not None
                and used[d.value] > row["grant"]["limits"][d.value]
            ],
            "physical_quiescence_verified": False,
        }
