from __future__ import annotations

import copy
import json
import runpy
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from llm_loop.browser.predicate import _scope_descendants
from llm_loop.semantic_logic.rules import evaluate_rulepack

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_ROOT = ROOT / "tools/semantic_logic/n3_validator"
RED_HARNESS = runpy.run_path(str(ROOT / "tests/unit/test_smc_semantic_logic_p2_red.py"))
P1C = runpy.run_path(str(VALIDATOR_ROOT / "harness.py"))
P1D = runpy.run_path(str(ROOT / "tools/semantic_logic/p1d_qualification.py"))

BACKEND_READY = P1C["backend_installation_available"]()
LIVE_BACKEND = pytest.mark.skipif(
    not BACKEND_READY,
    reason="qualification-only pinned N3 backend is not installed in this checkout",
)

RED = RED_HARNESS["RED"]
build_case = RED_HARNESS["build_case"]
G2_BRIDGE = VALIDATOR_ROOT / "p2_g2_bridge.mjs"

G2_RULES_SHA256 = "7d1f4c07c253e7934606656379914b3095d4dd0802548209f0791a2932936f6a"
G2_QUERY_SHA256 = "0e8c711dacdf0b821cb6af9de536694ae4aaa158dc28e7dc3d1bb50bc771112e"


def _g2_gates() -> list[dict[str, Any]]:
    gates = [gate for gate in RED["cases"] if str(gate["gate_id"]).startswith("P2-G2-")]
    assert [gate["gate_id"] for gate in gates] == [f"P2-G2-{i:02d}" for i in range(1, 7)]
    return gates


def _scope_nodes(input_document: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for fact in input_document["facts"]:
        predicate = str(fact["predicate"])
        if predicate not in {
            "scope.node.scope_ref",
            "scope.node.parent_scope_ref",
            "scope.node.kind",
        }:
            continue
        grouped.setdefault(str(fact["subject"]), {})[predicate] = fact.get("value")
    nodes = [
        {
            "scope_ref": fields["scope.node.scope_ref"],
            "parent_scope_ref": fields["scope.node.parent_scope_ref"],
            "kind": fields["scope.node.kind"],
        }
        for fields in grouped.values()
    ]
    return sorted(nodes, key=lambda item: str(item["scope_ref"]))


def _single_value(input_document: dict[str, Any], predicate: str) -> Any | None:
    values = [fact.get("value") for fact in input_document["facts"] if fact["predicate"] == predicate]
    if len(values) != 1:
        return None
    return values[0]


def _typed_values(result: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for fact in result["derived_facts"]:
        predicate = str(fact["predicate"])
        if predicate == "scope.descendant_of":
            continue
        if predicate in values:
            raise AssertionError(f"duplicate derived predicate: {predicate}")
        values[predicate] = fact.get("value")
    return values


def _typed_descendants(result: dict[str, Any]) -> list[tuple[str, str]]:
    rows = {
        (str(fact["subject"]), str((fact.get("context") or {})["scope_ref"]))
        for fact in result["derived_facts"]
        if fact["predicate"] == "scope.descendant_of"
    }
    return sorted(rows)


def _python_descendants(nodes: list[dict[str, Any]]) -> list[tuple[str, str]]:
    refs = [str(node["scope_ref"]) for node in nodes]
    rows: set[tuple[str, str]] = set()
    for ancestor in refs:
        for child in _scope_descendants(nodes, ancestor):
            if child != ancestor:
                rows.add((child, ancestor))
    return sorted(rows)


def _python_relation(input_document: dict[str, Any], nodes: list[dict[str, Any]]) -> tuple[str, str]:
    observed = {str(node["scope_ref"]) for node in nodes}
    request_scope = _single_value(input_document, "request.scope_ref")
    target_scope = _single_value(input_document, "target.scope_ref")
    if (
        not isinstance(request_scope, str)
        or not request_scope
        or not isinstance(target_scope, str)
        or not target_scope
        or request_scope not in observed
        or target_scope not in observed
    ):
        return ("indeterminate", "scope_unobserved")
    if request_scope == target_scope:
        return ("match", "exact_scope")
    return ("mismatch", "target_scope_mismatch")


def _run_n3_shadow(gate_id: str, input_document: dict[str, Any]) -> dict[str, Any]:
    P1C["verify_backend_identity"]()
    P1D["verify_p1d_parser_identity"]()
    node = shutil.which("node")
    assert node is not None
    request = {
        "answer_cap": 128,
        "case_ref": gate_id,
        "scope_nodes": _scope_nodes(input_document),
        "request_scope": _single_value(input_document, "request.scope_ref"),
        "target_scope": _single_value(input_document, "target.scope_ref"),
    }
    request_bytes = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="smc-p2-g2-") as raw_home:
        home = Path(raw_home)
        proc = subprocess.run(
            P1C["_sandbox_command"](node, G2_BRIDGE),
            input=request_bytes,
            capture_output=True,
            check=False,
            timeout=20,
            cwd=VALIDATOR_ROOT,
            env=P1C["_sanitized_env"](home),
        )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    assert proc.stderr == b""
    receipt = json.loads(proc.stdout.decode("utf-8"))
    assert receipt["schema"] == "smc.p2_g2_eye_bridge_receipt.v0.1"
    assert receipt["ok"] is True
    assert receipt["case_ref"] == gate_id
    assert receipt["rules_sha256"] == G2_RULES_SHA256
    assert receipt["query_sha256"] == G2_QUERY_SHA256
    if receipt["validation_status"] == "accepted":
        assert "--restricted" in receipt["eye_args"]
        assert receipt["eye_args"][-4:] == ["./data.n3", "./rules.n3", "--query", "./query.n3"]
    else:
        assert receipt["eye_args"] == []
    return receipt


@LIVE_BACKEND
@pytest.mark.parametrize("gate", _g2_gates(), ids=lambda gate: gate["gate_id"])
def test_g2_python_typed_and_restricted_n3_shadow(gate: dict[str, Any]) -> None:
    gate_id = str(gate["gate_id"])
    case = build_case(gate)
    typed = evaluate_rulepack(
        rulepack_document=case.rulepack,
        input_document=case.input_document,
    )
    n3 = _run_n3_shadow(gate_id, case.input_document)
    nodes = _scope_nodes(case.input_document)

    if gate_id == "P2-G2-05":
        assert typed["status"] == "rejected"
        assert typed["reason"] == "scope_graph_cycle"
        assert n3["validation_status"] == "rejected"
        assert n3["validation_reason"] == "scope_graph_cycle"
        return
    if gate_id == "P2-G2-06":
        assert typed["status"] == "rejected"
        assert typed["reason"] == "max_scope_depth_exceeded"
        assert n3["validation_status"] == "rejected"
        assert n3["validation_reason"] == "max_scope_depth_exceeded"
        return

    assert typed["status"] == "complete"
    assert n3["validation_status"] == "accepted"
    typed_values = _typed_values(typed)
    n3_values = {str(key): value for key, value in n3["relations"]}
    if gate_id in {"P2-G2-01", "P2-G2-02", "P2-G2-03"}:
        python_relation, python_reason = _python_relation(case.input_document, nodes)
        assert typed_values["scope.relation"] == python_relation
        assert typed_values["scope.reason"] == python_reason
        assert n3_values["scopeRelation"] == python_relation
        assert n3_values["scopeReason"] == python_reason
    else:
        assert "scope.relation" not in typed_values
        assert "scope.reason" not in typed_values

    python_descendants = _python_descendants(nodes)
    typed_descendants = _typed_descendants(typed)
    n3_descendants = sorted((str(child), str(parent)) for child, parent in n3["descendants"])
    assert typed_descendants == python_descendants
    assert n3_descendants == python_descendants


def test_g2_open_world_missing_ancestor_does_not_invent_negative_or_extra_ancestry() -> None:
    gate = next(gate for gate in _g2_gates() if gate["gate_id"] == "P2-G2-04")
    case = build_case(gate)
    mutated = copy.deepcopy(case.input_document)
    parent_fact = next(
        fact
        for fact in mutated["facts"]
        if fact["predicate"] == "scope.node.parent_scope_ref"
        and fact["value"] == "scope:page:1"
    )
    parent_fact["value"] = "scope:ancestor:not-observed"
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=mutated)
    assert result["status"] == "complete"
    pairs = _typed_descendants(result)
    assert ("scope:document:1", "scope:ancestor:not-observed") in pairs
    assert ("scope:frame:1", "scope:ancestor:not-observed") in pairs
    assert ("scope:document:1", "scope:page:1") not in pairs
    assert ("scope:frame:1", "scope:page:1") not in pairs
    assert not any(
        str(fact["predicate"]).startswith("scope.not_")
        or fact.get("value") in {False, "false", "outside"}
        for fact in result["derived_facts"]
    )


