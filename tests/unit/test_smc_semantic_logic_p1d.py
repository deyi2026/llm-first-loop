from __future__ import annotations

import ast
import runpy
from pathlib import Path

import pytest

from llm_loop.semantic_logic import canonical_n3_bytes, project_document

ROOT = Path(__file__).resolve().parents[2]
P1A = runpy.run_path(str(ROOT / "tests/unit/test_smc_semantic_logic_p1a.py"))
P1D = runpy.run_path(str(ROOT / "tools/semantic_logic/p1d_qualification.py"))
CASE_BUILDERS = P1A["CASE_BUILDERS"]
MANIFEST = P1A["MANIFEST"]
qualify_case = P1D["qualify_case"]
sentinel_result = P1D["sentinel_result"]
verify_p1d_parser_identity = P1D["verify_p1d_parser_identity"]

BACKEND_READY = P1D["P1C_HARNESS"]["backend_installation_available"]()
LIVE_BACKEND = pytest.mark.skipif(
    not BACKEND_READY,
    reason="qualification-only pinned N3 backend is not installed in this checkout",
)


def _manifest_cases() -> list[tuple[str, str]]:
    return [
        (str(gate["gate_id"]), str(case["fixture_id"]))
        for gate in MANIFEST["gates"]
        for case in gate["cases"]
    ]


def _case(tmp_path: Path, gate_id: str, fixture_id: str):
    canonical = CASE_BUILDERS[fixture_id](tmp_path / fixture_id)
    graph = project_document(
        graph_id=fixture_id,
        document=canonical,
        domain="browser",
        source_ref=f"python_oracle:{gate_id}:{fixture_id}",
    )
    return canonical, graph


def test_p1d_reuses_exact_frozen_15_case_manifest() -> None:
    cases = _manifest_cases()
    assert len(cases) == 15
    assert len({fixture_id for _, fixture_id in cases}) == 15
    assert set(CASE_BUILDERS) == {fixture_id for _, fixture_id in cases}


@LIVE_BACKEND
@pytest.mark.parametrize(("gate_id", "fixture_id"), _manifest_cases())
def test_all_15_cases_are_relation_equivalent_across_python_typed_and_eye(
    tmp_path: Path, gate_id: str, fixture_id: str
) -> None:
    canonical, graph = _case(tmp_path, gate_id, fixture_id)
    result = qualify_case(
        fixture_id=fixture_id,
        canonical_document=canonical,
        typed_graph=graph,
    )

    assert result["relation_equivalent"] is True
    assert result["a_equals_b"] is True
    assert result["a_equals_c"] is True
    assert result["b_equals_c"] is True
    assert result["plane_b_added"] == 0
    assert result["plane_b_missing"] == 0
    assert result["false_closure"] == 0
    assert result["plane_c_missing"] == 0
    assert result["unknown_to_false_collapse"] == 0
    assert result["source_or_provenance_loss"] == 0
    assert result["context_or_version_loss"] == 0
    assert result["plane_a_relation_count"] == result["plane_b_relation_count"]
    assert result["plane_a_relation_count"] == result["plane_c_relation_count"]


@pytest.mark.parametrize(
    ("gate_id", "fixture_id"),
    [
        ("S2", "S2-dom-ax-field-conflict"),
        ("S3", "S3-absence-complete-vs-partial"),
        ("S4", "S4-document-generation-change"),
        ("S5", "S5-duplicate-action-id"),
    ],
)
@LIVE_BACKEND
def test_frozen_narrow_sentinels_match_python_oracle_without_generic_rulepack(
    tmp_path: Path, gate_id: str, fixture_id: str
) -> None:
    _, graph = _case(tmp_path, gate_id, fixture_id)
    result = sentinel_result(canonical_n3_bytes(graph), fixture_ref=fixture_id)
    assert result["hits"] == result["expected_hits"]
    assert result["hits"]
    assert result["expectation_source"] == "independent_python_frozen_oracle"


@LIVE_BACKEND
def test_p1d_parser_is_exactly_pinned_by_existing_p1c_lock() -> None:
    identity = verify_p1d_parser_identity()
    assert identity == {
        "package": "n3",
        "version": "2.7.12",
        "integrity": "sha512-Hy6dfGg9yniLQpSBirvH2E2yO3EG7dSmA3aefRbtO411oqtzG8roD3h1kTc/N065bivCOPfTFIjf0KlwW7KlnQ==",
    }


def test_plane_a_and_plane_b_are_independent_surfaces() -> None:
    source = (ROOT / "tools/semantic_logic/p1d_qualification.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: ast.get_source_segment(source, node) or "" for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

    assert "project_document" not in functions["relations_from_python_oracle"]
    assert ".reconstruct(" not in functions["relations_from_typed_ir"]
    assert "relations_from_typed_ir" not in functions["relations_from_python_oracle"]
    assert "relations_from_python_oracle" not in functions["relations_from_typed_ir"]


def test_plane_c_parsing_is_js_eye_output_not_python_n3_decoder() -> None:
    bridge = (ROOT / "tools/semantic_logic/n3_validator/p1d_bridge.mjs").read_text(encoding="utf-8")
    assert "queryOnce" in bridge
    assert "new Parser({ format: 'text/n3' })" in bridge
    assert "semanticRelations(quads)" in bridge
    assert "load_canonical_n3" not in bridge
    assert "project_document" not in bridge


def test_p1d_bridge_has_only_fixed_modes_and_fixture_keyed_sentinels() -> None:
    bridge = (ROOT / "tools/semantic_logic/n3_validator/p1d_bridge.mjs").read_text(encoding="utf-8")
    assert "['relations', 'sentinels']" in bridge
    assert "request.query" not in bridge
    assert "request.rulepack" not in bridge
    assert "S2-dom-ax-field-conflict" in bridge
    assert "S3-absence-complete-vs-partial" in bridge
    assert "S4-document-generation-change" in bridge
    assert "S5-duplicate-action-id" in bridge
    assert "expected:" not in bridge


def test_p1d_adds_no_production_consumer() -> None:
    offenders: list[str] = []
    for path in (ROOT / "src/llm_loop").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "p1d_qualification" in text or "p1d_bridge" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
