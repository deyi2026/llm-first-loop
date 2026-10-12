"""Qualification-only three-plane comparison for SMC Semantic Logic P1-D.

Plane A traverses the frozen Python oracle document directly. Plane B reads the Typed
FactGraph representation directly. Plane C invokes pinned restricted EYE and consumes
relations parsed independently from actual EYE output by the JS qualification bridge.

This module is outside ``src/llm_loop`` and has no production consumer or authority.
"""

from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.semantic_logic import FactGraph, canonical_n3_bytes, load_canonical_n3

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_ROOT = ROOT / "tools/semantic_logic/n3_validator"
P1D_BRIDGE = VALIDATOR_ROOT / "p1d_bridge.mjs"
PACKAGE_LOCK = VALIDATOR_ROOT / "package-lock.json"
NODE_MODULES = VALIDATOR_ROOT / "node_modules"
P1C_HARNESS = runpy.run_path(str(VALIDATOR_ROOT / "harness.py"))
SEATBELT_PROFILE = str(P1C_HARNESS["SEATBELT_PROFILE"])
VERIFY_BACKEND_IDENTITY = P1C_HARNESS["verify_backend_identity"]
BRIDGE_SCHEMA = "smc.p1d_eye_bridge_receipt.v0.1"
PINNED_N3_PARSER_VERSION = "2.7.12"
PINNED_N3_PARSER_INTEGRITY = (
    "sha512-Hy6dfGg9yniLQpSBirvH2E2yO3EG7dSmA3aefRbtO411oqtzG8roD3h1kTc/N065bivCOPfTFIjf0KlwW7KlnQ=="
)

FROZEN_SENTINEL_EXPECTED_HITS: dict[str, frozenset[str]] = {
    "S2-dom-ax-field-conflict": frozenset({"S2-conflict-canonical-null"}),
    "S3-absence-complete-vs-partial": frozenset(
        {
            "S3-partial-indeterminate",
            "S3-complete-false-absence",
            "S3-complete-satisfied",
        }
    ),
    "S4-document-generation-change": frozenset({"S4-document-change-stale"}),
    "S5-duplicate-action-id": frozenset({"S5-single-dispatch", "S5-no-auto-retry"}),
}

type JsonScalar = None | bool | int | float | str
type PathSegment = str | int
type FactPath = tuple[PathSegment, ...]
type RelationSet = frozenset[str]


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _path_key(path: FactPath) -> str:
    return _canonical(
        [
            {"kind": "index", "value": segment}
            if isinstance(segment, int)
            else {"kind": "key", "value": segment}
            for segment in path
        ]
    )


def _relation(*parts: Any) -> str:
    return _canonical(list(parts))


def _value_type(value: JsonScalar) -> str:
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


def _relation_value(value: JsonScalar, value_type: str) -> JsonScalar:
    """Normalize only number lexical form while retaining explicit value_type.

    EYE may render an xsd:double 1060.0 as the mathematically equivalent 1060.
    The relation set therefore compares the number's semantic value, while the
    separate ``value_type`` field continues to distinguish JSON number from integer.
    """

    if value_type == "number":
        if not isinstance(value, float):
            raise TypeError("number relation requires Python float")
        text = str(value)
        if text.endswith(".0"):
            text = text[:-2]
        return text
    return value


@dataclass(frozen=True, slots=True)
class _Meta:
    source: str
    domain: str
    grounding_ref: str | None = None
    observed_version: str | None = None
    scope_ref: str | None = None
    snapshot_id: str | None = None
    sensor_contract_ref: str | None = None


def _string_field(value: dict[str, Any], key: str) -> str | None:
    candidate = value.get(key)
    return candidate if isinstance(candidate, str) and candidate else None


