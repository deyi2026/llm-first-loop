"""SMC Browser Phase 1 mutation orchestration and append-only ActionReceipts.

This layer owns only mechanical dispatch boundaries.  It never decides whether an
action advances or completes a user task, never chooses a substitute target, and never
replays a mutation automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from llm_loop.browser.perception import BrowserPerceptionAdapter

_MUTATION_CONTRACT: dict[str, dict[str, Any]] = {
    "click": {"version_scopes": {"object", "snapshot"}, "args": set()},
    "fill": {"version_scopes": {"object", "snapshot"}, "args": {"text", "mode"}},
    "select": {"version_scopes": {"object", "snapshot"}, "args": {"value"}},
    "navigate": {"version_scopes": {"resource", "snapshot"}, "args": {"url"}},
    "scroll": {"version_scopes": {"object", "snapshot"}, "args": {"delta_pages"}},
}
_TERMINAL = frozenset({"ok", "failed", "rejected"})


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _action_hash(action_id: str) -> str:
    return hashlib.sha256(action_id.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_arg_facts(verb: str, args: dict[str, Any]) -> dict[str, Any]:
    """Return privacy-safe mechanical request facts; never persist sensitive values."""
    if verb == "fill":
        text = str(args.get("text") or "")
        return {
            "mode": str(args.get("mode") or ""),
            "text_length": len(text),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    if verb == "select":
        value = str(args.get("value") or "")
        return {
            "value_length": len(value),
            "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }
    if verb == "navigate":
        url = str(args.get("url") or "")
        return {
            "url_length": len(url),
            "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
        }
    if verb == "scroll":
        return {"delta_pages": args.get("delta_pages")}
    return {}


@dataclass(frozen=True)
class BrowserDispatchResult:
    """Mechanical actuator acknowledgement, not task success."""

    acknowledged: bool
    boundary_events: tuple[dict[str, Any], ...] = ()
    completeness_reasons: tuple[str, ...] = ("boundary_detector_non_exhaustive",)


class BrowserCaptureBackend(Protocol):
    def capture(self) -> dict[str, Any]: ...


class BrowserMutationActuator(Protocol):
    def dispatch(
        self,
        *,
        verb: str,
        physical_target: str | None,
        args: dict[str, Any],
    ) -> BrowserDispatchResult: ...


class BrowserActionReceiptStore:
    """Append-only, session-fenced Browser ActionReceipt journal.

    A small internal reservation record prevents concurrent duplicate action_id dispatch.
    Canonical receipts remain immutable JSONL revisions with monotonic receipt_seq.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _dir(self, session_id: str, action_id: str) -> Path:
        return self.root / _session_hash(session_id) / _action_hash(action_id)

    def _receipt_path(self, session_id: str, action_id: str) -> Path:
        return self._dir(session_id, action_id) / "receipts.jsonl"

    def reserve(self, session_id: str, action_id: str, action_fingerprint: str) -> bool:
        if not session_id or not action_id:
            raise ValueError("session_id and action_id are required")
        directory = self._dir(session_id, action_id)
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / "reservation.json"
        with self._lock:
            try:
                fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                return False
            try:
                payload = {
                    "owner_session_sha256": _session_hash(session_id),
                    "action_id_sha256": _action_hash(action_id),
                    "action_fingerprint": action_fingerprint,
                }
                os.write(fd, json.dumps(payload, sort_keys=True).encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            return True

    def _next_seq(self, session_id: str, action_id: str) -> int:
        history = self.list_action(session_id, action_id)
        return int(history[-1]["receipt_seq"]) + 1 if history else 1

    def append(self, session_id: str, action_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        if receipt.get("action_id") != action_id:
            raise ValueError("receipt action_id mismatch")
        path = self._receipt_path(session_id, action_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name("receipts.lock")
        with self._lock, lock_path.open("a+", encoding="utf-8") as lock_handle:
            try:
                import fcntl
            except ImportError:  # pragma: no cover - process-local lock remains on Windows.
                fcntl = None  # type: ignore[assignment]
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                seq = self._next_seq(session_id, action_id)
                doc = dict(receipt)
                doc["receipt_seq"] = seq
                doc["receipt_id"] = f"rcp_{_action_hash(action_id)[:16]}_{seq:04d}"
                line = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                return doc
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def list_action(self, session_id: str, action_id: str) -> list[dict[str, Any]]:
        path = self._receipt_path(session_id, action_id)
        if not path.is_file():
            return []
        docs: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("action_id") == action_id:
                docs.append(item)
        return docs

    def persist_dispatch_grounding(
        self,
        session_id: str,
        action_id: str,
        *,
        action_fingerprint: str,
        verb: str,
        physical_target: str | None,
        safe_args: dict[str, Any],
        before_version: str,
    ) -> str:
        directory = self._dir(session_id, action_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "dispatch.json"
        ref = f"grounding://browser-action/v0.1/{_action_hash(action_id)}/dispatch"
        doc = {
            "schema": "smc.browser_action_dispatch_grounding.v0.1",
            "owner_session_sha256": _session_hash(session_id),
            "action_id_sha256": _action_hash(action_id),
            "action_fingerprint": action_fingerprint,
            "verb": verb,
            "physical_target_sha256": (
                hashlib.sha256(str(physical_target).encode("utf-8")).hexdigest()
                if physical_target is not None
                else None
            ),
            "args": safe_args,
            "before_version": before_version,
        }
        if path.exists():
            raise FileExistsError("dispatch grounding already exists")
        tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        try:
            tmp.write_text(
                json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()
        return ref

    def hydrate_dispatch_grounding(
        self, session_id: str, action_id: str
    ) -> dict[str, Any] | None:
        path = self._dir(session_id, action_id) / "dispatch.json"
        if not path.is_file():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(doc, dict) or doc.get("owner_session_sha256") != _session_hash(session_id):
            return None
        return doc


class BrowserActionAdapter:
    """Mechanical Browser mutation guard + single-dispatch receipt orchestrator."""

    def __init__(
        self,
        *,
        perception: BrowserPerceptionAdapter,
        receipt_store: BrowserActionReceiptStore,
        capture_backend: BrowserCaptureBackend,
        actuator: BrowserMutationActuator,
    ) -> None:
        self.perception = perception
        self.receipt_store = receipt_store
        self.capture_backend = capture_backend
        self.actuator = actuator

    @staticmethod
    def _validate(action: dict[str, Any]) -> str | None:
        required = {
            "schema",
            "domain",
            "scope_ref",
            "action_id",
            "verb",
            "target_id",
            "args",
            "operation_class",
            "idempotency_class",
            "atomicity_class",
            "expected_version",
            "version_scope",
            "version_precondition",
        }
        if set(action) != required:
            return "semantic_action_fields_mismatch"
        if action.get("schema") != "smc.semantic_action.v0.1" or action.get("domain") != "browser":
            return "semantic_action_schema_mismatch"
        if any(not str(action.get(key) or "").strip() for key in ("scope_ref", "action_id", "target_id")):
            return "semantic_action_identity_missing"
        verb = str(action.get("verb") or "")
        contract = _MUTATION_CONTRACT.get(verb)
        if contract is None:
            return "verb_not_in_browser_mutation_profile"
        if action.get("operation_class") != "mutate":
            return "operation_class_mismatch"
        if action.get("idempotency_class") != "unknown":
            return "idempotency_class_mismatch"
        if action.get("atomicity_class") != "single_dispatch":
            return "atomicity_class_mismatch"
        if action.get("version_precondition") != "required":
            return "version_precondition_mismatch"
        if str(action.get("version_scope") or "") not in contract["version_scopes"]:
            return "version_scope_mismatch"
        if not str(action.get("expected_version") or ""):
            return "expected_version_missing"
        args = action.get("args")
        if not isinstance(args, dict) or set(args) != contract["args"]:
            return "args_contract_mismatch"
        if verb == "fill" and str(args.get("mode")) not in {"replace", "append"}:
            return "fill_mode_invalid"
        if verb in {"fill", "select", "navigate"}:
            key = {"fill": "text", "select": "value", "navigate": "url"}[verb]
            if not isinstance(args.get(key), str) or (verb == "navigate" and not args.get(key)):
                return f"{verb}_args_invalid"
        if verb == "navigate":
            parsed = urlparse(str(args.get("url") or ""))
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return "navigate_url_scheme_rejected"
            if parsed.username or parsed.password:
                return "navigate_url_credentials_rejected"
        if verb == "scroll":
            delta = args.get("delta_pages")
            if isinstance(delta, bool) or not isinstance(delta, (int, float)):
                return "scroll_args_invalid"
        return None

    @staticmethod
    def _receipt_base(action: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": "smc.action_receipt.v0.1",
            "domain": "browser",
            "scope_ref": str(action.get("scope_ref") or "invalid"),
            "action_id": str(action.get("action_id") or "invalid"),
            "receipt_id": "pending",
            "receipt_seq": 0,
            "verb": str(action.get("verb") or "click"),
            "operation_class": str(action.get("operation_class") or "mutate"),
            "idempotency_class": str(action.get("idempotency_class") or "unknown"),
            "atomicity_class": str(action.get("atomicity_class") or "single_dispatch"),
            "target_id": str(action.get("target_id") or "invalid"),
            "status": "rejected",
            "before_version": None,
            "after_version": None,
            "observed_effects": {
                "diff_ref": None,
                "scope_transition_ref": None,
                "provisional": True,
            },
            "boundary_events": [],
            "grounding_refs": {"before": None, "after": None, "dispatch": None},
            "completeness": {"complete": False, "reasons": []},
            "predicate_result": None,
            "retry": {
                "attempt_count": 1,
                "automatic_retry_performed": False,
                "mechanism": None,
                "reason": None,
            },
        }

    def _append_rejected(
        self,
        session_id: str,
        action: dict[str, Any],
        reason: str,
        *,
        before_version: str | None = None,
        before_ref: str | None = None,
    ) -> dict[str, Any]:
        receipt = self._receipt_base(action)
        receipt["status"] = "rejected"
        receipt["before_version"] = before_version
        receipt["grounding_refs"]["before"] = before_ref
        receipt["completeness"] = {"complete": False, "reasons": [reason]}
        receipt["retry"]["reason"] = reason
        return self.receipt_store.append(session_id, str(action["action_id"]), receipt)

    @staticmethod
    def _physical_target(bundle: dict[str, Any], target_id: str) -> str | None:
        identity = ((bundle.get("private_capture") or {}).get("identity") or {}).get(target_id)
        if not isinstance(identity, dict) or identity.get("stable") is not True:
            return None
        physical = str(identity.get("physical_id") or "").strip()
        if not physical:
            return None
        source = str(identity.get("source") or "")
        if source not in {"dom", "ax"}:
            return None
        return physical if physical.startswith("dom:") else f"dom:{physical}"

    def execute(self, session_id: str, action: dict[str, Any]) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required")
        validation_error = self._validate(action)
        action_id = str(action.get("action_id") or "invalid")
        if validation_error is not None:
            # A canonical-shaped action with a cross-field mismatch gets a canonical
            # rejected receipt.  Inputs that cannot themselves be represented by the
            # frozen ActionReceipt schema are protocol errors rather than fake receipts.
            if (
                action.get("schema") != "smc.semantic_action.v0.1"
                or action.get("domain") != "browser"
                or action.get("verb") not in _MUTATION_CONTRACT
                or not str(action.get("action_id") or "").strip()
                or not str(action.get("scope_ref") or "").strip()
                or not str(action.get("target_id") or "").strip()
            ):
                raise ValueError(f"Browser SemanticAction contract rejected: {validation_error}")
            return self._append_rejected(session_id, action, validation_error)

        fingerprint = _sha256_json(
            {
                "scope_ref": action["scope_ref"],
                "action_id": action_id,
                "verb": action["verb"],
                "target_id": action["target_id"],
                "args": _safe_arg_facts(str(action["verb"]), dict(action["args"])),
                "expected_version": action["expected_version"],
                "version_scope": action["version_scope"],
            }
        )
        if not self.receipt_store.reserve(session_id, action_id, fingerprint):
            return self._append_rejected(session_id, action, "duplicate_action_id")

        try:
            before_raw = self.capture_backend.capture()
            before_result = self.perception.snapshot(session_id, before_raw, projection_limit=1)
            before_snapshot = dict(before_result.get("snapshot") or {})
            before_version = str(before_snapshot.get("snapshot_id") or "")
            before_ref = str(before_snapshot.get("objects_ref") or "") or None
        except Exception as exc:  # noqa: BLE001 - observer failure is a mechanical rejection fact.
            return self._append_rejected(
                session_id,
                action,
                f"pre_dispatch_observation_failed:{type(exc).__name__}",
            )

        assessment = self.perception.assess_version_precondition(
            session_id,
            expected_version=str(action["expected_version"]),
            observed_version=before_version,
            version_scope=str(action["version_scope"]),
            scope_ref=str(action["scope_ref"]),
            target_id=(str(action["target_id"]) if action["version_scope"] == "object" else None),
        )
        if assessment.get("result") != "match":
            return self._append_rejected(
                session_id,
                action,
                f"version_precondition_{assessment.get('result')}:{assessment.get('reason')}",
                before_version=before_version,
                before_ref=before_ref,
            )

        before_bundle = self.perception.store.load_snapshot_bundle(session_id, before_version)
        verb = str(action["verb"])
        target_id = str(action["target_id"])
        scope_ref = str(action["scope_ref"])
        physical_target: str | None = None
        if verb in {"click", "fill", "select", "scroll"}:
            object_grounding = (before_bundle.get("object_grounding") or {}).get(target_id)
            semantic_object = (object_grounding or {}).get("semantic_object") if isinstance(object_grounding, dict) else None
            if not isinstance(semantic_object, dict) or str(semantic_object.get("scope_ref") or "") != scope_ref:
                return self._append_rejected(
                    session_id,
                    action,
                    "target_scope_mismatch",
                    before_version=before_version,
                    before_ref=before_ref,
                )
            physical_target = self._physical_target(before_bundle, target_id)
            if physical_target is None:
                return self._append_rejected(
                    session_id,
                    action,
                    "target_identity_not_stably_resolved",
                    before_version=before_version,
                    before_ref=before_ref,
                )
        elif verb == "navigate":
            page_scope = next(
                (
                    item
                    for item in list(before_bundle.get("scope_facts") or [])
                    if item.get("kind") == "page"
                ),
                None,
            )
            if (
                not isinstance(page_scope, dict)
                or str(page_scope.get("scope_ref") or "") != scope_ref
                or target_id != scope_ref
            ):
                return self._append_rejected(
                    session_id,
                    action,
                    "navigate_page_target_mismatch",
                    before_version=before_version,
                    before_ref=before_ref,
                )

        dispatch_ref = self.receipt_store.persist_dispatch_grounding(
            session_id,
            action_id,
            action_fingerprint=fingerprint,
            verb=verb,
            physical_target=physical_target,
            safe_args=_safe_arg_facts(verb, dict(action["args"])),
            before_version=before_version,
        )
        running = self._receipt_base(action)
        running["status"] = "running"
        running["before_version"] = before_version
        running["grounding_refs"]["before"] = before_ref
        running["grounding_refs"]["dispatch"] = dispatch_ref
        running["completeness"] = {"complete": False, "reasons": ["action_in_progress"]}
        running_receipt = self.receipt_store.append(session_id, action_id, running)

        dispatch_error: Exception | None = None
        dispatch_result: BrowserDispatchResult | None = None
        try:
            dispatch_result = self.actuator.dispatch(
                verb=str(action["verb"]),
                physical_target=physical_target,
                args=dict(action["args"]),
            )
        except Exception as exc:  # noqa: BLE001 - ambiguity must be surfaced, never replayed.
            dispatch_error = exc

        after_version: str | None = None
        after_ref: str | None = None
        diff_ref: str | None = None
        post_reasons: list[str] = []
        try:
            after_raw = self.capture_backend.capture()
            after_result = self.perception.snapshot(session_id, after_raw, projection_limit=1)
            after_snapshot = dict(after_result.get("snapshot") or {})
            after_version = str(after_snapshot.get("snapshot_id") or "") or None
            after_ref = str(after_snapshot.get("objects_ref") or "") or None
            if after_version is not None:
                diff = self.perception.diff(
                    session_id,
                    from_version=before_version,
                    to_version=after_version,
                )
                diff_ref = str(diff.get("full_list_ref") or "") or None
                if not bool((diff.get("completeness") or {}).get("complete")):
                    post_reasons.extend(str(x) for x in (diff.get("completeness") or {}).get("reasons", []))
        except Exception as exc:  # noqa: BLE001 - post-observation failure degrades evidence only.
            post_reasons.append(f"post_dispatch_observation_failed:{type(exc).__name__}")

        terminal = self._receipt_base(action)
        terminal["before_version"] = before_version
        terminal["after_version"] = after_version
        terminal["observed_effects"] = {
            "diff_ref": diff_ref,
            "scope_transition_ref": None,
            "provisional": True,
        }
        terminal["grounding_refs"] = {
            "before": before_ref,
            "after": after_ref,
            "dispatch": running_receipt["grounding_refs"]["dispatch"],
        }
        reasons = list(post_reasons)
        if dispatch_error is not None:
            terminal["status"] = "failed"
            reasons.append("dispatch_outcome_ambiguous")
            terminal["retry"]["reason"] = f"dispatch_error:{type(dispatch_error).__name__}"
        elif dispatch_result is None or not dispatch_result.acknowledged:
            terminal["status"] = "failed"
            reasons.append("dispatch_not_acknowledged")
            terminal["retry"]["reason"] = "dispatch_not_acknowledged"
        else:
            terminal["status"] = "ok"
            terminal["boundary_events"] = [dict(x) for x in dispatch_result.boundary_events]
            reasons.extend(dispatch_result.completeness_reasons)
        # v0.1 boundary detection is intentionally non-exhaustive; terminal evidence is provisional.
        if not reasons:
            reasons.append("boundary_detector_non_exhaustive")
        terminal["completeness"] = {"complete": False, "reasons": sorted(set(reasons))}
        return self.receipt_store.append(session_id, action_id, terminal)
