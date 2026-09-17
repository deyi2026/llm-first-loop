"""Canonical shadow serialization for SMC Semantic Logic P1-B.

The serializers in this module are deliberately representation-only.  They do not
perform semantic closure, rule evaluation, target selection, routing, retry, mutation,
or runtime authority checks.  The N3 document is a deterministic projection of the
P1-A Typed FactGraph and uses only a full-IRI Turtle-compatible triple subset, which is
also valid N3 syntax.  No reasoner is required or invoked here.

Opaque runtime identities are preserved as exact literals.  They are never rewritten,
coalesced, similarity-matched, or normalized.  Qualification-critical entities use
deterministic URNs rather than blank nodes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from llm_loop.semantic_logic.ir import (
    ContainerShape,
    FactContext,
    FactGraph,
    FactProvenance,
    SemanticFact,
)

CANONICAL_JSON_PROFILE = "smc.fact_graph_json.v0.1"
CANONICAL_N3_PROFILE = "smc.fact_graph_n3.v0.1"
OPAQUE_IDENTITY_POLICY = "exact_literal_no_normalization"

_IR_SCHEMA = "smc.typed_fact_graph.v0.1"
_NS = "urn:smc:semantic-logic:v0.1#"
_URN_BASE = "urn:smc:semantic-logic:v0.1:"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_XSD = "http://www.w3.org/2001/XMLSchema#"
_XSD_STRING = f"{_XSD}string"
_XSD_BOOLEAN = f"{_XSD}boolean"
_XSD_INTEGER = f"{_XSD}integer"
_XSD_DOUBLE = f"{_XSD}double"
_JSON_PATH_DATATYPE = f"{_NS}jsonPath"
_NULL_IRI = f"{_NS}null"

type JsonScalar = None | bool | int | float | str
type FactPath = tuple[str | int, ...]
type ObjectKind = Literal["iri", "literal"]


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _path_wire(path: FactPath) -> list[dict[str, str | int]]:
    return [
        {"kind": "index", "value": segment}
        if isinstance(segment, int)
        else {"kind": "key", "value": segment}
        for segment in path
    ]


def _decode_path(value: Any) -> FactPath:
    if not isinstance(value, list):
        raise ValueError("path must be an array")
    path: list[str | int] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"kind", "value"}:
            raise ValueError("path segment must contain exactly kind/value")
        kind = item["kind"]
        segment = item["value"]
        if kind == "key":
            if not isinstance(segment, str):
                raise ValueError("key path segment must be a string")
            path.append(segment)
        elif kind == "index":
            if isinstance(segment, bool) or not isinstance(segment, int) or segment < 0:
                raise ValueError("index path segment must be a non-negative integer")
            path.append(segment)
        else:
            raise ValueError(f"unknown path segment kind: {kind!r}")
    return tuple(path)


def _scalar_type(value: JsonScalar) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("non-finite float")
        return "number"
    if isinstance(value, str):
        return "string"
    raise TypeError(f"unsupported scalar type: {type(value).__name__}")


def _require_exact_keys(value: Any, keys: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise ValueError(f"{label} fields mismatch: {actual!r}")
    return value


def _optional_string(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be string|null")
    return value


def _fact_graph_from_dict(value: Any) -> FactGraph:
    root = _require_exact_keys(
        value,
        {
            "schema",
            "graph_id",
            "domain",
            "source_ref",
            "root_kind",
            "authority",
            "production_consumed",
            "containers",
            "facts",
        },
        label="FactGraph",
    )
    if root["schema"] != _IR_SCHEMA:
        raise ValueError("unsupported FactGraph schema")
    if root["authority"] != "shadow_only" or root["production_consumed"] is not False:
        raise ValueError("P1 serialization accepts shadow-only graphs")
    graph_id = root["graph_id"]
    domain = root["domain"]
    source_ref = root["source_ref"]
    root_kind = root["root_kind"]
    if not all(isinstance(item, str) and item for item in (graph_id, domain, source_ref)):
        raise ValueError("graph_id/domain/source_ref must be non-empty strings")
    if root_kind not in {"object", "array", "scalar"}:
        raise ValueError("invalid root_kind")

    raw_containers = root["containers"]
    if not isinstance(raw_containers, list):
        raise ValueError("containers must be an array")
    containers: list[ContainerShape] = []
    for item in raw_containers:
        doc = _require_exact_keys(item, {"path", "kind"}, label="ContainerShape")
        kind = doc["kind"]
        if kind not in {"object", "array"}:
            raise ValueError("invalid container kind")
        containers.append(ContainerShape(path=_decode_path(doc["path"]), kind=kind))

    raw_facts = root["facts"]
    if not isinstance(raw_facts, list):
        raise ValueError("facts must be an array")
    facts: list[SemanticFact] = []
    for item in raw_facts:
        doc = _require_exact_keys(
            item,
            {"fact_id", "path", "value", "value_type", "truth_state", "context", "provenance"},
            label="SemanticFact",
        )
        path = _decode_path(doc["path"])
        scalar = doc["value"]
        if not (scalar is None or isinstance(scalar, (bool, int, float, str))):
            raise ValueError("fact value must be a JSON scalar")
        value_type = _scalar_type(scalar)
        if doc["value_type"] != value_type:
            raise ValueError("fact value_type mismatch")
        if doc["truth_state"] != "asserted":
            raise ValueError("unsupported truth_state")

        context_doc = _require_exact_keys(
            doc["context"],
            {"domain", "scope_ref", "observed_version", "snapshot_id", "sensor_contract_ref"},
            label="FactContext",
        )
        context_domain = context_doc["domain"]
        if not isinstance(context_domain, str) or not context_domain:
            raise ValueError("context.domain must be a non-empty string")
        context = FactContext(
            domain=context_domain,
            scope_ref=_optional_string(context_doc["scope_ref"], label="context.scope_ref"),
            observed_version=_optional_string(
                context_doc["observed_version"], label="context.observed_version"
            ),
            snapshot_id=_optional_string(context_doc["snapshot_id"], label="context.snapshot_id"),
            sensor_contract_ref=_optional_string(
                context_doc["sensor_contract_ref"], label="context.sensor_contract_ref"
            ),
        )
        provenance_doc = _require_exact_keys(
            doc["provenance"],
            {"kind", "source", "grounding_ref", "observed_version"},
            label="FactProvenance",
        )
        if provenance_doc["kind"] != "oracle_projection":
            raise ValueError("unsupported provenance kind")
        provenance_source = provenance_doc["source"]
        if not isinstance(provenance_source, str) or not provenance_source:
            raise ValueError("provenance.source must be a non-empty string")
        provenance = FactProvenance(
            kind="oracle_projection",
            source=provenance_source,
            grounding_ref=_optional_string(
                provenance_doc["grounding_ref"], label="provenance.grounding_ref"
            ),
            observed_version=_optional_string(
                provenance_doc["observed_version"], label="provenance.observed_version"
            ),
        )
        if provenance.observed_version != context.observed_version:
            raise ValueError("context/provenance observed_version mismatch")

        fact_id = doc["fact_id"]
        if not isinstance(fact_id, str) or not fact_id:
            raise ValueError("fact_id must be a non-empty string")
        expected_id_payload = {
            "graph_id": graph_id,
            "path": _path_wire(path),
            "value": scalar,
            "source": provenance.source,
            "domain": context.domain,
            "grounding_ref": provenance.grounding_ref,
            "observed_version": context.observed_version,
            "scope_ref": context.scope_ref,
            "snapshot_id": context.snapshot_id,
        }
        expected_fact_id = f"sfact-{_sha256_text(_canonical_json(expected_id_payload))[:24]}"
        if fact_id != expected_fact_id:
            raise ValueError("fact_id integrity mismatch")
        facts.append(
            SemanticFact(
                fact_id=fact_id,
                path=path,
                value=scalar,
                value_type=value_type,  # type: ignore[arg-type]
                truth_state="asserted",
                context=context,
                provenance=provenance,
            )
        )

    graph = FactGraph(
        graph_id=graph_id,
        domain=domain,
        source_ref=source_ref,
        root_kind=root_kind,  # type: ignore[arg-type]
        containers=tuple(containers),
        facts=tuple(facts),
    )
    graph.reconstruct()
    if graph.structural_fingerprint() != _sha256_text(_canonical_json(graph.to_dict())):
        raise AssertionError("FactGraph structural fingerprint invariant failed")
    return graph


def canonical_json_bytes(graph: FactGraph) -> bytes:
    """Serialize one Typed FactGraph to canonical UTF-8 JSON bytes."""

    envelope = {
        "schema": "smc.fact_graph_serialization.v0.1",
        "profile": CANONICAL_JSON_PROFILE,
        "opaque_identity_policy": OPAQUE_IDENTITY_POLICY,
        "normalization": "none",
        "production_consumed": False,
        "graph_fingerprint": graph.structural_fingerprint(),
        "graph": graph.to_dict(),
    }
    return (_canonical_json(envelope) + "\n").encode("utf-8")


def load_canonical_json(payload: bytes | str) -> FactGraph:
    """Load exact canonical JSON and reject non-canonical or policy-changing bytes."""

    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid canonical JSON") from exc
    envelope = _require_exact_keys(
        decoded,
        {
            "schema",
            "profile",
            "opaque_identity_policy",
            "normalization",
            "production_consumed",
            "graph_fingerprint",
            "graph",
        },
        label="serialization envelope",
    )
    if envelope["schema"] != "smc.fact_graph_serialization.v0.1":
        raise ValueError("unsupported serialization envelope")
    if envelope["profile"] != CANONICAL_JSON_PROFILE:
        raise ValueError("unsupported JSON profile")
    if envelope["opaque_identity_policy"] != OPAQUE_IDENTITY_POLICY:
        raise ValueError("opaque identity policy mismatch")
    if envelope["normalization"] != "none" or envelope["production_consumed"] is not False:
        raise ValueError("serialization policy mismatch")
    graph = _fact_graph_from_dict(envelope["graph"])
    if envelope["graph_fingerprint"] != graph.structural_fingerprint():
        raise ValueError("graph fingerprint mismatch")
    if canonical_json_bytes(graph) != raw:
        raise ValueError("JSON bytes are not canonical")
    return graph


@dataclass(frozen=True, slots=True, order=True)
class _N3Statement:
    subject: str
    predicate: str
    object_token: str

    def render(self) -> str:
        return f"<{self.subject}> <{self.predicate}> {self.object_token} ."


def _entity_urn(kind: str, identity: str) -> str:
    return f"{_URN_BASE}{kind}:{_sha256_text(identity)}"


def _fact_urn(fact_id: str) -> str:
    return f"{_URN_BASE}fact:{fact_id}"


def _context_urn(fact_id: str) -> str:
    return f"{_URN_BASE}context:{fact_id}"


def _provenance_urn(fact_id: str) -> str:
    return f"{_URN_BASE}provenance:{fact_id}"


def _container_urn(graph_id: str, ordinal: int, path: FactPath) -> str:
    identity = _canonical_json({"graph_id": graph_id, "ordinal": ordinal, "path": _path_wire(path)})
    return _entity_urn("container", identity)


def _iri_object(iri: str) -> str:
    if not iri or any(char in iri for char in "<>\r\n"):
        raise ValueError("invalid generated IRI")
    return f"<{iri}>"


def _literal(lexical: str, datatype: str) -> str:
    return f"{json.dumps(lexical, ensure_ascii=False)}^^<{datatype}>"


def _string_literal(value: str) -> str:
    return _literal(value, _XSD_STRING)


def _boolean_literal(value: bool) -> str:
    return _literal("true" if value else "false", _XSD_BOOLEAN)


def _integer_literal(value: int) -> str:
    return _literal(str(value), _XSD_INTEGER)


def _double_literal(value: float) -> str:
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("non-finite float")
    return _literal(json.dumps(value, allow_nan=False), _XSD_DOUBLE)


def _path_literal(path: FactPath) -> str:
    return _literal(_canonical_json(_path_wire(path)), _JSON_PATH_DATATYPE)


def _scalar_object(value: JsonScalar) -> str:
    if value is None:
        return _iri_object(_NULL_IRI)
    if isinstance(value, bool):
        return _boolean_literal(value)
    if isinstance(value, int):
        return _integer_literal(value)
    if isinstance(value, float):
        return _double_literal(value)
    if isinstance(value, str):
        return _string_literal(value)
    raise TypeError(f"unsupported scalar type: {type(value).__name__}")


def _add_literal(
    rows: list[_N3Statement], subject: str, predicate: str, value: str | None
) -> None:
    if value is not None:
        rows.append(_N3Statement(subject, f"{_NS}{predicate}", _string_literal(value)))


def _n3_statements(graph: FactGraph) -> tuple[_N3Statement, ...]:
    graph_urn = _entity_urn("graph", graph.graph_id)
    rows: list[_N3Statement] = [
        _N3Statement(graph_urn, _RDF_TYPE, _iri_object(f"{_NS}TypedFactGraph")),
        _N3Statement(graph_urn, f"{_NS}serializationProfile", _string_literal(CANONICAL_N3_PROFILE)),
        _N3Statement(graph_urn, f"{_NS}namespaceVersion", _string_literal("v0.1")),
        _N3Statement(graph_urn, f"{_NS}schema", _string_literal(graph.schema)),
        _N3Statement(graph_urn, f"{_NS}graphId", _string_literal(graph.graph_id)),
        _N3Statement(graph_urn, f"{_NS}domain", _string_literal(graph.domain)),
        _N3Statement(graph_urn, f"{_NS}sourceRef", _string_literal(graph.source_ref)),
        _N3Statement(graph_urn, f"{_NS}rootKind", _string_literal(graph.root_kind)),
        _N3Statement(graph_urn, f"{_NS}authority", _string_literal(graph.authority)),
        _N3Statement(
            graph_urn,
            f"{_NS}productionConsumed",
            _boolean_literal(graph.production_consumed),
        ),
        _N3Statement(
            graph_urn,
            f"{_NS}opaqueIdentityPolicy",
            _string_literal(OPAQUE_IDENTITY_POLICY),
        ),
        _N3Statement(
            graph_urn,
            f"{_NS}graphFingerprint",
            _string_literal(graph.structural_fingerprint()),
        ),
    ]

    for ordinal, container in enumerate(graph.containers):
        container_urn = _container_urn(graph.graph_id, ordinal, container.path)
        rows.extend(
            [
                _N3Statement(graph_urn, f"{_NS}containsContainer", _iri_object(container_urn)),
                _N3Statement(container_urn, _RDF_TYPE, _iri_object(f"{_NS}ContainerShape")),
                _N3Statement(container_urn, f"{_NS}belongsToGraph", _iri_object(graph_urn)),
                _N3Statement(container_urn, f"{_NS}ordinal", _integer_literal(ordinal)),
                _N3Statement(container_urn, f"{_NS}path", _path_literal(container.path)),
                _N3Statement(
                    container_urn,
                    f"{_NS}containerKind",
                    _string_literal(container.kind),
                ),
            ]
        )

    for ordinal, fact in enumerate(graph.facts):
        fact_urn = _fact_urn(fact.fact_id)
        context_urn = _context_urn(fact.fact_id)
        provenance_urn = _provenance_urn(fact.fact_id)
        rows.extend(
            [
                _N3Statement(graph_urn, f"{_NS}containsFact", _iri_object(fact_urn)),
                _N3Statement(fact_urn, _RDF_TYPE, _iri_object(f"{_NS}SemanticFact")),
                _N3Statement(fact_urn, f"{_NS}belongsToGraph", _iri_object(graph_urn)),
                _N3Statement(fact_urn, f"{_NS}ordinal", _integer_literal(ordinal)),
                _N3Statement(fact_urn, f"{_NS}factId", _string_literal(fact.fact_id)),
                _N3Statement(fact_urn, f"{_NS}path", _path_literal(fact.path)),
                _N3Statement(fact_urn, f"{_NS}value", _scalar_object(fact.value)),
                _N3Statement(fact_urn, f"{_NS}valueType", _string_literal(fact.value_type)),
                _N3Statement(
                    fact_urn,
                    f"{_NS}truthState",
                    _string_literal(fact.truth_state),
                ),
                _N3Statement(fact_urn, f"{_NS}context", _iri_object(context_urn)),
                _N3Statement(fact_urn, f"{_NS}provenance", _iri_object(provenance_urn)),
                _N3Statement(context_urn, _RDF_TYPE, _iri_object(f"{_NS}FactContext")),
                _N3Statement(
                    context_urn,
                    f"{_NS}domain",
                    _string_literal(fact.context.domain),
                ),
                _N3Statement(
                    provenance_urn,
                    _RDF_TYPE,
                    _iri_object(f"{_NS}FactProvenance"),
                ),
                _N3Statement(
                    provenance_urn,
                    f"{_NS}kind",
                    _string_literal(fact.provenance.kind),
                ),
                _N3Statement(
                    provenance_urn,
                    f"{_NS}source",
                    _string_literal(fact.provenance.source),
                ),
            ]
        )
        _add_literal(rows, context_urn, "scopeRef", fact.context.scope_ref)
        _add_literal(rows, context_urn, "observedVersion", fact.context.observed_version)
        _add_literal(rows, context_urn, "snapshotId", fact.context.snapshot_id)
        _add_literal(rows, context_urn, "sensorContractRef", fact.context.sensor_contract_ref)
        _add_literal(rows, provenance_urn, "groundingRef", fact.provenance.grounding_ref)
        _add_literal(
            rows,
            provenance_urn,
            "observedVersion",
            fact.provenance.observed_version,
        )

    return tuple(sorted(rows))


def canonical_n3_bytes(graph: FactGraph) -> bytes:
    """Serialize one FactGraph to deterministic full-IRI N3/Turtle triples."""

    return ("\n".join(row.render() for row in _n3_statements(graph)) + "\n").encode("utf-8")


_TRIPLE_RE = re.compile(r"^<([^<>\r\n]+)> <([^<>\r\n]+)> (.+) \.$")
_TYPED_LITERAL_RE = re.compile(r'^("(?:[^"\\]|\\.)*")\^\^<([^<>\r\n]+)>$')


def _parse_n3(payload: bytes | str) -> tuple[_N3Statement, ...]:
    raw = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    if not raw.endswith("\n"):
        raise ValueError("canonical N3 must end with newline")
    rows: list[_N3Statement] = []
    for line in raw.splitlines():
        if not line:
            raise ValueError("blank lines are not canonical")
        match = _TRIPLE_RE.fullmatch(line)
        if match is None:
            raise ValueError(f"unsupported N3 statement: {line!r}")
        rows.append(_N3Statement(match.group(1), match.group(2), match.group(3)))
    if rows != sorted(rows) or len(set(rows)) != len(rows):
        raise ValueError("N3 statements must be unique and canonically sorted")
    return tuple(rows)


def _parse_object(token: str) -> tuple[ObjectKind, str, str | None]:
    if token.startswith("<") and token.endswith(">") and "<" not in token[1:-1]:
        return "iri", token[1:-1], None
    match = _TYPED_LITERAL_RE.fullmatch(token)
    if match is None:
        raise ValueError(f"unsupported canonical object token: {token!r}")
    try:
        lexical = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid literal lexical form") from exc
    if not isinstance(lexical, str):
        raise ValueError("typed literal lexical form must decode to a string")
    return "literal", lexical, match.group(2)


def _index_statements(
    statements: tuple[_N3Statement, ...],
) -> dict[str, dict[str, list[str]]]:
    index: dict[str, dict[str, list[str]]] = {}
    for row in statements:
        predicates = index.setdefault(row.subject, {})
        predicates.setdefault(row.predicate, []).append(row.object_token)
    return index


def _objects(index: dict[str, dict[str, list[str]]], subject: str, predicate: str) -> list[str]:
    return list(index.get(subject, {}).get(predicate, []))


def _one(index: dict[str, dict[str, list[str]]], subject: str, predicate: str) -> str:
    values = _objects(index, subject, predicate)
    if len(values) != 1:
        raise ValueError(f"expected one {predicate} for {subject}, got {len(values)}")
    return values[0]


def _as_iri(token: str, *, label: str) -> str:
    kind, lexical, datatype = _parse_object(token)
    if kind != "iri" or datatype is not None:
        raise ValueError(f"{label} must be an IRI")
    return lexical


def _as_literal(token: str, datatype: str, *, label: str) -> str:
    kind, lexical, actual_datatype = _parse_object(token)
    if kind != "literal" or actual_datatype != datatype:
        raise ValueError(f"{label} datatype mismatch")
    return lexical


def _as_string(token: str, *, label: str) -> str:
    return _as_literal(token, _XSD_STRING, label=label)


def _as_bool(token: str, *, label: str) -> bool:
    lexical = _as_literal(token, _XSD_BOOLEAN, label=label)
    if lexical == "true":
        return True
    if lexical == "false":
        return False
    raise ValueError(f"{label} invalid boolean lexical form")


def _as_int(token: str, *, label: str) -> int:
    lexical = _as_literal(token, _XSD_INTEGER, label=label)
    if not re.fullmatch(r"0|[1-9][0-9]*", lexical):
        raise ValueError(f"{label} invalid integer lexical form")
    return int(lexical)


def _as_path(token: str, *, label: str) -> FactPath:
    lexical = _as_literal(token, _JSON_PATH_DATATYPE, label=label)
    try:
        raw = json.loads(lexical)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} invalid path JSON") from exc
    if _canonical_json(raw) != lexical:
        raise ValueError(f"{label} path JSON is not canonical")
    return _decode_path(raw)


def _optional_n3_string(
    index: dict[str, dict[str, list[str]]], subject: str, predicate: str, *, label: str
) -> str | None:
    values = _objects(index, subject, predicate)
    if not values:
        return None
    if len(values) != 1:
        raise ValueError(f"{label} must occur at most once")
    return _as_string(values[0], label=label)


def _decode_scalar(token: str, value_type: str) -> JsonScalar:
    if value_type == "null":
        if _as_iri(token, label="fact.value") != _NULL_IRI:
            raise ValueError("null fact must use the canonical null IRI")
        return None
    if value_type == "boolean":
        return _as_bool(token, label="fact.value")
    if value_type == "integer":
        return _as_int(token, label="fact.value")
    if value_type == "number":
        lexical = _as_literal(token, _XSD_DOUBLE, label="fact.value")
        try:
            value = float(lexical)
        except ValueError as exc:
            raise ValueError("invalid number lexical form") from exc
        if json.dumps(value, allow_nan=False) != lexical:
            raise ValueError("number lexical form is not canonical JSON")
        return value
    if value_type == "string":
        return _as_string(token, label="fact.value")
    raise ValueError(f"unsupported value_type: {value_type!r}")


def load_canonical_n3(payload: bytes | str) -> FactGraph:
    """Load the exact P1-B restricted N3 surface and reconstruct the Typed FactGraph."""

    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    statements = _parse_n3(raw)
    index = _index_statements(statements)
    graph_type = _iri_object(f"{_NS}TypedFactGraph")
    graph_subjects = [
        row.subject
        for row in statements
        if row.predicate == _RDF_TYPE and row.object_token == graph_type
    ]
    if len(graph_subjects) != 1:
        raise ValueError("canonical N3 must contain exactly one TypedFactGraph")
    graph_urn = graph_subjects[0]

    profile = _as_string(
        _one(index, graph_urn, f"{_NS}serializationProfile"), label="serializationProfile"
    )
    namespace_version = _as_string(
        _one(index, graph_urn, f"{_NS}namespaceVersion"), label="namespaceVersion"
    )
    opaque_policy = _as_string(
        _one(index, graph_urn, f"{_NS}opaqueIdentityPolicy"), label="opaqueIdentityPolicy"
    )
    if profile != CANONICAL_N3_PROFILE or namespace_version != "v0.1":
        raise ValueError("unsupported N3 serialization profile")
    if opaque_policy != OPAQUE_IDENTITY_POLICY:
        raise ValueError("opaque identity policy mismatch")

    schema = _as_string(_one(index, graph_urn, f"{_NS}schema"), label="schema")
    graph_id = _as_string(_one(index, graph_urn, f"{_NS}graphId"), label="graphId")
    domain = _as_string(_one(index, graph_urn, f"{_NS}domain"), label="domain")
    source_ref = _as_string(_one(index, graph_urn, f"{_NS}sourceRef"), label="sourceRef")
    root_kind = _as_string(_one(index, graph_urn, f"{_NS}rootKind"), label="rootKind")
    authority = _as_string(_one(index, graph_urn, f"{_NS}authority"), label="authority")
    production_consumed = _as_bool(
        _one(index, graph_urn, f"{_NS}productionConsumed"), label="productionConsumed"
    )
    fingerprint = _as_string(
        _one(index, graph_urn, f"{_NS}graphFingerprint"), label="graphFingerprint"
    )
    if schema != _IR_SCHEMA or authority != "shadow_only" or production_consumed is not False:
        raise ValueError("N3 graph authority/schema mismatch")
    if root_kind not in {"object", "array", "scalar"}:
        raise ValueError("invalid rootKind")
    if graph_urn != _entity_urn("graph", graph_id):
        raise ValueError("graph IRI integrity mismatch")

    containers_by_ordinal: dict[int, ContainerShape] = {}
    for token in _objects(index, graph_urn, f"{_NS}containsContainer"):
        subject = _as_iri(token, label="containsContainer")
        if _as_iri(_one(index, subject, _RDF_TYPE), label="container type") != f"{_NS}ContainerShape":
            raise ValueError("invalid ContainerShape type")
        if _as_iri(_one(index, subject, f"{_NS}belongsToGraph"), label="container graph") != graph_urn:
            raise ValueError("container graph mismatch")
        ordinal = _as_int(_one(index, subject, f"{_NS}ordinal"), label="container ordinal")
        path = _as_path(_one(index, subject, f"{_NS}path"), label="container path")
        kind = _as_string(_one(index, subject, f"{_NS}containerKind"), label="containerKind")
        if kind not in {"object", "array"}:
            raise ValueError("invalid containerKind")
        if subject != _container_urn(graph_id, ordinal, path):
            raise ValueError("container IRI integrity mismatch")
        if ordinal in containers_by_ordinal:
            raise ValueError("duplicate container ordinal")
        containers_by_ordinal[ordinal] = ContainerShape(path=path, kind=kind)  # type: ignore[arg-type]
    if set(containers_by_ordinal) != set(range(len(containers_by_ordinal))):
        raise ValueError("container ordinals must be contiguous")
    containers = tuple(containers_by_ordinal[i] for i in range(len(containers_by_ordinal)))

    facts_by_ordinal: dict[int, SemanticFact] = {}
    for token in _objects(index, graph_urn, f"{_NS}containsFact"):
        subject = _as_iri(token, label="containsFact")
        if _as_iri(_one(index, subject, _RDF_TYPE), label="fact type") != f"{_NS}SemanticFact":
            raise ValueError("invalid SemanticFact type")
        if _as_iri(_one(index, subject, f"{_NS}belongsToGraph"), label="fact graph") != graph_urn:
            raise ValueError("fact graph mismatch")
        ordinal = _as_int(_one(index, subject, f"{_NS}ordinal"), label="fact ordinal")
        fact_id = _as_string(_one(index, subject, f"{_NS}factId"), label="factId")
        if subject != _fact_urn(fact_id):
            raise ValueError("fact IRI integrity mismatch")
        path = _as_path(_one(index, subject, f"{_NS}path"), label="fact path")
        value_type = _as_string(_one(index, subject, f"{_NS}valueType"), label="valueType")
        value = _decode_scalar(_one(index, subject, f"{_NS}value"), value_type)
        truth_state = _as_string(_one(index, subject, f"{_NS}truthState"), label="truthState")
        if truth_state != "asserted":
            raise ValueError("unsupported truthState")

        context_urn = _as_iri(_one(index, subject, f"{_NS}context"), label="context")
        provenance_urn = _as_iri(_one(index, subject, f"{_NS}provenance"), label="provenance")
        if context_urn != _context_urn(fact_id) or provenance_urn != _provenance_urn(fact_id):
            raise ValueError("context/provenance IRI integrity mismatch")
        if _as_iri(_one(index, context_urn, _RDF_TYPE), label="context type") != f"{_NS}FactContext":
            raise ValueError("invalid FactContext type")
        if _as_iri(_one(index, provenance_urn, _RDF_TYPE), label="provenance type") != f"{_NS}FactProvenance":
            raise ValueError("invalid FactProvenance type")

        context = FactContext(
            domain=_as_string(_one(index, context_urn, f"{_NS}domain"), label="context domain"),
            scope_ref=_optional_n3_string(
                index, context_urn, f"{_NS}scopeRef", label="context scopeRef"
            ),
            observed_version=_optional_n3_string(
                index,
                context_urn,
                f"{_NS}observedVersion",
                label="context observedVersion",
            ),
            snapshot_id=_optional_n3_string(
                index, context_urn, f"{_NS}snapshotId", label="context snapshotId"
            ),
            sensor_contract_ref=_optional_n3_string(
                index,
                context_urn,
                f"{_NS}sensorContractRef",
                label="context sensorContractRef",
            ),
        )
        kind = _as_string(_one(index, provenance_urn, f"{_NS}kind"), label="provenance kind")
        if kind != "oracle_projection":
            raise ValueError("unsupported provenance kind")
        provenance = FactProvenance(
            kind="oracle_projection",
            source=_as_string(
                _one(index, provenance_urn, f"{_NS}source"), label="provenance source"
            ),
            grounding_ref=_optional_n3_string(
                index,
                provenance_urn,
                f"{_NS}groundingRef",
                label="provenance groundingRef",
            ),
            observed_version=_optional_n3_string(
                index,
                provenance_urn,
                f"{_NS}observedVersion",
                label="provenance observedVersion",
            ),
        )
        if context.observed_version != provenance.observed_version:
            raise ValueError("context/provenance observedVersion mismatch")
        if ordinal in facts_by_ordinal:
            raise ValueError("duplicate fact ordinal")
        facts_by_ordinal[ordinal] = SemanticFact(
            fact_id=fact_id,
            path=path,
            value=value,
            value_type=value_type,  # type: ignore[arg-type]
            truth_state="asserted",
            context=context,
            provenance=provenance,
        )
    if set(facts_by_ordinal) != set(range(len(facts_by_ordinal))):
        raise ValueError("fact ordinals must be contiguous")
    facts = tuple(facts_by_ordinal[i] for i in range(len(facts_by_ordinal)))

    graph = FactGraph(
        graph_id=graph_id,
        domain=domain,
        source_ref=source_ref,
        root_kind=root_kind,  # type: ignore[arg-type]
        containers=containers,
        facts=facts,
    )
    # Reuse the canonical JSON decoder as an independent structural/integrity check.
    graph = load_canonical_json(canonical_json_bytes(graph))
    if graph.structural_fingerprint() != fingerprint:
        raise ValueError("graph fingerprint mismatch")
    if canonical_n3_bytes(graph) != raw:
        raise ValueError("N3 bytes are not canonical")
    return graph
