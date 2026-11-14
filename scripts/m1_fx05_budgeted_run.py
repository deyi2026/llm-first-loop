"""Explicit, one-shot, budget-bound LFL M1 FX05 qualification runner.

Not a production entrypoint — this is an isolated CLI experiment contract, not
an integrated Web entry. Each invocation creates a *new* session/root and uses
existing TaskBudgetExecution provider/tool dispatch reservations. It never
reactivates a historical grant. No Web switch, global env override or second
budget store implementation is installed.

v3: four physical attempts (tool rounds plus a final natural-language
summary round), per-request payload <= 40,000 bytes, max_tokens <= 3,000, and
a run-wide worst-case precharge of 4 * (2*40k + 8k + 3k) = 364,000
token-equivalent units <= the 400,000 ceiling. Pre-send charges remain a
conservative token-equivalent *proxy*, not a mathematical bound from the
provider's proprietary tokenizer.

One usage source of truth, one settlement commit point (v3.2):
  * reserved (authoritative precharge): the CAS store reservation
    allocations — the conservative proxy that hard-rejects any further
    dispatch. It is never refunded by observation.
  * observed (provider measures): the ONLY durable usage authority is the
    existing EventStore ``provider.transport.settled`` event written by
    the production ShadowTransportRecorder / ProviderCallSettlementJournal
    when the transport attempt exits. FX05BudgetExecution.settle() joins
    that event by current session, run_generation (via the matching
    ``provider.call.opened``) and the REAL provider attempt id, then
    re-verifies provider/model/outcome/usage_observations/status_code and
    usage equality. There is deliberately NO second persistent usage
    ledger (the former usage-receipts.jsonl sidecar is removed).
  * settlement commit point: exactly one FX05-only CAS mutation
    (store._mutate with expected_revision) rewrites the same reservation's
    allocations to the observed measures and marks phase=settled /
    outcome=success / receipt_ref. receipt_ref (new code) binds the
    EventStore event_id plus a SHA-256 digest over attempt_id + event_id
    + observed usage. The historical run's ledger keeps its legacy
    ``m1fx05u:<attempt_id>:<digest>`` receipt_ref format untouched; the
    new receipt records both facts honestly.
  * fail-closed: missing, duplicated, wrong-generation, tampered-usage,
    over-precharge, or ownership/envelope-mismatched evidence keeps the
    reservation at its original precharge as an UNKNOWN liability and
    latches a durable stop (no refund, no next physical attempt).
This reconciliation does NOT turn the proxy into a mathematical token
upper bound; the strict ceiling remains the precharge hard-rejection.

Formal re-runs must not overwrite the historical FX05 draft (already
updated to 2026-11-27): --target-path refuses an existing target and every
attempt/receipt is append-only history.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import time
import uuid
from collections.abc import Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from llm_loop.core.run_context import (
    current_reasoning_effort,
    current_reasoning_mode,
    current_run_generation,
    current_tool_discovery_scope,
    current_write_scope,
)
from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.core.write_scope import WriteScope
from llm_loop.resources.task_budget_contracts import (
    BudgetDimension,
    BudgetPhase,
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
    _identifier,
)
from llm_loop.resources.task_budget_dispatch import (
    _MAX_CAS_RETRIES,
    TaskBudgetExecution,
    active_task_budget,
    bind_task_budget,
    exact_workspace_scope,
)
from llm_loop.resources.task_budget_store import (
    TaskBudgetConflictError,
    TaskBudgetDeniedError,
    TaskBudgetStore,
)
from llm_loop.resources.task_budget_transport_context import (
    IsolatedTransportProfile,
    bind_authorized_provider_proxy,
    bind_isolated_provider_transport,
    qualify_loopback_provider_proxy,
)

MODEL = "glm/glm-5.3"
PROFILE = "m1-t1-fx05-bounded-cli-v3"
# Pre-send charges are conservative token-equivalent *proxy* units, not a
# mathematical upper bound from the provider's proprietary tokenizer.
#   per-attempt input proxy = 2 * MAX_JSON_BYTES + INPUT_PROXY_CONST = 88,000
#   per-attempt output     = MAX_OUTPUT_TOKENS                 =  3,000
#   4 attempts total       = 4 * 91,000                        = 364,000
#     <= MODEL_TOTAL_TOKEN_CEILING (400,000), so the whole run is prechargeable.
# Four physical attempts keep a terminal natural-language round available after
# the observed read/edit/read tool rounds that exhausted the v2 3-attempt run.
ATTEMPTS = 4
MAX_JSON_BYTES = 40_000
MAX_OUTPUT_TOKENS = 3_000
INPUT_PROXY_CONST = 8_000
MODEL_TOTAL_TOKEN_CEILING = 400_000
# Single source of truth for the FX05 tool allowlist: the grant AND the
# post-run verifier both read this constant (no second truth to drift).
FX05_ALLOWED_TOOLS = frozenset({"read_file", "edit_file", "get_tool_schema"})
# Stop reasons are fixed constants: request_stop is idempotent per identical
# reason and raises on a *different* reason once the root is already stopped.
STOP_REASON_USAGE_MISSING = "m1_provider_usage_missing"
STOP_REASON_USAGE_EXCEEDED = "m1_usage_exceeded_reserved"
STOP_REASON_USAGE_CONFLICT = "m1_repeated_usage_conflict"
STOP_REASON_LEDGER_MISMATCH = "m1_reservation_ledger_mismatch"
STOP_REASON_OBSERVED_INVALID = "m1_observed_usage_invalid"
STOP_REASON_ATTEMPT_UNBOUND = "m1_provider_attempt_id_unavailable"
STOP_REASON_EVENT_JOIN = "m1_event_store_join_failed"
STOP_REASON_SETTLE_CAS = "m1_settlement_cas_conflict"
# EventStore is the ONLY durable provider-usage authority (no sidecar).
EVENT_TRANSPORT_SETTLED = "provider.transport.settled"
EVENT_TRANSPORT_OPENED = "provider.transport.opened"
EVENT_CALL_OPENED = "provider.call.opened"
# receipt_ref formats: legacy runs bound the attempt id; new code binds the
# EventStore event_id (the attempt id stays inside the digest input).
RECEIPT_REF_PREFIX_LEGACY = "m1fx05u"
RECEIPT_REF_PREFIX_EVENT = "m1fx05ev"
PROVIDER_ATTEMPT_ID_PATTERN = "pattempt:"
USAGE_DIGEST_HEX = 16
MAX_TOOLS = 8
MAX_RUNTIME_SECONDS = 1800
# Default target of the historical FX05 run. The draft was already updated to
# 2026-11-27; a formal re-run MUST pass --target-path with a brand-new target
# and fresh synthetic inputs — the runner refuses to overwrite an existing
# target so prior success history stays append-only.
TARGET_PATH = "t1-sandbox/outputs/fx05-draft.md"
_PRE_SEND_ENVELOPE: ContextVar[tuple[int, int, int] | None] = ContextVar(
    "m1_fx05_exact_pre_send_envelope", default=None
)
# Prepare-facts channel: the payload HMAC + key id captured together with the
# pre-send envelope, binding the ledger payload_bytes measure to the prepared
# canonical request bytes (production measures and serializes the request
# inside the same transport scope — write-before-send). Recorded honestly as
# null when the transport HMAC layer is disabled and no digest exists.
_PRE_SEND_PREPARED_FACTS: ContextVar[tuple[str, str] | None] = ContextVar(
    "m1_fx05_pre_send_prepared_facts", default=None
)


class FX05BudgetExecution(TaskBudgetExecution):
    """Reuse the production CAS/dispatch gate with conservative pre-send charge.

    Physical attempts reserve a worst-case proxy before a single HTTP byte
    can leave. Usage unknown is still an unknown obligation, not refunded.

    v3 addition (FX05-local, global I2 semantics untouched): each physical
    reservation can be *reconciled* against the provider's actual usage once
    it is observed. Reconciliation upgrades the reservation from the I2
    ``complete=False`` unknown liability to ``usage_complete=True`` only when
    the audited actual measures are present exactly once, conflict-free, and
    within the precharge allocation; the receipt_ref binds the provider
    attempt id plus the usage summary. Any missing, repeated-with-different-
    values, or over-precharge usage keeps the reservation UNKNOWN and latches
    a durable stop: no refund, no further physical attempt.
    """

    def __init__(
        self,
        *args: Any,
        event_store: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        # reservation_id -> locked pre-send envelope (input proxy, output, bytes)
        self._m1_envelopes: dict[str, tuple[int, int, int]] = {}
        # reservation_id -> prepared canonical-request facts (payload_hmac, key id)
        self._m1_prepare_facts: dict[str, tuple[str, str] | None] = {}
        # reservation_id -> observed provider usage snapshot
        self._m1_observed: dict[str, dict[str, Any]] = {}
        self._m1_active_reservation: str | None = None
        # The existing EventStore is the ONLY durable usage authority.
        # Required for any authoritative settlement: settle() joins the
        # provider.transport.settled event by session + run_generation +
        # real attempt id and fail-closes without it (no sidecar ledger).
        self._m1_event_store = event_store

    def reserve(self, kind: BudgetDimension, *, tool_id: str = "") -> str:
        if kind != BudgetDimension.PHYSICAL_ATTEMPTS:
            return super().reserve(kind, tool_id=tool_id)
        self._get_validated()
        envelope = _PRE_SEND_ENVELOPE.get()
        if envelope is None:
            raise TaskBudgetDeniedError("m1_physical_send_without_bound_envelope")
        input_limit, output_limit, payload_bytes = envelope
        reservation_id = "dispatch-" + uuid.uuid4().hex
        self._cas_mutate(
            "reserve",
            member=self.member,
            reservation_id=reservation_id,
            kind=kind,
            measures={
                BudgetDimension.INPUT_TOKENS: input_limit,
                BudgetDimension.OUTPUT_TOKENS: output_limit,
                BudgetDimension.PAYLOAD_BYTES: payload_bytes,
            },
        )
        self._cas_mutate("mark_dispatched", reservation_id=reservation_id)
        self._m1_envelopes[reservation_id] = (input_limit, output_limit, payload_bytes)
        self._m1_prepare_facts[reservation_id] = _PRE_SEND_PREPARED_FACTS.get()
        self._m1_active_reservation = reservation_id
        return reservation_id

    def record_observed_usage(
        self,
        *,
        attempt_id: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        cached_input_tokens: int | None,
        provider_event_ref: str = "",
    ) -> None:
        """Record the provider usage snapshot for the active reservation.

        ``attempt_id`` is the real provider transport attempt id (str)
        captured from the transport observer's active transport capture; a
        local round ordinal is never accepted as a substitute (see the
        fail-closed guard in ``_install_fail_closed_transport_guard``).
        Same-value repeated reports are idempotent (some providers emit usage
        across several SSE chunks); a second report with *different* values for
        the same reservation is an unreconcilable conflict and is latched.
        ``prompt_tokens`` is the provider's total input including cached input;
        ``cached_input_tokens`` is bookkeeping only and is never subtracted.
        ``provider_event_ref`` (when the provider reports a response/event id)
        is carried into the durable usage receipt verbatim.
        """
        rid = self._m1_active_reservation
        if rid is None:
            raise TaskBudgetDeniedError("m1_usage_without_active_reservation")
        snapshot = self._m1_observed.get(rid)
        if snapshot is None:
            self._m1_observed[rid] = {
                "attempt_id": attempt_id,
                "input": prompt_tokens,
                "output": completion_tokens,
                "cached_input": cached_input_tokens,
                "provider_event_ref": provider_event_ref,
                "conflict": False,
            }
            return
        if snapshot["attempt_id"] != attempt_id:
            snapshot["conflict"] = True
        if (
            provider_event_ref
            and snapshot.get("provider_event_ref", "")
            not in ("", provider_event_ref)
        ):
            snapshot["conflict"] = True
        elif provider_event_ref:
            snapshot["provider_event_ref"] = provider_event_ref
        if prompt_tokens is not None and snapshot["input"] not in (None, prompt_tokens):
            snapshot["conflict"] = True
        elif prompt_tokens is not None:
            snapshot["input"] = prompt_tokens
        if completion_tokens is not None and snapshot["output"] not in (None, completion_tokens):
            snapshot["conflict"] = True
        elif completion_tokens is not None:
            snapshot["output"] = completion_tokens
        if cached_input_tokens is not None and snapshot["cached_input"] not in (
            None,
            cached_input_tokens,
        ):
            snapshot["conflict"] = True
        elif cached_input_tokens is not None:
            snapshot["cached_input"] = cached_input_tokens

    def _m1_request_stop(self, reason: str) -> None:
        """Latch stop, tolerating an already-stopped root (idempotence).

        request_stop sets the local latch before its CAS; if the root is
        already stopped for a different reason the durable write raises
        TaskBudgetConflictError (not a TaskBudgetDeniedError subclass).
        The already-stopped ledger is the desired end state either way.
        """
        with suppress(TaskBudgetDeniedError, TaskBudgetConflictError):
            self.request_stop(reason=reason)

    def _m1_join_event_store_evidence(
        self, attempt_id: str, observed: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Join the ONE authoritative usage + prepared-request events.

        Two EventStore events are joined by the REAL attempt id, each
        exactly once: ``provider.transport.settled`` (the only durable
        provider-usage authority, written by the production settlement
        journal before settle() runs) and ``provider.transport.opened``
        (whose ``payload.prepared`` carries the exact pre-send
        projected_bytes and per-request controls.max_tokens — the durable
        source for the reserved triple). Join key: current session (from
        the grant) + this member's run_generation (via ``provider.call
        .opened``) + the REAL ``pattempt:<32hex>`` id. On success the
        returned ``reserved`` is rebuilt purely from the opened event:
        {input_tokens: 2*projected_bytes+INPUT_PROXY_CONST, output_tokens:
        controls.max_tokens, payload_bytes: projected_bytes} — the caller
        cross-checks it against the local pre-send envelope. Any miss,
        duplicate, attribute mismatch, generation mismatch, or usage
        inequality is reported as ``joined: False`` with a precise reason;
        the caller keeps the reservation UNKNOWN and latches a durable stop.
        """
        if self._m1_event_store is None:
            return {"joined": False, "reason": "event_store_unavailable"}
        grant = self.store.read(self.budget_id).get("grant") or {}
        session_id = grant.get("session_id") or ""
        if not session_id:
            return {"joined": False, "reason": "grant_session_missing"}
        events = self._m1_event_store.read(session_id)
        settled = [
            event
            for event in events
            if event.type == EVENT_TRANSPORT_SETTLED
            and (event.payload or {}).get("attempt_id") == attempt_id
        ]
        if len(settled) != 1:
            return {"joined": False, "reason": f"settled_events={len(settled)}"}
        event = settled[0]
        payload = event.payload or {}
        if not (
            payload.get("provider_id") == "glm"
            and payload.get("model_id") == "glm-5.3"
            and payload.get("outcome") == "success"
            and payload.get("usage_observations") == 1
            and payload.get("status_code") == 200
        ):
            return {"joined": False, "reason": "event_attributes_mismatch"}
        opened_calls = [
            event
            for event in events
            if event.type == EVENT_CALL_OPENED
            and (event.payload or {}).get("call_id") == payload.get("call_id")
        ]
        if len(opened_calls) != 1 or (
            (opened_calls[0].payload or {}).get("origin_run_generation")
            != self.member.run_generation
        ):
            return {"joined": False, "reason": "generation_join_failed"}
        transport_opened = [
            event
            for event in events
            if event.type == EVENT_TRANSPORT_OPENED
            and (event.payload or {}).get("attempt_id") == attempt_id
        ]
        if len(transport_opened) != 1:
            return {
                "joined": False,
                "reason": f"transport_opened_events={len(transport_opened)}",
            }
        opened_payload = transport_opened[0].payload or {}
        prepared = opened_payload.get("prepared")
        controls = prepared.get("controls") if isinstance(prepared, dict) else None
        projected = prepared.get("projected_bytes") if isinstance(prepared, dict) else None
        max_tokens = controls.get("max_tokens") if isinstance(controls, dict) else None
        if not (
            opened_payload.get("provider_id") == "glm"
            and opened_payload.get("model_id") == "glm-5.3"
            # The opened event must belong to the SAME provider call as the
            # settled event (one join chain, no cross-call splicing).
            and opened_payload.get("call_id") == payload.get("call_id")
            and type(projected) is int
            and 0 < projected <= MAX_JSON_BYTES
            and type(max_tokens) is int
            and 0 < max_tokens <= MAX_OUTPUT_TOKENS
        ):
            return {"joined": False, "reason": "prepared_request_unqualified"}
        reserved = {
            "input_tokens": 2 * projected + INPUT_PROXY_CONST,
            "output_tokens": max_tokens,
            "payload_bytes": projected,
        }
        usage = payload.get("usage") or {}
        if not (
            type(usage.get("input_tokens")) is int
            and usage["input_tokens"] == observed["input"]
            and type(usage.get("output_tokens")) is int
            and usage["output_tokens"] == observed["output"]
        ):
            return {"joined": False, "reason": "usage_mismatch"}
        event_cached = usage.get("cached_input_tokens")
        if not (type(event_cached) is int and 0 <= event_cached <= usage["input_tokens"]):
            return {"joined": False, "reason": "cached_input_unqualified"}
        cached = observed.get("cached_input")
        if cached is not None and not (
            type(event_cached) is int and event_cached == cached
        ):
            return {"joined": False, "reason": "cached_input_mismatch"}
        return {
            "joined": True,
            "event_id": event.event_id,
            "reserved": reserved,
            # Authoritative cached figure: when the provider usage stream
            # omitted cached_tokens, settle() normalizes the digest input
            # from THIS durable value instead of fabricating one locally.
            "event_cached": event_cached,
        }

    def _m1_settle_with_actual_allocations(
        self,
        reservation_id: str,
        *,
        receipt_ref: str,
        observed_input: int,
        observed_output: int,
        payload_bytes: int,
    ) -> None:
        """FX05-only settlement: align allocations with observed usage.

        One atomic CAS mutation (the existing store-level
        ``_mutate(budget_id, expected_revision, apply)``; global I2 code is
        untouched) re-verifies against the *freshly-read* row — not the
        local cache: reservation exists, belongs to exactly this member_id
        and run_generation, phase == dispatched, and the int actuals stay
        within the precharge (input/output <= reserved; payload_bytes ==
        reserved: the prepared canonical request size is both the atomic
        precharge measure and the actual ledger measure). It then rewrites
        the same reservation's allocations to the observed values and marks
        phase=settled / outcome=success / receipt_ref in the same atomic
        step, so ``report().used_or_reserved`` reflects real provider usage.

        Replaying the identical settlement is an idempotent no-op (no
        revision bump); different evidence against an already-settled row is
        a conflict. Any refusal leaves the row unchanged — callers keep the
        original precharge as an UNKNOWN liability and fail closed (no
        refund). A ValueError from the shared ``_identifier`` contract
        (receipt ref pattern) propagates to the same fail-closed path.
        """
        _identifier("receipt ref", receipt_ref)

        def apply(row: dict[str, Any]) -> bool:
            entry = row["reservations"].get(reservation_id)
            if not isinstance(entry, dict):
                raise TaskBudgetDeniedError(STOP_REASON_LEDGER_MISMATCH)
            if (
                entry.get("member_id") != self.member.member_id
                or entry.get("run_generation") != self.member.run_generation
            ):
                raise TaskBudgetDeniedError(STOP_REASON_LEDGER_MISMATCH)
            allocations = entry.get("allocations")
            if not isinstance(allocations, dict) or not all(
                type(allocations.get(key)) is int and allocations[key] > 0
                for key in ("input_tokens", "output_tokens", "payload_bytes")
            ):
                raise TaskBudgetDeniedError(STOP_REASON_LEDGER_MISMATCH)
            if not (
                type(observed_input) is int
                and type(observed_output) is int
                and type(payload_bytes) is int
                and observed_input >= 0
                and observed_output >= 0
                and payload_bytes > 0
                and observed_input <= allocations["input_tokens"]
                and observed_output <= allocations["output_tokens"]
                and payload_bytes == allocations["payload_bytes"]
            ):
                raise TaskBudgetDeniedError(STOP_REASON_USAGE_EXCEEDED)
            phase = entry.get("phase")
            if phase == "settled":
                if (
                    entry.get("receipt_ref") == receipt_ref
                    and entry.get("outcome") == "success"
                    and allocations["input_tokens"] == observed_input
                    and allocations["output_tokens"] == observed_output
                    and allocations["payload_bytes"] == payload_bytes
                ):
                    return False  # idempotent replay of the same settlement
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
        raise TaskBudgetDeniedError("m1_settlement_cas_contention_exhausted")

    def settle(self, reservation_id: str, *, outcome: str, complete: bool) -> None:
        """I2 hook: reconcile observed usage against the authoritative ledger.

        Returns None, mirroring the production parent contract exactly: the
        parent settle performs a CAS mutation and returns None, and this
        override keeps that contract (no dict is returned here either).

        The production transport scope settles every physical reservation
        with complete=False. Upgrading to usage_complete=True requires ALL of:
          1. ownership: the reservation record read back from the CAS store
             belongs to exactly this member_id and run_generation;
          2. authoritative envelope: the record's persisted allocations
             re-derive the local pre-send envelope exactly — actual prepared
             bytes must equal the ledger payload_bytes allocation, and the
             local cache is cross-checked against the ledger, never trusted
             by itself (an already-applied settlement matches its observed
             measures instead, so replays stay idempotent);
          3. valid observation: exactly one conflict-free snapshot with
             non-negative input/output and cached <= input;
          4. within-reservation: observed input/output <= the authoritative
             allocations (the conservative precharge stays the hard ceiling);
          5. EventStore join (v3.2): exactly one ``provider.transport.settled``
             event for the REAL attempt id, in the grant's session, opened
             under this member's run_generation, with provider=glm /
             model=glm-5.3 / outcome=success / usage_observations=1 /
             status 200, and usage equal to the observed snapshot. The
             EventStore is the ONLY durable usage authority — there is no
             sidecar receipt ledger anymore.
        The single settlement commit point is the FX05-only CAS mutation
        over the freshly-read row (existing store _mutate with
        expected_revision; global I2 untouched) that re-verifies
        ownership/phase/precharge and then rewrites the same reservation's
        allocations to the observed input/output while payload_bytes stays
        the prepared canonical request size — so report().used_or_reserved
        reflects real provider usage (cached input is part of prompt_tokens
        and is never deducted). receipt_ref is
        "m1fx05ev:<event_id>:<sha256(attempt_id+event_id+observed)[:16]>" —
        bound to the authoritative EventStore event, never a local ordinal.
        Unknown, over-reservation, join-failed, CAS-refused, or
        changed-evidence duplicates keep the original precharge and stay
        UNKNOWN (no refund) and fail closed with a durable stop.
        """
        actual = self._m1_observed.get(reservation_id)
        envelope = self._m1_envelopes.get(reservation_id)
        if (
            complete is False
            and outcome == "success"
            and actual is not None
            and envelope is not None
        ):
            reservation = self.store.read(self.budget_id)["reservations"].get(
                reservation_id
            )
            allocations = (
                reservation.get("allocations")
                if isinstance(reservation, dict)
                else None
            )
            reserved: dict[str, int] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "payload_bytes": 0,
            }
            ledger_ok = False
            if (
                isinstance(reservation, dict)
                and isinstance(allocations, dict)
                and reservation.get("member_id") == self.member.member_id
                and reservation.get("run_generation") == self.member.run_generation
                and all(
                    type(allocations.get(key)) is int and allocations[key] > 0
                    for key in ("input_tokens", "output_tokens", "payload_bytes")
                )
            ):
                reserved = {
                    "input_tokens": allocations["input_tokens"],
                    "output_tokens": allocations["output_tokens"],
                    "payload_bytes": allocations["payload_bytes"],
                }
                # The authoritative row must re-derive the local pre-send
                # envelope — except for an idempotent replay AFTER the
                # allocations rewrite, where the stored measures are the
                # observed ones and only the payload byte size must still
                # match the prepared canonical request.
                ledger_ok = envelope == (
                    reserved["input_tokens"],
                    reserved["output_tokens"],
                    reserved["payload_bytes"],
                ) or (
                    reservation.get("phase") == "settled"
                    and reservation.get("outcome") == "success"
                    and reserved["input_tokens"] == actual["input"]
                    and reserved["output_tokens"] == actual["output"]
                    and reserved["payload_bytes"] == envelope[2]
                )
            observed = {
                "input": actual["input"],
                "output": actual["output"],
                "cached_input": actual["cached_input"],
            }
            if not ledger_ok:
                # Ownership or allocation/envelope mismatch against the
                # authoritative record: never settle authoritatively on it.
                super().settle(reservation_id, outcome=outcome, complete=complete)
                self._m1_request_stop(STOP_REASON_LEDGER_MISMATCH)
                return
            cached = actual["cached_input"]
            observed_valid = (
                not actual["conflict"]
                and type(actual["input"]) is int
                and actual["input"] >= 0
                and type(actual["output"]) is int
                and actual["output"] >= 0
                and (
                    cached is None
                    or (type(cached) is int and 0 <= cached <= actual["input"])
                )
            )
            if not observed_valid:
                reason = (
                    STOP_REASON_USAGE_CONFLICT
                    if actual["conflict"]
                    else STOP_REASON_OBSERVED_INVALID
                )
                super().settle(reservation_id, outcome=outcome, complete=complete)
                self._m1_request_stop(reason)
                return
            if (
                actual["input"] > reserved["input_tokens"]
                or actual["output"] > reserved["output_tokens"]
            ):
                super().settle(reservation_id, outcome=outcome, complete=complete)
                self._m1_request_stop(STOP_REASON_USAGE_EXCEEDED)
                return
            # v3.2: the EventStore provider.transport.settled event is the
            # ONLY durable usage authority. Without exactly one matching,
            # generation-bound, usage-equal event there is no settlement:
            # the reservation keeps its precharge as an UNKNOWN liability.
            # v3.4: the joined provider.transport.opened event is the
            # durable source of the reserved triple (prepared
            # projected_bytes + per-request controls.max_tokens); it must
            # re-derive the local pre-send envelope EXACTLY — the process-
            # local map is a cross-check, never the sole authority.
            join = self._m1_join_event_store_evidence(actual["attempt_id"], observed)
            if not join.get("joined"):
                super().settle(reservation_id, outcome=outcome, complete=complete)
                self._m1_request_stop(STOP_REASON_EVENT_JOIN)
                return
            event_reserved = join["reserved"]
            if (
                envelope[0] != event_reserved["input_tokens"]
                or envelope[1] != event_reserved["output_tokens"]
                or envelope[2] != event_reserved["payload_bytes"]
            ):
                super().settle(reservation_id, outcome=outcome, complete=complete)
                self._m1_request_stop(STOP_REASON_LEDGER_MISMATCH)
                return
            # receipt_ref binds the authoritative event_id (recorded as its
            # own segment — never impersonating a provider_event_ref) plus a
            # SHA-256 digest over canonical JSON {attempt_id,
            # provider_event_ref:"", observed, reserved}. reserved is the
            # EventStore-opened-rebuilt triple (verified equal to the local
            # envelope above); when the provider usage stream omitted
            # cached_tokens the observed cached figure is NORMALIZED from
            # the authoritative EventStore event (never fabricated locally,
            # never left as null — the verifier rebuilds the identical
            # digest from durable events alone). No other ledger claims
            # settlement.
            observed_for_digest = {
                "input": observed["input"],
                "output": observed["output"],
                "cached_input": (
                    observed["cached_input"]
                    if observed["cached_input"] is not None
                    else join["event_cached"]
                ),
            }
            usage_digest = hashlib.sha256(
                json.dumps(
                    {
                        "attempt_id": actual["attempt_id"],
                        "provider_event_ref": actual.get("provider_event_ref", ""),
                        "observed": observed_for_digest,
                        "reserved": event_reserved,
                    },
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            receipt_ref = (
                f"{RECEIPT_REF_PREFIX_EVENT}:{join['event_id']}"
                f":{usage_digest[:USAGE_DIGEST_HEX]}"
            )
            try:
                self._m1_settle_with_actual_allocations(
                    reservation_id,
                    receipt_ref=receipt_ref,
                    observed_input=actual["input"],
                    observed_output=actual["output"],
                    payload_bytes=reserved["payload_bytes"],
                )
            except (TaskBudgetDeniedError, TaskBudgetConflictError, ValueError):
                # The atomic upgrade was refused against the freshly-read row
                # (defense-in-depth: ownership, phase, measure shape, or CAS
                # contention). The settlement is NOT claimed: the reservation
                # keeps its precharge as an UNKNOWN liability, the run
                # fail-closes, and no refund happens. No settled observation
                # receipt exists anywhere — EventStore usage stays a plain
                # observation and the ledger row stays UNKNOWN.
                super().settle(reservation_id, outcome=outcome, complete=complete)
                self._m1_request_stop(STOP_REASON_SETTLE_CAS)
                return
            return
        if actual is not None and actual["conflict"]:
            # Repeated usage reports disagree for this reservation: the
            # liability stays UNKNOWN and the run fail-closes.
            super().settle(reservation_id, outcome=outcome, complete=complete)
            self._m1_request_stop(STOP_REASON_USAGE_CONFLICT)
            return
        super().settle(reservation_id, outcome=outcome, complete=complete)


def _install_fail_closed_transport_guard() -> dict[str, int]:
    """No physical provider send without one explicit active M1 root."""
    from llm_loop.llm.client import LLMClient

    origin = LLMClient._transport_attempt_scope
    observe = LLMClient._observe_transport_usage
    counters = {"attempts": 0, "usage_reports": 0, "tokens_in": 0, "tokens_out": 0}
    current: dict[str, int | None] = {"in": None, "out": None}

    def on_usage(self: LLMClient, usage: dict[str, Any], *, model_id: str) -> None:
        budget = active_task_budget()
        if budget is None:
            raise TaskBudgetDeniedError("m1_unbound_provider_usage")
        if not isinstance(budget, FX05BudgetExecution):
            raise TaskBudgetDeniedError("m1_uninstrumented_budget_execution")
        value_in = usage.get("prompt_tokens")
        value_out = usage.get("completion_tokens")
        details = usage.get("prompt_tokens_details")
        value_cached = (
            details.get("cached_tokens")
            if isinstance(details, dict)
            else usage.get("cached_tokens")
        )
        if type(value_in) is int and value_in >= 0:
            current["in"] = value_in
        if type(value_out) is int and value_out >= 0:
            current["out"] = value_out
        # Bind the report to the REAL provider transport attempt id exposed by
        # the transport observer's active transport capture (set for the whole
        # transport scope, so it is live when usage is observed). A missing
        # capture or attempt id is never approximated with a local round
        # counter: settlement is refused and the run fail-closes instead.
        active_observer = getattr(self, "transport_observer", None)
        active_attempt = None
        if active_observer is not None:
            try:
                active_attempt = getattr(
                    active_observer._active_transport.get(), "attempt", None
                )
            except LookupError:
                active_attempt = None
        provider_attempt_id = getattr(active_attempt, "attempt_id", None)
        if not isinstance(provider_attempt_id, str) or not provider_attempt_id.strip():
            budget._m1_request_stop(STOP_REASON_ATTEMPT_UNBOUND)
            raise TaskBudgetDeniedError(STOP_REASON_ATTEMPT_UNBOUND)
        # provider_event_ref stays empty by contract: the provider usage
        # dict carries no event id, and usage["id"] is a wrong field to
        # read (cross-review fix). The EventStore event_id is joined
        # separately at settle() time and is never impersonated here.
        budget.record_observed_usage(
            attempt_id=provider_attempt_id,
            prompt_tokens=value_in if type(value_in) is int and value_in >= 0 else None,
            completion_tokens=value_out if type(value_out) is int and value_out >= 0 else None,
            cached_input_tokens=(
                value_cached if type(value_cached) is int and value_cached >= 0 else None
            ),
            provider_event_ref="",
        )
        return observe(self, usage, model_id=model_id)

    @contextmanager
    def bounded(
        self: LLMClient,
        *,
        model_id: str,
        target_url: str = "",
        transport_retry_index: int = 0,
        prepared: Mapping[str, Any] | None = None,
    ):
        budget = active_task_budget()
        if budget is None or budget.store.read(budget.budget_id)["grant"]["profile"] != PROFILE:
            raise TaskBudgetDeniedError("m1_explicit_budget_binding_required")
        if not isinstance(budget, FX05BudgetExecution):
            raise TaskBudgetDeniedError("m1_uninstrumented_budget_execution")
        if counters["attempts"] != counters["usage_reports"]:
            raise TaskBudgetDeniedError("m1_previous_provider_usage_unknown")
        endpoint = urlsplit(target_url)
        if (
            self.provider != "glm" or model_id != "glm-5.3"
            or endpoint.scheme != "https" or endpoint.hostname != "open.bigmodel.cn"
            or endpoint.username is not None or endpoint.password is not None
            or endpoint.query or endpoint.fragment or not endpoint.path.startswith("/api/")
        ):
            raise TaskBudgetDeniedError("m1_provider_endpoint_unqualified")
        size = prepared.get("projected_bytes") if isinstance(prepared, dict) else None
        controls = prepared.get("controls") if isinstance(prepared, dict) else None
        output_limit = controls.get("max_tokens") if isinstance(controls, dict) else None
        if (
            type(size) is not int or size <= 0 or size > MAX_JSON_BYTES
            or type(output_limit) is not int
            or output_limit <= 0 or output_limit > MAX_OUTPUT_TOKENS
        ):
            raise TaskBudgetDeniedError("m1_payload_or_output_bound_unqualified")
        current["in"], current["out"] = None, None
        # Prepare-facts: the payload HMAC over the canonical request bytes is
        # captured together with the envelope (null-honest when the transport
        # HMAC layer is disabled — no digest exists to record).
        payload_hmac = prepared.get("payload_hmac") if isinstance(prepared, dict) else None
        payload_hmac_key_id = (
            prepared.get("payload_hmac_key_id") if isinstance(prepared, dict) else None
        )
        prepared_facts = (
            (payload_hmac, payload_hmac_key_id)
            if isinstance(payload_hmac, str)
            and payload_hmac
            and isinstance(payload_hmac_key_id, str)
            else None
        )
        # This is a deliberately over-conservative token-equivalent *proxy*.
        # Exact GLM token accounting remains the provider's observed usage.
        token = _PRE_SEND_ENVELOPE.set((2 * size + INPUT_PROXY_CONST, output_limit, size))
        facts_token = _PRE_SEND_PREPARED_FACTS.set(prepared_facts)
        try:
            with origin(
                self,
                model_id=model_id,
                target_url=target_url,
                transport_retry_index=transport_retry_index,
                prepared=prepared,
            ):
                counters["attempts"] += 1
                yield
            if current["in"] is None or current["out"] is None:
                # The reservation is already UNKNOWN (I2 settle with
                # complete=False): fail closed, no refund, no next attempt.
                budget._m1_request_stop(STOP_REASON_USAGE_MISSING)
                raise TaskBudgetDeniedError("m1_provider_usage_missing")
            counters["usage_reports"] += 1
            if int(current["in"]) > 2 * size + INPUT_PROXY_CONST or int(current["out"]) > output_limit:
                # usage_reports is already advanced here, so the attempts !=
                # usage_reports gate above cannot stop the next attempt; the
                # durable stop latch is what fail-closes the run.
                budget._m1_request_stop(STOP_REASON_USAGE_EXCEEDED)
                raise TaskBudgetDeniedError("m1_provider_usage_exceeded_reserved_proxy")
            counters["tokens_in"] += int(current["in"])
            counters["tokens_out"] += int(current["out"])
            if counters["tokens_in"] + counters["tokens_out"] > MODEL_TOTAL_TOKEN_CEILING:
                budget._m1_request_stop("m1_actual_token_budget_exceeded")
                raise TaskBudgetDeniedError("m1_actual_token_budget_exceeded")
        finally:
            _PRE_SEND_PREPARED_FACTS.reset(facts_token)
            _PRE_SEND_ENVELOPE.reset(token)

    LLMClient._transport_attempt_scope = bounded  # explicit isolated-process scope
    LLMClient._observe_transport_usage = on_usage
    return counters


def _refuse_existing_target(
    root: Path,
    target_path: str,
    *,
    execute: bool,
    prepared_target_sha256: str = "",
) -> None:
    """Refuse unattested targets; the historical FX05 draft is never writable.

    The historical draft (TARGET_PATH, already updated to 2026-11-27) is
    refused under --execute forever (append-only history). A formal re-run
    targets a brand-new synthetic fixture prepared out-of-band through a
    controlled create-only entry and separately accounted: because the
    read_file(snapshot) -> edit_file CAS flow requires the target to already
    exist, an existing target is accepted only when (a) it is not the
    historical path and (b) the caller attests its exact sha256. A missing
    target, a missing/mismatched attestation, or an attestation without a
    file all fail closed before any budget is spent.
    """
    if not execute:
        return
    if target_path == TARGET_PATH:
        raise TaskBudgetDeniedError("m1_refuse_overwrite_prior_fx05_target")
    resolved = root / target_path
    if not resolved.exists():
        raise TaskBudgetDeniedError("m1_execute_requires_prepared_fx05_target")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if not prepared_target_sha256:
        raise TaskBudgetDeniedError("m1_target_requires_prepared_attestation")
    if digest != prepared_target_sha256.strip().lower():
        raise TaskBudgetDeniedError("m1_target_sha_mismatch_vs_prepared_attestation")


def _verify_ledger_alignment(
    store: TaskBudgetStore,
    budget_id: str,
    *,
    event_store: Any = None,
) -> bool:
    """Post-run mechanical check: budget ledger vs EventStore usage events.

    Classification is by reservation.kind (never by allocation shape):
      * physical_attempts settled/success — must join EXACTLY ONE
        ``provider.transport.settled`` EventStore event, one-to-one by the
        REAL ``pattempt:<32hex>`` attempt id. receipt_ref must be
        ``m1fx05ev:<event_id>:<sha256(canonical)[:16]>`` (new code; the
        event_id is its own segment and never impersonates the attempt id)
        or the legacy ``m1fx05u:<attempt_id>:<digest>`` kept verbatim on
        the historical ledger. The digest is RECOMPUTED from the canonical
        JSON {attempt_id, provider_event_ref:"", observed, reserved
        precharge} and compared exactly (legacy rows without a persisted
        precharge are format+join checked and honestly marked). Event
        attributes (glm / glm-5.3 / success / usage_observations==1 /
        status 200), the generation join via ``provider.call.opened``, and
        allocations == event usage are all required (cached input is part
        of input, never deducted). Missing, duplicated, extra, misbound,
        or tampered evidence fails.
      * tool_invocations settled/success — only the dispatch-receipt
        closure is required (no provider usage exists to join).
      * any other kind — fail-closed.
      * UNKNOWN liabilities keep the dispatch-receipt closure.
    ``event_store=None`` means the EventStore join is impossible: physical
    rows are reported ``event_store_join=unavailable`` and FAIL — no claim
    of a completed EventStore reconciliation is made.
    """
    import re as _re

    row = store.read(budget_id)
    session_id = (row.get("grant") or {}).get("session_id") or ""
    events: list[Any] = []
    if event_store is not None and session_id:
        events = list(event_store.read(session_id))
    settled_by_attempt: dict[str, list[Any]] = {}
    settled_by_event: dict[str, Any] = {}
    transport_opened_by_attempt: dict[str, list[Any]] = {}
    opened_by_call: dict[str, list[Any]] = {}
    for event in events:
        payload = event.payload or {}
        if event.type == EVENT_TRANSPORT_SETTLED:
            attempt_id = payload.get("attempt_id")
            if isinstance(attempt_id, str):
                settled_by_attempt.setdefault(attempt_id, []).append(event)
            settled_by_event[event.event_id] = event
        elif event.type == EVENT_TRANSPORT_OPENED:
            attempt_id = payload.get("attempt_id")
            if isinstance(attempt_id, str):
                transport_opened_by_attempt.setdefault(attempt_id, []).append(event)
        elif event.type == EVENT_CALL_OPENED:
            call_id = payload.get("call_id")
            if isinstance(call_id, str):
                opened_by_call.setdefault(call_id, []).append(event)
    bound_attempts: set[str] = set()
    aligned = event_store is not None or not any(
        entry.get("kind") == BudgetDimension.PHYSICAL_ATTEMPTS.value
        for entry in row["reservations"].values()
    )
    for reservation_id, entry in sorted(row["reservations"].items()):
        kind = entry.get("kind")
        allocations = entry.get("allocations") or {}
        receipt_ref = entry.get("receipt_ref") or ""
        attempt_id = ""
        event_id = ""
        join_status = "not_required"
        if kind not in (
            BudgetDimension.PHYSICAL_ATTEMPTS.value,
            BudgetDimension.TOOL_INVOCATIONS.value,
        ):
            # Unknown reservation kind fails closed in ANY phase — an
            # unrecognized row is never silently reclassified as an
            # UNKNOWN-liability row that merely needs a receipt prefix.
            ok = False
            join_status = "unknown_kind"
        elif entry.get("phase") == "settled" and entry.get("outcome") == "success":
            if kind == BudgetDimension.PHYSICAL_ATTEMPTS.value:
                parts = receipt_ref.split(":")
                ok = False
                # receipt_ref shapes: "m1fx05ev:<event_id>:<digest16>" (3
                # segments) and the historical "m1fx05u:pattempt:<32hex>:
                # <digest16>" (4 segments — the attempt id itself contains
                # a colon and is NOT rewritten; the legacy ledger stays
                # verbatim). Both formats get the SAME recomputation.
                prefix = receipt_ref.split(":", 1)[0]
                parts = receipt_ref.split(":")
                event = None
                digest16 = ""
                parsed = False
                if (
                    prefix == RECEIPT_REF_PREFIX_EVENT
                    and len(parts) == 3
                    and parts[1]
                    and len(parts[2]) == USAGE_DIGEST_HEX
                ):
                    token, digest16 = parts[1], parts[2]
                    parsed = True
                    event = settled_by_event.get(token)
                    if event is not None:
                        event_id = token
                elif (
                    prefix == RECEIPT_REF_PREFIX_LEGACY
                    and len(parts) == 4
                    and len(parts[3]) == USAGE_DIGEST_HEX
                ):
                    token = ":".join(parts[1:3])
                    digest16 = parts[3]
                    parsed = True
                    attempt_id = token
                    matches = settled_by_attempt.get(token, [])
                    event = matches[0] if len(matches) == 1 else None
                if event is not None and digest16:
                        payload = event.payload or {}
                        event_attempt = payload.get("attempt_id") or ""
                        duplicates = len(settled_by_attempt.get(event_attempt, [])) != 1
                        attempt_id = event_attempt or attempt_id
                        usage = payload.get("usage") or {}
                        opened = opened_by_call.get(payload.get("call_id") or "", [])
                        generation_ok = (
                            len(opened) == 1
                            and (opened[0].payload or {}).get("origin_run_generation")
                            == entry.get("run_generation")
                        )
                        attrs_ok = bool(
                            payload.get("provider_id") == "glm"
                            and payload.get("model_id") == "glm-5.3"
                            and payload.get("outcome") == "success"
                            and payload.get("usage_observations") == 1
                            and payload.get("status_code") == 200
                        )
                        usage_ok = bool(
                            type(usage.get("input_tokens")) is int
                            and usage["input_tokens"]
                            == allocations.get("input_tokens")
                            and type(usage.get("output_tokens")) is int
                            and usage["output_tokens"]
                            == allocations.get("output_tokens")
                        )
                        attempt_ok = _re.fullmatch(
                            r"pattempt:[0-9a-f]{32}", attempt_id or ""
                        ) is not None
                        # reserved is rebuilt from the DURABLE EventStore
                        # provider.transport.opened event (prepared
                        # projected_bytes + per-request controls.max_tokens)
                        # — exactly one such event per attempt, with the
                        # input proxy invariant 2*payload+INPUT_PROXY_CONST
                        # and output limit taken from the event itself (it
                        # may be below MAX_OUTPUT_TOKENS; never a global
                        # constant). No process-local envelope map, no
                        # second ledger, no shared-schema change.
                        opened_events = transport_opened_by_attempt.get(
                            attempt_id, []
                        )
                        precharge = None
                        if len(opened_events) == 1:
                            prepared_payload = opened_events[0].payload or {}
                            prepared = prepared_payload.get("prepared")
                            controls = (
                                prepared.get("controls")
                                if isinstance(prepared, dict)
                                else None
                            )
                            projected = (
                                prepared.get("projected_bytes")
                                if isinstance(prepared, dict)
                                else None
                            )
                            event_max_tokens = (
                                controls.get("max_tokens")
                                if isinstance(controls, dict)
                                else None
                            )
                            if (
                                prepared_payload.get("provider_id") == "glm"
                                and prepared_payload.get("model_id") == "glm-5.3"
                                # Same provider call as the settled event —
                                # no cross-call splicing of opened facts.
                                and prepared_payload.get("call_id")
                                == payload.get("call_id")
                                and type(projected) is int
                                and 0 < projected <= MAX_JSON_BYTES
                                and type(event_max_tokens) is int
                                and 0 < event_max_tokens <= MAX_OUTPUT_TOKENS
                                and projected == allocations.get("payload_bytes")
                            ):
                                precharge = (
                                    2 * projected + INPUT_PROXY_CONST,
                                    event_max_tokens,
                                    projected,
                                )
                        digest_ok = False
                        if (
                            precharge is not None
                            and type(usage.get("cached_input_tokens")) is int
                        ):
                            recomputed = hashlib.sha256(
                                json.dumps(
                                    {
                                        "attempt_id": attempt_id,
                                        "provider_event_ref": "",
                                        "observed": {
                                            "input": allocations.get("input_tokens"),
                                            "output": allocations.get("output_tokens"),
                                            "cached_input": usage.get(
                                                "cached_input_tokens"
                                            ),
                                        },
                                        "reserved": {
                                            "input_tokens": precharge[0],
                                            "output_tokens": precharge[1],
                                            "payload_bytes": precharge[2],
                                        },
                                    },
                                    sort_keys=True,
                                ).encode("utf-8")
                            ).hexdigest()[:USAGE_DIGEST_HEX]
                            digest_ok = recomputed == digest16
                        # Event internal consistency: cached is an int within
                        # [0, input]; the settled allocation stays within the
                        # opened-rebuilt precharge (conservative ceiling).
                        cached_bounds_ok = bool(
                            type(usage.get("cached_input_tokens")) is int
                            and type(usage.get("input_tokens")) is int
                            and 0
                            <= usage["cached_input_tokens"]
                            <= usage["input_tokens"]
                        )
                        within_reserved_ok = bool(
                            precharge is not None
                            and type(allocations.get("input_tokens")) is int
                            and type(allocations.get("output_tokens")) is int
                            and allocations["input_tokens"] <= precharge[0]
                            and allocations["output_tokens"] <= precharge[1]
                        )
                        # No legacy skip: both the legacy m1fx05u and the new
                        # m1fx05ev receipt_ref digests are recomputed from the
                        # SAME canonical input rebuilt out of durable events
                        # (opened reserved + settled observed). Verified
                        # against the accepted historical run: all 4 legacy
                        # digests recompute exactly (attempt ids, generation,
                        # usage equality, and one-to-one settled/opened joins
                        # are all enforced above for both formats).
                        ok = bool(
                            attrs_ok
                            and generation_ok
                            and usage_ok
                            and attempt_ok
                            and digest_ok
                            and cached_bounds_ok
                            and within_reserved_ok
                            and not duplicates
                        )
                        if ok:
                            bound_attempts.add(attempt_id)
                            join_status = "joined"
                        else:
                            join_status = "failed"
                elif not parsed:
                    join_status = (
                        "unavailable" if event_store is None else "bad_receipt_ref"
                    )
                else:
                    join_status = "unavailable" if event_store is None else "missing"
            elif kind == BudgetDimension.TOOL_INVOCATIONS.value:
                # Tool invocation: no provider usage exists to join; the
                # dispatch-receipt closure must be EXACT and the tool must
                # be inside the FX05 runner allowlist (single source of
                # truth shared with the grant — no second truth to drift).
                tool_ok = bool(
                    receipt_ref == f"dispatch-receipt-{reservation_id}"
                    and entry.get("tool_id") in FX05_ALLOWED_TOOLS
                )
                ok = tool_ok
                if not tool_ok:
                    join_status = "tool_not_allowed" if receipt_ref == (
                        f"dispatch-receipt-{reservation_id}"
                    ) else "bad_receipt_ref"
            else:
                # Defensive: unreachable after the top-level kind gate.
                ok = False
                join_status = "unknown_kind"
        else:
            # UNKNOWN liability (tool and physical alike): precharge kept,
            # closed under the default I2 dispatch receipt EXACTLY — never
            # a prefix match, never an unrelated receipt, never a
            # reconciled m1fx05 receipt_ref. A tool row must ALSO be an
            # allowlisted tool even while UNKNOWN: a disallowed tool_id
            # (e.g. exec_command) with a forged-exact dispatch receipt
            # never passes alignment (parent-side reproduced miss).
            ok = bool(
                receipt_ref == f"dispatch-receipt-{reservation_id}"
                and (
                    kind != BudgetDimension.TOOL_INVOCATIONS.value
                    or entry.get("tool_id") in FX05_ALLOWED_TOOLS
                )
            )
            join_status = "n/a"
            if not ok and kind == BudgetDimension.TOOL_INVOCATIONS.value and (
                entry.get("tool_id") not in FX05_ALLOWED_TOOLS
            ):
                join_status = "tool_not_allowed"
        aligned = aligned and ok
        print(json.dumps({
            "event": "ledger_reservation",
            "reservation_id": reservation_id,
            "kind": kind,
            "phase": entry.get("phase"),
            "outcome": entry.get("outcome"),
            "receipt_ref": receipt_ref,
            "allocations": allocations,
            "event_store_event_id": event_id,
            "attempt_id": attempt_id,
            "event_store_join": join_status,
            "aligned": ok,
        }), flush=True)
    extra_events = sorted(set(settled_by_attempt) - bound_attempts)
    extra_ok = not extra_events or not any(
        entry.get("kind") == BudgetDimension.PHYSICAL_ATTEMPTS.value
        and entry.get("phase") == "settled"
        for entry in row["reservations"].values()
    )
    aligned = aligned and extra_ok
    print(json.dumps({
        "event": "ledger_alignment",
        "aligned": aligned,
        "reservations": len(row["reservations"]),
        "event_store_available": event_store is not None,
        "extra_unjoined_events": extra_events,
    }), flush=True)
    return aligned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--smoke", action="store_true", help="one tiny direct GLM request under the same CAS gate")
    mode.add_argument("--execute", action="store_true", help="run the one-shot FX05 task under the same CAS gate")
    parser.add_argument("--proxy", default="", help="optional explicit local HTTP proxy, e.g. http://127.0.0.1:6152")
    parser.add_argument(
        "--target-path",
        default=TARGET_PATH,
        help=(
            "FX05 draft target path relative to the worktree root. Under "
            "--execute this must be a brand-new synthetic fixture prepared "
            "through a controlled create-only entry (never the historical "
            "draft), attested by --prepared-target-sha256."
        ),
    )
    parser.add_argument(
        "--prepared-target-sha256",
        default="",
        help=(
            "sha256 of the prepared target fixture (required for --execute "
            "when the target file exists): separates fixture preparation "
            "accounting from the budgeted tool actions under test."
        ),
    )
    args = parser.parse_args()
    if not args.probe and not args.smoke and args.prompt_file is None:
        parser.error("--prompt-file required unless --probe")
    root = Path(__file__).resolve().parents[1]
    from llm_loop.config import load_settings
    from llm_loop.runtime.resolver import apply_to_environ, legacy_env_snapshot, resolve_effective

    resolved = resolve_effective("web")
    # Factory's provider registry still reads process-local environment;
    # inject the same resolved snapshot without modifying host configuration.
    apply_to_environ(resolved)
    settings = load_settings(legacy_env_snapshot(resolved))
    # Preserve the Mac's authoritative model registry BEFORE changing data_dir
    # to an isolated test runtime. Otherwise the isolated root has no
    # providers.local.json and silently synthesizes a DeepSeek-backed alias
    # named "glm/glm-5.3" (model-label spoofing).
    from llm_loop.llm.providers import load_registry

    trusted_registry = load_registry(settings)
    if trusted_registry.degraded or trusted_registry.resolve(MODEL) != ("glm", "glm-5.3"):
        raise TaskBudgetDeniedError("m1_glm_registry_not_qualified")
    settings = dataclasses.replace(
        settings,
        data_dir=str(root / "data" / "m1-budgeted-run"),
        llm_model=MODEL,
        llm_max_tokens=MAX_OUTPUT_TOKENS,
        llm_timeout_s=180.0,
        history_max_chars=50_000,
        max_iterations=ATTEMPTS,
        llm_retry_disconnect=0,
        runner_background=False,
    )
    from llm_loop.factory import build_engine

    engine = build_engine(settings, workspace_root=str(root))
    pool = engine.llm_pool
    if pool is None:
        engine.close()
        raise TaskBudgetDeniedError("m1_model_pool_unavailable")
    pool.replace_registry(trusted_registry)
    pool.set_default_model(MODEL)
    pool.model_fallbacks_raw = ""
    routed_client, resolved_provider, resolved_model = pool.get_resolved_client(MODEL)
    if (
        resolved_provider != "glm" or resolved_model != "glm-5.3"
        or getattr(routed_client, "provider", None) != "glm"
        or getattr(routed_client, "model", None) != "glm-5.3"
    ):
        engine.close()
        raise TaskBudgetDeniedError("m1_glm_routing_identity_mismatch")
    # Per-model registry defaults may be larger than the frozen output quota.
    # This is a process-local instance only; no change to production config.
    routed_client.max_tokens = 128 if args.smoke else min(
        int(routed_client.max_tokens or MAX_OUTPUT_TOKENS), MAX_OUTPUT_TOKENS
    )
    routed_client.timeout_s = 45.0 if args.smoke else 60.0
    if args.smoke:
        routed_client.retry_disconnect = 0
    session_id = engine.session.create()
    generation = uuid.uuid4().hex
    root_id = "m1fx05-" + uuid.uuid4().hex
    scope = exact_workspace_scope(str(root))
    grant = TaskBudgetGrant(
        budget_id=root_id,
        issuer="user-approved-host-controller",
        authority_source="user-2026-11-13-m1-fx05-regrant",
        workspace_scope=scope,
        session_id=session_id,
        human_turn_ref="approved-fx05-" + generation,
        surface="cli-test_harness",
        profile=PROFILE,
        policy_version="m1-t1-budgeted-cli-v3",
        deadline_epoch_s=time.time() + MAX_RUNTIME_SECONDS,
        limits=TaskBudgetLimits(
            physical_attempts=ATTEMPTS,
            tool_invocations=MAX_TOOLS,
            input_tokens=MODEL_TOTAL_TOKEN_CEILING,
            output_tokens=MODEL_TOTAL_TOKEN_CEILING,
            payload_bytes=2 * 1024 * 1024,
        ),
        capabilities=TaskBudgetCapabilities(
            allowed_tools=FX05_ALLOWED_TOOLS,
            allow_wake=False,
            allow_subagents=False,
        ),
        provider_identity="glm",
        exact_model_ref="glm-5.3",
    )
    store = TaskBudgetStore(root / "data" / "m1-budgeted-run" / "budgets")
    row = store.issue_root(grant, root_run_generation=generation, ingress_kind="cli", reject_duplicate=True)
    row = store.activate(root_id, expected_revision=row["revision"])
    assert row["phase"] == BudgetPhase.ACTIVE
    member = TaskBudgetMember.from_dict(row["members"][root_id])
    # Read-only fact for the receipt: the EventStore used by this run lives
    # inside the isolated worktree (event_logs_dir derives from data_dir
    # when the override is empty).
    print(json.dumps({
        "event": "event_store_path",
        "event_logs_dir": str(settings.event_logs_dir),
        "event_logs_dir_override": bool(settings.event_logs_dir_override),
        "isolated_in_worktree": str(settings.event_logs_dir).startswith(str(root)),
    }), flush=True)
    execution = FX05BudgetExecution(
        store=store,
        budget_id=root_id,
        member=member,
        event_store=engine._event_store,
    )
    counters = _install_fail_closed_transport_guard()
    print(json.dumps({"event": "admitted", "session_id": session_id, "budget_id": root_id, "generation": generation, "model": MODEL, "profile": PROFILE}), flush=True)

    target_path = args.target_path
    _refuse_existing_target(
        root,
        target_path,
        execute=args.execute,
        prepared_target_sha256=args.prepared_target_sha256,
    )
    scope_token = current_write_scope.set(WriteScope(paths=(target_path,)))
    discovery_token = current_tool_discovery_scope.set(
        frozenset({"read_file", "edit_file", "get_tool_schema"})
    )
    generation_token = current_run_generation.set(generation)
    exit_code = 0
    try:
        # Without the existing I5-D isolated worker, budgeted_transport_timeout
        # deliberately falls back to a 1s socket timeout. Bind the qualified
        # per-attempt worker so Stop can terminate/reap the exact HTTP process;
        # this is what makes the existing <=60s IO timeout safe for real GLM.
        with (
            bind_task_budget(execution),
            bind_isolated_provider_transport(IsolatedTransportProfile(verify=True)),
        ):
            if args.probe:
                # Deliberately attempt no provider send. The actual Registry and
                # HTTP hooks must still be tested by subsequent qualification.
                execution.assert_tool_allowed("read_file")
                try:
                    execution.assert_tool_allowed("execute_command")
                except TaskBudgetDeniedError:
                    print(json.dumps({"event": "probe", "shell_denied": True}), flush=True)
                else:
                    raise AssertionError("shell unexpectedly admitted")
            elif args.smoke:
                proxy = qualify_loopback_provider_proxy(args.proxy or None)
                if args.proxy and proxy is None:
                    raise TaskBudgetDeniedError("m1_smoke_proxy_must_be_explicit_loopback_http")
                mode_token = current_reasoning_mode.set("off")
                effort_token = current_reasoning_effort.set("low")
                started = time.monotonic()
                response = None
                try:
                    with bind_authorized_provider_proxy(proxy), bind_isolated_provider_transport(
                        IsolatedTransportProfile(verify=True, proxy=proxy)
                    ):
                        iterator = routed_client._stream_openai(
                            [{"role": "user", "content": "Reply with exactly OK."}],
                            [],
                            timeout_s=45.0,
                            model="glm-5.3",
                        )
                        try:
                            while True:
                                try:
                                    next(iterator)
                                except StopIteration as stop:
                                    response = stop.value
                                    break
                        finally:
                            close_iterator = getattr(iterator, "close", None)
                            if callable(close_iterator):
                                close_iterator()
                finally:
                    current_reasoning_effort.reset(effort_token)
                    current_reasoning_mode.reset(mode_token)
                elapsed = round(time.monotonic() - started, 3)
                if (
                    response is None or not getattr(response, "content", "")
                    or counters["attempts"] != counters["usage_reports"]
                    or counters["tokens_in"] <= 0 or counters["tokens_out"] <= 0
                ):
                    exit_code = 3
                print(json.dumps({
                    "event": "smoke_terminal",
                    "provider": resolved_provider,
                    "model": resolved_model,
                    "proxy": "explicit_loopback" if proxy else "direct",
                    "elapsed_s": elapsed,
                    "response_chars": len(getattr(response, "content", "") or ""),
                    "finish_reason": getattr(response, "finish_reason", ""),
                    "usage_in": counters["tokens_in"],
                    "usage_out": counters["tokens_out"],
                    "physical_attempts": counters["attempts"],
                    "usage_reports": counters["usage_reports"],
                }), flush=True)
            else:
                prompt = args.prompt_file.read_text(encoding="utf-8")
                proxy = qualify_loopback_provider_proxy(args.proxy or None)
                if args.proxy and proxy is None:
                    raise TaskBudgetDeniedError("m1_run_proxy_must_be_explicit_loopback_http")
                # The full FX05 attempt uses the same isolated, one-request
                # worker proven by both smoke paths. No shared httpx pool or
                # ambient system-proxy discovery can strand this Run.
                with bind_authorized_provider_proxy(proxy), bind_isolated_provider_transport(
                    IsolatedTransportProfile(verify=True, proxy=proxy)
                ):
                    result = engine.run(
                        session_id,
                        prompt,
                        model=MODEL,
                        reasoning_mode="off",
                        reasoning_effort="low",
                        ingress=issue_ingress("cli"),
                    )
                if (
                    result.model_used != MODEL or result.run_incomplete
                    or counters["attempts"] != counters["usage_reports"]
                    or counters["tokens_in"] + counters["tokens_out"] > MODEL_TOTAL_TOKEN_CEILING
                ):
                    exit_code = 3
                print(json.dumps({
                    "event": "terminal", "model_used": result.model_used,
                    "run_incomplete": result.run_incomplete,
                    "rounds": result.rounds, "tools": len(result.tool_calls),
                    "provider_usage_in": counters["tokens_in"],
                    "provider_usage_out": counters["tokens_out"],
                    "physical_attempts": counters["attempts"],
                    "provider_usage_reports": counters["usage_reports"],
                    "result_tokens_in": result.tokens_in,
                    "result_tokens_out": result.tokens_out,
                    "session_id": session_id,
                }), flush=True)
    except Exception as exc:
        print(json.dumps({
            "event": "error",
            "type": type(exc).__name__,
            "reason": getattr(exc, "reason", ""),
        }), flush=True)
        exit_code = 3
    finally:
        # Terminal Run never leaves a reusable ACTIVE grant, even on error.
        try:
            execution.seal_at_run_end(reason="m1_cli_run_end")
        finally:
            current_run_generation.reset(generation_token)
            current_tool_discovery_scope.reset(discovery_token)
            current_write_scope.reset(scope_token)
            engine.close()
        state = store.read(root_id)
        print(json.dumps({
            "event": "sealed", "phase": state["phase"],
            "revision": state["revision"], "reservations": len(state["reservations"]),
            "budget_id": root_id,
        }), flush=True)
        if not _verify_ledger_alignment(
            store,
            root_id,
            event_store=engine._event_store,
        ):
            exit_code = exit_code or 3
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
