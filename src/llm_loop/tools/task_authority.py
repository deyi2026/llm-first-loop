"""Verify Host-signed, revocable task capabilities without ever issuing them.

The public verifier is safe in LFL. Only a separate privileged Owner/Host
authority may sign leases and replace root-owned state files. No private key,
HMAC secret, model-supplied authority flag, or self-approval path exists here.

A signed lease alone is NOT an execution grant: callers must still check the
parent write scope, live Lane/CAS, OS permissions, physical sandbox, and effect
journal at the mutation boundary.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from llm_loop.core.task_capabilities import (
    CapabilityRequest,
    CapabilityResource,
    TaskLeaseClaims,
)

_LEASE_DOMAIN = b"lfl.task-lease.v1\x00"
_STATE_DOMAIN = b"lfl.task-lease-state.v1\x00"
_MAX_RECEIPT_BYTES = 65536
_LEASE_ID_RE = re.compile(r"[a-zA-Z0-9_-]{8,64}\Z")


class TaskAuthorityError(RuntimeError):
    """Stable fail-closed authority failure (never includes signed raw content)."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _parse_document(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > _MAX_RECEIPT_BYTES:
        raise TaskAuthorityError("authority_receipt_size_invalid")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise TaskAuthorityError("authority_receipt_invalid") from exc
    if not isinstance(data, dict) or set(data) != {"key_id", "payload", "signature"}:
        raise TaskAuthorityError("authority_receipt_invalid")
    if not isinstance(data["payload"], dict):
        raise TaskAuthorityError("authority_receipt_invalid")
    return data


def _verify_document(
    raw: bytes,
    *,
    public_key: Ed25519PublicKey,
    key_id: str,
    domain: bytes,
) -> dict[str, Any]:
    doc = _parse_document(raw)
    if doc["key_id"] != key_id or not isinstance(doc["signature"], str):
        raise TaskAuthorityError("authority_key_mismatch")
    try:
        signature = base64.b64decode(doc["signature"], validate=True)
        public_key.verify(signature, domain + _canonical_json(doc["payload"]))
    except (InvalidSignature, ValueError, binascii.Error, TypeError) as exc:
        raise TaskAuthorityError("authority_signature_invalid") from exc
    return doc["payload"]


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise TaskAuthorityError("authority_time_invalid")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TaskAuthorityError("authority_time_invalid") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise TaskAuthorityError("authority_time_invalid")
    return stamp.astimezone(UTC)


def _verify_lease_state_schema(lease: dict[str, Any], state: dict[str, Any]) -> None:
    """Check exact signed schema, state binding and revocation before use."""
    required = {
        "schema",
        "lease_id",
        "goal_id",
        "task_id",
        "owner_session_id",
        "agent_id",
        "lane_id",
        "revision",
        "issued_at",
        "expires_at",
        "authority_epoch",
        "resources",
        "parent_lease_id",
    }
    if set(lease) != required or lease.get("schema") != "lfl.task-capability-lease/v1":
        raise TaskAuthorityError("authority_lease_schema_invalid")
    if (
        set(state)
        != {
            "schema",
            "lease_id",
            "lease_revision",
            "lease_sha256",
            "authority_epoch",
            "status",
        }
        or state.get("schema") != "lfl.task-lease-state/v1"
    ):
        raise TaskAuthorityError("authority_state_schema_invalid")
    if (
        not isinstance(lease["lease_id"], str)
        or not _LEASE_ID_RE.fullmatch(lease["lease_id"])
        or type(lease["revision"]) is not int
        or lease["revision"] < 1
        or type(lease["authority_epoch"]) is not int
        or lease["authority_epoch"] < 1
    ):
        raise TaskAuthorityError("authority_lease_schema_invalid")
    if (
        state["lease_id"] != lease["lease_id"]
        or state["lease_revision"] != lease["revision"]
        or state["lease_sha256"] != hashlib.sha256(_canonical_json(lease)).hexdigest()
        or state["authority_epoch"] != lease["authority_epoch"]
    ):
        raise TaskAuthorityError("authority_state_stale")
    if state["status"] != "active":
        raise TaskAuthorityError("authority_lease_revoked")


