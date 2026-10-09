"""I5-G: isolated control-plane proof for ONE bounded GLM physical attempt.

This is an explicitly installed, externally approved, offline-canary profile.
It does not install a Web route, model tool, production operator daemon or
private key. No token/fee hard cap is claimed. Signer and Run use different
process trust domains in a *qualified* deployment (not established by tests).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import time
from collections.abc import Mapping
from typing import Any, NoReturn

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from llm_loop.event_log.model import Event
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_authority import (
    OperatorBudgetIssuer,
    _canonical,
    _decode,
    _encode,
)
from llm_loop.resources.task_budget_contracts import (
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
)
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_event_authority import (
    _event_hash,
    _rehydrate_event,
)
from llm_loop.resources.task_budget_operator_proof import OperatorApprovalVerifier
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError

_DOMAIN = b"LFL-TaskBudget-one-GLM-physical-attempt-v3\0"
PREFIX = "tb3"
POLICY = "I5-G-glm-one-attempt-v3"
PROFILE = "web-glm-one-physical-attempt-v3"
_MAX_TTL = 30
_SKEW = 5
_ID = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = frozenset({
    "approval_nonce", "issued_at", "key_id", "grant", "event_id",
    "event_seq", "event_sha256", "operator_ref",
})


def _deny() -> NoReturn:
    raise TaskBudgetDeniedError("one_attempt_operator_proof_invalid")


def limits() -> TaskBudgetLimits:
    # Rounds/logical calls and billing are NOT hard-qualified by this gate;
    # do not claim a ceiling for resources not mechanically enforced.
    return TaskBudgetLimits(physical_attempts=1, tool_invocations=0)


def capabilities() -> TaskBudgetCapabilities:
    return TaskBudgetCapabilities(
        allowed_tools=frozenset(), allow_wake=False, allow_subagents=False,
    )


class ApprovedOneAttemptIssuer:
    """Control-plane signer requiring an independent op1 Ed25519 approval.

    Cannot use the old arbitrary authenticate_operator callback and never
    exposes the v1/v2 zero-profile methods as an alternative sign path.
    Only an explicitly authorized operator may request this fixed policy.
    """

    def __init__(
        self, *, key_id: str, private_key_pem: bytes,
        operator_verifier: OperatorApprovalVerifier,
    ) -> None:
        if not isinstance(operator_verifier, OperatorApprovalVerifier):
            raise TypeError("independent_cryptographic_operator_verifier_required")
        signer = OperatorBudgetIssuer(key_id=key_id, private_key_pem=private_key_pem)
        self.key_id = signer.key_id
        self._signer = signer._signer
        self._operator_verifier = operator_verifier

    def approve_exact_event(
        self, *, event_store: EventStore, event: Event, operator_proof: str,
        workspace_root: str, session_id: str, ttl_seconds: int = 30,
        now: float | None = None,
    ) -> str:
        if type(ttl_seconds) is not int or not 0 < ttl_seconds <= _MAX_TTL:
            _deny()
        if not isinstance(event, Event) or event.session_id != session_id:
            _deny()
        actual = _rehydrate_event(event_store, session_id, event.event_id)
        if actual != event:
            _deny()
        scope = exact_workspace_scope(workspace_root)
        principal = self._operator_verifier.authenticate(
            operator_proof, event_id=actual.event_id, event_seq=actual.seq,
            event_sha256=_event_hash(actual), session_id=session_id,
            workspace_scope=scope,
        )
        instant = time.time() if now is None else now
        if (
            isinstance(instant, bool)
            or not isinstance(instant, (int, float))
            or not math.isfinite(instant)
        ):
            _deny()
        nonce = secrets.token_hex(16)
        grant = TaskBudgetGrant(
            # Same event, same root identity even across zero/positive tokens,
            # distinct signer nonce and parallel Processes.
            budget_id=f"webbudget-event-{actual.event_id.replace('-', '')}",
            issuer="web-operator",
            authority_source="operator-event-ed25519-v3",
            workspace_scope=scope, session_id=session_id,
            human_turn_ref=f"event-{actual.event_id}",
            surface="web", profile=PROFILE, policy_version=POLICY,
            deadline_epoch_s=instant + ttl_seconds,
            limits=limits(), capabilities=capabilities(),
            provider_identity="glm", exact_model_ref="glm-5.3",
        )
        payload = {
            "approval_nonce": nonce, "issued_at": instant,
            "key_id": self.key_id, "grant": grant.to_dict(),
            "event_id": actual.event_id, "event_seq": actual.seq,
            "event_sha256": _event_hash(actual),
            "operator_ref": hashlib.sha256(_DOMAIN + principal.encode()).hexdigest(),
        }
        body = _canonical(payload)
        return ".".join((PREFIX, _encode(body), _encode(self._signer.sign(_DOMAIN + body))))


def verify_positive_proof(proof: str, public_keys: Mapping[str, bytes]) -> dict[str, Any]:
    """Validate the v3 signature in its own domain, never as a tb2 proof."""
    if not isinstance(proof, str) or len(proof) > 8192:
        _deny()
    parts = proof.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        _deny()
    try:
        body = _decode(parts[1], max_bytes=6144)
        sig = _decode(parts[2], max_bytes=64)
        data = json.loads(body)
        if len(sig) != 64 or not isinstance(data, dict) or set(data) != _FIELDS:
            _deny()
        if _canonical(data) != body:
            _deny()
        kid = data["key_id"]
        if not isinstance(kid, str) or not _ID.fullmatch(kid):
            _deny()
        public_pem = public_keys.get(kid)
        if not isinstance(public_pem, bytes):
            _deny()
        key = ECC.import_key(public_pem)
        if key.curve != "Ed25519" or key.has_private():
            _deny()
        eddsa.new(key, "rfc8032").verify(_DOMAIN + body, sig)
        nonce, operator = data["approval_nonce"], data["operator_ref"]
        if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
            _deny()
        if not isinstance(operator, str) or not _SHA.fullmatch(operator):
            _deny()
        return data
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
        _deny()
