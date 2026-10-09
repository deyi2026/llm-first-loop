"""I5-F offline cryptographic OPERATOR approval, separate from Web login.

Two independent Ed25519 keys: an operator identity signs an exact persisted
human event approval, and a separate budget authority signs the tb2 grant.
The Web Run can verify operator approval with public keys ONLY. There is no
production key provisioning, Web endpoint, or auto-approval in this module.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import stat
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from llm_loop.resources.task_budget_authority import _canonical, _decode, _encode
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError

_DOMAIN = b"LFL-TaskBudget-independent-operator-event-approval-v1\0"
_FIELDS = frozenset({
    "operator_id", "key_id", "event_id", "event_seq", "event_sha256",
    "session_id", "workspace_scope", "issued_at", "expires_at", "nonce",
})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_MAX_TTL = 60


def _deny() -> NoReturn:
    raise TaskBudgetDeniedError("independent_operator_approval_invalid")


@dataclass(frozen=True)
class OperatorApprovalVerifier:
    """Pinned public operator keys; no password, cookie, or signing ability."""

    trusted_keys: Mapping[str, bytes]
    authorized_operators: Mapping[str, str]  # operator_id -> exact key_id
    revoked_keys: frozenset[str] = frozenset()

    def authenticate(
        self, ticket: str, *, event_id: str, event_seq: int,
        event_sha256: str, session_id: str, workspace_scope: str,
        now: float | None = None,
    ) -> str:
        if not isinstance(ticket, str) or len(ticket) > 8192:
            _deny()
        parts = ticket.split(".")
        if len(parts) != 3 or parts[0] != "op1":
            _deny()
        try:
            body = _decode(parts[1], max_bytes=4096)
            sig = _decode(parts[2], max_bytes=64)
            data = json.loads(body)
            if len(sig) != 64 or not isinstance(data, dict) or set(data) != _FIELDS:
                _deny()
            if _canonical(data) != body:
                _deny()
            kid, principal = data["key_id"], data["operator_id"]
            if not isinstance(kid, str) or not _ID.fullmatch(kid):
                _deny()
            if not isinstance(principal, str) or not _ID.fullmatch(principal):
                _deny()
            if (
                kid in self.revoked_keys or self.authorized_operators.get(principal) != kid
                or kid not in self.trusted_keys
            ):
                _deny()
            public_key = self.trusted_keys[kid]
            if not isinstance(public_key, bytes):
                _deny()
            key = ECC.import_key(public_key)
            if key.curve != "Ed25519" or key.has_private():
                _deny()
            eddsa.new(key, "rfc8032").verify(_DOMAIN + body, sig)
            stamp, expiry = data["issued_at"], data["expires_at"]
            moment = time.time() if now is None else now
            if any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in (stamp, expiry, moment)
            ):
                _deny()
            if stamp > moment + 5 or moment >= expiry or not 0 < expiry - stamp <= _MAX_TTL:
                _deny()
            if not isinstance(data["nonce"], str) or not _NONCE.fullmatch(data["nonce"]):
                _deny()
            if (
                data["event_id"] != event_id
                or type(data["event_seq"]) is not int or data["event_seq"] != event_seq
                or data["event_sha256"] != event_sha256
                or not isinstance(data["event_sha256"], str)
                or not _HEX.fullmatch(data["event_sha256"])
                or data["session_id"] != session_id
                or data["workspace_scope"] != workspace_scope
            ):
                _deny()
            return principal
        except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
            _deny()


def load_pinned_operator_verifier(path: str | os.PathLike[str]) -> OperatorApprovalVerifier:
    """Load ONLY pinned public keys from an operator-owned local trust file.

    This is a read-only control-plane primitive, not a Web API or runtime
    source of operator approval. It never loads a private key, bearer token,
    or values submitted by the chat/model. Call for every approval so key
    revocation/rotation has no stale process-local cache.
    """
    target = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(target))
    try:
        directory = os.lstat(parent)
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid not in {0, os.geteuid()}
            or directory.st_mode & 0o022
        ):
            _deny()
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            file_stat = os.fstat(fd)
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_uid not in {0, os.geteuid()}
                or file_stat.st_mode & 0o077
                or file_stat.st_nlink != 1
                or file_stat.st_size > 16_384
            ):
                _deny()
            with os.fdopen(fd, "rb", closefd=False) as f:
                raw = f.read(16_385)
        finally:
            os.close(fd)
        if len(raw) > 16_384:
            _deny()
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {
            "schema", "public_keys", "authorized_operators", "revoked_keys"
        } or data["schema"] != "task-budget-operator-trust/v1":
            _deny()
        pub, roles, revoked = data["public_keys"], data["authorized_operators"], data["revoked_keys"]
        if (
            not isinstance(pub, dict) or not isinstance(roles, dict)
            or not isinstance(revoked, list) or len(pub) > 16 or len(roles) > 32
            or len(revoked) != len(set(revoked))
        ):
            _deny()
        keys: dict[str, bytes] = {}
        for key_id, pem in pub.items():
            if not isinstance(key_id, str) or not _ID.fullmatch(key_id) or not isinstance(pem, str):
                _deny()
            imported = ECC.import_key(pem)
            if imported.curve != "Ed25519" or imported.has_private():
                _deny()
            keys[key_id] = pem.encode("ascii")
        for operator_id, key_id in roles.items():
            if (
                not isinstance(operator_id, str) or not _ID.fullmatch(operator_id)
                or not isinstance(key_id, str) or key_id not in keys
            ):
                _deny()
        if any(not isinstance(key, str) or key not in keys for key in revoked):
            _deny()
        return OperatorApprovalVerifier(keys, roles, frozenset(revoked))
    except (OSError, ValueError, UnicodeError, TypeError, KeyError):
        _deny()


class OfflineOperatorApprovalSigner:
    """Test/operator-process helper. Private key never belongs to a Web Run."""

    def __init__(self, *, key_id: str, operator_id: str, private_key_pem: bytes) -> None:
        if not _ID.fullmatch(key_id) or not _ID.fullmatch(operator_id):
            raise ValueError("invalid_operator_identity")
        key = ECC.import_key(private_key_pem)
        if key.curve != "Ed25519" or not key.has_private():
            raise ValueError("operator_signer_requires_private_ed25519_key")
        self.key_id = key_id
        self.operator_id = operator_id
        self._signer = eddsa.new(key, "rfc8032")

    def sign_exact_event(
        self, *, event_id: str, event_seq: int, event_sha256: str,
        session_id: str, workspace_scope: str, ttl_seconds: int = 30,
        now: float | None = None,
    ) -> str:
        if type(ttl_seconds) is not int or not 0 < ttl_seconds <= _MAX_TTL:
            raise ValueError("invalid_operator_approval_ttl")
        stamp = time.time() if now is None else now
        if not isinstance(stamp, (int, float)) or isinstance(stamp, bool) or not math.isfinite(stamp):
            raise ValueError("invalid_operator_approval_clock")
        if not isinstance(event_sha256, str) or not _HEX.fullmatch(event_sha256):
            raise ValueError("invalid_operator_event_hash")
        payload: dict[str, Any] = {
            "operator_id": self.operator_id, "key_id": self.key_id,
            "event_id": event_id, "event_seq": event_seq,
            "event_sha256": event_sha256, "session_id": session_id,
            "workspace_scope": workspace_scope,
            "issued_at": stamp, "expires_at": stamp + ttl_seconds,
            "nonce": secrets.token_hex(16),
        }
        body = _canonical(payload)
        return ".".join(("op1", _encode(body), _encode(self._signer.sign(_DOMAIN + body))))