def verify_signed_task_lease(
    public_key_pem: bytes,
    lease_document: bytes,
    state_document: bytes,
    request: CapabilityRequest,
    *,
    now: datetime | None = None,
) -> TaskLeaseClaims:
    """Pure verification; caller must supply bytes from a trusted Host source.

    This pure function is NOT a production file loader or approval interface.
    It deliberately does not infer parent/Lane/backend/OS authority from JSON.
    """
    try:
        key = serialization.load_pem_public_key(public_key_pem)
    except (ValueError, TypeError) as exc:
        raise TaskAuthorityError("authority_public_key_invalid") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise TaskAuthorityError("authority_public_key_invalid")
    key_id = hashlib.sha256(
        key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).hexdigest()[:16]
    lease = _verify_document(lease_document, public_key=key, key_id=key_id, domain=_LEASE_DOMAIN)
    state = _verify_document(state_document, public_key=key, key_id=key_id, domain=_STATE_DOMAIN)
    _verify_lease_state_schema(lease, state)

    issued, expiry = _parse_time(lease["issued_at"]), _parse_time(lease["expires_at"])
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise TaskAuthorityError("authority_time_invalid")
    clock = clock.astimezone(UTC)
    if clock >= expiry or clock < issued - timedelta(seconds=60):
        raise TaskAuthorityError("authority_lease_expired_or_not_yet_valid")
    if expiry <= issued or expiry - issued > timedelta(hours=24):
        raise TaskAuthorityError("authority_lease_ttl_invalid")
    if not isinstance(lease["resources"], list) or not lease["resources"]:
        raise TaskAuthorityError("authority_lease_schema_invalid")
    try:
        resources = tuple(
            CapabilityResource(
                kind=item["kind"],
                identity=item["identity"],
                verbs=frozenset(item["verbs"]),
            )
            for item in lease["resources"]
            if isinstance(item, dict)
            and set(item) == {"kind", "identity", "verbs"}
            and isinstance(item["verbs"], list)
            and all(isinstance(v, str) for v in item["verbs"])
        )
        if len(resources) != len(lease["resources"]):
            raise ValueError("invalid resource")
        parent_id = lease["parent_lease_id"]
        if parent_id is not None and (
            not isinstance(parent_id, str) or not _LEASE_ID_RE.fullmatch(parent_id)
        ):
            raise ValueError("invalid parent")
        claims = TaskLeaseClaims(
            lease_id=lease["lease_id"],
            goal_id=lease["goal_id"],
            task_id=lease["task_id"],
            owner_session_id=lease["owner_session_id"],
            agent_id=lease["agent_id"],
            lane_id=lease["lane_id"],
            revision=lease["revision"],
            expires_at=expiry,
            resources=resources,
            parent_lease_id=parent_id,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TaskAuthorityError("authority_lease_schema_invalid") from exc

    if (
        claims.goal_id != request.goal_id
        or claims.task_id != request.task_id
        or claims.owner_session_id != request.owner_session_id
        or claims.agent_id != request.agent_id
        or claims.lane_id != request.lane_id
        or claims.revision != request.expected_revision
    ):
        raise TaskAuthorityError("authority_identity_or_revision_mismatch")
    return claims


def _read_root_owned(path: Path) -> bytes:
    """Reject a user-writable parent, symlink, or untrusted inode before read."""
    if not path.is_absolute():
        raise TaskAuthorityError("authority_store_untrusted")
    parent = path.parent
    while True:
        try:
            info = os.lstat(parent)
        except OSError as exc:
            raise TaskAuthorityError("authority_store_unavailable") from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise TaskAuthorityError("authority_store_untrusted")
        if parent == parent.parent:
            break
        parent = parent.parent
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise TaskAuthorityError("authority_store_unavailable") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_mode & 0o022
            or info.st_nlink != 1
        ):
            raise TaskAuthorityError("authority_store_untrusted")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(_MAX_RECEIPT_BYTES + 1)
        if len(raw) > _MAX_RECEIPT_BYTES:
            raise TaskAuthorityError("authority_receipt_size_invalid")
        return raw
    finally:
        os.close(fd)


def _read_separated_issuer_file(path: Path, root: Path, issuer_uid: int) -> bytes:
    """Trust a distinct Host UID only below a root-owned pinned trust anchor."""
    if (
        not path.is_absolute()
        or not root.is_absolute()
        or os.path.commonpath((str(path), str(root))) != str(root)
    ):
        raise TaskAuthorityError("authority_store_untrusted")
    parent = path.parent
    while parent != root:
        try:
            info = os.lstat(parent)
        except OSError as exc:
            raise TaskAuthorityError("authority_store_unavailable") from exc
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in (0, issuer_uid)
            or info.st_mode & 0o022
        ):
            raise TaskAuthorityError("authority_store_untrusted")
        parent = parent.parent
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise TaskAuthorityError("authority_store_unavailable") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != issuer_uid
            or info.st_mode & 0o022
            or info.st_nlink != 1
        ):
            raise TaskAuthorityError("authority_store_untrusted")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(_MAX_RECEIPT_BYTES + 1)
        if not raw or len(raw) > _MAX_RECEIPT_BYTES:
            raise TaskAuthorityError("authority_receipt_size_invalid")
        return raw
    finally:
        os.close(fd)


