"""Mechanical P4-LIVE Browser ActionRef alias authority.

This module is intentionally non-dispatching.  It owns only durable opaque aliases,
exact hidden GroundingRef recovery, and the identity/lifetime/integrity fences frozen by
the P4-LIVE v0.1 protocol.  It does not capture, search, match, rebind, compile, or
execute Browser mutations.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

ACTION_REF_SCHEMA = "smc.browser_action_ref_binding.v0.1"
ACTION_REF_PREFIX = "actionref://browser/v0.1/"
ACTION_REF_INTEGRITY_ALGORITHM = "sha256"
ACTION_REF_TOKEN_HEX_CHARS = 32  # 128 bits of cryptographic randomness.
_ACTION_REF_RE = re.compile(r"^actionref://browser/v0\.1/[0-9a-f]{32}$")
_NO_WORKSPACE_SENTINEL = "<unbound-workspace>"
_STABLE_OBJECT_IDENTITY_BASES = frozenset(
    {"dom_physical_identity", "ax_backend_physical_identity"}
)


class BrowserSnapshotStore(Protocol):
    runtime_generation: int
    runtime_nonce: str

    def load_snapshot_bundle(self, session_id: str, snapshot_id: str) -> dict[str, Any]: ...


class ActionRefError(RuntimeError):
    """Stable mechanical rejection for ActionRef issuance/resolution."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}")


@dataclass(frozen=True)
class ActionRefIssueContext:
    workspace_scope: str = ""
    origin_run_generation: str = ""


@dataclass(frozen=True)
class ActionRefResolveContext:
    session_id: str
    workspace_scope: str = ""
    current_run_generation: str = ""
    run_active: bool = True


@dataclass(frozen=True)
class ActionRefResolution:
    action_ref: str
    binding_id: str
    binding_digest: str
    target_kind: Literal["object", "resource"]
    grounding_ref: str
    observed_snapshot_id: str
    scope_ref: str
    semantic_object_or_resource_identity: str
    browser_target_id_sha256: str


