#!/usr/bin/env python3
"""Offline operator-only Task Capability issuer for the separated Host UID.

Never expose as an LFL model tool, Web route, daemon or arbitrary signing API.
Production execution requires root-owned installed code, dedicated UID462,
Python -I -S and an issuer-owned 0600 Owner-reviewed approval file.
The premerge Host signing key/domain is never read or reused.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_ISSUER_UID = 462
_BASE = Path("/Library/Application Support/LFL-HostIssuer/task-authority")
_TRUSTED_SITE = Path("/Library/Application Support/LFL-DualAgent/runtime/site")
_ID = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")
_VERBS = {
    "project": {"read", "write", "create", "rename", "delete", "build", "git_commit"},
    "app": {"observe", "edit"},
    "service": {"status", "restart"},
}


class IssuerHoldError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise IssuerHoldError(code)


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise IssuerHoldError("approval_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IssuerHoldError("approval_time_invalid") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "approval_time_invalid")
    return parsed.astimezone(UTC)


def _validate_approval(approval: dict[str, Any], now: datetime) -> None:
    required = {
        "schema",
        "approval_id",
        "approved_at",
        "approved_by",
        "purpose",
        "goal_id",
        "task_id",
        "owner_session_id",
        "agent_id",
        "lane_id",
        "revision",
        "authority_epoch",
        "ttl_seconds",
        "parent_lease_id",
        "resources",
    }
    require(
        set(approval) == required and approval.get("schema") == "lfl.task-approval/v1",
        "approval_schema_invalid",
    )
    require(
        isinstance(approval["approval_id"], str) and bool(_ID.fullmatch(approval["approval_id"])),
        "approval_id_invalid",
    )
    for name in (
        "approved_by",
        "purpose",
        "goal_id",
        "task_id",
        "owner_session_id",
        "agent_id",
        "lane_id",
    ):
        require(
            isinstance(approval[name], str) and 0 < len(approval[name]) <= 256,
            "approval_identity_invalid",
        )
    for name in ("revision", "authority_epoch"):
        require(type(approval[name]) is int and approval[name] > 0, "approval_revision_invalid")
    ttl = approval["ttl_seconds"]
    require(type(ttl) is int and 1 <= ttl <= 86400, "approval_ttl_invalid")
    age = now - _utc(approval["approved_at"])
    require(timedelta(seconds=-60) <= age <= timedelta(minutes=10), "approval_stale")
    parent = approval["parent_lease_id"]
    require(
        parent is None or (isinstance(parent, str) and bool(_ID.fullmatch(parent))),
        "approval_parent_invalid",
    )
    require(parent is None, "approval_parent_chain_not_yet_supported")
    resources = approval["resources"]
    require(isinstance(resources, list) and 1 <= len(resources) <= 8, "approval_resources_invalid")
    for resource in resources:
        require(
            isinstance(resource, dict) and set(resource) == {"kind", "identity", "verbs"},
            "approval_resource_schema_invalid",
        )
        kind, identity, verbs = (resource["kind"], resource["identity"], resource["verbs"])
        require(isinstance(kind, str) and kind in _VERBS, "approval_resource_kind_invalid")
        require(
            isinstance(verbs, list)
            and bool(verbs)
            and all(isinstance(v, str) for v in verbs)
            and set(verbs).issubset(_VERBS[kind]),
            "approval_resource_verbs_invalid",
        )
        require(isinstance(identity, str) and bool(identity), "approval_resource_identity_invalid")
        if kind == "project":
            require(
                os.path.isabs(identity)
                and os.path.realpath(identity) == identity
                and os.path.isdir(identity)
                and not os.path.islink(identity)
                and identity not in ("/", "/tmp", "/private/tmp", "/Users", "/home")
                and Path(identity).parent != Path("/Users")
                and Path(identity).parent != Path("/home")
                and os.path.commonpath((identity, str(_BASE))) != identity,
                "approval_project_root_unsafe",
            )
        else:
            require(
                "/" not in identity and "\\" not in identity and "*" not in identity,
                "approval_resource_identity_invalid",
            )


def _envelope(key: Any, payload: dict[str, Any], domain: bytes, eddsa: Any) -> bytes:
    public = key.public_key()
    key_id = hashlib.sha256(public.export_key(format="raw")).hexdigest()[:16]
    signature = eddsa.new(key, "rfc8032").sign(domain + b"\x00" + canonical(payload))
    return canonical(
        {
            "key_id": key_id,
            "payload": payload,
            "signature": base64.b64encode(signature).decode("ascii"),
        }
    )


def issue_receipts(
    approval: dict[str, Any],
    key: Any,
    eddsa: Any,
    *,
    now: datetime | None = None,
    lease_id: str | None = None,
) -> tuple[bytes, bytes, str]:
    """Construct ONLY the fixed Task Lease/State schemas after Owner approval."""
    clock = now or datetime.now(UTC)
    require(clock.tzinfo is not None and clock.utcoffset() is not None, "approval_time_invalid")
    clock = clock.astimezone(UTC)
    _validate_approval(approval, clock)
    ident = lease_id or "lease-" + secrets.token_hex(16)
    require(bool(_ID.fullmatch(ident)), "lease_id_invalid")
    lease = {
        "schema": "lfl.task-capability-lease/v1",
        "lease_id": ident,
        "goal_id": approval["goal_id"],
        "task_id": approval["task_id"],
        "owner_session_id": approval["owner_session_id"],
        "agent_id": approval["agent_id"],
        "lane_id": approval["lane_id"],
        "revision": approval["revision"],
        "issued_at": clock.isoformat(),
        "expires_at": (clock + timedelta(seconds=approval["ttl_seconds"])).isoformat(),
        "authority_epoch": approval["authority_epoch"],
        "parent_lease_id": approval["parent_lease_id"],
        "resources": approval["resources"],
    }
    state = {
        "schema": "lfl.task-lease-state/v1",
        "lease_id": ident,
        "lease_revision": lease["revision"],
        "lease_sha256": hashlib.sha256(canonical(lease)).hexdigest(),
        "authority_epoch": lease["authority_epoch"],
        "status": "active",
    }
    return (
        _envelope(key, lease, b"lfl.task-lease.v1", eddsa),
        _envelope(key, state, b"lfl.task-lease-state.v1", eddsa),
        ident,
    )


def revoked_state(lease_document: bytes, key: Any, eddsa: Any) -> tuple[bytes, str]:
    """Sign an irreversible revoked state for the exact existing lease."""
    try:
        lease_doc = json.loads(lease_document)
        lease = lease_doc["payload"]
    except (ValueError, KeyError, TypeError) as exc:
        raise IssuerHoldError("lease_receipt_invalid") from exc
    require(
        lease.get("schema") == "lfl.task-capability-lease/v1"
        and isinstance(lease.get("lease_id"), str)
        and bool(_ID.fullmatch(lease["lease_id"])),
        "lease_receipt_invalid",
    )
    # Do not revoke an unverified/forged lease by merely trusting its JSON.
    expected = _envelope(key, lease, b"lfl.task-lease.v1", eddsa)
    require(
        json.loads(expected)["signature"] == lease_doc.get("signature"),
        "lease_receipt_signature_invalid",
    )
    state = {
        "schema": "lfl.task-lease-state/v1",
        "lease_id": lease["lease_id"],
        "lease_revision": lease["revision"],
        "lease_sha256": hashlib.sha256(canonical(lease)).hexdigest(),
        "authority_epoch": lease["authority_epoch"],
        "status": "revoked",
    }
    return _envelope(key, state, b"lfl.task-lease-state.v1", eddsa), lease["lease_id"]


def _crypto() -> tuple[Any, Any]:
    """Only root-owned frozen runtime modules are importable in production."""
    info = _TRUSTED_SITE.lstat()
    require(
        stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
        "issuer_crypto_runtime_untrusted",
    )
    sys.path.insert(0, str(_TRUSTED_SITE))
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    trusted = _TRUSTED_SITE.resolve(strict=True)
    for module in (ECC, eddsa):
        require(
            Path(module.__file__).resolve(strict=True).is_relative_to(trusted),
            "issuer_crypto_module_untrusted",
        )
    return ECC, eddsa


def _check_installed() -> None:
    require(os.getuid() == _ISSUER_UID and os.geteuid() == _ISSUER_UID, "issuer_uid_invalid")
    require(bool(sys.flags.isolated and sys.flags.no_site), "issuer_python_not_isolated")
    installed = _BASE.parent / "bin" / "task_lease_issuer.py"
    info = installed.lstat()
    parent = installed.parent
    while True:
        st = parent.lstat()
        require(
            stat.S_ISDIR(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022,
            "issuer_install_parent_untrusted",
        )
        if parent == parent.parent:
            break
        parent = parent.parent
    require(
        Path(__file__).resolve(strict=True) == installed
        and stat.S_ISREG(info.st_mode)
        and info.st_uid == 0
        and info.st_mode & 0o222 == 0,
        "issuer_install_untrusted",
    )
    for path, uid, private in (
        (_BASE, 0, False),
        (_BASE / "private", _ISSUER_UID, True),
        (_BASE / "private" / "approvals", _ISSUER_UID, True),
        (_BASE / "private" / "consumed", _ISSUER_UID, True),
        (_BASE / "leases", _ISSUER_UID, False),
        (_BASE / "states", _ISSUER_UID, False),
        (_BASE / "bindings", _ISSUER_UID, False),
    ):
        st = path.lstat()
        require(
            stat.S_ISDIR(st.st_mode)
            and st.st_uid == uid
            and st.st_mode & 0o022 == 0
            and (not private or st.st_mode & 0o077 == 0),
            "issuer_directory_untrusted",
        )


def _read_owned(path: Path, *, mode_private: bool) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        require(
            stat.S_ISREG(st.st_mode)
            and st.st_uid == _ISSUER_UID
            and st.st_nlink == 1
            and (st.st_mode & (0o077 if mode_private else 0o022)) == 0
            and 0 < st.st_size <= 65536,
            "issuer_file_untrusted",
        )
        raw = os.read(fd, 65537)
        require(len(raw) == st.st_size, "issuer_file_changed")
        return raw
    finally:
        os.close(fd)


def _read_root_trust(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        require(
            stat.S_ISREG(st.st_mode)
            and st.st_uid == 0
            and st.st_nlink == 1
            and st.st_mode & 0o022 == 0
            and 0 < st.st_size <= 65536,
            "issuer_root_trust_untrusted",
        )
        raw = os.read(fd, 65537)
        require(len(raw) == st.st_size, "issuer_root_trust_changed")
        return raw
    finally:
        os.close(fd)


def _verify_public_trust(key: Any, ecc_module: Any) -> None:
    trust = json.loads(_read_root_trust(_BASE / "trust.json"))
    public_pem = _read_root_trust(_BASE / "public_key.pem")
    require(
        isinstance(trust, dict)
        and set(trust) == {"schema", "issuer_uid", "public_key_sha256"}
        and trust["schema"] == "lfl.task-authority-trust/v1"
        and type(trust["issuer_uid"]) is int
        and trust["issuer_uid"] == _ISSUER_UID
        and trust["public_key_sha256"] == hashlib.sha256(public_pem).hexdigest(),
        "issuer_public_trust_mismatch",
    )
    pub = ecc_module.import_key(public_pem)
    require(
        pub.export_key(format="raw") == key.public_key().export_key(format="raw"),
        "issuer_public_key_mismatch",
    )


def _create(path: Path, raw: bytes, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            written = stream.write(raw)
            require(written == len(raw), "issuer_write_incomplete")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def _audit(event: str, lease_id: str, approval_id: str = "") -> None:
    path = _BASE / "private" / "task-issuer-audit.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        raw = (
            canonical(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "event": event,
                    "lease_id": lease_id,
                    "approval_id": approval_id,
                }
            )
            + b"\n"
        )
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            require(written > 0, "issuer_audit_write_incomplete")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("keygen", "issue", "revoke"), required=True)
    parser.add_argument("--approval-id", default="")
    parser.add_argument("--lease-id", default="")
    args = parser.parse_args(argv)
    try:
        _check_installed()
        ecc_module, eddsa = _crypto()
        key_path = _BASE / "private" / "task-ed25519.pem"
        if args.mode == "keygen":
            require(not key_path.exists(), "issuer_key_already_exists")
            key = ecc_module.generate(curve="Ed25519")
            _create(key_path, key.export_key(format="PEM").encode(), 0o600)
            _create(
                _BASE / "private" / "task-public.pending.pem",
                key.public_key().export_key(format="PEM").encode(),
                0o600,
            )
            result = {"decision": "KEY_CREATED", "public_pending": True}
        else:
            key = ecc_module.import_key(_read_owned(key_path, mode_private=True))
            _verify_public_trust(key, ecc_module)
            if args.mode == "issue":
                require(bool(_ID.fullmatch(args.approval_id)), "approval_id_invalid")
                approval_raw = _read_owned(
                    _BASE / "private" / "approvals" / f"{args.approval_id}.json",
                    mode_private=True,
                )
                approval = json.loads(approval_raw)
                require(
                    isinstance(approval, dict) and approval.get("approval_id") == args.approval_id,
                    "approval_id_mismatch",
                )
                lease_doc, state_doc, ident = issue_receipts(approval, key, eddsa)
                # A reviewed Owner approval is one-shot; O_EXCL is the CAS.
                _create(
                    _BASE / "private" / "consumed" / f"{args.approval_id}.used",
                    ident.encode("ascii"),
                    0o600,
                )
                _audit("issue_intent", ident, args.approval_id)
                _create(_BASE / "leases" / f"{ident}.json", lease_doc, 0o644)
                _create(_BASE / "states" / f"{ident}.json", state_doc, 0o644)
                # Session selection is issuer-owned, never an LFL/model input.
                # Old bindings remain for audit; runtime ignores revoked/expired
                # leases and refuses multiple concurrently active candidates.
                session_digest = hashlib.sha256(
                    approval["owner_session_id"].encode("utf-8")
                ).hexdigest()
                binding_dir = _BASE / "bindings" / session_digest
                with contextlib.suppress(FileExistsError):
                    binding_dir.mkdir(mode=0o755)
                binding_info = binding_dir.lstat()
                require(
                    stat.S_ISDIR(binding_info.st_mode)
                    and binding_info.st_uid == _ISSUER_UID
                    and binding_info.st_mode & 0o022 == 0,
                    "issuer_binding_dir_untrusted",
                )
                _create(
                    binding_dir / f"{ident}.json",
                    canonical(
                        {
                            "schema": "lfl.task-session-binding/v1",
                            "owner_session_id": approval["owner_session_id"],
                            "lease_id": ident,
                        }
                    ),
                    0o644,
                )
                _audit("issue_published", ident, args.approval_id)
                result = {"decision": "SIGNED", "lease_id": ident}
            else:
                require(bool(_ID.fullmatch(args.lease_id)), "lease_id_invalid")
                lease_doc = _read_owned(
                    _BASE / "leases" / f"{args.lease_id}.json", mode_private=False
                )
                state_doc, ident = revoked_state(lease_doc, key, eddsa)
                state_path = _BASE / "states" / f"{ident}.json"
                existing = _read_owned(state_path, mode_private=False)
                require(
                    json.loads(existing)["payload"].get("status") == "active",
                    "issuer_lease_not_active",
                )
                _audit("revoke_intent", ident)
                temporary = _BASE / "states" / (f".{ident}.{secrets.token_hex(8)}.tmp")
                _create(temporary, state_doc, 0o644)
                os.replace(temporary, state_path)
                _audit("revoke_published", ident)
                result = {"decision": "REVOKED", "lease_id": ident}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (IssuerHoldError, OSError, ValueError, KeyError) as exc:
        code = str(exc) if isinstance(exc, IssuerHoldError) else type(exc).__name__
        print(json.dumps({"decision": "HOLD", "reason": code}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