@dataclass(frozen=True)
class RootOwnedTaskAuthority:
    """Read-only Host adapter with root-pinned public key and separate issuer UID.

    Root-owned trust.json fixes issuer UID and public PEM digest. Lease/state
    files must be owned by that distinct UID, not by the agent's Unix user.
    No signer or privileged shell is exposed to the model.
    """

    root: Path

    def _trust(self) -> tuple[int, bytes]:
        try:
            trust = json.loads(_read_root_owned(self.root / "trust.json"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TaskAuthorityError("authority_trust_config_invalid") from exc
        if (
            not isinstance(trust, dict)
            or set(trust) != {"schema", "issuer_uid", "public_key_sha256"}
            or trust["schema"] != "lfl.task-authority-trust/v1"
            or type(trust["issuer_uid"]) is not int
            or trust["issuer_uid"] < 0
            or trust["issuer_uid"] == os.getuid()
            or not isinstance(trust["public_key_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", trust["public_key_sha256"])
        ):
            raise TaskAuthorityError("authority_trust_config_invalid")
        public_key = _read_root_owned(self.root / "public_key.pem")
        if not hmac.compare_digest(
            hashlib.sha256(public_key).hexdigest(), trust["public_key_sha256"]
        ):
            raise TaskAuthorityError("authority_public_key_mismatch")
        return trust["issuer_uid"], public_key

    def verify(self, lease_id: str, request: CapabilityRequest) -> TaskLeaseClaims:
        if not isinstance(lease_id, str) or not _LEASE_ID_RE.fullmatch(lease_id):
            raise TaskAuthorityError("authority_lease_id_invalid")
        issuer_uid, public_key = self._trust()
        return verify_signed_task_lease(
            public_key,
            _read_separated_issuer_file(
                self.root / "leases" / f"{lease_id}.json",
                self.root,
                issuer_uid,
            ),
            _read_separated_issuer_file(
                self.root / "states" / f"{lease_id}.json",
                self.root,
                issuer_uid,
            ),
            request,
        )

    def load(self, lease_id: str) -> TaskLeaseClaims:
        """Verify signed identity without accepting any model-authored claims."""
        if not isinstance(lease_id, str) or not _LEASE_ID_RE.fullmatch(lease_id):
            raise TaskAuthorityError("authority_lease_id_invalid")
        issuer_uid, _public = self._trust()
        raw = _read_separated_issuer_file(
            self.root / "leases" / f"{lease_id}.json", self.root, issuer_uid
        )
        try:
            payload = _parse_document(raw)["payload"]
            first = payload["resources"][0]
            request = CapabilityRequest(
                goal_id=payload["goal_id"],
                task_id=payload["task_id"],
                owner_session_id=payload["owner_session_id"],
                agent_id=payload["agent_id"],
                lane_id=payload["lane_id"],
                expected_revision=payload["revision"],
                kind=first["kind"],
                target=first["identity"],
                verb=first["verbs"][0],
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise TaskAuthorityError("authority_lease_schema_invalid") from exc
        claims = self.verify(lease_id, request)
        if claims.lease_id != lease_id:
            raise TaskAuthorityError("authority_lease_id_mismatch")
        return claims

    def discover_for_session(self, session_id: str) -> TaskLeaseClaims | None:
        """Resolve one Host-owned session binding; ambiguous active leases HOLD."""
        if not isinstance(session_id, str) or not 0 < len(session_id) <= 256:
            raise TaskAuthorityError("authority_session_invalid")
        issuer_uid, _public = self._trust()
        base = self.root / "bindings"
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        directory = base / digest
        for candidate, may_be_absent in ((base, False), (directory, True)):
            try:
                info = os.lstat(candidate)
            except FileNotFoundError as exc:
                if may_be_absent:
                    return None
                raise TaskAuthorityError("authority_bindings_unavailable") from exc
            except OSError as exc:
                raise TaskAuthorityError("authority_bindings_unavailable") from exc
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != issuer_uid or info.st_mode & 0o022:
                raise TaskAuthorityError("authority_bindings_untrusted")
        try:
            names = sorted(os.listdir(directory))
        except OSError as exc:
            raise TaskAuthorityError("authority_bindings_unavailable") from exc
        if len(names) > 64:
            raise TaskAuthorityError("authority_bindings_ambiguous")
        active: list[TaskLeaseClaims] = []
        for name in names:
            if not name.endswith(".json") or not _LEASE_ID_RE.fullmatch(name[:-5]):
                raise TaskAuthorityError("authority_binding_invalid")
            lease_id = name[:-5]
            try:
                binding = json.loads(
                    _read_separated_issuer_file(directory / name, self.root, issuer_uid)
                )
            except (ValueError, UnicodeDecodeError) as exc:
                raise TaskAuthorityError("authority_binding_invalid") from exc
            if (
                not isinstance(binding, dict)
                or set(binding) != {"schema", "owner_session_id", "lease_id"}
                or binding["schema"] != "lfl.task-session-binding/v1"
                or binding["owner_session_id"] != session_id
                or binding["lease_id"] != lease_id
            ):
                raise TaskAuthorityError("authority_binding_invalid")
            try:
                claims = self.load(lease_id)
            except TaskAuthorityError as exc:
                if exc.reason_code in (
                    "authority_lease_revoked",
                    "authority_lease_expired_or_not_yet_valid",
                ):
                    continue
                raise
            if claims.owner_session_id != session_id or claims.parent_lease_id is not None:
                raise TaskAuthorityError("authority_binding_identity_invalid")
            active.append(claims)
            if len(active) > 1:
                raise TaskAuthorityError("authority_bindings_ambiguous")
        return active[0] if active else None