def canonical_workspace_scope(workspace_scope: str | None) -> str:
    """Return the canonical mechanical workspace identity or an explicit sentinel."""
    raw = str(workspace_scope or "").strip()
    if not raw:
        return _NO_WORKSPACE_SENTINEL
    return str(Path(raw).expanduser().resolve())


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _write_json_create_only(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_bytes(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        with suppress(FileNotFoundError):
            path.unlink()
        raise


class ActionRefBindingStore:
    """Durable immutable ActionRef records plus idempotent binding index."""

    def __init__(
        self,
        root: str | Path,
        *,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self._now = now_fn
        self._thread_lock = threading.RLock()

    def now(self) -> float:
        return float(self._now())

    @contextmanager
    def _locked(self) -> Iterator[None]:
        lock_path = self.root / "action_ref.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock, lock_path.open("a+", encoding="utf-8") as handle:
            try:
                import fcntl
            except ImportError:  # pragma: no cover - non-POSIX fallback.
                fcntl = None  # type: ignore[assignment]
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def record_path(self, action_ref: str) -> Path:
        if _ACTION_REF_RE.fullmatch(action_ref) is None:
            raise ActionRefError("action_ref_unavailable", "invalid ActionRef format")
        return self.root / "records" / f"{_sha_text(action_ref)}.json"

    def _binding_index_path(self, binding_id: str) -> Path:
        return self.root / "bindings" / f"{binding_id}.json"

    @staticmethod
    def _integrity_digest(record: dict[str, Any]) -> str:
        unsigned = {key: value for key, value in record.items() if key != "integrity"}
        return _digest(unsigned)

    def _load_record(self, action_ref: str) -> dict[str, Any]:
        path = self.record_path(action_ref)
        if not path.is_file():
            raise ActionRefError("action_ref_unavailable", "ActionRef does not exist")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ActionRefError("action_ref_integrity_error", "binding record unreadable") from exc
        if not isinstance(record, dict):
            raise ActionRefError("action_ref_integrity_error", "binding record is not an object")
        if record.get("schema") != ACTION_REF_SCHEMA or record.get("action_ref") != action_ref:
            raise ActionRefError("action_ref_integrity_error", "binding identity mismatch")
        integrity = record.get("integrity")
        if not isinstance(integrity, dict):
            raise ActionRefError("action_ref_integrity_error", "binding integrity missing")
        if integrity.get("algorithm") != ACTION_REF_INTEGRITY_ALGORITHM:
            raise ActionRefError("action_ref_integrity_error", "binding integrity algorithm mismatch")
        expected = str(integrity.get("digest") or "")
        actual = self._integrity_digest(record)
        if not expected or not secrets.compare_digest(expected, actual):
            raise ActionRefError("action_ref_integrity_error", "binding integrity mismatch")
        return record

    def load_exact(self, action_ref: str) -> dict[str, Any]:
        """Load only the exact opaque handle; no search, normalization, or rebinding."""
        return self._load_record(str(action_ref))

    def issue(
        self,
        *,
        session_id: str,
        workspace_scope: str,
        origin_run_generation: str,
        browser_runtime_generation: int,
        browser_runtime_nonce: str,
        browser_target_id: str,
        observed_snapshot_id: str,
        scope_ref: str,
        semantic_object_or_resource_identity: str,
        grounding_ref: str,
        target_kind: Literal["object", "resource"],
        source_snapshot_expires_at_epoch: float,
    ) -> dict[str, Any]:
        if not session_id:
            raise ActionRefError("action_ref_session_mismatch", "session identity is required")
        if not origin_run_generation:
            raise ActionRefError(
                "action_ref_run_generation_mismatch", "active origin run generation is required"
            )
        if target_kind not in {"object", "resource"}:
            raise ActionRefError("action_ref_kind_mismatch", "target kind must be object or resource")
        if not browser_runtime_nonce or not browser_target_id:
            raise ActionRefError(
                "action_ref_source_unavailable", "Browser runtime/target identity unavailable"
            )
        if not observed_snapshot_id or not grounding_ref or not scope_ref:
            raise ActionRefError("action_ref_source_unavailable", "exact source binding incomplete")

        now = self.now()
        source_expiry = float(source_snapshot_expires_at_epoch)
        if source_expiry <= now:
            raise ActionRefError("action_ref_expired", "source snapshot already expired")
        workspace_identity = canonical_workspace_scope(workspace_scope)
        basis = {
            "domain": "browser",
            "target_kind": target_kind,
            "owner_session_sha256": _sha_text(session_id),
            "workspace_scope_sha256": _sha_text(workspace_identity),
            "origin_run_generation_sha256": _sha_text(origin_run_generation),
            "browser_runtime_generation": int(browser_runtime_generation),
            "browser_runtime_nonce_sha256": _sha_text(browser_runtime_nonce),
            "browser_target_id_sha256": _sha_text(browser_target_id),
            "observed_snapshot_id": observed_snapshot_id,
            "scope_ref": scope_ref,
            "semantic_object_or_resource_identity": semantic_object_or_resource_identity,
            "grounding_ref": grounding_ref,
            "source_snapshot_expires_at_epoch": source_expiry,
        }
        binding_id = _digest(basis)
        index_path = self._binding_index_path(binding_id)

        with self._locked():
            action_ref = ""
            if index_path.is_file():
                try:
                    index = json.loads(index_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ActionRefError(
                        "action_ref_integrity_error", "binding index unreadable"
                    ) from exc
                if not isinstance(index, dict) or index.get("binding_id") != binding_id:
                    raise ActionRefError("action_ref_integrity_error", "binding index invalid")
                action_ref = str(index.get("action_ref") or "")
                if _ACTION_REF_RE.fullmatch(action_ref) is None:
                    raise ActionRefError("action_ref_integrity_error", "binding index handle invalid")
            else:
                while True:
                    candidate = f"{ACTION_REF_PREFIX}{secrets.token_hex(16)}"
                    if not self.record_path(candidate).exists():
                        action_ref = candidate
                        break
                _write_json_create_only(
                    index_path,
                    {"schema": "smc.browser_action_ref_binding_index.v0.1", "binding_id": binding_id, "action_ref": action_ref},
                )

            record_path = self.record_path(action_ref)
            if record_path.is_file():
                existing = self._load_record(action_ref)
                if existing.get("binding_id") != binding_id:
                    raise ActionRefError("action_ref_integrity_error", "ActionRef collision")
                return existing

            record: dict[str, Any] = {
                "schema": ACTION_REF_SCHEMA,
                "action_ref": action_ref,
                "binding_id": binding_id,
                **basis,
                "issued_at_epoch": now,
                "expires_at_epoch": source_expiry,
            }
            record["integrity"] = {
                "algorithm": ACTION_REF_INTEGRITY_ALGORITHM,
                "digest": self._integrity_digest(record),
            }
            _write_json_create_only(record_path, record)
            return record


class ActionRefIssuer:
    """Annotate only an already-persisted Browser projection with opaque handles."""

    def __init__(
        self,
        *,
        binding_store: ActionRefBindingStore,
        perception_store: BrowserSnapshotStore,
    ) -> None:
        self.binding_store = binding_store
        self.perception_store = perception_store

    def _issue(
        self,
        *,
        session_id: str,
        context: ActionRefIssueContext,
        bundle: dict[str, Any],
        target_kind: Literal["object", "resource"],
        scope_ref: str,
        identity: str,
        grounding_ref: str,
    ) -> str:
        retention = bundle.get("retention") or {}
        source_expiry = float(retention.get("expires_at_epoch") or 0.0)
        page_token = str((bundle.get("private_capture") or {}).get("page_token") or "")
        record = self.binding_store.issue(
            session_id=session_id,
            workspace_scope=context.workspace_scope,
            origin_run_generation=context.origin_run_generation,
            browser_runtime_generation=int(self.perception_store.runtime_generation),
            browser_runtime_nonce=str(self.perception_store.runtime_nonce),
            browser_target_id=page_token,
            observed_snapshot_id=str((bundle.get("snapshot") or {}).get("snapshot_id") or ""),
            scope_ref=scope_ref,
            semantic_object_or_resource_identity=identity,
            grounding_ref=grounding_ref,
            target_kind=target_kind,
            source_snapshot_expires_at_epoch=source_expiry,
        )
        return str(record["action_ref"])

    def annotate_projection(
        self,
        *,
        session_id: str,
        projection: dict[str, Any],
        context: ActionRefIssueContext,
    ) -> dict[str, Any]:
        if not context.origin_run_generation:
            raise ActionRefError(
                "action_ref_run_generation_mismatch", "active run generation required for issuance"
            )
        snapshot_id = str((projection.get("snapshot") or {}).get("snapshot_id") or "")
        if not snapshot_id:
            raise ActionRefError("action_ref_source_unavailable", "projection snapshot id missing")

        # This exact load is the issuance barrier: projection annotation can happen only
        # after BrowserPerceptionStore.persist() has durably committed the snapshot.
        bundle = self.perception_store.load_snapshot_bundle(session_id, snapshot_id)
        resource_grounding = bundle.get("resource_grounding") or {}
        resource_ref = str(resource_grounding.get("grounding_ref") or "")
        resource_scope = str(resource_grounding.get("scope_ref") or "")
        result = dict(projection)
        result["resource_action_ref"] = self._issue(
            session_id=session_id,
            context=context,
            bundle=bundle,
            target_kind="resource",
            scope_ref=resource_scope,
            identity=resource_ref,
            grounding_ref=resource_ref,
        )

        object_grounding = bundle.get("object_grounding") or {}
        annotated_objects: list[dict[str, Any]] = []
        for raw_obj in projection.get("objects", []):
            if not isinstance(raw_obj, dict):
                continue
            obj = dict(raw_obj)
            semantic_id = str(obj.get("id") or "")
            grounding = object_grounding.get(semantic_id) if isinstance(object_grounding, dict) else None
            if isinstance(grounding, dict) and grounding.get("identity_basis") in _STABLE_OBJECT_IDENTITY_BASES:
                semantic_object = grounding.get("semantic_object") or {}
                grounding_ref = str(semantic_object.get("grounding_ref") or obj.get("grounding_ref") or "")
                scope_ref = str(semantic_object.get("scope_ref") or obj.get("scope_ref") or "")
                if grounding_ref and scope_ref and semantic_id:
                    obj["action_ref"] = self._issue(
                        session_id=session_id,
                        context=context,
                        bundle=bundle,
                        target_kind="object",
                        scope_ref=scope_ref,
                        identity=semantic_id,
                        grounding_ref=grounding_ref,
                    )
            annotated_objects.append(obj)
        result["objects"] = annotated_objects
        return result


class ActionRefResolver:
    """Exact-only resolver with mechanical ownership/lifetime/integrity fences."""

    def __init__(
        self,
        *,
        binding_store: ActionRefBindingStore,
        perception_store: BrowserSnapshotStore,
    ) -> None:
        self.binding_store = binding_store
        self.perception_store = perception_store

    def resolve(
        self,
        action_ref: str,
        *,
        context: ActionRefResolveContext,
        expected_kind: Literal["object", "resource"] | None = None,
    ) -> ActionRefResolution:
        record = self.binding_store.load_exact(str(action_ref))

        if record.get("owner_session_sha256") != _sha_text(context.session_id):
            raise ActionRefError("action_ref_session_mismatch", "ActionRef belongs to another session")
        workspace_identity = canonical_workspace_scope(context.workspace_scope)
        if record.get("workspace_scope_sha256") != _sha_text(workspace_identity):
            raise ActionRefError(
                "action_ref_workspace_mismatch", "ActionRef belongs to another workspace"
            )
        if (
            not context.run_active
            or not context.current_run_generation
            or record.get("origin_run_generation_sha256")
            != _sha_text(context.current_run_generation)
        ):
            raise ActionRefError(
                "action_ref_run_generation_mismatch", "ActionRef origin run is not active"
            )

        now = self.binding_store.now()
        expires_at = float(record.get("expires_at_epoch") or 0.0)
        source_expires_at = float(record.get("source_snapshot_expires_at_epoch") or 0.0)
        if now >= expires_at or now >= source_expires_at:
            raise ActionRefError("action_ref_expired", "ActionRef/source snapshot expired")

        snapshot_id = str(record.get("observed_snapshot_id") or "")
        try:
            source = self.perception_store.load_snapshot_bundle(context.session_id, snapshot_id)
        except PermissionError as exc:
            raise ActionRefError("action_ref_session_mismatch", "source snapshot session mismatch") from exc
        except ValueError as exc:
            if "expired" in str(exc).lower():
                raise ActionRefError("action_ref_expired", "source snapshot expired") from exc
            raise ActionRefError("action_ref_source_unavailable", "source snapshot unavailable") from exc
        persisted_expiry = float((source.get("retention") or {}).get("expires_at_epoch") or 0.0)
        if persisted_expiry != source_expires_at:
            raise ActionRefError(
                "action_ref_integrity_error", "source snapshot expiry no longer matches binding"
            )

        runtime_nonce_sha = _sha_text(str(self.perception_store.runtime_nonce))
        if (
            int(record.get("browser_runtime_generation") or -1)
            != int(self.perception_store.runtime_generation)
            or record.get("browser_runtime_nonce_sha256") != runtime_nonce_sha
        ):
            raise ActionRefError(
                "action_ref_browser_runtime_mismatch", "Browser runtime incarnation changed"
            )

        target_kind = str(record.get("target_kind") or "")
        if target_kind not in {"object", "resource"}:
            raise ActionRefError("action_ref_integrity_error", "stored target kind invalid")
        if expected_kind is not None and target_kind != expected_kind:
            raise ActionRefError(
                "action_ref_kind_mismatch",
                f"expected {expected_kind}, binding is {target_kind}",
            )

        integrity = record.get("integrity") or {}
        return ActionRefResolution(
            action_ref=str(record["action_ref"]),
            binding_id=str(record["binding_id"]),
            binding_digest=str(integrity.get("digest") or ""),
            target_kind=target_kind,  # type: ignore[arg-type]
            grounding_ref=str(record.get("grounding_ref") or ""),
            observed_snapshot_id=snapshot_id,
            scope_ref=str(record.get("scope_ref") or ""),
            semantic_object_or_resource_identity=str(
                record.get("semantic_object_or_resource_identity") or ""
            ),
            browser_target_id_sha256=str(record.get("browser_target_id_sha256") or ""),
        )
