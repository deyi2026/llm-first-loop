"""I5-E: operator-authenticated zero-budget bound to a *persisted* human event.

This is an offline, opt-in capability. Production Web has no operator signer,
approval endpoint, authentication adapter or bound plan. Model text, headers,
cookies and tool results never provide signing or approval authority.

Unlike I5-A's pre-persisted text-only proof, this token identifies the actual
EventStore message.appended event_id and seq, and is verified only after the
Run acquired the session lease and its human event became observable.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, NoReturn

from llm_loop.core.trace_leak.ingress_token import IngressToken, is_whitelisted
from llm_loop.event_log.model import Event
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_authority import (
    OperatorBudgetIssuer,
    _canonical,
    _decode,
    _encode,
)
from llm_loop.resources.task_budget_contracts import (
    BudgetPhase,
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import TaskBudgetExecution, exact_workspace_scope
from llm_loop.resources.task_budget_operator_proof import OperatorApprovalVerifier
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore

_DOMAIN = b"LFL-TaskBudget-web-human-event-zero-v2\0"
_PREFIX = "tb2"
_POLICY = "I5-E-web-event-zero-v2"
_TTL = 60
_SKEW = 5
_EVENT_ID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")
_FIELDS = frozenset({
    "approval_nonce", "issued_at", "key_id", "grant", "event_id", "event_seq",
    "event_sha256", "operator_ref",
})


def _deny() -> NoReturn:
    raise TaskBudgetDeniedError("operator_human_event_proof_invalid")


def _zero_limits() -> TaskBudgetLimits:
    return TaskBudgetLimits(
        logical_calls=1, physical_attempts=0, rounds=1, tool_invocations=0,
    )


def _zero_capabilities() -> TaskBudgetCapabilities:
    return TaskBudgetCapabilities(
        allowed_tools=frozenset(), allow_wake=False, allow_subagents=False,
    )


def _event_fields(event: Event) -> dict[str, Any]:
    """Exact source fields, never inferred from model-readable excerpts."""
    payload = event.payload
    if (
        not _EVENT_ID.fullmatch(event.event_id)
        or not isinstance(event.seq, int) or isinstance(event.seq, bool) or event.seq < 1
        or event.type != "message.appended"
        or not isinstance(payload, dict)
        or payload.get("role") != "user" or payload.get("source") != "user"
        or not isinstance(payload.get("content"), str)
        or not isinstance(payload.get("index"), int)
        or isinstance(payload.get("index"), bool) or payload["index"] < 0
    ):
        _deny()
    metadata = payload.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("origin_layer") != "user_instruction"
        or metadata.get("program_origin") is not False
    ):
        _deny()
    return {
        "event_id": event.event_id,
        "seq": event.seq,
        "session_id": event.session_id,
        "type": event.type,
        "index": payload["index"],
        "role": payload["role"],
        "source": payload["source"],
        "content": payload["content"],
        "metadata": metadata,
    }


def _event_hash(event: Event) -> str:
    return hashlib.sha256(_DOMAIN + _canonical(_event_fields(event))).hexdigest()


def _rehydrate_event(store: EventStore, session_id: str, event_id: str) -> Event:
    """Fresh on-disk EventStore read, not the caller's cached Event object."""
    if not isinstance(store, EventStore) or not store.enabled:
        _deny()
    try:
        # New reader avoids a stale process-local EventStore read cache.
        reader = EventStore(store._dir, enabled=True)
        rows = reader.read(session_id)
        matches = [e for e in rows if e.event_id == event_id]
        if reader.last_read_skipped or len(matches) != 1:
            _deny()
        event = matches[0]
        if event.session_id != session_id:
            _deny()
        _event_fields(event)
        return event
    except (OSError, ValueError, TypeError, KeyError):
        _deny()