def test_g2_derived_provenance_is_mechanical_and_context_preserving() -> None:
    gate = next(gate for gate in _g2_gates() if gate["gate_id"] == "P2-G2-04")
    case = build_case(gate)
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    assert result["status"] == "complete"
    asserted_ids = {str(fact["fact_id"]) for fact in case.input_document["facts"]}
    derived_by_id = {str(fact["fact_id"]): fact for fact in result["derived_facts"]}
    for derivation in result["derivations"]:
        assert derivation["rule_hash"]
        assert set(derivation["input_fact_refs"]) <= asserted_ids | set(derived_by_id)
        assert derivation["output_fact_refs"]
        for output_ref in derivation["output_fact_refs"]:
            fact = derived_by_id[str(output_ref)]
            assert fact["provenance"]["kind"] == "mechanically_derived"
            assert fact["provenance"]["derivation_ref"] == derivation["derivation_id"]
            assert fact["provenance"]["rule_ref"] == derivation["rule_ref"]
            assert fact["provenance"]["input_fact_refs"] == derivation["input_fact_refs"]
            assert fact["context"]["domain"] == "browser"
            assert not str(fact["predicate"]).startswith("runtime.")


def test_g2_same_input_is_byte_deterministic() -> None:
    gate = next(gate for gate in _g2_gates() if gate["gate_id"] == "P2-G2-04")
    case = build_case(gate)
    first = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    second = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )


def test_g2_bridge_has_no_dynamic_rule_or_query_input_surface() -> None:
    source = G2_BRIDGE.read_text(encoding="utf-8")
    assert "request.rules" not in source
    assert "request.query" not in source
    assert "rules.n3" in source
    assert "query.n3" in source
    assert "--restricted" in source
