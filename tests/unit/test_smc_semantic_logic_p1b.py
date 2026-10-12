from __future__ import annotations

import ast
import json
import runpy
from pathlib import Path
from typing import Any

import pytest

from llm_loop.semantic_logic import (
    CANONICAL_JSON_PROFILE,
    CANONICAL_N3_PROFILE,
    OPAQUE_IDENTITY_POLICY,
    FactGraph,
    canonical_json_bytes,
    canonical_n3_bytes,
    load_canonical_json,
    load_canonical_n3,
    project_document,
)

ROOT = Path(__file__).resolve().parents[2]
P1A = runpy.run_path(str(ROOT / "tests/unit/test_smc_semantic_logic_p1a.py"))
CASE_BUILDERS = P1A["CASE_BUILDERS"]
MANIFEST = P1A["MANIFEST"]


def _manifest_cases() -> list[tuple[str, str]]:
    return [
        (str(gate["gate_id"]), str(case["fixture_id"]))
        for gate in MANIFEST["gates"]
        for case in gate["cases"]
    ]


def _case_graph(tmp_path: Path, gate_id: str, fixture_id: str) -> tuple[dict[str, Any], FactGraph]:
    canonical = CASE_BUILDERS[fixture_id](tmp_path / fixture_id)
    graph = project_document(
        graph_id=fixture_id,
        document=canonical,
        domain="browser",
        source_ref=f"python_oracle:{gate_id}:{fixture_id}",
    )
    return canonical, graph


def test_p1b_reuses_exact_p1a_frozen_case_set() -> None:
    frozen = _manifest_cases()
    assert len(frozen) == 15
    assert len({fixture_id for _, fixture_id in frozen}) == 15
    assert set(CASE_BUILDERS) == {fixture_id for _, fixture_id in frozen}


@pytest.mark.parametrize(("gate_id", "fixture_id"), _manifest_cases())
def test_all_15_frozen_cases_round_trip_through_canonical_json_and_n3(
    tmp_path: Path, gate_id: str, fixture_id: str
) -> None:
    canonical, graph = _case_graph(tmp_path, gate_id, fixture_id)

    json_wire = canonical_json_bytes(graph)
    assert json_wire == canonical_json_bytes(graph)
    from_json = load_canonical_json(json_wire)
    assert from_json == graph
    assert from_json.reconstruct() == canonical
    assert canonical_json_bytes(from_json) == json_wire

    n3_wire = canonical_n3_bytes(graph)
    assert n3_wire == canonical_n3_bytes(graph)
    from_n3 = load_canonical_n3(n3_wire)
    assert from_n3 == graph
    assert from_n3.reconstruct() == canonical
    assert canonical_n3_bytes(from_n3) == n3_wire

    # Cross-format round-trip must preserve the exact Typed IR, including opaque
    # runtime identity strings.  P1-B performs no identity normalization.
    assert load_canonical_json(canonical_json_bytes(from_n3)) == from_json


def test_json_envelope_is_closed_versioned_and_explicit_about_opaque_identity_policy() -> None:
    graph = project_document(
        graph_id="json-envelope",
        document={"grounding_ref": "grounding://opaque/exact", "unknown": None},
        domain="browser",
        source_ref="python_oracle:test",
    )
    payload = canonical_json_bytes(graph)
    decoded = json.loads(payload)

    assert set(decoded) == {
        "schema",
        "profile",
        "opaque_identity_policy",
        "normalization",
        "production_consumed",
        "graph_fingerprint",
        "graph",
    }
    assert decoded["profile"] == CANONICAL_JSON_PROFILE
    assert decoded["opaque_identity_policy"] == OPAQUE_IDENTITY_POLICY
    assert decoded["normalization"] == "none"
    assert decoded["production_consumed"] is False
    assert b"grounding://opaque/exact" in payload


def test_n3_surface_uses_full_stable_iris_no_blank_nodes_and_explicit_policy(tmp_path: Path) -> None:
    _, graph = _case_graph(tmp_path, "S2", "S2-dom-ax-field-conflict")
    payload = canonical_n3_bytes(graph)
    text = payload.decode("utf-8")

    assert "_:" not in text
    assert "@prefix" not in text
    assert CANONICAL_N3_PROFILE in text
    assert OPAQUE_IDENTITY_POLICY in text
    assert "urn:smc:semantic-logic:v0.1#TypedFactGraph" in text
    assert "urn:smc:semantic-logic:v0.1#SemanticFact" in text
    assert "urn:smc:semantic-logic:v0.1#FactContext" in text
    assert "urn:smc:semantic-logic:v0.1#FactProvenance" in text
    assert "urn:smc:semantic-logic:v0.1#ContainerShape" in text
    assert all(line.startswith("<") and line.endswith(" .") for line in text.splitlines())
    assert text.splitlines() == sorted(text.splitlines())


