"""Operator-configured, ONE Web session / ONE Run budgeted GLM write (T1).

Reuses the existing Web canary chain end to end: the strict operator
config -> this plan -> the LoopEngine human-event hook -> the production
``TaskBudgetExecution`` reservation/CAS settle path. The provider send is
gated BEFORE any bytes leave (prepared request envelope CAS precharge);
actual usage is reconciled only from the EventStore
``provider.transport.settled`` event (the sole durable usage authority,
joined with ``provider.transport.opened`` for the reserved triple) and is
settled exclusively through the existing TaskBudgetStore CAS. No sidecar
ledger, no shared-schema change, no scripts import, no monkey-patching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.core.run_context import current_write_scope
from llm_loop.core.trace_leak.ingress_token import IngressToken, is_whitelisted
from llm_loop.event_log.model import Event
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_contracts import (
    BudgetDimension,
    BudgetPhase,
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import (
    _MAX_CAS_RETRIES,
    TaskBudgetExecution,
    exact_workspace_scope,
)
from llm_loop.resources.task_budget_event_authority import (
    _event_fields,
    _rehydrate_event,
)
from llm_loop.resources.task_budget_store import (
    TaskBudgetConflictError,
    TaskBudgetDeniedError,
    TaskBudgetStore,
)

PROFILE = "web-glm-t1-budgeted-write-v1"
POLICY = "t1-web-budgeted-write-v1"
CONFIG_SCHEMA = "web-task-budget-t1/v1"
RECEIPT_REF_PREFIX = "webt1ev"
USAGE_DIGEST_HEX = 16
MAX_ATTEMPTS = 4
MAX_TOOLS = 3
MAX_JSON_BYTES = 40_000
MAX_OUTPUT_TOKENS = 3_000
INPUT_PROXY_CONST = 8_000
TOTAL_TOKEN_CEILING = 400_000
MAX_CONFIG_WINDOW_SECONDS = 3600
RUN_DEADLINE_SECONDS = 1800
_ATTEMPT_ID = re.compile(r"pattempt:[0-9a-f]{32}\Z")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")
# A read_file(snapshot=True) success result carries its snapshot ref as a
# line "snapshot_ref=<token>"; arming requires this ref to exist in the
# REAL tool result (never a caller-supplied guess).
# Goal hard bound on the target artifact: a controlled edit must provably
# stay within 2 MiB BEFORE the write (current bytes + conservative growth).
T1_TARGET_MAX_BYTES = 2 * 1024 * 1024

STOP_EVENT_JOIN = "t1_event_store_join_failed"
STOP_LEDGER_MISMATCH = "t1_reservation_ledger_mismatch"
STOP_USAGE_EXCEEDED = "t1_usage_exceeded_reserved"
STOP_SETTLE_CAS = "t1_settlement_cas_conflict"
# A physical attempt that failed / was interrupted / cancelled, or whose
# settle lacks the arming envelope, leaves an UNKNOWN liability whose usage
# can never be authoritatively reconciled: latch a durable stop at once.
STOP_OUTCOME_UNKNOWN = "t1_provider_outcome_unknown_liability"


def limits() -> TaskBudgetLimits:
    return TaskBudgetLimits(
        physical_attempts=MAX_ATTEMPTS,
        tool_invocations=MAX_TOOLS,
        input_tokens=TOTAL_TOKEN_CEILING,
        output_tokens=TOTAL_TOKEN_CEILING,
        payload_bytes=MAX_ATTEMPTS * MAX_JSON_BYTES,
    )


def capabilities() -> TaskBudgetCapabilities:
    return TaskBudgetCapabilities(
        allowed_tools=frozenset({"read_file", "edit_file"}),
        allow_wake=False,
        allow_subagents=False,
    )


# Same operator-config artifact contract as web/task_budget_canary.py
# (_read_operator_config): regular file, owner root-or-self, no group/other
# permission bits, exactly one hardlink, <=16 KiB. The revocation re-check
# below re-validates the FULL startup identity on every action, not just
# the bytes: a chmod-0644 relaxation, a symlink swap (even to byte-identical
# content), an nlink bump, a FIFO, or an oversized file all count as revoked.
_OPERATOR_CONFIG_MAX_BYTES = 16384


def _operator_config_intact(path_str: str, expected_sha256: str) -> bool:
    """Re-read the operator config under its startup security identity.

    Equivalent to the production ``_read_operator_config`` checks (parent
    cross-review 2026-11-14 07:50): ``O_NOFOLLOW`` open (symlink = ELOOP =
    revoked), ``fstat`` on the opened fd (S_ISREG, owner in {root, euid},
    mode & 0o077 == 0, st_nlink == 1, st_size <= 16 KiB), one bounded
    ``os.read`` (max+1 bytes, oversized rejected from stat first so a FIFO
    or huge file never blocks or reads unbounded; O_NONBLOCK makes a FIFO
    open return immediately instead of hanging on a writer), then the
    sha256 comparison against the startup-pinned fingerprint. Any failure
    is simply False — callers fail closed; no new state store.
    """
    path = Path(path_str)
    if not path.is_absolute():
        return False
    try:
        fd = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
    except OSError:
        return False
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid not in (0, os.geteuid())
            or metadata.st_mode & 0o077
            or metadata.st_nlink != 1
            or metadata.st_size > _OPERATOR_CONFIG_MAX_BYTES
        ):
            return False
        content = os.read(fd, _OPERATOR_CONFIG_MAX_BYTES + 1)
    except OSError:
        return False
    finally:
        with suppress(OSError):
            os.close(fd)
    if len(content) > _OPERATOR_CONFIG_MAX_BYTES:
        return False
    return hashlib.sha256(content).hexdigest() == expected_sha256


@dataclass(frozen=True)
class T1WebEventPlan:
    session_id: str
    workspace_scope: str
    authorization_id: str
    target_path: str
    prepared_target_sha256: str
    valid_from_epoch_s: float
    valid_until_epoch_s: float
    event_store: EventStore
    budget_store: TaskBudgetStore
    # Operator revocation facts (F18, parent cross-review 2026-11-14 07:44):
    # the 0600 operator config file IS the durable authority. At startup the
    # loader captures its absolute path plus the sha256 of the exact bytes it
    # validated; every provider/tool action re-reads the file and compares.
    # Deletion, unreadable permission, or ANY byte change (rotation/swap)
    # counts as revocation — no second state store, no approval service.
    operator_config_path: str = ""
    operator_config_sha256: str = ""
    # Production Web operator-config T1 plans require M5 durable Run facts
    # before any Provider/Tool reservation. Synthetic legacy fixtures opt out.
    durable_run_admission_required: bool = False

    def operator_revoked(self) -> bool:
        """True when the operator authorization no longer holds verbatim.

        Re-reads the pinned operator config file under its FULL startup
        security identity (``_operator_config_intact``: O_NOFOLLOW open,
        fstat regular/0600/nlink==1/owner/16-KiB bound, then the sha256
        of the bounded bytes). Deletion, permission relaxation (chmod
        0644), a symlink swap to byte-identical content, a FIFO or
        oversized artifact, or ANY byte change (rotation) means the
        authorization was withdrawn or rotated: the cached plan must fail
        closed before the next budget action. An empty
        ``operator_config_path`` (legacy synthetic fixtures that build
        the plan directly) cannot be verified, so it reports revoked only
        when the loader explicitly armed it — see the loader wiring.
        """
        if not self.operator_config_path:
            return False
        return not _operator_config_intact(
            self.operator_config_path, self.operator_config_sha256
        )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.session_id, str) or not self.session_id
            or not isinstance(self.workspace_scope, str) or not self.workspace_scope
            or not isinstance(self.authorization_id, str)
            or not _ID.fullmatch(self.authorization_id)
            or not isinstance(self.target_path, str)
            or not self.target_path
            or self.target_path.startswith("/")
            or self.target_path.startswith("~")
            or self.target_path.startswith("./")
            or self.target_path.endswith("/")
            or "\\" in self.target_path
            or "//" in self.target_path
            or "/./" in self.target_path
            or ".." in Path(self.target_path).parts
            or "." in Path(self.target_path).parts
            or self.target_path in {".", ""}
            or not isinstance(self.prepared_target_sha256, str)
            or not _SHA256_HEX.fullmatch(self.prepared_target_sha256)
            or isinstance(self.valid_from_epoch_s, bool)
            or isinstance(self.valid_until_epoch_s, bool)
            or not isinstance(self.valid_from_epoch_s, (int, float))
            or not isinstance(self.valid_until_epoch_s, (int, float))
            or not 0 < self.valid_until_epoch_s - self.valid_from_epoch_s
            <= MAX_CONFIG_WINDOW_SECONDS
            or not isinstance(self.event_store, EventStore)
            or not self.event_store.enabled
            or not isinstance(self.budget_store, TaskBudgetStore)
            or type(self.durable_run_admission_required) is not bool
            # Revocation facts are both-or-neither; when present the path is
            # absolute and the digest is exactly 64 lowercase hex.
            or bool(self.operator_config_path) != bool(self.operator_config_sha256)
            or (
                bool(self.operator_config_path)
                and (
                    not isinstance(self.operator_config_path, str)
                    or not Path(self.operator_config_path).is_absolute()
                    or not _SHA256_HEX.fullmatch(self.operator_config_sha256)
                )
            )
        ):
            raise TaskBudgetDeniedError("t1_plan_invalid")

    @property
    def budget_id(self) -> str:
        # The single-use authorization ID is the durable CAS key: a second
        # human event, Run, or process restart can never mint a second root.
        return "webt1-" + self.authorization_id


_T1_PLAN: ContextVar[T1WebEventPlan | None] = ContextVar(
    "lfl_web_t1_one_run_plan", default=None
)


def active_t1_web_plan() -> T1WebEventPlan | None:
    return _T1_PLAN.get()


@contextmanager
def bind_t1_web_plan(plan: T1WebEventPlan) -> Iterator[None]:
    if not isinstance(plan, T1WebEventPlan):
        raise TypeError("t1_web_plan_required")
    token = _T1_PLAN.set(plan)
    try:
        yield
    finally:
        _T1_PLAN.reset(token)


class T1WebBudgetExecution(TaskBudgetExecution):
    """Production-path budgeted execution with EventStore-only reconciliation.

    * ``note_prepared_request`` (called by ``checked_provider_attempt`` with
      the real prepared request BEFORE reserving) validates the envelope
      (projected_bytes <= 40k, controls.max_tokens <= 3000) and arms the
      exact precharge measures: input proxy = 2*bytes+8000, output = the
      per-request max_tokens, payload = prepared canonical request size.
    * ``settle`` (production transport scope exit — EventStore settled and
      opened events are already durable) joins the ONE unbound event pair
      by attempt id, verifies attributes, generation (via call.opened),
      envelope equality and usage bounds, then commits the observed usage
      through one TaskBudgetStore CAS mutation. Any miss/duplicate/mismatch
      keeps the reservation at its precharge as an UNKNOWN liability and
      latches a durable stop. No refund, no second ledger.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._t1_envelopes: dict[str, tuple[int, int, int]] = {}
        # reservation_id -> (attempt_id, settled_event_id, opened_event_id):
        # BOTH durable events are bound per settled reservation so a later
        # attempt's unbound-event scan never re-counts a prior opened event.
        self._t1_bound: dict[str, tuple[str, str, str]] = {}
        self._t1_pending_envelope: tuple[int, int, int] | None = None
        self._t1_event_store: EventStore | None = None
        # Per-edit gate facts (injected by prepare_t1_web_event_budget).
        self._t1_workspace_root: str | None = None
        self._t1_target_path: str | None = None
        self._t1_target_sha: str | None = None
        # Cross-review P1-3 (hardened): arming happens ONLY after a real,
        # SUCCESSFUL read_file(snapshot=True) of the attested target whose
        # tool result actually carries that read's snapshot ref — reported
        # by the tool executor via note_t1_read_result. The gate below only
        # validates arguments; it never arms by itself. An edit_file must
        # then present EXACTLY the armed ref (not any non-empty string) and
        # consumes it; a failed read, a forged ref, or a second edit
        # without a fresh successful read all fail closed.
        self._t1_armed_ref: str | None = None
        # F18 replay guard bookkeeping: the cross-instance liability scan
        # runs exactly once, before this instance's first reservation.
        self._t1_first_reservation_done: bool = False
        # F18 operator revocation (parent cross-review 2026-11-14 07:44):
        # the plan carrying the pinned operator-config facts. Armed by
        # prepare_t1_web_event_budget; when armed, EVERY provider/tool
        # reserve re-verifies the durable operator authorization first and
        # latches a durable stop on revocation (config deleted, chmod
        # revoked, or bytes rotated — the file IS the authority).
        self._t1_plan: T1WebEventPlan | None = None
        # Armed only after strict opened + admission_fenced have both been
        # fsynced and independently read back. Never reconstructed from memory.
        self._t1_durable_run_fenced: bool = False
        self._t1_durable_admission_revision: int | None = None

    def seal_at_run_end(self, *, reason: str = "run_ended") -> None:
        """Reuse the existing lifecycle seal, then strictly record local Run-end."""
        super().seal_at_run_end(reason=reason)
        if not self._t1_durable_run_fenced or self._t1_event_store is None:
            return
        try:
            from llm_loop.core.durable_run_recovery import (
                append_durable_terminal_from_run_end,
            )

            append_durable_terminal_from_run_end(
                event_store=self._t1_event_store,
                budget_store=self.store,
                session_id=self.member.session_id,
                run_generation=self.member.run_generation,
                authorization_id=self.budget_id.removeprefix("webt1-"),
                admission_revision=self._t1_durable_admission_revision,
            )
        except Exception:  # noqa: BLE001 - uncertain terminal remains HOLD
            logging.getLogger(__name__).exception(
                "M5 strict terminal unconfirmed: session=%s generation=%s; HOLD",
                self.member.session_id, self.member.run_generation,
            )

    def _t1_assert_operator_authorized(self) -> None:
        """Fail-closed F18 gate: one check before every budget action.

        Runs inside ``reserve`` (both provider and tool paths), i.e. before
        ANY further spending. On revocation the root is durably stopped
        (``t1_operator_canary_revoked``) — idempotent against an already
        stopped root, so a CAS race with another stop reason still leaves
        the run closed — and the current action is denied. Never refunds,
        never downgrades an existing liability.
        """
        plan = self._t1_plan
        if plan is not None and plan.operator_revoked():
            with suppress(TaskBudgetDeniedError, TaskBudgetConflictError):
                self.request_stop(reason="t1_operator_canary_revoked")
            raise TaskBudgetDeniedError("t1_operator_canary_revoked")

    def assert_t1_tool_action(
        self, name: str, arguments: Mapping[str, Any] | None
    ) -> None:
        """P1-3: the tool gate checks arguments, not just the name allowlist.

        read_file must target exactly the attested path with
        ``snapshot=True`` — this only QUALIFIES the dispatch; arming is done
        by note_t1_read_result after the real tool run succeeded and its
        snapshot ref was observed. edit_file must then present exactly the
        armed ref for that same path (the tool layer's own CAS additionally
        enforces the ref matches the live file) before the per-edit
        target-SHA / write-scope re-verification in ``reserve``.
        """
        target_path = self._t1_target_path
        if target_path is None:
            raise TaskBudgetDeniedError("t1_plan_unbound")
        args = arguments if isinstance(arguments, Mapping) else None
        if name == "read_file":
            if (
                args is None
                or args.get("path") != target_path
                or args.get("snapshot") is not True
            ):
                raise TaskBudgetDeniedError("t1_read_requires_target_snapshot")
            return
        if name == "edit_file":
            ref = args.get("expected_snapshot_ref") if args is not None else None
            if args is None or args.get("path") != target_path:
                raise TaskBudgetDeniedError("t1_edit_requires_bound_snapshot")
            if not isinstance(ref, str) or not ref:
                raise TaskBudgetDeniedError("t1_edit_requires_bound_snapshot")
            if self._t1_armed_ref is None:
                raise TaskBudgetDeniedError("t1_edit_without_armed_read")
            if ref != self._t1_armed_ref:
                raise TaskBudgetDeniedError("t1_edit_snapshot_ref_not_armed")
            self._t1_assert_edit_size_bound(args)
            self._t1_armed_ref = None
            return
        raise TaskBudgetDeniedError("t1_tool_not_qualified")

    def _t1_assert_edit_size_bound(self, args: Mapping[str, Any]) -> None:
        """P1-2: prove the edited target stays <= 2 MiB BEFORE any write.

        Parent review (2026-11-14 06:59): estimation-shaped bounds (raw
        byte counting, per-occurrence growth deltas, hand-rolled CRLF
        dominance) are NOT a safe hard upper bound — ``FileService.edit``
        normalizes text/old/new to LF, matches and replaces on the
        normalized text, then restores the ORIGINAL dominant line ending
        across the whole result (workspace/file_service.py), so a CRLF
        target matched by an LF-form old_string can replace orders of
        magnitude more occurrences than the raw bytes suggest, and a
        LF-heavy new_string inflates again under CRLF restoration. An
        empty old_string is an insertion at every character boundary.

        The bound is therefore computed with the SAME pure in-memory
        algorithm as FileService.edit — importing the production
        ``detect_line_ending``/``normalize_lf`` helpers, not a re-derivation:
        decode (BOM stripped as FileService does), normalize all three
        strings, count occurrences, apply the identical replace, restore
        the detected ending, and encode the exact final UTF-8 byte length.
        A match-count/replace_all combination FileService itself would
        reject (NoMatch / MultipleMatches) is denied here too (fail-closed
        preview); dry_run previews are held to the same bound. Non-UTF-8
        targets and already-oversized targets are denied before any write.
        """
        from llm_loop.resources.text_normalization import (
            detect_line_ending,
            normalize_lf,
        )

        target_path = self._t1_target_path or ""
        root = self._t1_workspace_root or ""
        try:
            raw = Path(root, target_path).read_bytes()
        except OSError:
            raise TaskBudgetDeniedError("t1_target_unreadable_for_size_bound") from None
        if len(raw) > T1_TARGET_MAX_BYTES:
            raise TaskBudgetDeniedError("t1_target_exceeds_size_bound")
        old = args.get("old_string")
        new = args.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            raise TaskBudgetDeniedError("t1_edit_requires_string_replacement")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise TaskBudgetDeniedError("t1_target_not_utf8") from None
        had_bom = raw.startswith(b"\xef\xbb\xbf")
        if had_bom:
            text = text[1:]
        ending = detect_line_ending(text)
        original = normalize_lf(text)
        old_n = normalize_lf(old)
        new_n = normalize_lf(new)
        occurrences = original.count(old_n)
        if occurrences == 0:
            raise TaskBudgetDeniedError("t1_edit_no_match_preview")
        if occurrences > 1 and not bool(args.get("replace_all")):
            raise TaskBudgetDeniedError("t1_edit_multiple_matches_preview")
        updated = original.replace(old_n, new_n)
        out_text = updated if ending == "\n" else updated.replace("\n", ending)
        final_bytes = len((b"\xef\xbb\xbf" if had_bom else b"") + out_text.encode("utf-8"))
        if final_bytes > T1_TARGET_MAX_BYTES:
            raise TaskBudgetDeniedError("t1_edit_result_exceeds_size_bound")

    def note_t1_read_result(
        self, arguments: Mapping[str, Any] | None, artifact_facts: Any
    ) -> None:
        """Arm the edit gate from a REAL successful read_file result.

        Called by the tool executor only after read_file returned SUCCESS,
        with the result's ``artifact_facts`` (tools/builtin/read_file.py
        attaches one fact whose ``artifact_ref`` IS the read's authoritative
        physical snapshot_ref — registry-level authority, not a regex guess
        scraped from the content text). The arguments must be the target
        read (same path). Anything else — a failed read, missing/empty
        facts, or a fact without a well-formed artifact ref — leaves the
        gate unarmed (fail-closed: the refusal surfaces as
        t1_edit_without_armed_read on the next edit dispatch).
        """
        if self._t1_target_path is None:
            return
        if not isinstance(arguments, Mapping):
            return
        if arguments.get("path") != self._t1_target_path:
            return
        ref = ""
        if isinstance(artifact_facts, (list, tuple)) and artifact_facts:
            first = artifact_facts[0]
            if isinstance(first, Mapping):
                candidate = first.get("artifact_ref")
                if isinstance(candidate, str) and candidate.startswith("artifact://v1/"):
                    ref = candidate
        if not ref:
            return
        self._t1_armed_ref = ref

    # -- pre-send gate -----------------------------------------------------

    def note_prepared_request(self, prepared: Mapping[str, Any] | None) -> None:
        if not isinstance(prepared, Mapping):
            raise TaskBudgetDeniedError("t1_prepared_request_missing")
        size = prepared.get("projected_bytes")
        controls = prepared.get("controls")
        output_limit = controls.get("max_tokens") if isinstance(controls, Mapping) else None
        if (
            type(size) is not int or size <= 0 or size > MAX_JSON_BYTES
            or type(output_limit) is not int
            or output_limit <= 0 or output_limit > MAX_OUTPUT_TOKENS
        ):
            raise TaskBudgetDeniedError("t1_prepared_request_unqualified")
        # Exclusive arming: at most ONE un-consumed prepared-request envelope
        # may exist at any time. A second note while a previous envelope is
        # still pending (concurrent/retried transport scopes sharing this
        # execution) can never overwrite or borrow another attempt's
        # precharge — the second caller fails closed instead.
        if self._t1_pending_envelope is not None:
            raise TaskBudgetDeniedError("t1_pending_envelope_conflict")
        self._t1_pending_envelope = (2 * size + INPUT_PROXY_CONST, output_limit, size)

    def reserve(self, kind: BudgetDimension, *, tool_id: str = "") -> str:
        if self._t1_plan is not None and self._t1_plan.durable_run_admission_required:
            if not self._t1_durable_run_fenced:
                raise TaskBudgetDeniedError("t1_durable_run_admission_not_fenced")
            from llm_loop.core.durable_run_recovery import durable_run_admission_verified

            if not durable_run_admission_verified(
                event_store=self._t1_plan.event_store,
                session_id=self._t1_plan.session_id,
                run_generation=self.member.run_generation,
                authorization_id=self._t1_plan.authorization_id,
                budget_revision=self._t1_durable_admission_revision,
            ):
                with suppress(Exception):
                    self.request_stop(reason="t1_durable_run_evidence_unverifiable")
                raise TaskBudgetDeniedError("t1_durable_run_evidence_unverifiable")
        # F18 operator authorization must hold verbatim before EVERY
        # provider/tool reservation — a revoked (deleted/rotated) operator
        # config durably stops the root and denies this action.
        self._t1_assert_operator_authorized()
        if kind == BudgetDimension.TOOL_INVOCATIONS and tool_id == "edit_file":
            # Cross-review point 4: EVERY edit_file dispatch re-verifies the
            # pinned write scope and the prepared-target attestation — the
            # check is per-invocation, never only at authorization time.
            self._t1_assert_target_intact()
        # Cross-instance fail-closed guard (parent F18 replay): if a prior
        # execution instance left an UNKNOWN/dispatched liability and its
        # durable stop write lost the CAS race (or never persisted), a NEW
        # execution instance bound to the same root must not resume
        # spending — the same-instance local latch cannot travel across
        # processes, so the liability itself is the durable stop signal.
        # Runs once, before this instance's FIRST reservation only.
        if not self._t1_first_reservation_done:
            self._t1_assert_no_open_liability()
            self._t1_first_reservation_done = True
        if kind != BudgetDimension.PHYSICAL_ATTEMPTS:
            return super().reserve(kind, tool_id=tool_id)
        self._get_validated()
        envelope = self._t1_pending_envelope
        if envelope is None:
            raise TaskBudgetDeniedError("t1_prepared_request_missing")
        self._t1_pending_envelope = None
        reservation_id = "dispatch-" + uuid.uuid4().hex
        self._cas_mutate(
            "reserve",
            member=self.member,
            reservation_id=reservation_id,
            kind=kind,
            tool_id="",
            measures={
                BudgetDimension.INPUT_TOKENS: envelope[0],
                BudgetDimension.OUTPUT_TOKENS: envelope[1],
                BudgetDimension.PAYLOAD_BYTES: envelope[2],
            },
        )
        self._cas_mutate("mark_dispatched", reservation_id=reservation_id)
        self._t1_envelopes[reservation_id] = envelope
        return reservation_id

    def _t1_assert_no_open_liability(self) -> None:
        """Refuse a NEW execution instance's first spend on an encumbered root.

        Terminal phases are exactly ``settled`` and ``aborted_before_dispatch``
        (shared ReservationPhase contract); anything else — ``unknown``,
        ``dispatched``, ``reserved`` — is an open obligation of this root.
        Scope (parent F18 replay wording): the check runs once, before this
        instance's FIRST reservation, so the in-run I2 semantics stay intact
        (a tool failure keeps its unknown liability and the SAME run may
        still fail closed at the argument layer, as the armed-read fence
        already proves). The point is the cross-instance/cross-process
        replay — when the prior instance's durable stop write lost its CAS
        race or never persisted, the local latch is gone and only the
        durable ledger can speak: a fresh instance bound to the same root
        must find the liability and refuse to resume spending.
        """
        row = self.store.read(self.budget_id)
        for reservation in row["reservations"].values():
            if reservation.get("phase") not in (
                "settled",
                "aborted_before_dispatch",
            ):
                raise TaskBudgetDeniedError("t1_root_has_unsettled_liability")

    def _t1_assert_target_intact(self) -> None:
        """Per-edit gate: pinned write scope + prepared-target attestation.

        The write scope must still be pinned to exactly the attested target
        path, and the on-disk target must still hash to the attested
        sha256 (a strict normalized relative path under the workspace
        root, no ``..``/symlink escape — re-resolved here on every call).
        Any drift, missing binding, escape, or mutation denies the edit.
        """
        target_path = self._t1_target_path
        if (
            target_path is None
            or self._t1_workspace_root is None
            or self._t1_target_sha is None
        ):
            raise TaskBudgetDeniedError("t1_plan_unbound")
        scope = current_write_scope.get(None)
        if scope is None or tuple(getattr(scope, "paths", ()) or ()) != (
            target_path,
        ):
            raise TaskBudgetDeniedError("t1_write_scope_drift")
        root = Path(self._t1_workspace_root).resolve()
        target = (root / target_path).resolve()
        if root not in target.parents:
            raise TaskBudgetDeniedError("t1_target_escape")
        if not target.is_file():
            raise TaskBudgetDeniedError("t1_prepared_target_missing")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != self._t1_target_sha:
            raise TaskBudgetDeniedError("t1_target_drift")

    # -- settlement --------------------------------------------------------

    def _t1_request_stop(self, reason: str) -> None:
        from contextlib import suppress

        with suppress(TaskBudgetDeniedError, TaskBudgetConflictError):
            self.request_stop(reason=reason)

    def _t1_fail_closed(
        self,
        reservation_id: str,
        *,
        outcome: str,
        complete: bool,
        reason: str,
    ) -> None:
        """Shared fail-closed tail: keep the I2 unknown liability (no
        refund, no rewrite) and latch a durable stop for this reason."""
        super().settle(reservation_id, outcome=outcome, complete=complete)
        self._t1_request_stop(reason)

    def _t1_unbound_events(self, kind: str) -> list[Event]:
        grant = self.store.read(self.budget_id).get("grant") or {}
        session_id = grant.get("session_id") or ""
        if not session_id:
            raise TaskBudgetDeniedError("t1_grant_session_missing")
        if self._t1_event_store is None:
            raise TaskBudgetDeniedError('t1_event_store_unavailable')
        events = self._t1_event_store.read(session_id)
        bound_attempts = {key[0] for key in self._t1_bound.values()}
        bound_event_ids = {
            event_id
            for key in self._t1_bound.values()
            for event_id in key[1:]
        }
        found: list[Event] = []
        for event in events:
            payload = event.payload or {}
            if event.type != kind:
                continue
            attempt_id = payload.get("attempt_id")
            if attempt_id in bound_attempts or event.event_id in bound_event_ids:
                continue
            found.append(event)
        return found

    def _t1_digest16(self, attempt_id: str, event_id: str, observed: Mapping[str, Any], reserved: Mapping[str, int]) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "attempt_id": attempt_id,
                    "provider_event_ref": "",
                    "observed": dict(observed),
                    "reserved": dict(reserved),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:USAGE_DIGEST_HEX]

    def _t1_reverify_committed_receipt(
        self,
        event_id: str,
        digest16: str,
        existing: Mapping[str, Any],
        envelope: tuple[int, int, int],
    ) -> bool:
        """Re-derive a committed T1 settlement purely from durable facts.

        No trust in the stored receipt_ref beyond its parse shape: the
        settled event is fetched by its event_id segment (exactly one),
        its attempt's opened event must be the single one, the call must
        be generation-bound, the opened prepared facts must re-derive the
        exact arming envelope, the settled usage must equal the row's
        allocations (cached within [0, input]), and the canonical digest
        must recompute to the receipt's tail. Anything less means the
        stored settlement cannot be proven — it is not an idempotent
        replay and the caller must fail closed.
        """
        grant = self.store.read(self.budget_id).get("grant") or {}
        session_id = grant.get("session_id") or ""
        if self._t1_event_store is None or not session_id:
            return False
        events = self._t1_event_store.read(session_id)
        settled = [
            event
            for event in events
            if event.type == "provider.transport.settled"
            and event.event_id == event_id
        ]
        if len(settled) != 1:
            return False
        payload = settled[0].payload or {}
        attempt_id = payload.get("attempt_id") or ""
        if (
            not _ATTEMPT_ID.fullmatch(attempt_id)
            or payload.get("provider_id") != "glm"
            or payload.get("model_id") != "glm-5.3"
            or payload.get("outcome") != "success"
            or payload.get("usage_observations") != 1
            or payload.get("status_code") != 200
        ):
            return False
        opened = [
            event
            for event in events
            if event.type == "provider.transport.opened"
            and (event.payload or {}).get("attempt_id") == attempt_id
        ]
        if len(opened) != 1:
            return False
        opened_payload = opened[0].payload or {}
        prepared = opened_payload.get("prepared")
        controls = prepared.get("controls") if isinstance(prepared, Mapping) else None
        projected = (
            prepared.get("projected_bytes") if isinstance(prepared, Mapping) else None
        )
        max_tokens = controls.get("max_tokens") if isinstance(controls, Mapping) else None
        call_id = payload.get("call_id")
        if (
            opened_payload.get("provider_id") != "glm"
            or opened_payload.get("model_id") != "glm-5.3"
            or type(projected) is not int
            or type(max_tokens) is not int
            or opened_payload.get("call_id") != call_id
            or (2 * projected + INPUT_PROXY_CONST, max_tokens, projected) != envelope
        ):
            return False
        run_calls = [
            event
            for event in events
            if event.type == "provider.call.opened"
            and (event.payload or {}).get("origin_run_generation")
            == self.member.run_generation
        ]
        same_call = [
            event
            for event in run_calls
            if (event.payload or {}).get("call_id") == call_id
        ]
        if not isinstance(call_id, str) or not call_id or len(same_call) != 1:
            return False
        usage = payload.get("usage") or {}
        observed_in = usage.get("input_tokens")
        observed_out = usage.get("output_tokens")
        cached = usage.get("cached_input_tokens")
        allocations = existing.get("allocations") or {}
        if (
            type(observed_in) is not int
            or observed_in != allocations.get("input_tokens")
            or type(observed_out) is not int
            or observed_out != allocations.get("output_tokens")
            or type(cached) is not int
            or not 0 <= cached <= observed_in
            or allocations.get("payload_bytes") != envelope[2]
        ):
            return False
        recomputed = self._t1_digest16(
            attempt_id,
            event_id,
            {
                "input": observed_in,
                "output": observed_out,
                "cached_input": cached,
            },
            {
                "input_tokens": envelope[0],
                "output_tokens": envelope[1],
                "payload_bytes": envelope[2],
            },
        )
        return recomputed == digest16

    def _t1_settle_unreconciled(
        self, reservation_id: str, *, outcome: str, complete: bool
    ) -> None:
        """P1-2 (measured by the parent): a physical attempt that failed,
        was interrupted or cancelled — or a physical settle without its
        arming envelope — leaves an UNKNOWN liability whose usage can never
        be reconciled. Keep the I2 unknown bookkeeping and IMMEDIATELY
        latch a durable stop so no further provider send (or tool use) can
        happen on this root, across restarts. Tool reservations settle
        through the normal I2 path (no envelope, no provider usage) and
        are untouched by this latch."""
        entry = self.store.read(self.budget_id)["reservations"].get(reservation_id)
        physical = isinstance(entry, dict) and entry.get(
            "kind"
        ) == BudgetDimension.PHYSICAL_ATTEMPTS.value
        super().settle(reservation_id, outcome=outcome, complete=complete)
        if physical:
            self._t1_request_stop(STOP_OUTCOME_UNKNOWN)

    def _t1_call_generation_bound(self, settled_event: Event, opened_event: Event) -> bool:
        """Cross-review point 2: never join over raw unfiltered session
        events. First restrict provider.call.opened to THIS run generation,
        then require the settled event's call_id to belong to that set
        (exactly one matching call) and the joined transport.opened event
        to carry the SAME call_id — foreign-run pollution, missing or
        duplicated call bindings all fail closed."""
        call_id = (settled_event.payload or {}).get("call_id")
        grant = self.store.read(self.budget_id).get("grant") or {}
        session_id = grant.get("session_id") or ""
        if self._t1_event_store is None or not session_id:
            return False
        run_calls = [
            event
            for event in self._t1_event_store.read(session_id)
            if event.type == "provider.call.opened"
            and (event.payload or {}).get("origin_run_generation")
            == self.member.run_generation
        ]
        same_call = [
            event
            for event in run_calls
            if (event.payload or {}).get("call_id") == call_id
        ]
        return bool(
            isinstance(call_id, str)
            and call_id
            and len(same_call) == 1
            and (opened_event.payload or {}).get("call_id") == call_id
        )

    @staticmethod
    def _t1_transport_evidence(settled_event: Event, opened_event: Event):
        """Attribute gate for BOTH joined events: the settled event must
        carry a real pattempt id, glm/glm-5.3, success, one usage
        observation and HTTP 200; the opened event must bind the SAME
        attempt with qualified prepared (projected_bytes, max_tokens).
        Returns (attempt_id, projected_bytes, max_tokens) or None."""
        payload = settled_event.payload or {}
        attempt_id = payload.get("attempt_id") or ""
        if (
            not _ATTEMPT_ID.fullmatch(attempt_id)
            or payload.get("provider_id") != "glm"
            or payload.get("model_id") != "glm-5.3"
            or payload.get("outcome") != "success"
            or payload.get("usage_observations") != 1
            or payload.get("status_code") != 200
        ):
            return None
        opened_payload = opened_event.payload or {}
        prepared = opened_payload.get("prepared")
        controls = prepared.get("controls") if isinstance(prepared, Mapping) else None
        projected = prepared.get("projected_bytes") if isinstance(prepared, Mapping) else None
        max_tokens = controls.get("max_tokens") if isinstance(controls, Mapping) else None
        if (
            opened_payload.get("attempt_id") != attempt_id
            or opened_payload.get("provider_id") != "glm"
            or opened_payload.get("model_id") != "glm-5.3"
            or type(projected) is not int
            or type(max_tokens) is not int
        ):
            return None
        return attempt_id, projected, max_tokens

    @staticmethod
    def _t1_observed_usage_view(payload: Mapping[str, Any], envelope):
        """Usage gate returning (values, "") on success or (None, reason).
        Cross-review point 3: cached input must be a legitimate integer
        within [0, input]; the receipt digest uses the M1 canonical
        observed view {input, output, cached_input} + reserved — never the
        raw usage mapping (extra provider fields would change the digest
        and must not be trusted into the hash)."""
        usage = payload.get("usage") or {}
        observed_in, observed_out = usage.get("input_tokens"), usage.get("output_tokens")
        cached = usage.get("cached_input_tokens")
        if (
            type(observed_in) is not int or observed_in < 0
            or type(observed_out) is not int or observed_out < 0
            or observed_in > envelope[0] or observed_out > envelope[1]
        ):
            return None, STOP_USAGE_EXCEEDED
        if type(cached) is not int or not 0 <= cached <= observed_in:
            return None, STOP_EVENT_JOIN
        return (observed_in, observed_out, cached), ""

    def settle(self, reservation_id: str, *, outcome: str, complete: bool) -> None:
        envelope = self._t1_envelopes.get(reservation_id)
        if complete is not False or outcome != "success" or envelope is None:
            self._t1_settle_unreconciled(
                reservation_id, outcome=outcome, complete=complete
            )
            return
        existing = self.store.read(self.budget_id)["reservations"].get(reservation_id)
        if (
            isinstance(existing, dict)
            and existing.get("phase") == "settled"
            and existing.get("outcome") == "success"
            and isinstance(existing.get("receipt_ref"), str)
        ):
            # P1-2: an already-committed settlement is an idempotent no-op
            # ONLY when its receipt_ref can be fully re-derived from the
            # durable EventStore evidence (settled event by event_id, the
            # one opened event for that attempt, generation-bound call,
            # envelope-equal reserved view, usage-equal observed view, and
            # the recomputed canonical digest). A same-prefix forged
            # receipt_ref fails the re-derivation and falls through: the
            # CAS below then treats it as changed evidence and fails
            # closed (the UNKNOWN stays UNKNOWN, the run stops).
            parts = existing["receipt_ref"].split(":")
            if (
                len(parts) == 3
                and parts[0] == RECEIPT_REF_PREFIX
                and len(parts[2]) == USAGE_DIGEST_HEX
            ):
                if self._t1_reverify_committed_receipt(
                    parts[1], parts[2], existing, envelope
                ):
                    return
                # Stored settlement cannot be re-derived from durable
                # facts: changed evidence — durable stop, never silent.
                self._t1_request_stop(STOP_SETTLE_CAS)
                return
        try:
            settled = self._t1_unbound_events("provider.transport.settled")
            opened = self._t1_unbound_events("provider.transport.opened")
        except TaskBudgetDeniedError:
            self._t1_fail_closed(reservation_id, outcome=outcome, complete=complete, reason=STOP_LEDGER_MISMATCH)
            return
        if len(settled) != 1 or len(opened) != 1:
            self._t1_fail_closed(reservation_id, outcome=outcome, complete=complete, reason=STOP_EVENT_JOIN)
            return
        settled_event, opened_event = settled[0], opened[0]
        evidence = self._t1_transport_evidence(settled_event, opened_event)
        if evidence is None or not self._t1_call_generation_bound(
            settled_event, opened_event
        ):
            self._t1_fail_closed(reservation_id, outcome=outcome, complete=complete, reason=STOP_EVENT_JOIN)
            return
        attempt_id, projected, max_tokens = evidence
        reserved_view = (2 * projected + INPUT_PROXY_CONST, max_tokens, projected)
        if reserved_view != envelope:
            self._t1_fail_closed(reservation_id, outcome=outcome, complete=complete, reason=STOP_LEDGER_MISMATCH)
            return
        values, usage_reason = self._t1_observed_usage_view(
            settled_event.payload or {}, envelope
        )
        if usage_reason:
            self._t1_fail_closed(reservation_id, outcome=outcome, complete=complete, reason=usage_reason)
            return
        assert values is not None  # (values, "") on the success path
        observed_in, observed_out, cached = values
        observed_view = {
            "input": observed_in,
            "output": observed_out,
            "cached_input": cached,
        }
        receipt_ref = (
            f"{RECEIPT_REF_PREFIX}:{settled_event.event_id}"
            f":{self._t1_digest16(attempt_id, settled_event.event_id, observed_view, {
                'input_tokens': envelope[0],
                'output_tokens': envelope[1],
                'payload_bytes': envelope[2],
            })}"
        )
        try:
            self._t1_settle_with_actual_allocations(
                reservation_id,
                receipt_ref=receipt_ref,
                observed_input=observed_in,
                observed_output=observed_out,
                payload_bytes=envelope[2],
            )
        except (TaskBudgetDeniedError, TaskBudgetConflictError, ValueError):
            self._t1_fail_closed(reservation_id, outcome=outcome, complete=complete, reason=STOP_SETTLE_CAS)
            return
        # Cross-review point 1: bind BOTH the settled and the opened event
        # ids so the NEXT attempt's unbound scan excludes this attempt's
        # opened event too (a lone settled-id binding left prior opened
        # events visible and broke consecutive attempts).
        self._t1_bound[reservation_id] = (
            attempt_id,
            settled_event.event_id,
            opened_event.event_id,
        )

    def _t1_settle_with_actual_allocations(
        self,
        reservation_id: str,
        *,
        receipt_ref: str,
        observed_input: int,
        observed_output: int,
        payload_bytes: int,
    ) -> None:
        def apply(row: dict[str, Any]) -> bool:
            entry = row["reservations"].get(reservation_id)
            if not isinstance(entry, dict):
                raise TaskBudgetDeniedError(STOP_LEDGER_MISMATCH)
            if (
                entry.get("member_id") != self.member.member_id
                or entry.get("run_generation") != self.member.run_generation
            ):
                raise TaskBudgetDeniedError(STOP_LEDGER_MISMATCH)
            allocations = entry.get("allocations")
            if not isinstance(allocations, dict) or not all(
                type(allocations.get(key)) is int and allocations[key] > 0
                for key in ("input_tokens", "output_tokens", "payload_bytes")
            ):
                raise TaskBudgetDeniedError(STOP_LEDGER_MISMATCH)
            if not (
                type(observed_input) is int and observed_input >= 0
                and type(observed_output) is int and observed_output >= 0
                and type(payload_bytes) is int and payload_bytes > 0
                and observed_input <= allocations["input_tokens"]
                and observed_output <= allocations["output_tokens"]
                and payload_bytes == allocations["payload_bytes"]
            ):
                raise TaskBudgetDeniedError(STOP_USAGE_EXCEEDED)
            phase = entry.get("phase")
            if phase == "settled":
                if (
                    entry.get("receipt_ref") == receipt_ref
                    and entry.get("outcome") == "success"
                    and allocations["input_tokens"] == observed_input
                    and allocations["output_tokens"] == observed_output
                    and allocations["payload_bytes"] == payload_bytes
                ):
                    return False
                raise TaskBudgetConflictError("settlement evidence changed")
            if phase != "dispatched":
                raise TaskBudgetDeniedError("only dispatched work can be settled")
            allocations["input_tokens"] = observed_input
            allocations["output_tokens"] = observed_output
            allocations["payload_bytes"] = payload_bytes
            entry["phase"] = "settled"
            entry["receipt_ref"] = receipt_ref
            entry["outcome"] = "success"
            return True

        with self._ledger_lock:
            for _ in range(_MAX_CAS_RETRIES):
                try:
                    revision = self.store.read(self.budget_id)["revision"]
                    self.store._mutate(self.budget_id, revision, apply)
                    return
                except TaskBudgetConflictError as exc:
                    if "stale budget revision CAS" not in str(exc):
                        raise
        raise TaskBudgetDeniedError("t1_settlement_cas_contention_exhausted")


