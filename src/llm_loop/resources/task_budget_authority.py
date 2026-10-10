"""I5-A: operator-signed, zero-side-effect Web budget approvals.

The signing key lives in a distinct operator authority; an LFL Run only
receives a preconfigured public verification key. No production Web route,
model message, factory, scheduler or config automatically enables this path.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import secrets
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, NoReturn

from llm_loop.core.trace_leak.ingress_token import IngressToken, is_whitelisted
from llm_loop.resources.task_budget_contracts import (
    BudgetPhase,
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import TaskBudgetExecution, exact_workspace_scope
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore

_DOMAIN = b"LFL-TaskBudget-operator-web-zero-v1\0"
_TOKEN_PREFIX = "tb1"
_POLICY_VERSION = "I5-A-web-zero-v1"
_MAX_TTL_SECONDS = 60
_MAX_SKEW_SECONDS = 5
_MAX_TOKEN_LENGTH = 8192
_FIELDS = frozenset({"approval_nonce", "grant", "issued_at", "key_id", "turn_digest"})
_URLSAFE = re.compile(r"[A-Za-z0-9_-]+\Z")
_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")


def _deny() -> NoReturn:
    # Never echo the proof or user input into error/telemetry.
    raise TaskBudgetDeniedError("operator_budget_proof_invalid")


def _canonical(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str, *, max_bytes: int) -> bytes:
    if not value or len(value) > max_bytes * 2 or not _URLSAFE.fullmatch(value):
        _deny()
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        _deny()
    if len(raw) > max_bytes or _encode(raw) != value:
        _deny()
    return raw


def _turn_digest(nonce: str, text: str) -> str:
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce) or not isinstance(text, str):
        _deny()
    return hashlib.sha256(_DOMAIN + nonce.encode() + b"\0" + text.encode()).hexdigest()


class OperatorBudgetIssuer:
    """Operator-side signing capability; not constructed by any model tool.

    Key creation, storage, user authentication and approval are owned by the
    operator service, not by TaskBudget or an LLM request. This method issues
    *only* the fixed zero-send profile, never user-provided policy fields.
    """

    def __init__(self, *, key_id: str, private_key_pem: bytes) -> None:
        from Crypto.PublicKey import ECC
        from Crypto.Signature import eddsa

        if not _KEY_ID.fullmatch(key_id):
            raise ValueError("invalid operator key id")
        private = ECC.import_key(private_key_pem)
        if private.curve != "Ed25519" or not private.has_private():
            raise ValueError("operator signer requires an Ed25519 private key")
        self._signer = eddsa.new(private, "rfc8032")
        self.key_id = key_id

    def approve_zero_web_turn(
        self, *, workspace_root: str, session_id: str, user_text: str,
        ttl_seconds: int = 30, now: float | None = None,
    ) -> str:
        if type(ttl_seconds) is not int or not 0 < ttl_seconds <= _MAX_TTL_SECONDS:
            raise ValueError("operator approval TTL is bounded to 1..60 seconds")
        start = time.time() if now is None else now
        if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start):
            raise ValueError("invalid operator clock")
        nonce = secrets.token_hex(16)
        grant = TaskBudgetGrant(
            budget_id=f"webbudget-{nonce}",
            issuer="web-operator",
            authority_source="operator-ed25519-v1",
            workspace_scope=exact_workspace_scope(workspace_root),
            session_id=session_id,
            human_turn_ref=f"human-{nonce}",
            surface="web",
            profile="web-zero-send-v1",
            policy_version=_POLICY_VERSION,
            deadline_epoch_s=start + ttl_seconds,
            limits=TaskBudgetLimits(
                logical_calls=1, physical_attempts=0, rounds=1, tool_invocations=0,
            ),
            capabilities=TaskBudgetCapabilities(
                allowed_tools=frozenset(), allow_wake=False, allow_subagents=False,
            ),
        )
        payload = {
            "approval_nonce": nonce,
            "key_id": self.key_id,
            "issued_at": start,
            "turn_digest": _turn_digest(nonce, user_text),
            "grant": grant.to_dict(),
        }
        body = _canonical(payload)
        signature = self._signer.sign(_DOMAIN + body)
        return ".".join((_TOKEN_PREFIX, _encode(body), _encode(signature)))


@dataclass(frozen=True)
class SignedWebBudgetIntent:
    """Explicit, caller-installed approval plus public-key trust anchors.

    This value is never parsed out of the chat message, tool arguments,
    Session history, environment, Web requests or Model-supplied metadata.
    """

    proof: str
    trusted_public_keys: Mapping[str, bytes]
    store: TaskBudgetStore


_SIGNED_WEB_INTENT: ContextVar[SignedWebBudgetIntent | None] = ContextVar(
    "lfl_signed_web_budget_intent", default=None
)


def active_signed_web_budget_intent() -> SignedWebBudgetIntent | None:
    """I5-E: prevent simultaneous text-only and event-bound authorities."""
    return _SIGNED_WEB_INTENT.get()


@contextmanager
def bind_signed_web_budget_intent(intent: SignedWebBudgetIntent) -> Iterator[None]:
    if not isinstance(intent, SignedWebBudgetIntent):
        raise TypeError("signed Web intent must be typed")
    token = _SIGNED_WEB_INTENT.set(intent)
    try:
        yield
    finally:
        _SIGNED_WEB_INTENT.reset(token)


def _verify(proof: str, trusted_public_keys: Mapping[str, bytes]) -> dict[str, Any]:
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    if not isinstance(proof, str) or len(proof) > _MAX_TOKEN_LENGTH:
        _deny()
    parts = proof.split(".")
    if len(parts) != 3 or parts[0] != _TOKEN_PREFIX:
        _deny()
    body = _decode(parts[1], max_bytes=6144)
    signature = _decode(parts[2], max_bytes=64)
    if len(signature) != 64:
        _deny()
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict) or set(payload) != _FIELDS:
            _deny()
        if _canonical(payload) != body:
            _deny()
        kid = payload["key_id"]
        if not isinstance(kid, str) or not _KEY_ID.fullmatch(kid):
            _deny()
        public_pem = trusted_public_keys.get(kid)
        if not isinstance(public_pem, bytes):
            _deny()
        public = ECC.import_key(public_pem)
        if public.curve != "Ed25519" or public.has_private():
            _deny()
        eddsa.new(public, "rfc8032").verify(_DOMAIN + body, signature)
    except (ValueError, TypeError, KeyError, UnicodeError):
        _deny()
    return payload


def prepare_signed_web_run_budget(
    *, session_id: str, workspace_root: str, run_generation: str,
    user_text: str, ingress: object | None,
) -> TaskBudgetExecution | None:
    """Consume a signed approval only after the actual Run lease is acquired.

    An absent intent is a no-op; any present but malformed/expired/mismatched
    intent must reject before the first provider or tool operation.
    """
    intent = _SIGNED_WEB_INTENT.get()
    if intent is None:
        return None
    if (
        not isinstance(ingress, IngressToken) or not is_whitelisted(ingress)
        or ingress.delegated or ingress.channel != "web" or ingress.entry != "web"
    ):
        raise TaskBudgetDeniedError("operator_budget_requires_human_web_ingress")
    if not run_generation:
        raise TaskBudgetDeniedError("operator_budget_missing_run_generation")
    payload = _verify(intent.proof, intent.trusted_public_keys)
    issued = payload["issued_at"]
    try:
        grant = TaskBudgetGrant.from_dict(payload["grant"])
    except (TypeError, ValueError, KeyError):
        _deny()
    clock = time.time()
    if (
        isinstance(issued, bool) or not isinstance(issued, (int, float))
        or not math.isfinite(issued) or issued > clock + _MAX_SKEW_SECONDS
        or clock >= issued + _MAX_TTL_SECONDS
        or grant.deadline_epoch_s <= issued or grant.deadline_epoch_s > issued + _MAX_TTL_SECONDS
        or clock >= grant.deadline_epoch_s
    ):
        _deny()
    nonce = payload["approval_nonce"]
    if (
        not isinstance(nonce, str) or not _NONCE.fullmatch(nonce)
        or grant.budget_id != f"webbudget-{nonce}"
        or grant.human_turn_ref != f"human-{nonce}"
        or payload["turn_digest"] != _turn_digest(nonce, user_text)
        or grant.issuer != "web-operator"
        or grant.authority_source != "operator-ed25519-v1"
        or grant.surface != "web" or grant.profile != "web-zero-send-v1"
        or grant.policy_version != _POLICY_VERSION or grant.generation != 1
        or grant.provider_identity or grant.exact_model_ref
        or grant.session_id != session_id
        or grant.workspace_scope != exact_workspace_scope(workspace_root)
        or grant.limits != TaskBudgetLimits(
            logical_calls=1, physical_attempts=0, rounds=1, tool_invocations=0,
        )
        or grant.capabilities != TaskBudgetCapabilities(
            allowed_tools=frozenset(), allow_wake=False, allow_subagents=False,
        )
    ):
        _deny()
    row = intent.store.issue_root(
        grant, root_run_generation=run_generation, ingress_kind="web",
        reject_duplicate=True,
    )
    if row["phase"] == BudgetPhase.ISSUED:
        row = intent.store.activate(grant.budget_id, expected_revision=row["revision"])
    if row["phase"] != BudgetPhase.ACTIVE:
        raise TaskBudgetDeniedError("operator_budget_not_active")
    member = TaskBudgetMember.from_dict(row["members"][grant.budget_id])
    return TaskBudgetExecution(store=intent.store, budget_id=grant.budget_id, member=member)