class AuthenticatedEventBudgetIssuer:
    """Separate operator signer; never constructed by Web chat or model tools.

    The callback must authenticate a distinct OPERATOR credential and return
    a stable principal. It is *not* the ordinary Web login cookie or bearer.
    Real operator auth and key custody remain external/unwired in I5-E.
    """

    def __init__(
        self, *, key_id: str, private_key_pem: bytes,
        authenticate_operator: Callable[[str], str | None] | None = None,
        operator_proof_verifier: OperatorApprovalVerifier | None = None,
    ) -> None:
        # Composition is deliberate. Exposing OperatorBudgetIssuer's legacy
        # approve_zero_web_turn() here would bypass this operator auth check.
        legacy_key = OperatorBudgetIssuer(key_id=key_id, private_key_pem=private_key_pem)
        self.key_id = legacy_key.key_id
        self._signer = legacy_key._signer
        if (authenticate_operator is None) == (operator_proof_verifier is None):
            raise TypeError("exactly_one_independent_operator_authenticator_required")
        if authenticate_operator is not None and not callable(authenticate_operator):
            raise TypeError("independent_operator_authenticator_required")
        self._authenticate_operator = authenticate_operator
        self._operator_proof_verifier = operator_proof_verifier

    def approve_zero_web_event(
        self, *, event_store: EventStore, event: Event, operator_ticket: str,
        workspace_root: str, session_id: str, now: float | None = None,
        ttl_seconds: int = 30,
    ) -> str:
        if (
            not isinstance(operator_ticket, str) or not operator_ticket
            or type(ttl_seconds) is not int or not 0 < ttl_seconds <= _TTL
        ):
            _deny()
        if not isinstance(event, Event) or event.session_id != session_id:
            _deny()
        real = _rehydrate_event(event_store, session_id, event.event_id)
        if real != event:
            _deny()
        if self._operator_proof_verifier is not None:
            principal = self._operator_proof_verifier.authenticate(
                operator_ticket, event_id=real.event_id, event_seq=real.seq,
                event_sha256=_event_hash(real), session_id=session_id,
                workspace_scope=exact_workspace_scope(workspace_root),
            )
        else:
            assert self._authenticate_operator is not None
            principal = self._authenticate_operator(operator_ticket)
        if not isinstance(principal, str) or not principal or len(principal) > 256:
            _deny()
        instant = time.time() if now is None else now
        if isinstance(instant, bool) or not isinstance(instant, (int, float)) or not math.isfinite(instant):
            _deny()
        nonce = secrets.token_hex(16)
        grant = TaskBudgetGrant(
            # All independent signatures over the SAME human event converge
            # on one durable ledger identity. Different nonces cannot mint
            # new root budgets or new Runs for one persisted message.
            budget_id=f"webbudget-event-{real.event_id.replace('-', '')}",
            issuer="web-operator", authority_source="operator-event-ed25519-v2",
            workspace_scope=exact_workspace_scope(workspace_root),
            session_id=session_id, human_turn_ref=f"event-{real.event_id}",
            surface="web", profile="web-event-zero-send-v2",
            policy_version=_POLICY, deadline_epoch_s=instant + ttl_seconds,
            limits=_zero_limits(), capabilities=_zero_capabilities(),
        )
        payload = {
            "approval_nonce": nonce,
            "issued_at": instant,
            "key_id": self.key_id,
            "grant": grant.to_dict(),
            "event_id": real.event_id,
            "event_seq": real.seq,
            "event_sha256": _event_hash(real),
            # No operator credential or plaintext principal in the proof.
            "operator_ref": hashlib.sha256(_DOMAIN + principal.encode()).hexdigest(),
        }
        body = _canonical(payload)
        return ".".join((_PREFIX, _encode(body), _encode(self._signer.sign(_DOMAIN + body))))


@dataclass(frozen=True)
class SignedWebEventPlan:
    """Control-plane-only approval callback, intentionally not Web-wired.

    issue_for_event models the separately authenticated operator RPC: it
    receives the *actual* event after its EventStore append. Only a valid
    Ed25519 proof accepted by trusted_public_keys can authorize a budget.
    """

    issue_for_event: Callable[[Event], str]
    trusted_public_keys: Mapping[str, bytes]
    event_store: EventStore
    budget_store: TaskBudgetStore


_EVENT_PLAN: ContextVar[SignedWebEventPlan | None] = ContextVar(
    "lfl_signed_web_event_approval_plan", default=None
)


def active_signed_web_event_plan() -> SignedWebEventPlan | None:
    return _EVENT_PLAN.get()


@contextmanager
def bind_signed_web_event_plan(plan: SignedWebEventPlan) -> Iterator[None]:
    if not isinstance(plan, SignedWebEventPlan):
        raise TypeError("signed_web_event_plan_type_required")
    token = _EVENT_PLAN.set(plan)
    try:
        yield
    finally:
        _EVENT_PLAN.reset(token)