def _arm_t1_durable_run_admission(
    plan: T1WebEventPlan,
    execution: T1WebBudgetExecution,
    *,
    session_id: str,
    run_generation: str,
    budget_revision: int,
) -> None:
    """Strict evidence after Run lease + budget CAS, before external dispatch.

    The production caller holds the Session run lease and has already durably
    appended the authenticated human ingress. No external action is allowed
    until BOTH facts are independently verified by EventStore.
    """
    from llm_loop.core.durable_run_recovery import FENCED, OPENED, SCHEMA

    payload = {
        "schema": SCHEMA,
        "run_generation": run_generation,
        "authorization_id": plan.authorization_id,
        "budget_id": plan.budget_id,
        "budget_revision": budget_revision,
    }
    try:
        plan.event_store.append_durable_run_fact(session_id, OPENED, payload)
        plan.event_store.append_durable_run_fact(session_id, FENCED, payload)
    except Exception as exc:
        # A partial/UNCERTAIN append is NOT evidence of no external action.
        # The one-use budget must remain spent; no replay/new authorization.
        with suppress(Exception):
            execution.request_stop(reason="t1_durable_run_admission_unverified")
        raise TaskBudgetDeniedError(
            "t1_durable_run_admission_unverified"
        ) from exc
    execution._t1_durable_admission_revision = budget_revision
    execution._t1_durable_run_fenced = True