def _inherit(meta: _Meta, value: dict[str, Any]) -> _Meta:
    snapshot_id = _string_field(value, "snapshot_id")
    return _Meta(
        source=_string_field(value, "source") or meta.source,
        domain=_string_field(value, "domain") or meta.domain,
        grounding_ref=_string_field(value, "grounding_ref") or meta.grounding_ref,
        observed_version=(
            _string_field(value, "observed_version") or snapshot_id or meta.observed_version
        ),
        scope_ref=_string_field(value, "scope_ref") or meta.scope_ref,
        snapshot_id=snapshot_id or meta.snapshot_id,
        sensor_contract_ref=(
            _string_field(value, "sensor_contract_ref") or meta.sensor_contract_ref
        ),
    )


def relations_from_python_oracle(
    document: Any, *, graph_id: str, domain: str, source_ref: str
) -> RelationSet:
    """Plane A: derive relations directly from frozen Python canonical JSON."""

    rows: set[str] = {
        _relation("graph", "graph_id", graph_id),
        _relation("graph", "domain", domain),
        _relation("graph", "source_ref", source_ref),
        _relation("graph", "authority", "shadow_only"),
        _relation("graph", "production_consumed", False),
    }
    if isinstance(document, dict):
        root_kind = "object"
    elif isinstance(document, list):
        root_kind = "array"
    else:
        root_kind = "scalar"
    rows.add(_relation("graph", "root_kind", root_kind))
    initial = _Meta(source=source_ref, domain=domain)

    def walk(value: Any, path: FactPath, meta: _Meta) -> None:
        if isinstance(value, dict):
            rows.add(_relation("container", _path_key(path), "object"))
            next_meta = _inherit(meta, value)
            for key in sorted(value):
                walk(value[key], (*path, key), next_meta)
            return
        if isinstance(value, list):
            rows.add(_relation("container", _path_key(path), "array"))
            for index, child in enumerate(value):
                walk(child, (*path, index), meta)
            return
        if not (value is None or isinstance(value, (bool, int, float, str))):
            raise TypeError(f"non-JSON leaf at {path!r}")
        key = _path_key(path)
        value_type = _value_type(value)
        rows.add(_relation("fact", key, value_type, _relation_value(value, value_type)))
        rows.add(_relation("truth_state", key, "asserted"))
        for field, field_value in (
            ("domain", meta.domain),
            ("scope_ref", meta.scope_ref),
            ("observed_version", meta.observed_version),
            ("snapshot_id", meta.snapshot_id),
            ("sensor_contract_ref", meta.sensor_contract_ref),
        ):
            rows.add(_relation("context", key, field, field_value))
        for field, field_value in (
            ("kind", "oracle_projection"),
            ("source", meta.source),
            ("grounding_ref", meta.grounding_ref),
            ("observed_version", meta.observed_version),
        ):
            rows.add(_relation("provenance", key, field, field_value))

    walk(document, (), initial)
    return frozenset(rows)


def relations_from_typed_ir(graph: FactGraph) -> RelationSet:
    """Plane B: derive relations from Typed FactGraph fields without reconstruction."""

    rows: set[str] = {
        _relation("graph", "graph_id", graph.graph_id),
        _relation("graph", "domain", graph.domain),
        _relation("graph", "source_ref", graph.source_ref),
        _relation("graph", "root_kind", graph.root_kind),
        _relation("graph", "authority", graph.authority),
        _relation("graph", "production_consumed", graph.production_consumed),
    }
    for container in graph.containers:
        rows.add(_relation("container", _path_key(container.path), container.kind))
    for fact in graph.facts:
        key = _path_key(fact.path)
        rows.add(
            _relation(
                "fact",
                key,
                fact.value_type,
                _relation_value(fact.value, fact.value_type),
            )
        )
        rows.add(_relation("truth_state", key, fact.truth_state))
        for field, field_value in (
            ("domain", fact.context.domain),
            ("scope_ref", fact.context.scope_ref),
            ("observed_version", fact.context.observed_version),
            ("snapshot_id", fact.context.snapshot_id),
            ("sensor_contract_ref", fact.context.sensor_contract_ref),
        ):
            rows.add(_relation("context", key, field, field_value))
        for field, field_value in (
            ("kind", fact.provenance.kind),
            ("source", fact.provenance.source),
            ("grounding_ref", fact.provenance.grounding_ref),
            ("observed_version", fact.provenance.observed_version),
        ):
            rows.add(_relation("provenance", key, field, field_value))
    return frozenset(rows)


