"""Typed FactGraph IR for SMC Semantic Logic P1-A.

This module is deliberately representation-only.  It performs no semantic closure,
target selection, routing, retry, mutation, task-completion inference, or runtime
authority checks.  During P1 the current Python implementation remains the oracle.

The projector losslessly flattens a JSON-compatible canonical document into typed
leaf facts plus explicit container shapes.  Context/provenance fields are copied only
from mechanically visible ancestor keys; they do not change the reconstructed source
document and therefore cannot manufacture authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

type PathSegment = str | int
type FactPath = tuple[PathSegment, ...]
type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type ContainerKind = Literal["object", "array"]
type ValueType = Literal["null", "boolean", "integer", "number", "string"]


def _value_type(value: JsonScalar) -> ValueType:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    raise TypeError(f"unsupported scalar type: {type(value).__name__}")


def _path_wire(path: FactPath) -> list[dict[str, str | int]]:
    return [
        {"kind": "index", "value": segment}
        if isinstance(segment, int)
        else {"kind": "key", "value": segment}
        for segment in path
    ]


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class FactContext:
    """Observation context copied from mechanically visible canonical fields."""

    domain: str
    scope_ref: str | None = None
    observed_version: str | None = None
    snapshot_id: str | None = None
    sensor_contract_ref: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "domain": self.domain,
            "scope_ref": self.scope_ref,
            "observed_version": self.observed_version,
            "snapshot_id": self.snapshot_id,
            "sensor_contract_ref": self.sensor_contract_ref,
        }


@dataclass(frozen=True, slots=True)
class FactProvenance:
    """Mechanical provenance for one oracle-projected leaf fact."""

    kind: Literal["oracle_projection"]
    source: str
    grounding_ref: str | None = None
    observed_version: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "kind": self.kind,
            "source": self.source,
            "grounding_ref": self.grounding_ref,
            "observed_version": self.observed_version,
        }


@dataclass(frozen=True, slots=True)
class SemanticFact:
    """One typed leaf fact in an oracle projection.

    `truth_state=asserted` means only that the frozen Python oracle emitted this exact
    JSON leaf.  It is not a claim that the leaf is an eternal world truth.
    """

    fact_id: str
    path: FactPath
    value: JsonScalar
    value_type: ValueType
    truth_state: Literal["asserted"]
    context: FactContext
    provenance: FactProvenance

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "path": _path_wire(self.path),
            "value": self.value,
            "value_type": self.value_type,
            "truth_state": self.truth_state,
            "context": self.context.to_dict(),
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ContainerShape:
    """Explicit container marker required to preserve empty dict/list structure."""

    path: FactPath
    kind: ContainerKind

    def to_dict(self) -> dict[str, Any]:
        return {"path": _path_wire(self.path), "kind": self.kind}


@dataclass(frozen=True, slots=True)
class FactGraph:
    """Lossless shadow representation of one canonical JSON-compatible document."""

    graph_id: str
    domain: str
    source_ref: str
    root_kind: Literal["object", "array", "scalar"]
    containers: tuple[ContainerShape, ...]
    facts: tuple[SemanticFact, ...]
    schema: Literal["smc.typed_fact_graph.v0.1"] = "smc.typed_fact_graph.v0.1"
    authority: Literal["shadow_only"] = "shadow_only"
    production_consumed: Literal[False] = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "graph_id": self.graph_id,
            "domain": self.domain,
            "source_ref": self.source_ref,
            "root_kind": self.root_kind,
            "authority": self.authority,
            "production_consumed": self.production_consumed,
            "containers": [item.to_dict() for item in self.containers],
            "facts": [fact.to_dict() for fact in self.facts],
        }

    def structural_fingerprint(self) -> str:
        """Stable hash of this concrete graph; P1-B owns canonical wire format later."""

        return _stable_hash(self.to_dict())

    def reconstruct(self) -> JsonValue:
        """Reconstruct the source document exactly modulo Python dict key order."""

        if self.root_kind == "scalar":
            roots = [fact for fact in self.facts if fact.path == ()]
            if len(roots) != 1:
                raise ValueError("scalar graph requires exactly one root fact")
            return roots[0].value

        root: JsonValue = {} if self.root_kind == "object" else []

        def get_parent(path: FactPath) -> JsonValue:
            current: JsonValue = root
            for segment in path:
                if isinstance(segment, int):
                    if not isinstance(current, list) or segment >= len(current):
                        raise ValueError(f"invalid array path segment: {path!r}")
                    current = current[segment]
                else:
                    if not isinstance(current, dict) or segment not in current:
                        raise ValueError(f"invalid object path segment: {path!r}")
                    current = current[segment]
            return current

        def assign(path: FactPath, value: JsonValue) -> None:
            if not path:
                raise ValueError("container graph cannot assign scalar at root")
            parent = get_parent(path[:-1])
            leaf = path[-1]
            if isinstance(leaf, int):
                if not isinstance(parent, list):
                    raise ValueError(f"array index under non-array parent: {path!r}")
                while len(parent) <= leaf:
                    parent.append(None)
                parent[leaf] = value
            else:
                if not isinstance(parent, dict):
                    raise ValueError(f"object key under non-object parent: {path!r}")
                parent[leaf] = value

        # Build containers before leaves.  Empty containers therefore survive projection.
        for container in sorted(self.containers, key=lambda item: len(item.path)):
            if not container.path:
                expected = "object" if isinstance(root, dict) else "array"
                if container.kind != expected:
                    raise ValueError("root container kind mismatch")
                continue
            assign(container.path, {} if container.kind == "object" else [])

        for fact in self.facts:
            assign(fact.path, fact.value)
        return root


@dataclass(frozen=True, slots=True)
class _InheritedMetadata:
    source: str
    domain: str
    grounding_ref: str | None = None
    observed_version: str | None = None
    scope_ref: str | None = None
    snapshot_id: str | None = None
    sensor_contract_ref: str | None = None


def _string_field(value: dict[str, JsonValue], key: str) -> str | None:
    candidate = value.get(key)
    return candidate if isinstance(candidate, str) and candidate else None


def _inherit(meta: _InheritedMetadata, value: dict[str, JsonValue]) -> _InheritedMetadata:
    return _InheritedMetadata(
        source=_string_field(value, "source") or meta.source,
        domain=_string_field(value, "domain") or meta.domain,
        grounding_ref=_string_field(value, "grounding_ref") or meta.grounding_ref,
        observed_version=(
            _string_field(value, "observed_version")
            or _string_field(value, "snapshot_id")
            or meta.observed_version
        ),
        scope_ref=_string_field(value, "scope_ref") or meta.scope_ref,
        snapshot_id=_string_field(value, "snapshot_id") or meta.snapshot_id,
        sensor_contract_ref=_string_field(value, "sensor_contract_ref") or meta.sensor_contract_ref,
    )


def _validate_json_value(value: Any, *, path: FactPath = ()) -> JsonValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError(f"non-finite float at {path!r}")
        return value
    if isinstance(value, list):
        return [_validate_json_value(item, path=(*path, index)) for index, item in enumerate(value)]
    if isinstance(value, dict):
        normalized: dict[str, JsonValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError(f"non-string object key at {path!r}: {key!r}")
            normalized[key] = _validate_json_value(child, path=(*path, key))
        return normalized
    raise TypeError(f"non-JSON value at {path!r}: {type(value).__name__}")


def project_document(
    *,
    graph_id: str,
    document: Any,
    domain: str,
    source_ref: str,
) -> FactGraph:
    """Project one Python-oracle document into a lossless typed FactGraph.

    P1-A performs representation only.  No field is synthesized except mechanical IR
    metadata and deterministic fact IDs; every source leaf remains byte-equivalent when
    JSON-encoded after `reconstruct()`.
    """

    if not graph_id or not domain or not source_ref:
        raise ValueError("graph_id, domain and source_ref are required")
    normalized = _validate_json_value(document)
    containers: list[ContainerShape] = []
    facts: list[SemanticFact] = []
    initial = _InheritedMetadata(source=source_ref, domain=domain)

    def walk(value: JsonValue, path: FactPath, meta: _InheritedMetadata) -> None:
        if isinstance(value, dict):
            next_meta = _inherit(meta, value)
            containers.append(ContainerShape(path=path, kind="object"))
            for key in sorted(value):
                walk(value[key], (*path, key), next_meta)
            return
        if isinstance(value, list):
            containers.append(ContainerShape(path=path, kind="array"))
            for index, child in enumerate(value):
                walk(child, (*path, index), meta)
            return

        fact_payload = {
            "graph_id": graph_id,
            "path": _path_wire(path),
            "value": value,
            "source": meta.source,
            "domain": meta.domain,
            "grounding_ref": meta.grounding_ref,
            "observed_version": meta.observed_version,
            "scope_ref": meta.scope_ref,
            "snapshot_id": meta.snapshot_id,
        }
        facts.append(
            SemanticFact(
                fact_id=f"sfact-{_stable_hash(fact_payload)[:24]}",
                path=path,
                value=value,
                value_type=_value_type(value),
                truth_state="asserted",
                context=FactContext(
                    domain=meta.domain,
                    scope_ref=meta.scope_ref,
                    observed_version=meta.observed_version,
                    snapshot_id=meta.snapshot_id,
                    sensor_contract_ref=meta.sensor_contract_ref,
                ),
                provenance=FactProvenance(
                    kind="oracle_projection",
                    source=meta.source,
                    grounding_ref=meta.grounding_ref,
                    observed_version=meta.observed_version,
                ),
            )
        )

    walk(normalized, (), initial)
    root_kind: Literal["object", "array", "scalar"]
    if isinstance(normalized, dict):
        root_kind = "object"
    elif isinstance(normalized, list):
        root_kind = "array"
    else:
        root_kind = "scalar"

    graph = FactGraph(
        graph_id=graph_id,
        domain=domain,
        source_ref=source_ref,
        root_kind=root_kind,
        containers=tuple(containers),
        facts=tuple(facts),
    )
    if graph.reconstruct() != normalized:
        raise AssertionError("typed FactGraph projection is not lossless")
    return graph
