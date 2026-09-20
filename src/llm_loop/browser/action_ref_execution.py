"""Durable non-dispatching execution join for P4-LIVE ActionRef.

G2-S1 owns only the PREPARED identity bridge between the outer ToolExecutionJournal
attempt and the already-qualified GREEN-1 ActionRef/hidden GroundingRef facts.  This
module intentionally has no Browser action adapter, actuator, receipt-store, provider,
or tool-registration dependency.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any

from llm_loop.browser.action_ref import ActionRefResolution
from llm_loop.core.tool_execution_journal import current_action_ref_effect_binding_authority

ACTION_REF_EXECUTION_SCHEMA = "smc.browser_action_ref_execution_binding.v0.1"
ACTION_REF_EXECUTION_STATE = "prepared"
ACTION_REF_RECEIPT_CURSOR_SCHEMA = "smc.browser_action_ref_receipt_cursor.v0.1"
ACTION_REF_RECEIPT_CURSOR_STATE = "armed"
_INTEGRITY_ALGORITHM = "sha256"


class ActionRefExecutionBridgeError(RuntimeError):
    """Stable mechanical rejection for the immutable PREPARED execution bridge."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}")


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
    """Create one durable immutable record or fail without replacing existing bytes."""
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


class ActionRefExecutionBridgeStore:
    """Create-only exact execution_id -> ActionRef/GroundingRef/action_id authority."""

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

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        lock_path = self.root / "execution_bridge.lock"
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

    def record_path(self, execution_id: str) -> Path:
        raw = str(execution_id or "")
        if not raw:
            raise ActionRefExecutionBridgeError(
                "action_ref_execution_binding_incomplete", "execution_id is required"
            )
        safe = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:32]
        return self.root / "prepared" / f"{safe}.json"

    def receipt_cursor_path(self, execution_id: str) -> Path:
        raw = str(execution_id or "")
        if not raw:
            raise ActionRefExecutionBridgeError(
                "action_ref_execution_binding_incomplete", "execution_id is required"
            )
        safe = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:32]
        return self.root / "receipt_cursor" / f"{safe}.json"

    @staticmethod
    def _integrity_digest(record: dict[str, Any]) -> str:
        unsigned = {key: value for key, value in record.items() if key != "integrity"}
        return _digest(unsigned)

    @staticmethod
    def _basis_from_record(record: dict[str, Any]) -> dict[str, Any]:
        return {
            key: record.get(key)
            for key in (
                "execution_id",
                "round",
                "tool_call_id",
                "tool_name",
                "session_id",
                "workspace_root",
                "origin_run_generation",
                "action_ref",
                "action_ref_binding_id",
                "action_ref_binding_digest",
                "grounding_ref",
                "inner_action_id",
                "expected_version",
                "browser_target_id_sha256",
            )
        }

    def load_exact(self, execution_id: str) -> dict[str, Any]:
        path = self.record_path(execution_id)
        if not path.is_file():
            raise ActionRefExecutionBridgeError(
                "action_ref_execution_binding_unavailable",
                "PREPARED execution binding does not exist",
            )
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ActionRefExecutionBridgeError(
                "action_ref_execution_binding_integrity_error",
                "PREPARED execution binding is unreadable",
            ) from exc
        if not isinstance(record, dict):
            raise ActionRefExecutionBridgeError(
                "action_ref_execution_binding_integrity_error",
                "PREPARED execution binding is not an object",
            )
        if (
            record.get("schema") != ACTION_REF_EXECUTION_SCHEMA
            or record.get("state") != ACTION_REF_EXECUTION_STATE
            or record.get("execution_id") != str(execution_id)
        ):
            raise ActionRefExecutionBridgeError(
                "action_ref_execution_binding_integrity_error",
                "PREPARED execution identity mismatch",
            )
        integrity = record.get("integrity")
        if not isinstance(integrity, dict) or integrity.get("algorithm") != _INTEGRITY_ALGORITHM:
            raise ActionRefExecutionBridgeError(
                "action_ref_execution_binding_integrity_error",
                "PREPARED execution integrity metadata missing",
            )
        expected = str(integrity.get("digest") or "")
        actual = self._integrity_digest(record)
        if not expected or expected != actual:
            raise ActionRefExecutionBridgeError(
                "action_ref_execution_binding_integrity_error",
                "PREPARED execution integrity mismatch",
            )
        basis = self._basis_from_record(record)
        if record.get("bridge_id") != _digest(basis):
            raise ActionRefExecutionBridgeError(
                "action_ref_execution_binding_integrity_error",
                "PREPARED execution bridge id mismatch",
            )
        return record

    def load_receipt_cursor(self, execution_id: str) -> dict[str, Any]:
        """Load the exact immutable Browser-receipt baseline for one outer execution."""
        bridge = self.load_exact(execution_id)
        path = self.receipt_cursor_path(execution_id)
        if not path.is_file():
            raise ActionRefExecutionBridgeError(
                "action_ref_receipt_cursor_unavailable",
                "Browser receipt cursor does not exist",
            )
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ActionRefExecutionBridgeError(
                "action_ref_receipt_cursor_integrity_error",
                "Browser receipt cursor is unreadable",
            ) from exc
        if not isinstance(record, dict):
            raise ActionRefExecutionBridgeError(
                "action_ref_receipt_cursor_integrity_error",
                "Browser receipt cursor is not an object",
            )
        if (
            record.get("schema") != ACTION_REF_RECEIPT_CURSOR_SCHEMA
            or record.get("state") != ACTION_REF_RECEIPT_CURSOR_STATE
            or record.get("execution_id") != str(execution_id)
            or record.get("bridge_id") != bridge.get("bridge_id")
            or record.get("session_id") != bridge.get("session_id")
            or record.get("tool_call_id") != bridge.get("tool_call_id")
            or record.get("inner_action_id") != bridge.get("inner_action_id")
        ):
            raise ActionRefExecutionBridgeError(
                "action_ref_receipt_cursor_integrity_error",
                "Browser receipt cursor identity mismatch",
            )
        integrity = record.get("integrity")
        if not isinstance(integrity, dict) or integrity.get("algorithm") != _INTEGRITY_ALGORITHM:
            raise ActionRefExecutionBridgeError(
                "action_ref_receipt_cursor_integrity_error",
                "Browser receipt cursor integrity metadata missing",
            )
        expected = str(integrity.get("digest") or "")
        actual = self._integrity_digest(record)
        if not expected or expected != actual:
            raise ActionRefExecutionBridgeError(
                "action_ref_receipt_cursor_integrity_error",
                "Browser receipt cursor integrity mismatch",
            )
        seq = record.get("receipt_seq_before")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise ActionRefExecutionBridgeError(
                "action_ref_receipt_cursor_integrity_error",
                "Browser receipt cursor sequence is invalid",
            )
        return record

    def prepare_receipt_cursor(
        self, execution_id: str, *, receipt_seq_before: int
    ) -> dict[str, Any]:
        """Durably fence recovery to receipts created after this exact execution entered Browser."""
        if isinstance(receipt_seq_before, bool) or int(receipt_seq_before) < 0:
            raise ActionRefExecutionBridgeError(
                "action_ref_receipt_cursor_invalid",
                "receipt_seq_before must be a non-negative integer",
            )
        bridge = self.load_exact(execution_id)
        basis = {
            "execution_id": str(bridge["execution_id"]),
            "bridge_id": str(bridge["bridge_id"]),
            "session_id": str(bridge["session_id"]),
            "tool_call_id": str(bridge["tool_call_id"]),
            "inner_action_id": str(bridge["inner_action_id"]),
            "receipt_seq_before": int(receipt_seq_before),
        }
        path = self.receipt_cursor_path(execution_id)
        with self._locked():
            if path.is_file():
                existing = self.load_receipt_cursor(execution_id)
                if any(existing.get(key) != value for key, value in basis.items()):
                    raise ActionRefExecutionBridgeError(
                        "action_ref_receipt_cursor_conflict",
                        "execution_id is already armed with a different Browser receipt baseline",
                    )
                return existing
            record: dict[str, Any] = {
                "schema": ACTION_REF_RECEIPT_CURSOR_SCHEMA,
                "state": ACTION_REF_RECEIPT_CURSOR_STATE,
                **basis,
                "armed_at_epoch": float(self._now()),
            }
            record["integrity"] = {
                "algorithm": _INTEGRITY_ALGORITHM,
                "digest": self._integrity_digest(record),
            }
            try:
                _write_json_create_only(path, record)
            except FileExistsError:
                existing = self.load_receipt_cursor(execution_id)
                if any(existing.get(key) != value for key, value in basis.items()):
                    raise ActionRefExecutionBridgeError(
                        "action_ref_receipt_cursor_conflict",
                        "execution_id raced with a different Browser receipt baseline",
                    ) from None
                return existing
            return record

    @staticmethod
    def _validate_resolution(
        resolution: ActionRefResolution, inner_action_id: str, expected_version: str
    ) -> None:
        required = {
            "action_ref": resolution.action_ref,
            "action_ref_binding_id": resolution.binding_id,
            "action_ref_binding_digest": resolution.binding_digest,
            "grounding_ref": resolution.grounding_ref,
            "inner_action_id": inner_action_id,
            "expected_version": expected_version,
            "browser_target_id_sha256": resolution.browser_target_id_sha256,
        }
        missing = [name for name, value in required.items() if not str(value or "")]
        if missing:
            raise ActionRefExecutionBridgeError(
                "action_ref_execution_binding_incomplete",
                f"PREPARED execution binding missing: {','.join(sorted(missing))}",
            )

    def prepare_current(
        self,
        *,
        resolution: ActionRefResolution,
        inner_action_id: str,
        expected_version: str,
    ) -> dict[str, Any]:
        """Persist PREPARED using outer identity only from the current strict binding."""
        self._validate_resolution(resolution, inner_action_id, expected_version)
        with current_action_ref_effect_binding_authority() as outer:
            basis: dict[str, Any] = {
                "execution_id": outer.execution_id,
                "round": outer.round_no,
                "tool_call_id": outer.tool_call_id,
                "tool_name": outer.tool_name,
                "session_id": outer.session_id,
                "workspace_root": outer.workspace_root,
                "origin_run_generation": outer.origin_run_generation,
                "action_ref": resolution.action_ref,
                "action_ref_binding_id": resolution.binding_id,
                "action_ref_binding_digest": resolution.binding_digest,
                "grounding_ref": resolution.grounding_ref,
                "inner_action_id": str(inner_action_id),
                "expected_version": str(expected_version),
                "browser_target_id_sha256": resolution.browser_target_id_sha256,
            }
            bridge_id = _digest(basis)
            path = self.record_path(outer.execution_id)

            with self._locked():
                if path.is_file():
                    existing = self.load_exact(outer.execution_id)
                    if existing.get("bridge_id") != bridge_id or self._basis_from_record(existing) != basis:
                        raise ActionRefExecutionBridgeError(
                            "action_ref_execution_binding_conflict",
                            "execution_id is already bound to different ActionRef execution facts",
                        )
                    return existing

                record: dict[str, Any] = {
                    "schema": ACTION_REF_EXECUTION_SCHEMA,
                    "state": ACTION_REF_EXECUTION_STATE,
                    "bridge_id": bridge_id,
                    **basis,
                    "prepared_at_epoch": float(self._now()),
                }
                record["integrity"] = {
                    "algorithm": _INTEGRITY_ALGORITHM,
                    "digest": self._integrity_digest(record),
                }
                try:
                    _write_json_create_only(path, record)
                except FileExistsError:
                    existing = self.load_exact(outer.execution_id)
                    if existing.get("bridge_id") != bridge_id or self._basis_from_record(existing) != basis:
                        raise ActionRefExecutionBridgeError(
                            "action_ref_execution_binding_conflict",
                            "execution_id raced with different ActionRef execution facts",
                        ) from None
                    return existing
                return record

    def classify_prepared_without_browser_running(self, execution_id: str) -> dict[str, Any]:
        """Classify the explicit PREPARED/no-running crash cut without replay.

        G2-S1 intentionally does not inspect Browser receipts.  A later exact correlator
        may call this only after mechanically proving that the bound action_id has no
        running receipt.
        """
        record = self.load_exact(execution_id)
        return {
            "state": "prepared_before_browser_running",
            "execution_id": str(record["execution_id"]),
            "bridge_id": str(record["bridge_id"]),
            "executed": False,
            "dispatch_attempted": False,
            "auto_reexecuted": False,
        }