def _sanitized_env(home: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
        "HOME": str(home),
        "TMPDIR": str(home),
        "LC_ALL": "C",
        "LANG": "C",
        "NODE_NO_WARNINGS": "1",
    }


def verify_p1d_parser_identity() -> dict[str, str]:
    """Pin the JS parser used on actual EYE output."""

    try:
        lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("p1d_package_lock_invalid") from exc
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise ValueError("p1d_package_lock_packages_missing")
    locked = packages.get("node_modules/n3")
    if not isinstance(locked, dict):
        raise ValueError("p1d_n3_parser_lock_missing")
    if locked.get("version") != PINNED_N3_PARSER_VERSION:
        raise ValueError("p1d_n3_parser_lock_version_mismatch")
    if locked.get("integrity") != PINNED_N3_PARSER_INTEGRITY:
        raise ValueError("p1d_n3_parser_lock_integrity_mismatch")

    installed_path = NODE_MODULES / "n3" / "package.json"
    try:
        installed = json.loads(installed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("p1d_n3_parser_not_installed") from exc
    if not isinstance(installed, dict) or installed.get("version") != PINNED_N3_PARSER_VERSION:
        raise ValueError("p1d_n3_parser_installed_version_mismatch")
    return {
        "package": "n3",
        "version": PINNED_N3_PARSER_VERSION,
        "integrity": PINNED_N3_PARSER_INTEGRITY,
    }


def _run_bridge(payload: bytes, *, fixture_ref: str, mode: str) -> dict[str, Any]:
    """Run fixed P1-D bridge under the already-qualified P1-C sandbox."""

    if mode not in {"relations", "sentinels"}:
        raise ValueError("unsupported_p1d_mode")
    load_canonical_n3(payload)  # strict P1-B byte/policy preflight before JS/EYE
    VERIFY_BACKEND_IDENTITY()
    verify_p1d_parser_identity()
    node = shutil.which("node")
    sandbox = shutil.which("sandbox-exec")
    if not node or not sandbox or not P1D_BRIDGE.is_file():
        raise ValueError("p1d_backend_unavailable")
    request = {
        "mode": mode,
        "n3": payload.decode("utf-8"),
        "fixture_ref": fixture_ref,
        "answer_cap": 4096,
    }
    request_bytes = (_canonical(request) + "\n").encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="smc-p1d-") as raw_home:
        home = Path(raw_home)
        proc = subprocess.run(
            [sandbox, "-p", SEATBELT_PROFILE, node, str(P1D_BRIDGE)],
            input=request_bytes,
            capture_output=True,
            check=False,
            timeout=20,
            cwd=VALIDATOR_ROOT,
            env=_sanitized_env(home),
        )
    if proc.stderr:
        raise ValueError(f"p1d_bridge_stderr:{proc.stderr[:256]!r}")
    try:
        receipt = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("p1d_bridge_invalid_receipt") from exc
    if proc.returncode != 0 or not isinstance(receipt, dict) or receipt.get("ok") is not True:
        raise ValueError(f"p1d_bridge_failed:{receipt}")
    if receipt.get("schema") != BRIDGE_SCHEMA or receipt.get("mode") != mode:
        raise ValueError("p1d_bridge_schema_or_mode_mismatch")
    if receipt.get("fixture_ref") != fixture_ref:
        raise ValueError("p1d_bridge_fixture_mismatch")
    return receipt


def relations_from_eye(payload: bytes, *, fixture_ref: str) -> RelationSet:
    """Plane C: relations independently parsed from actual restricted EYE output."""

    receipt = _run_bridge(payload, fixture_ref=fixture_ref, mode="relations")
    rows = receipt.get("relations")
    if not isinstance(rows, list) or not all(isinstance(row, str) for row in rows):
        raise ValueError("p1d_relation_receipt_invalid")
    if rows != sorted(set(rows)):
        raise ValueError("p1d_relations_not_canonical")
    return frozenset(rows)


