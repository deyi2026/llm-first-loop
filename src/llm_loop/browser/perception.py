"""Read-only SMC Browser Phase 1 perception substrate.

The module has three deliberately separated layers:

1. ``PlaywrightPageCaptureBackend`` reads the *currently bound page* through
   read-only CDP capture methods.  It never navigates, clicks, fills, evaluates
   model-supplied script, retries, or chooses a task-relevant target.
2. ``BrowserPerceptionAdapter`` converts source-qualified DOM + AX facts into
   B-SPEC ``WorldSnapshot`` + ``SemanticObject`` wires.  Identity is based only
   on mechanical runtime/page/document/frame generations and backend physical
   identity; task text never participates.
3. ``BrowserPerceptionStore`` persists immutable, session-scoped grounding.
   Raw backend locators remain private in the stored audit bundle and are never
   returned by model-facing hydration.

This is perception only.  No Browser mutation verb is implemented here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_SENSOR_CONTRACT = {
    "id": "browser-dom-ax-v0.1",
    "active_sources": ["dom", "ax"],
    "vision": "explicit_only_deferred_phase2",
}

_ATTRIBUTE_FIELDS = {
    "role",
    "name",
    "tag",
    "input_type",
    "value_text",
    "href",
    "dom_region",
    "text",
}
_STATE_FIELDS = {
    "exists",
    "enabled",
    "visible",
    "checked",
    "selected",
    "expanded",
    "focused",
    "editable",
    "readonly",
    "required",
    "busy",
}
_KINDS = {
    "document",
    "frame",
    "region",
    "button",
    "link",
    "input",
    "select",
    "option",
    "checkbox",
    "radio",
    "text",
    "image",
    "dialog",
    "list",
    "listitem",
    "table",
    "row",
    "cell",
    "form",
    "heading",
    "generic",
    "unknown",
}
_BLIND_SPOTS = {
    "closed_shadow_root",
    "cross_origin_frame",
    "canvas",
    "webgl",
    "dom_unavailable",
    "ax_unavailable",
    "ax_truncated",
    "permission_denied",
    "projection_cap",
}
_GROUNDING_PREFIX = "grounding://browser/v0.1/"
_SNAPSHOT_RE = re.compile(r"bsnap-[1-9][0-9]*-[0-9a-f]{16}")
_SEMANTIC_ID_RE = re.compile(r"el_[0-9a-f]{20}")
_RELATION_CAP_FACTOR = 4


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _content_fact_basis(value: Any) -> Any:
    """Remove per-capture reference identity while preserving observed facts."""
    if isinstance(value, dict):
        return {
            key: _content_fact_basis(child)
            for key, child in value.items()
            if key not in {"grounding_ref", "observed_version"}
        }
    if isinstance(value, list):
        return [_content_fact_basis(child) for child in value]
    return value


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _opaque_ref(prefix: str, *parts: object) -> str:
    basis = "\x1f".join(str(p) for p in parts)
    return f"{prefix}{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:24]}"


def _filter_fields(raw: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if k in allowed}


def _normalize_kind(value: Any) -> str:
    candidate = str(value or "unknown").strip().lower()
    return candidate if candidate in _KINDS else "unknown"


def _normalize_blind_spots(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({str(v) for v in values if str(v) in _BLIND_SPOTS})


def _origin(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.hostname:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port}"


class BrowserPerceptionStore:
    """Immutable Browser grounding store with declared retention and session fencing."""

    def __init__(
        self,
        root: str | Path,
        *,
        retention_seconds: int = 86_400,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        if retention_seconds < 1:
            raise ValueError("retention_seconds must be >= 1")
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention_seconds = int(retention_seconds)
        self._now = now_fn
        self._counter_lock = threading.Lock()
        self.runtime_generation = self._allocate_runtime_generation()
        self.runtime_nonce = secrets.token_hex(16)

    def _allocate_runtime_generation(self) -> int:
        counter_path = self.root / "runtime_generation.txt"
        with self._counter_lock:
            counter_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                import fcntl
            except ImportError:  # pragma: no cover - Windows fallback; nonce still prevents alias.
                fcntl = None  # type: ignore[assignment]
            with counter_path.open("a+", encoding="utf-8") as handle:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    handle.seek(0)
                    raw = handle.read().strip()
                    current = int(raw) if raw.isdigit() else 0
                    generation = current + 1
                    handle.seek(0)
                    handle.truncate()
                    handle.write(str(generation))
                    handle.flush()
                    os.fsync(handle.fileno())
                    return generation
                finally:
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _bundle_path(self, snapshot_id: str) -> Path:
        if _SNAPSHOT_RE.fullmatch(snapshot_id) is None:
            raise ValueError("invalid Browser snapshot id")
        return self.root / "snapshots" / f"{snapshot_id}.json"

    def persist(self, session_id: str, bundle: dict[str, Any]) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        snapshot_id = str(bundle.get("snapshot", {}).get("snapshot_id") or "")
        path = self._bundle_path(snapshot_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"snapshot already exists: {snapshot_id}")
        now = float(self._now())
        doc = dict(bundle)
        doc["owner_session_sha256"] = _session_hash(session_id)
        doc["retention"] = {
            "policy": "ttl_seconds",
            "retention_seconds": self.retention_seconds,
            "stored_at_epoch": now,
            "expires_at_epoch": now + self.retention_seconds,
        }
        doc["bundle_sha256"] = _sha256(
            {k: v for k, v in doc.items() if k != "bundle_sha256"}
        )
        tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
        try:
            tmp.write_text(
                json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()

    def _load(self, snapshot_id: str) -> tuple[dict[str, Any] | None, str | None]:
        try:
            path = self._bundle_path(snapshot_id)
        except ValueError:
            return None, "invalid_snapshot_id"
        if not path.is_file():
            return None, "not_found"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            return None, "read_error"
        except json.JSONDecodeError:
            return None, "invalid_json"
        expected = doc.get("bundle_sha256")
        actual = _sha256({k: v for k, v in doc.items() if k != "bundle_sha256"})
        if not isinstance(expected, str) or expected != actual:
            return None, "integrity_error"
        return doc, None

    @staticmethod
    def _parse_ref(ref: str) -> tuple[str, list[str]] | None:
        if not ref.startswith(_GROUNDING_PREFIX):
            return None
        tail = ref[len(_GROUNDING_PREFIX) :]
        parts = tail.split("/")
        if len(parts) < 2 or _SNAPSHOT_RE.fullmatch(parts[0]) is None:
            return None
        return parts[0], parts[1:]

    def hydrate(self, session_id: str, grounding_ref: str) -> dict[str, Any]:
        ref = str(grounding_ref or "").strip()
        parsed = self._parse_ref(ref)
        if parsed is None:
            return {"grounding_ref": ref, "availability": "unavailable", "reason": "invalid_ref"}
        snapshot_id, parts = parsed
        bundle, load_error = self._load(snapshot_id)
        if bundle is None:
            return {
                "grounding_ref": ref,
                "availability": "unavailable",
                "reason": load_error or "unavailable",
            }
        if bundle.get("owner_session_sha256") != _session_hash(session_id):
            return {"grounding_ref": ref, "availability": "unauthorized", "reason": "session_scope"}
        retention = bundle.get("retention") or {}
        expires_at = float(retention.get("expires_at_epoch") or 0)
        if self._now() > expires_at:
            return {
                "grounding_ref": ref,
                "availability": "expired",
                "expires_at_epoch": expires_at,
            }

        content: Any | None = None
        if parts == ["objects"]:
            content = bundle.get("objects")
        elif parts == ["scopes"]:
            content = bundle.get("scope_facts")
        elif len(parts) == 2 and parts[0] == "sensor" and parts[1] in {"dom", "ax"}:
            content = (bundle.get("sensor_grounding") or {}).get(parts[1])
        elif len(parts) == 2 and parts[0] == "object" and _SEMANTIC_ID_RE.fullmatch(parts[1]):
            content = (bundle.get("object_grounding") or {}).get(parts[1])
        elif (
            len(parts) == 3
            and parts[0] == "source"
            and parts[1] in {"dom", "ax"}
            and _SEMANTIC_ID_RE.fullmatch(parts[2])
        ):
            content = ((bundle.get("source_grounding") or {}).get(parts[1]) or {}).get(parts[2])
        if content is None:
            return {"grounding_ref": ref, "availability": "unavailable", "reason": "unknown_projection"}
        return {
            "grounding_ref": ref,
            "availability": "available",
            "content_sha256": _sha256(content),
            "content": content,
            "retention": {
                "policy": retention.get("policy"),
                "expires_at_epoch": expires_at,
            },
        }


class _SessionState:
    def __init__(self) -> None:
        self.page_generations: dict[str, int] = {}
        self.page_documents: dict[str, tuple[str, int]] = {}
        self.frame_documents: dict[tuple[str, str], tuple[str, int]] = {}
        self.identity_map: dict[tuple[int, int, int | None, str], str] = {}
        self.next_page_generation = 1


@dataclass
class _ObjectBuild:
    semantic_objects: list[dict[str, Any]]
    private_identity: dict[str, dict[str, Any]]
    source_grounding: dict[str, dict[str, Any]]
    object_grounding: dict[str, dict[str, Any]]
    dom_semantic_by_key: dict[tuple[str | None, str], str]


class BrowserPerceptionAdapter:
    """Task-invariant DOM+AX canonicalizer for Browser Phase 1."""

    def __init__(
        self,
        *,
        store: BrowserPerceptionStore,
        capture_node_cap: int = 20_000,
    ) -> None:
        if capture_node_cap < 1:
            raise ValueError("capture_node_cap must be >= 1")
        self.store = store
        self.capture_node_cap = int(capture_node_cap)
        self._sessions: dict[str, _SessionState] = {}

    def _state(self, session_id: str) -> _SessionState:
        if not session_id:
            raise ValueError("session_id is required")
        return self._sessions.setdefault(session_id, _SessionState())

    def _page_and_document_generation(
        self, state: _SessionState, page_token: str, document_token: str
    ) -> tuple[int, int, bool]:
        if page_token not in state.page_generations:
            state.page_generations[page_token] = state.next_page_generation
            state.next_page_generation += 1
        page_generation = state.page_generations[page_token]
        previous = state.page_documents.get(page_token)
        document_changed = previous is not None and previous[0] != document_token
        if previous is None:
            document_generation = 1
        elif document_changed:
            document_generation = previous[1] + 1
            # A new physical document invalidates all old child frame generations.
            for key in [k for k in state.frame_documents if k[0] == page_token]:
                del state.frame_documents[key]
        else:
            document_generation = previous[1]
        state.page_documents[page_token] = (document_token, document_generation)
        return page_generation, document_generation, document_changed

    @staticmethod
    def _frame_generation(
        state: _SessionState,
        page_token: str,
        frame_token: str,
        frame_document_token: str,
    ) -> int:
        key = (page_token, frame_token)
        previous = state.frame_documents.get(key)
        if previous is None:
            generation = 1
        elif previous[0] != frame_document_token:
            generation = previous[1] + 1
        else:
            generation = previous[1]
        state.frame_documents[key] = (frame_document_token, generation)
        return generation

    def _scope_ref(self, session_id: str, kind: str, *parts: object) -> str:
        return _opaque_ref(
            f"browser-{kind}-scope:",
            self.store.runtime_nonce,
            _session_hash(session_id),
            self.store.runtime_generation,
            *parts,
        )

    def _semantic_id(
        self,
        state: _SessionState,
        *,
        session_id: str,
        page_generation: int,
        document_generation: int,
        frame_generation: int | None,
        physical_key: str,
        stable: bool,
        snapshot_id: str,
    ) -> str:
        identity_key = (page_generation, document_generation, frame_generation, physical_key)
        if stable and identity_key in state.identity_map:
            return state.identity_map[identity_key]
        salt = "" if stable else snapshot_id
        basis = (
            self.store.runtime_nonce,
            _session_hash(session_id),
            page_generation,
            document_generation,
            frame_generation,
            physical_key,
            salt,
        )
        semantic_id = f"el_{hashlib.sha256(repr(basis).encode('utf-8')).hexdigest()[:20]}"
        if stable:
            state.identity_map[identity_key] = semantic_id
        return semantic_id

    @staticmethod
    def _source_ref(snapshot_id: str, source: str, semantic_id: str) -> str:
        return f"{_GROUNDING_PREFIX}{snapshot_id}/source/{source}/{semantic_id}"

    @staticmethod
    def _object_ref(snapshot_id: str, semantic_id: str) -> str:
        return f"{_GROUNDING_PREFIX}{snapshot_id}/object/{semantic_id}"

    @staticmethod
    def _merge_fields(
        *,
        prefix: str,
        dom: dict[str, Any],
        ax: dict[str, Any],
        dom_ref: str | None,
        ax_ref: str | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        merged: dict[str, Any] = {}
        conflicts: list[dict[str, Any]] = []
        for field in sorted(set(dom) | set(ax)):
            dom_present = field in dom
            ax_present = field in ax
            dom_value = dom.get(field)
            ax_value = ax.get(field)
            if dom_present and ax_present and dom_value != ax_value:
                observations = []
                if dom_ref is not None:
                    observations.append(
                        {"source": "dom", "value": dom_value, "grounding_ref": dom_ref}
                    )
                if ax_ref is not None:
                    observations.append(
                        {"source": "ax", "value": ax_value, "grounding_ref": ax_ref}
                    )
                merged[field] = None
                conflicts.append(
                    {
                        "field": f"{prefix}.{field}",
                        "observations": observations,
                        "resolution": "unresolved",
                        "derivation_basis": None,
                    }
                )
            elif dom_present:
                merged[field] = dom_value
            elif ax_present:
                merged[field] = ax_value
        return merged, conflicts

    @staticmethod
    def _object_coverage(
        sources: list[str], blind_spots: list[str], conflicts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        ordered_sources = [source for source in ("dom", "ax") if source in sources]
        status = "complete" if ordered_sources == ["dom", "ax"] and not blind_spots else "partial"
        if not ordered_sources:
            status = "unknown"
        return {
            "status": status,
            "sources": ordered_sources,
            "blind_spots": sorted(set(blind_spots)),
            "conflicts": conflicts,
        }

    @staticmethod
    def _snapshot_completeness(raw: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = []
        for source in ("dom", "ax"):
            sensor = raw.get(source) or {}
            if not sensor.get("available", False):
                reasons.append(f"{source}_unavailable")
            if sensor.get("truncated"):
                reasons.append("ax_truncated" if source == "ax" else "dom_truncated")
            reasons.extend(_normalize_blind_spots(sensor.get("blind_spots")))
        frames = raw.get("frames") or []
        if any(not bool(frame.get("same_origin", True)) and not bool(frame.get("captured")) for frame in frames):
            reasons.append("cross_origin_frame")
        if any(frame.get("document_identity_available") is False for frame in frames):
            reasons.append("frame_document_identity_unavailable")
        reasons = sorted(set(reasons))
        return {"complete": not reasons, "reasons": reasons}

    def _build_scope_facts(
        self,
        *,
        state: _SessionState,
        session_id: str,
        page_token: str,
        page_generation: int,
        document_generation: int,
        frames: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]]]:
        page_scope_ref = self._scope_ref(session_id, "page", page_generation)
        document_scope_ref = self._scope_ref(
            session_id, "document", page_generation, document_generation
        )
        page_scope = {
            "scope_ref": page_scope_ref,
            "kind": "page",
            "parent_scope_ref": None,
            "runtime_generation": self.store.runtime_generation,
            "page_generation": page_generation,
            "document_generation": document_generation,
            "frame_generation": None,
        }
        document_scope = {
            "scope_ref": document_scope_ref,
            "kind": "document",
            "parent_scope_ref": page_scope_ref,
            "runtime_generation": self.store.runtime_generation,
            "page_generation": page_generation,
            "document_generation": document_generation,
            "frame_generation": None,
        }
        frame_scopes: dict[str, dict[str, Any]] = {}
        frame_parents: dict[str, str | None] = {}
        for frame in frames:
            frame_token = str(frame.get("frame_token") or "").strip()
            frame_doc = str(frame.get("document_token") or "").strip()
            if not frame_token or not frame_doc:
                continue
            generation = self._frame_generation(state, page_token, frame_token, frame_doc)
            frame_parents[frame_token] = (
                str(frame.get("parent_frame_token") or "").strip() or None
            )
            frame_scopes[frame_token] = {
                "scope_ref": self._scope_ref(
                    session_id,
                    "frame",
                    page_generation,
                    document_generation,
                    frame_token,
                    generation,
                ),
                "kind": "frame",
                "parent_scope_ref": document_scope_ref,
                "runtime_generation": self.store.runtime_generation,
                "page_generation": page_generation,
                "document_generation": document_generation,
                "frame_generation": generation,
            }
        for frame_token, parent_token in frame_parents.items():
            if parent_token is not None and parent_token in frame_scopes:
                frame_scopes[frame_token]["parent_scope_ref"] = frame_scopes[parent_token][
                    "scope_ref"
                ]
        scope_facts = [page_scope, document_scope]
        scope_facts.extend(frame_scopes[key] for key in sorted(frame_scopes))
        return document_scope, frame_scopes, scope_facts

    def _prepare_sensor_nodes(
        self, raw_capture: dict[str, Any]
    ) -> tuple[
        dict[str, Any],
        dict[str, Any],
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, Any],
    ]:
        dom_sensor = dict(raw_capture.get("dom") or {})
        ax_sensor = dict(raw_capture.get("ax") or {})
        dom_nodes = list(dom_sensor.get("nodes") or [])
        ax_nodes = [
            node for node in list(ax_sensor.get("nodes") or []) if not node.get("ignored")
        ]
        if len(dom_nodes) > self.capture_node_cap:
            dom_nodes = dom_nodes[: self.capture_node_cap]
            dom_sensor["truncated"] = True
        if len(ax_nodes) > self.capture_node_cap:
            ax_nodes = ax_nodes[: self.capture_node_cap]
            ax_sensor["truncated"] = True
        capture_for_completeness = dict(raw_capture)
        capture_for_completeness["dom"] = dom_sensor
        capture_for_completeness["ax"] = ax_sensor
        completeness = self._snapshot_completeness(capture_for_completeness)
        return dom_sensor, ax_sensor, dom_nodes, ax_nodes, completeness

    def _record_source_grounding(
        self,
        *,
        source_grounding: dict[str, dict[str, Any]],
        snapshot_id: str,
        source: str,
        semantic_id: str,
        node: dict[str, Any],
        scope_ref: str,
    ) -> str:
        ref = self._source_ref(snapshot_id, source, semantic_id)
        source_grounding[source][semantic_id] = {
            "schema": "smc.browser_source_grounding.v0.1",
            "domain": "browser",
            "source": source,
            "semantic_id": semantic_id,
            "scope_ref": scope_ref,
            "observed_version": snapshot_id,
            "attributes": _filter_fields(node.get("attributes"), _ATTRIBUTE_FIELDS),
            "state": _filter_fields(node.get("state"), _STATE_FIELDS),
        }
        return ref

    def _canonicalize_objects(
        self,
        *,
        state: _SessionState,
        session_id: str,
        snapshot_id: str,
        page_generation: int,
        document_generation: int,
        document_scope: dict[str, Any],
        frame_scopes: dict[str, dict[str, Any]],
        dom_nodes: list[dict[str, Any]],
        ax_nodes: list[dict[str, Any]],
    ) -> _ObjectBuild:
        ax_by_physical: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
        ax_without_physical: list[dict[str, Any]] = []
        for node in ax_nodes:
            physical = str(node.get("physical_id") or "").strip()
            frame_token = str(node.get("frame_token") or "").strip() or None
            if physical:
                ax_by_physical.setdefault((frame_token, physical), []).append(node)
            else:
                ax_without_physical.append(node)

        build = _ObjectBuild([], {}, {"dom": {}, "ax": {}}, {}, {})

        def scope_for(frame_token: str | None) -> tuple[dict[str, Any], int | None]:
            if frame_token is not None and frame_token in frame_scopes:
                scope = frame_scopes[frame_token]
                return scope, int(scope["frame_generation"])
            return document_scope, None

        for dom_node in dom_nodes:
            physical = str(dom_node.get("physical_id") or "").strip()
            if not physical:
                continue
            frame_token = str(dom_node.get("frame_token") or "").strip() or None
            scope, frame_generation = scope_for(frame_token)
            semantic_id = self._semantic_id(
                state,
                session_id=session_id,
                page_generation=page_generation,
                document_generation=document_generation,
                frame_generation=frame_generation,
                physical_key=f"dom:{physical}",
                stable=True,
                snapshot_id=snapshot_id,
            )
            build.dom_semantic_by_key[(frame_token, physical)] = semantic_id
            candidates = ax_by_physical.pop((frame_token, physical), [])
            dom_ref = self._record_source_grounding(
                source_grounding=build.source_grounding,
                snapshot_id=snapshot_id,
                source="dom",
                semantic_id=semantic_id,
                node=dom_node,
                scope_ref=str(scope["scope_ref"]),
            )
            conflicts: list[dict[str, Any]] = []
            ax_ref: str | None = None
            ax_node: dict[str, Any] = {}
            sources = ["dom"]
            if len(candidates) == 1:
                ax_node = candidates[0]
                ax_ref = self._record_source_grounding(
                    source_grounding=build.source_grounding,
                    snapshot_id=snapshot_id,
                    source="ax",
                    semantic_id=semantic_id,
                    node=ax_node,
                    scope_ref=str(scope["scope_ref"]),
                )
                sources.append("ax")
            elif len(candidates) > 1:
                identity_observations: list[dict[str, Any]] = []
                for candidate in candidates:
                    candidate_key = str(candidate.get("ax_id") or secrets.token_hex(4))
                    candidate_id = self._semantic_id(
                        state,
                        session_id=session_id,
                        page_generation=page_generation,
                        document_generation=document_generation,
                        frame_generation=frame_generation,
                        physical_key=f"ax-ambiguous:{candidate_key}",
                        stable=False,
                        snapshot_id=snapshot_id,
                    )
                    candidate_ref = self._record_source_grounding(
                        source_grounding=build.source_grounding,
                        snapshot_id=snapshot_id,
                        source="ax",
                        semantic_id=candidate_id,
                        node=candidate,
                        scope_ref=str(scope["scope_ref"]),
                    )
                    candidate_obj = {
                        "schema": "smc.semantic_object.v0.1",
                        "domain": "browser",
                        "scope_ref": scope["scope_ref"],
                        "id": candidate_id,
                        "kind": _normalize_kind(candidate.get("kind")),
                        "attributes": _filter_fields(candidate.get("attributes"), _ATTRIBUTE_FIELDS),
                        "state": _filter_fields(candidate.get("state"), _STATE_FIELDS),
                        "relations": [],
                        "coverage": self._object_coverage(["ax"], [], []),
                        "grounding_ref": self._object_ref(snapshot_id, candidate_id),
                        "observed_version": snapshot_id,
                    }
                    build.semantic_objects.append(candidate_obj)
                    build.object_grounding[candidate_id] = {
                        "semantic_object": candidate_obj,
                        "sources": {"ax": candidate_ref},
                        "identity_basis": "snapshot_local_ax_identity",
                    }
                    build.private_identity[candidate_id] = {
                        "source": "ax",
                        "physical_id": candidate.get("physical_id"),
                        "ax_id": candidate.get("ax_id"),
                        "stable": False,
                    }
                    identity_observations.append(
                        {
                            "source": "ax",
                            "value": candidate_id,
                            "grounding_ref": candidate_ref,
                        }
                    )
                conflicts.append(
                    {
                        "identity_mapping": "dom_to_ax",
                        "observations": identity_observations,
                        "resolution": "unresolved",
                        "derivation_basis": None,
                    }
                )

            dom_attrs = _filter_fields(dom_node.get("attributes"), _ATTRIBUTE_FIELDS)
            ax_attrs = _filter_fields(ax_node.get("attributes"), _ATTRIBUTE_FIELDS)
            attributes, attr_conflicts = self._merge_fields(
                prefix="attributes",
                dom=dom_attrs,
                ax=ax_attrs,
                dom_ref=dom_ref,
                ax_ref=ax_ref,
            )
            dom_state = _filter_fields(dom_node.get("state"), _STATE_FIELDS)
            ax_state = _filter_fields(ax_node.get("state"), _STATE_FIELDS)
            object_state, state_conflicts = self._merge_fields(
                prefix="state",
                dom=dom_state,
                ax=ax_state,
                dom_ref=dom_ref,
                ax_ref=ax_ref,
            )
            conflicts.extend(attr_conflicts)
            conflicts.extend(state_conflicts)
            blind_spots = [
                "canvas"
                for _ in [0]
                if str(dom_attrs.get("tag") or "").lower() == "canvas"
            ]
            semantic_object = {
                "schema": "smc.semantic_object.v0.1",
                "domain": "browser",
                "scope_ref": scope["scope_ref"],
                "id": semantic_id,
                "kind": _normalize_kind(dom_node.get("kind") or ax_node.get("kind")),
                "attributes": attributes,
                "state": object_state,
                "relations": [],
                "coverage": self._object_coverage(sources, blind_spots, conflicts),
                "grounding_ref": self._object_ref(snapshot_id, semantic_id),
                "observed_version": snapshot_id,
            }
            build.semantic_objects.append(semantic_object)
            build.object_grounding[semantic_id] = {
                "semantic_object": semantic_object,
                "sources": {
                    key: value
                    for key, value in {"dom": dom_ref, "ax": ax_ref}.items()
                    if value is not None
                },
                "identity_basis": "dom_physical_identity",
            }
            build.private_identity[semantic_id] = {
                "source": "dom",
                "physical_id": physical,
                "ax_ids": [candidate.get("ax_id") for candidate in candidates],
                "stable": True,
            }

        remaining_ax = ax_without_physical + [
            node for group in ax_by_physical.values() for node in group
        ]
        for ax_node in remaining_ax:
            frame_token = str(ax_node.get("frame_token") or "").strip() or None
            scope, frame_generation = scope_for(frame_token)
            physical = str(ax_node.get("physical_id") or "").strip()
            ax_id = str(ax_node.get("ax_id") or secrets.token_hex(4))
            stable = bool(physical)
            semantic_id = self._semantic_id(
                state,
                session_id=session_id,
                page_generation=page_generation,
                document_generation=document_generation,
                frame_generation=frame_generation,
                physical_key=(f"ax-physical:{physical}" if stable else f"ax-local:{ax_id}"),
                stable=stable,
                snapshot_id=snapshot_id,
            )
            ax_ref = self._record_source_grounding(
                source_grounding=build.source_grounding,
                snapshot_id=snapshot_id,
                source="ax",
                semantic_id=semantic_id,
                node=ax_node,
                scope_ref=str(scope["scope_ref"]),
            )
            semantic_object = {
                "schema": "smc.semantic_object.v0.1",
                "domain": "browser",
                "scope_ref": scope["scope_ref"],
                "id": semantic_id,
                "kind": _normalize_kind(ax_node.get("kind")),
                "attributes": _filter_fields(ax_node.get("attributes"), _ATTRIBUTE_FIELDS),
                "state": _filter_fields(ax_node.get("state"), _STATE_FIELDS),
                "relations": [],
                "coverage": self._object_coverage(["ax"], [], []),
                "grounding_ref": self._object_ref(snapshot_id, semantic_id),
                "observed_version": snapshot_id,
            }
            build.semantic_objects.append(semantic_object)
            build.object_grounding[semantic_id] = {
                "semantic_object": semantic_object,
                "sources": {"ax": ax_ref},
                "identity_basis": (
                    "ax_backend_physical_identity" if stable else "snapshot_local_ax_identity"
                ),
            }
            build.private_identity[semantic_id] = {
                "source": "ax",
                "physical_id": physical or None,
                "ax_id": ax_id,
                "stable": stable,
            }
        return build

    def _attach_structural_relations(
        self,
        build: _ObjectBuild,
        dom_nodes: list[dict[str, Any]],
    ) -> tuple[int, bool]:
        objects_by_id = {obj["id"]: obj for obj in build.semantic_objects}
        relation_count = 0
        relation_cap = max(1, self.capture_node_cap * _RELATION_CAP_FACTOR)
        relation_truncated = False
        for node in dom_nodes:
            physical = str(node.get("physical_id") or "").strip()
            parent = str(node.get("parent_id") or "").strip()
            frame_token = str(node.get("frame_token") or "").strip() or None
            if not physical or not parent:
                continue
            child_id = build.dom_semantic_by_key.get((frame_token, physical))
            parent_id = build.dom_semantic_by_key.get((frame_token, parent))
            if not child_id or not parent_id:
                continue
            if relation_count + 2 > relation_cap:
                relation_truncated = True
                continue
            objects_by_id[child_id]["relations"].append(
                {"type": "parent", "target_id": parent_id}
            )
            objects_by_id[parent_id]["relations"].append(
                {"type": "child", "target_id": child_id}
            )
            relation_count += 2
        return relation_cap, relation_truncated

    @staticmethod
    def _sensor_grounding(
        dom_sensor: dict[str, Any],
        ax_sensor: dict[str, Any],
        dom_nodes: list[dict[str, Any]],
        ax_nodes: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        return {
            "dom": {
                "schema": "smc.browser_sensor_grounding.v0.1",
                "source": "dom",
                "available": bool(dom_sensor.get("available", False)),
                "truncated": bool(dom_sensor.get("truncated", False)),
                "captured_objects": len(dom_nodes),
                "blind_spots": _normalize_blind_spots(dom_sensor.get("blind_spots")),
            },
            "ax": {
                "schema": "smc.browser_sensor_grounding.v0.1",
                "source": "ax",
                "available": bool(ax_sensor.get("available", False)),
                "truncated": bool(ax_sensor.get("truncated", False)),
                "captured_objects": len(ax_nodes),
                "blind_spots": _normalize_blind_spots(ax_sensor.get("blind_spots")),
            },
        }

    def snapshot(
        self,
        session_id: str,
        raw_capture: dict[str, Any],
        *,
        projection_limit: int = 200,
    ) -> dict[str, Any]:
        """Canonicalize one read-only DOM+AX capture without task-semantic input."""
        state = self._state(session_id)
        page_token = str(raw_capture.get("page_token") or "").strip()
        document_token = str(raw_capture.get("document_token") or "").strip()
        if not page_token or not document_token:
            raise ValueError("raw capture requires page_token and document_token")
        page_generation, document_generation, _ = self._page_and_document_generation(
            state, page_token, document_token
        )
        snapshot_id = f"bsnap-{self.store.runtime_generation}-{secrets.token_hex(8)}"
        document_scope, frame_scopes, scope_facts = self._build_scope_facts(
            state=state,
            session_id=session_id,
            page_token=page_token,
            page_generation=page_generation,
            document_generation=document_generation,
            frames=list(raw_capture.get("frames") or []),
        )
        dom_sensor, ax_sensor, dom_nodes, ax_nodes, completeness = self._prepare_sensor_nodes(
            raw_capture
        )
        build = self._canonicalize_objects(
            state=state,
            session_id=session_id,
            snapshot_id=snapshot_id,
            page_generation=page_generation,
            document_generation=document_generation,
            document_scope=document_scope,
            frame_scopes=frame_scopes,
            dom_nodes=dom_nodes,
            ax_nodes=ax_nodes,
        )
        relation_cap, relation_truncated = self._attach_structural_relations(build, dom_nodes)
        if relation_truncated:
            completeness["complete"] = False
            completeness["reasons"] = sorted(
                set(completeness["reasons"] + ["relation_cap"])
            )

        objects_sorted = sorted(build.semantic_objects, key=lambda item: item["id"])
        projection_limit = max(1, min(int(projection_limit), 500))
        objects_ref = f"{_GROUNDING_PREFIX}{snapshot_id}/objects"
        scopes_ref = f"{_GROUNDING_PREFIX}{snapshot_id}/scopes"
        dom_ref = f"{_GROUNDING_PREFIX}{snapshot_id}/sensor/dom"
        ax_ref = f"{_GROUNDING_PREFIX}{snapshot_id}/sensor/ax"
        sensor_grounding = self._sensor_grounding(dom_sensor, ax_sensor, dom_nodes, ax_nodes)
        content_sha = _sha256(
            {
                "scopes": scope_facts,
                "sensor_contract": _SENSOR_CONTRACT,
                "completeness": completeness,
                "objects": _content_fact_basis(objects_sorted),
                "sensor_grounding": sensor_grounding,
            }
        )
        observed_at = str(raw_capture.get("observed_at") or "") or time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        snapshot = {
            "schema": "smc.world_snapshot.v0.1",
            "domain": "browser",
            "snapshot_id": snapshot_id,
            "scope": document_scope,
            "observed_at": observed_at,
            "sensor_contract": dict(_SENSOR_CONTRACT),
            "completeness": completeness,
            "projection": {
                "representation": "objects",
                "complete": len(objects_sorted) <= projection_limit,
                "full_ref": objects_ref,
            },
            "budget": {
                "object_cap": self.capture_node_cap,
                "relation_cap": relation_cap,
                "token_estimate": len(_json_bytes(objects_sorted)) // 4,
            },
            "grounding_version": content_sha,
            "content_sha256": content_sha,
            "objects_ref": objects_ref,
            "grounding_refs": {
                "dom": dom_ref if dom_sensor.get("available", False) else None,
                "ax": ax_ref if ax_sensor.get("available", False) else None,
            },
        }
        bundle = {
            "snapshot": snapshot,
            "scope_facts": scope_facts,
            "objects": objects_sorted,
            "sensor_grounding": sensor_grounding,
            "object_grounding": build.object_grounding,
            "source_grounding": build.source_grounding,
            "private_capture": {
                "page_token": page_token,
                "document_token": document_token,
                "frames": raw_capture.get("frames") or [],
                "identity": build.private_identity,
            },
        }
        self.store.persist(session_id, bundle)
        return {
            "action": "snapshot",
            "snapshot": snapshot,
            "scope_facts": scope_facts,
            "scope_facts_ref": scopes_ref,
            "objects": objects_sorted[:projection_limit],
            "objects_projection": {
                "returned": min(len(objects_sorted), projection_limit),
                "total": len(objects_sorted),
                "complete": len(objects_sorted) <= projection_limit,
            },
        }

    def hydrate(self, session_id: str, grounding_ref: str) -> dict[str, Any]:
        return self.store.hydrate(session_id, grounding_ref)


def _rare_string_values(raw: Any, strings: list[str]) -> dict[int, str]:
    if not isinstance(raw, dict):
        return {}
    indexes = raw.get("index") or []
    values = raw.get("value") or []
    out: dict[int, str] = {}
    for idx, value_idx in zip(indexes, values, strict=False):
        if isinstance(idx, int) and isinstance(value_idx, int) and 0 <= value_idx < len(strings):
            out[idx] = strings[value_idx]
    return out


def _string(strings: list[str], index: Any) -> str:
    if isinstance(index, int) and 0 <= index < len(strings):
        return strings[index]
    return ""


def _attrs(strings: list[str], raw: Any) -> dict[str, str]:
    if not isinstance(raw, list):
        return {}
    result: dict[str, str] = {}
    for i in range(0, len(raw) - 1, 2):
        key = _string(strings, raw[i])
        value = _string(strings, raw[i + 1])
        if key:
            result[key.lower()] = value
    return result


def _kind_for(role: str, tag: str) -> str:
    role_map = {
        "button": "button",
        "link": "link",
        "textbox": "input",
        "combobox": "select",
        "option": "option",
        "checkbox": "checkbox",
        "radio": "radio",
        "img": "image",
        "dialog": "dialog",
        "list": "list",
        "listitem": "listitem",
        "table": "table",
        "row": "row",
        "cell": "cell",
        "form": "form",
        "heading": "heading",
        "document": "document",
    }
    tag_map = {
        "button": "button",
        "a": "link",
        "input": "input",
        "select": "select",
        "option": "option",
        "img": "image",
        "form": "form",
        "table": "table",
        "tr": "row",
        "td": "cell",
        "th": "cell",
        "html": "document",
        "iframe": "frame",
    }
    return role_map.get(role.lower(), tag_map.get(tag.lower(), "generic"))


def _ax_property_map(node: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for prop in node.get("properties") or []:
        name = str(prop.get("name") or "")
        value = prop.get("value")
        if isinstance(value, dict):
            out[name] = value.get("value")
    return out


class PlaywrightPageCaptureBackend:
    """Read the currently bound Playwright page without navigation or interaction."""

    def __init__(self, page: Any, *, node_cap: int = 20_000) -> None:
        self.page = page
        self.node_cap = max(1, int(node_cap))

    @staticmethod
    def _flatten_frames(tree: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        def visit(node: dict[str, Any], parent: str | None) -> None:
            frame = node.get("frame") or {}
            frame_id = str(frame.get("id") or "")
            if frame_id:
                result.append(
                    {
                        "frame_id": frame_id,
                        "loader_id": str(frame.get("loaderId") or ""),
                        "url": str(frame.get("url") or ""),
                        "security_origin": str(frame.get("securityOrigin") or ""),
                        "parent": parent,
                    }
                )
                parent = frame_id
            for child in node.get("childFrames") or []:
                visit(child, parent)

        visit(tree, None)
        return result

    def capture(self) -> dict[str, Any]:
        cdp = self.page.context.new_cdp_session(self.page)
        target = cdp.send("Target.getTargetInfo")
        frame_tree_doc = cdp.send("Page.getFrameTree")
        dom_doc = cdp.send(
            "DOMSnapshot.captureSnapshot",
            {
                "computedStyles": [],
                "includePaintOrder": False,
                "includeDOMRects": False,
                "includeBlendedBackgroundColors": False,
                "includeTextColorOpacities": False,
            },
        )
        ax_doc = cdp.send("Accessibility.getFullAXTree")

        target_id = str((target.get("targetInfo") or {}).get("targetId") or "")
        flattened_frames = self._flatten_frames(frame_tree_doc.get("frameTree") or {})
        main_frame = flattened_frames[0] if flattened_frames else {}
        main_frame_id = str(main_frame.get("frame_id") or "")
        main_url = str(getattr(self.page, "url", "") or main_frame.get("url") or "")
        if not target_id:
            raise RuntimeError("Browser target identity unavailable; refusing URL-based page identity")
        if not main_frame_id or not str(main_frame.get("loader_id") or ""):
            raise RuntimeError("Browser document identity unavailable; refusing URL-based document identity")
        page_token = f"target:{target_id}"
        document_token = str(main_frame["loader_id"])
        strings = [str(value) for value in dom_doc.get("strings") or []]
        documents = list(dom_doc.get("documents") or [])
        captured_frame_ids = {str(doc.get("frameId") or "") for doc in documents}
        main_origin = _origin(main_url)

        frames: list[dict[str, Any]] = []
        for frame in flattened_frames[1:]:
            frame_id = str(frame.get("frame_id") or "")
            frame_url = str(frame.get("url") or "")
            frame_origin = str(frame.get("security_origin") or "") or _origin(frame_url)
            parent = frame.get("parent")
            loader_id = str(frame.get("loader_id") or "")
            frames.append(
                {
                    "frame_token": f"frame:{frame_id}",
                    # Missing child-frame loader identity must never preserve identity by URL.
                    # A capture-local token forces conservative invalidation on the next snapshot.
                    "document_token": loader_id or f"unknown:{secrets.token_hex(8)}",
                    "document_identity_available": bool(loader_id),
                    "parent_frame_token": None if parent == main_frame_id else (f"frame:{parent}" if parent else None),
                    "same_origin": not main_origin or not frame_origin or frame_origin == main_origin,
                    "captured": frame_id in captured_frame_ids,
                    "url": frame_url,
                }
            )

        dom_nodes: list[dict[str, Any]] = []
        dom_blind_spots: set[str] = set()
        dom_truncated = False
        for document in documents:
            nodes = document.get("nodes") or {}
            node_names = list(nodes.get("nodeName") or [])
            node_values = list(nodes.get("nodeValue") or [])
            parent_indexes = list(nodes.get("parentIndex") or [])
            backend_ids = list(nodes.get("backendNodeId") or [])
            attributes = list(nodes.get("attributes") or [])
            frame_id = str(document.get("frameId") or "")
            frame_token = None if frame_id == main_frame_id else (f"frame:{frame_id}" if frame_id else None)
            shadow_types = _rare_string_values(nodes.get("shadowRootType"), strings)
            for idx in range(len(node_names)):
                tag = _string(strings, node_names[idx]).lower()
                if not tag or tag.startswith("#"):
                    continue
                if len(dom_nodes) >= self.node_cap:
                    dom_truncated = True
                    break
                raw_attrs = _attrs(strings, attributes[idx] if idx < len(attributes) else [])
                role = raw_attrs.get("role", "")
                name = raw_attrs.get("aria-label") or raw_attrs.get("name") or ""
                dom_attributes: dict[str, Any] = {"tag": tag}
                if role:
                    dom_attributes["role"] = role
                if name:
                    dom_attributes["name"] = name
                if raw_attrs.get("type"):
                    dom_attributes["input_type"] = raw_attrs["type"]
                if raw_attrs.get("value"):
                    dom_attributes["value_text"] = raw_attrs["value"]
                if raw_attrs.get("href"):
                    dom_attributes["href"] = raw_attrs["href"]
                if idx < len(node_values):
                    text = _string(strings, node_values[idx]).strip()
                    if text:
                        dom_attributes["text"] = text
                # Layout-tree membership is not equivalent to user-visible state
                # (opacity/clipping/occlusion can disagree), so do not promote it
                # into the canonical ``visible`` field.
                dom_state: dict[str, Any] = {"exists": True}
                if tag in {"button", "input", "select", "option", "textarea"}:
                    dom_state["enabled"] = "disabled" not in raw_attrs
                for attr_name, state_name in (
                    ("checked", "checked"),
                    ("selected", "selected"),
                    ("readonly", "readonly"),
                    ("required", "required"),
                ):
                    if attr_name in raw_attrs:
                        dom_state[state_name] = True
                if tag == "canvas":
                    dom_blind_spots.add("canvas")
                if shadow_types.get(idx) == "closed":
                    dom_blind_spots.add("closed_shadow_root")
                backend_id = backend_ids[idx] if idx < len(backend_ids) else idx
                parent_id: str | None = None
                if idx < len(parent_indexes):
                    pidx = parent_indexes[idx]
                    if isinstance(pidx, int) and pidx >= 0 and pidx < len(backend_ids):
                        parent_id = f"dom:{backend_ids[pidx]}"
                dom_nodes.append(
                    {
                        "physical_id": f"dom:{backend_id}",
                        "parent_id": parent_id,
                        "frame_token": frame_token,
                        "kind": _kind_for(role, tag),
                        "attributes": dom_attributes,
                        "state": dom_state,
                    }
                )
            if dom_truncated:
                break

        ax_nodes: list[dict[str, Any]] = []
        ax_truncated = False
        for node in ax_doc.get("nodes") or []:
            if bool(node.get("ignored")):
                continue
            if len(ax_nodes) >= self.node_cap:
                ax_truncated = True
                break
            role = str((node.get("role") or {}).get("value") or "")
            name = str((node.get("name") or {}).get("value") or "")
            value_text = (node.get("value") or {}).get("value")
            props = _ax_property_map(node)
            ax_attributes: dict[str, Any] = {}
            if role:
                ax_attributes["role"] = role
            if name:
                ax_attributes["name"] = name
            if value_text is not None:
                ax_attributes["value_text"] = str(value_text)
            ax_state: dict[str, Any] = {"exists": True}
            if "disabled" in props:
                ax_state["enabled"] = not bool(props["disabled"])
            for prop_name in (
                "checked",
                "selected",
                "expanded",
                "focused",
                "editable",
                "readonly",
                "required",
                "busy",
            ):
                if prop_name in props and isinstance(props[prop_name], bool):
                    ax_state[prop_name] = props[prop_name]
            backend_id = node.get("backendDOMNodeId")
            ax_frame_id = str(node.get("frameId") or "")
            ax_nodes.append(
                {
                    "ax_id": str(node.get("nodeId") or ""),
                    "physical_id": f"dom:{backend_id}" if backend_id is not None else "",
                    "frame_token": (
                        None
                        if not ax_frame_id or ax_frame_id == main_frame_id
                        else f"frame:{ax_frame_id}"
                    ),
                    "kind": _kind_for(role, ""),
                    "attributes": ax_attributes,
                    "state": ax_state,
                }
            )

        return {
            "page_token": page_token,
            "document_token": document_token,
            "url": main_url,
            "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "frames": frames,
            "dom": {
                "available": True,
                "truncated": dom_truncated,
                "blind_spots": sorted(dom_blind_spots),
                "nodes": dom_nodes,
            },
            "ax": {
                "available": True,
                "truncated": ax_truncated,
                "blind_spots": ["ax_truncated"] if ax_truncated else [],
                "nodes": ax_nodes,
            },
        }