def prepare_t1_web_event_budget(
    *,
    plan: T1WebEventPlan,
    event: Event,
    session_id: str,
    workspace_root: str,
    run_generation: str,
    user_text: str,
    ingress: object | None,
) -> TaskBudgetExecution:
    """Consume the one-time T1 authorization after the human EventStore fsync."""
    if (
        not isinstance(ingress, IngressToken) or not is_whitelisted(ingress)
        or ingress.channel != "web" or ingress.entry != "web" or ingress.delegated
        or not run_generation or not isinstance(event, Event)
        or session_id != plan.session_id
        or exact_workspace_scope(workspace_root) != plan.workspace_scope
    ):
        raise TaskBudgetDeniedError("t1_human_ingress_mismatch")
    persisted = _rehydrate_event(plan.event_store, session_id, event.event_id)
    _event_fields(persisted)
    if persisted != event or persisted.payload["content"] != user_text:
        raise TaskBudgetDeniedError("t1_event_mismatch")
    now = time.time()
    if not plan.valid_from_epoch_s <= now < plan.valid_until_epoch_s:
        raise TaskBudgetDeniedError("t1_authorization_expired")
    # F18: a NEW Run may not even issue when the operator config was
    # revoked after startup (deleted/unreadable/rotated bytes).
    if plan.operator_revoked():
        raise TaskBudgetDeniedError("t1_operator_canary_revoked")
    target = (Path(workspace_root) / plan.target_path).resolve()
    root = Path(workspace_root).resolve()
    if root not in target.parents or not target.is_file():
        raise TaskBudgetDeniedError("t1_prepared_target_missing")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != plan.prepared_target_sha256:
        raise TaskBudgetDeniedError("t1_prepared_target_sha_mismatch")
    grant = TaskBudgetGrant(
        budget_id=plan.budget_id,
        issuer="web-admin",
        authority_source="t1-web-config-cas-v1",
        workspace_scope=plan.workspace_scope,
        session_id=session_id,
        human_turn_ref=f"event-{persisted.event_id}",
        surface="web",
        profile=PROFILE,
        policy_version=POLICY,
        deadline_epoch_s=min(now + RUN_DEADLINE_SECONDS, plan.valid_until_epoch_s),
        limits=limits(),
        capabilities=capabilities(),
        provider_identity="glm",
        exact_model_ref="glm-5.3",
    )
    row = plan.budget_store.issue_root(
        grant, root_run_generation=run_generation,
        ingress_kind="web", reject_duplicate=True,
    )
    if row["phase"] == BudgetPhase.ISSUED:
        row = plan.budget_store.activate(
            plan.budget_id, expected_revision=row["revision"]
        )
    if row["phase"] != BudgetPhase.ACTIVE:
        raise TaskBudgetDeniedError("t1_budget_not_active")
    member = TaskBudgetMember.from_dict(row["members"][plan.budget_id])
    execution = T1WebBudgetExecution(
        store=plan.budget_store, budget_id=plan.budget_id, member=member,
    )
    execution._t1_event_store = plan.event_store  # noqa: SLF001 - plan wiring
    # F18: arm the per-action operator revocation gate with the same plan
    # (pinned config path + startup sha256) that gates new Run issuance.
    execution._t1_plan = plan  # noqa: SLF001 - plan wiring
    # Per-edit gate facts: the exact attested target under the real
    # workspace root, re-verified before EVERY edit_file dispatch.
    execution._t1_workspace_root = workspace_root  # noqa: SLF001 - plan wiring
    execution._t1_target_path = plan.target_path  # noqa: SLF001 - plan wiring
    execution._t1_target_sha = plan.prepared_target_sha256  # noqa: SLF001 - plan wiring
    if plan.durable_run_admission_required:
        _arm_t1_durable_run_admission(
            plan, execution, session_id=session_id,
            run_generation=run_generation, budget_revision=row["revision"],
        )
    return execution


def assert_tool_action(
    budget: Any, name: str, arguments: Mapping[str, Any] | None
) -> None:
    """Dispatch-side T1 argument gate (checked_tool_dispatch wiring).

    The bound execution must be the T1 subclass; the argument-pattern gate
    itself lives on the execution so the armed-read state stays on the
    single object that owns the budget lifecycle.
    """
    if not isinstance(budget, T1WebBudgetExecution):
        raise TaskBudgetDeniedError("t1_uninstrumented_budget_execution")
    budget.assert_t1_tool_action(name, arguments)