def sentinel_result(payload: bytes, *, fixture_ref: str) -> dict[str, Any]:
    receipt = _run_bridge(payload, fixture_ref=fixture_ref, mode="sentinels")
    hits = receipt.get("hits")
    if not isinstance(hits, list) or not all(isinstance(value, str) for value in hits):
        raise ValueError("p1d_sentinel_hits_invalid")
    expected = FROZEN_SENTINEL_EXPECTED_HITS.get(fixture_ref)
    if expected is None:
        raise ValueError("fixture_has_no_independent_sentinel_expectation")
    expected_hit_ids = sorted(expected)
    if sorted(hits) != expected_hit_ids:
        raise ValueError(
            f"p1d_sentinel_mismatch:expected={expected_hit_ids!r}:observed={sorted(hits)!r}"
        )
    return {
        "fixture_ref": fixture_ref,
        "hits": sorted(hits),
        "expected_hits": expected_hit_ids,
        "expectation_source": "independent_python_frozen_oracle",
    }


def _fact_values(relations: RelationSet) -> dict[str, tuple[str, JsonScalar]]:
    result: dict[str, tuple[str, JsonScalar]] = {}
    for row in relations:
        decoded = json.loads(row)
        if isinstance(decoded, list) and len(decoded) == 4 and decoded[0] == "fact":
            result[str(decoded[1])] = (str(decoded[2]), decoded[3])
    return result


def qualify_case(
    *,
    fixture_id: str,
    canonical_document: Any,
    typed_graph: FactGraph,
) -> dict[str, Any]:
    """Compare all three planes and return mechanical P1-D qualification metrics."""

    plane_a = relations_from_python_oracle(
        canonical_document,
        graph_id=typed_graph.graph_id,
        domain=typed_graph.domain,
        source_ref=typed_graph.source_ref,
    )
    plane_b = relations_from_typed_ir(typed_graph)
    wire = canonical_n3_bytes(typed_graph)
    plane_c = relations_from_eye(wire, fixture_ref=fixture_id)

    added_b = plane_b - plane_a
    missing_b = plane_a - plane_b
    added_c = plane_c - plane_a
    missing_c = plane_a - plane_c
    a_facts = _fact_values(plane_a)
    c_facts = _fact_values(plane_c)
    unknown_to_false = sum(
        1
        for path, (_, value) in a_facts.items()
        if value is None and c_facts.get(path) == ("boolean", False)
    )
    provenance_a = {row for row in plane_a if json.loads(row)[0] == "provenance"}
    provenance_c = {row for row in plane_c if json.loads(row)[0] == "provenance"}
    context_a = {row for row in plane_a if json.loads(row)[0] == "context"}
    context_c = {row for row in plane_c if json.loads(row)[0] == "context"}

    return {
        "fixture_id": fixture_id,
        "plane_a_relation_count": len(plane_a),
        "plane_b_relation_count": len(plane_b),
        "plane_c_relation_count": len(plane_c),
        "a_equals_b": plane_a == plane_b,
        "a_equals_c": plane_a == plane_c,
        "b_equals_c": plane_b == plane_c,
        "plane_b_added": len(added_b),
        "plane_b_missing": len(missing_b),
        "false_closure": len(added_c),
        "plane_c_missing": len(missing_c),
        "unknown_to_false_collapse": unknown_to_false,
        "source_or_provenance_loss": len(provenance_a - provenance_c),
        "context_or_version_loss": len(context_a - context_c),
        "relation_equivalent": plane_a == plane_b == plane_c,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="SMC P1-D qualification helper")
    parser.add_argument("--fixture-ref", required=True)
    parser.add_argument("--mode", choices=("relations", "sentinels"), required=True)
    args = parser.parse_args()
    payload = os.read(0, 2_200_000)
    if args.mode == "relations":
        relations = relations_from_eye(payload, fixture_ref=args.fixture_ref)
        print(json.dumps(sorted(relations), ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(sentinel_result(payload, fixture_ref=args.fixture_ref), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