def _verify_event_proof(proof: str, keys: Mapping[str, bytes]) -> dict[str, Any]:
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    if not isinstance(proof, str) or len(proof) > 8192:
        _deny()
    parts = proof.split(".")
    if len(parts) != 3 or parts[0] != _PREFIX:
        _deny()
    body = _decode(parts[1], max_bytes=6144)
    signature = _decode(parts[2], max_bytes=64)
    if len(signature) != 64:
        _deny()
    try:
        data = json.loads(body)
        if not isinstance(data, dict) or set(data) != _FIELDS or _canonical(data) != body:
            _deny()
        kid = data["key_id"]
        if not isinstance(kid, str) or not _KEY_ID.fullmatch(kid):
            _deny()
        public_pem = keys.get(kid)
        if not isinstance(public_pem, bytes):
            _deny()
        key = ECC.import_key(public_pem)
        if key.curve != "Ed25519" or key.has_private():
            _deny()
        eddsa.new(key, "rfc8032").verify(_DOMAIN + body, signature)
    except (ValueError, TypeError, KeyError, UnicodeError):
        _deny()
    return data


def prepare_signed_web_event_budget(
    *, plan: SignedWebEventPlan, event: Event, session_id: str,
    workspace_root: str, run_generation: str, user_text: str,
    ingress: object | None,
) -> TaskBudgetExecution:
    """Fail closed after real human EventStore append, before any dispatch."""
    if (
        not isinstance(ingress, IngressToken) or not is_whitelisted(ingress)
        or ingress.channel != "web" or ingress.entry != "web" or ingress.delegated
        or not run_generation or not isinstance(event, Event)
    ):
        raise TaskBudgetDeniedError("operator_budget_requires_human_web_ingress")
    persisted = _rehydrate_event(plan.event_store, session_id, event.event_id)
    if persisted != event or persisted.payload.get("content") != user_text:
        _deny()
    proof = plan.issue_for_event(persisted)
    payload = _verify_event_proof(proof, plan.trusted_public_keys)
    try:
        grant = TaskBudgetGrant.from_dict(payload["grant"])
    except (ValueError, TypeError, KeyError):
        _deny()
    issued = payload["issued_at"]
    clock = time.time()
    nonce = payload["approval_nonce"]
    if (
        isinstance(issued, bool) or not isinstance(issued, (int, float))
        or not math.isfinite(issued) or issued > clock + _SKEW
        or clock >= issued + _TTL
        or grant.deadline_epoch_s <= issued or grant.deadline_epoch_s > issued + _TTL
        or clock >= grant.deadline_epoch_s
        or not isinstance(nonce, str) or not _NONCE.fullmatch(nonce)
        or grant.budget_id != f"webbudget-event-{persisted.event_id.replace('-', '')}"
        or grant.human_turn_ref != f"event-{persisted.event_id}"
        or payload["event_id"] != persisted.event_id
        or payload["event_seq"] != persisted.seq
        or payload["event_sha256"] != _event_hash(persisted)
        or not isinstance(payload["operator_ref"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", payload["operator_ref"])
        or grant.issuer != "web-operator"
        or grant.authority_source != "operator-event-ed25519-v2"
        or grant.surface != "web" or grant.profile != "web-event-zero-send-v2"
        or grant.policy_version != _POLICY or grant.generation != 1
        or grant.provider_identity or grant.exact_model_ref
        or grant.session_id != session_id
        or grant.workspace_scope != exact_workspace_scope(workspace_root)
        or grant.limits != _zero_limits() or grant.capabilities != _zero_capabilities()
    ):
        _deny()
    row = plan.budget_store.issue_root(
        grant, root_run_generation=run_generation, ingress_kind="web",
        reject_duplicate=True,
    )
    if row["phase"] == BudgetPhase.ISSUED:
        row = plan.budget_store.activate(grant.budget_id, expected_revision=row["revision"])
    if row["phase"] != BudgetPhase.ACTIVE:
        raise TaskBudgetDeniedError("operator_budget_not_active")
    member = TaskBudgetMember.from_dict(row["members"][grant.budget_id])
    return TaskBudgetExecution(store=plan.budget_store, budget_id=grant.budget_id, member=member)