def test_n3_keeps_conflict_unknown_source_context_and_provenance_explicit(tmp_path: Path) -> None:
    conflict_canonical, conflict_graph = _case_graph(
        tmp_path / "conflict", "S2", "S2-dom-ax-field-conflict"
    )
    unknown_canonical, unknown_graph = _case_graph(
        tmp_path / "unknown", "S3", "S3-unknown-or-unstable-identity"
    )
    conflict_wire = canonical_n3_bytes(conflict_graph)
    unknown_wire = canonical_n3_bytes(unknown_graph)

    assert load_canonical_n3(conflict_wire).reconstruct() == conflict_canonical
    assert load_canonical_n3(unknown_wire).reconstruct() == unknown_canonical
    conflict_text = conflict_wire.decode("utf-8")
    unknown_text = unknown_wire.decode("utf-8")

    # The canonical null is explicit and source-qualified DOM/AX observations remain
    # distinct leaves with provenance rather than being silently prioritized.
    assert "urn:smc:semantic-logic:v0.1#null" in conflict_text
    assert '"dom"^^<http://www.w3.org/2001/XMLSchema#string>' in conflict_text
    assert '"ax"^^<http://www.w3.org/2001/XMLSchema#string>' in conflict_text
    assert "#groundingRef>" in conflict_text
    assert "#observedVersion>" in conflict_text
    assert '"indeterminate"^^<http://www.w3.org/2001/XMLSchema#string>' in unknown_text


def test_observation_and_projection_completeness_paths_remain_distinct() -> None:
    canonical = {
        "snapshot": {
            "completeness": {"complete": True, "reasons": []},
            "projection": {"complete": False, "reasons": ["projection_limit"]},
        }
    }
    graph = project_document(
        graph_id="completeness-separation",
        document=canonical,
        domain="browser",
        source_ref="python_oracle:test",
    )
    wire = canonical_n3_bytes(graph).decode("utf-8")
    loaded = load_canonical_n3(wire)

    assert loaded.reconstruct() == canonical
    complete_paths = [fact.path for fact in loaded.facts if fact.path[-1:] == ("complete",)]
    assert ("snapshot", "completeness", "complete") in complete_paths
    assert ("snapshot", "projection", "complete") in complete_paths


def test_all_json_scalar_types_have_unambiguous_n3_round_trip() -> None:
    canonical = {
        "null": None,
        "bool_false": False,
        "bool_true": True,
        "integer": 7,
        "number": 1.25,
        "string": "x\nquote=\" unicode=语义",
        "empty_object": {},
        "empty_array": [],
    }
    graph = project_document(
        graph_id="scalar-shape-probe",
        document=canonical,
        domain="test",
        source_ref="python_oracle:test",
    )

    assert load_canonical_n3(canonical_n3_bytes(graph)) == graph
    assert load_canonical_json(canonical_json_bytes(graph)) == graph
    assert load_canonical_n3(canonical_n3_bytes(graph)).reconstruct() == canonical


def test_canonical_json_rejects_pretty_or_policy_mutated_payload() -> None:
    graph = project_document(
        graph_id="strict-json",
        document={"value": 1},
        domain="test",
        source_ref="python_oracle:test",
    )
    canonical = canonical_json_bytes(graph)
    decoded = json.loads(canonical)

    pretty = (json.dumps(decoded, ensure_ascii=False, indent=2) + "\n").encode()
    with pytest.raises(ValueError, match="not canonical"):
        load_canonical_json(pretty)

    decoded["opaque_identity_policy"] = "normalize_opaque_ids"
    mutated = (
        json.dumps(decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    with pytest.raises(ValueError, match="opaque identity policy"):
        load_canonical_json(mutated)


def test_canonical_n3_rejects_unsorted_duplicate_or_policy_mutated_statements() -> None:
    graph = project_document(
        graph_id="strict-n3",
        document={"value": 1, "grounding_ref": "grounding://opaque/exact"},
        domain="test",
        source_ref="python_oracle:test",
    )
    canonical = canonical_n3_bytes(graph)
    lines = canonical.decode().splitlines()

    with pytest.raises(ValueError, match="canonically sorted"):
        load_canonical_n3(("\n".join(reversed(lines)) + "\n").encode())
    with pytest.raises(ValueError, match="unique"):
        load_canonical_n3(("\n".join(sorted([*lines, lines[0]])) + "\n").encode())

    policy_line = next(line for line in lines if "#opaqueIdentityPolicy>" in line)
    mutated_line = policy_line.replace(OPAQUE_IDENTITY_POLICY, "normalize_opaque_ids")
    mutated = "\n".join(sorted(mutated_line if line == policy_line else line for line in lines)) + "\n"
    with pytest.raises(ValueError, match="opaque identity policy"):
        load_canonical_n3(mutated)


def test_n3_loader_rejects_blank_node_surface() -> None:
    with pytest.raises(ValueError, match="unsupported N3 statement"):
        load_canonical_n3('_:x <urn:test:p> "v"^^<http://www.w3.org/2001/XMLSchema#string> .\n')


def test_p1b_serialization_has_no_reasoner_network_or_process_dependency() -> None:
    source = (ROOT / "src/llm_loop/semantic_logic/serialization.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert not imported_roots.intersection(
        {"rdflib", "requests", "httpx", "socket", "subprocess", "eye", "swipl"}
    )
    assert "http://www.w3.org" in source  # datatype vocabulary only, never fetched


def test_p1b_does_not_add_a_production_consumer() -> None:
    semantic_root = (ROOT / "src/llm_loop/semantic_logic").resolve()
    offenders: list[str] = []
    for path in (ROOT / "src/llm_loop").rglob("*.py"):
        if semantic_root in path.resolve().parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and str(node.module or "").startswith(
                "llm_loop.semantic_logic"
            ):
                offenders.append(str(path.relative_to(ROOT)))
            elif isinstance(node, ast.Import):
                offenders.extend(
                    str(path.relative_to(ROOT))
                    for alias in node.names
                    if alias.name.startswith("llm_loop.semantic_logic")
                )
    assert offenders == []
