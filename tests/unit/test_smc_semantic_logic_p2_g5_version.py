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

from llm_loop.semantic_logic.rules import evaluate_rulepack

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_ROOT = ROOT / "tools/semantic_logic/n3_validator"
RED_HARNESS = runpy.run_path(str(ROOT / "tests/unit/test_smc_semantic_logic_p2_red.py"))
P1A = runpy.run_path(str(ROOT / "tests/unit/test_smc_semantic_logic_p1a.py"))
P1C = runpy.run_path(str(VALIDATOR_ROOT / "harness.py"))
P1D = runpy.run_path(str(ROOT / "tools/semantic_logic/p1d_qualification.py"))

RED = RED_HARNESS["RED"]
build_case = RED_HARNESS["build_case"]
G5_VERSION_BRIDGE = VALIDATOR_ROOT / "p2_g5_version_bridge.mjs"

G5_VERSION_RULES_SHA256 = "66da1bfa360d6254a61ba6ab0823a37094b32942d3e9d700a2115f8726689d04"
G5_VERSION_QUERY_SHA256 = "9b73a4b4689d8d701da2c79dc1562fc2bddbfcac4c371bbcf017e228e4880db8"


def _version_gates() -> list[dict[str, Any]]:
    gates = [
        gate
        for gate in RED["cases"]
        if str(gate["gate_id"]) in {f"P2-G5-{index:02d}" for index in range(1, 8)}
    ]
    assert [gate["gate_id"] for gate in gates] == [f"P2-G5-{index:02d}" for index in range(1, 8)]
    return gates


def _single(input_document: dict[str, Any], predicate: str) -> Any | None:
    values = [
        fact.get("value")
        for fact in input_document["facts"]
        if fact["predicate"] == predicate
    ]
    return values[0] if len(values) == 1 else None


def _typed_values(result: dict[str, Any]) -> dict[str, Any]:
    return {
        str(fact["predicate"]): fact.get("value")
        for fact in result["derived_facts"]
        if str(fact["predicate"]).startswith("version.")
    }


def _scope_relation(input_document: dict[str, Any]) -> str:
    observed = {
        str(fact["value"])
        for fact in input_document["facts"]
        if fact["predicate"] == "scope.node.scope_ref"
    }
    request = _single(input_document, "request.scope_ref")
    target = _single(input_document, "target.scope_ref")
    if request not in observed or target not in observed:
        return "indeterminate"
    return "match" if request == target else "mismatch"


def _coverage_complete(input_document: dict[str, Any]) -> bool:
    expected = set(_single(input_document, "coverage.expected_sources") or [])
    observed = set(_single(input_document, "coverage.observed_sources") or [])
    blind = list(_single(input_document, "coverage.blind_spots") or [])
    truncated = _single(input_document, "coverage.sensor_truncated") is True
    return bool(expected) and observed == expected and not blind and not truncated


def _production_oracle(gate_id: str, tmp_path: Path) -> dict[str, Any]:
    builders = P1A["CASE_BUILDERS"]
    if gate_id == "P2-G5-01":
        return builders["S4-object-same-generation-changed"](tmp_path / "changed")
    if gate_id == "P2-G5-02":
        return builders["S4-object-unchanged-new-observation"](tmp_path / "unchanged")
    if gate_id == "P2-G5-03":
        return builders["S4-document-generation-change"](tmp_path / "document")
    if gate_id in {"P2-G5-04", "P2-G5-05"}:
        result = builders["S4-incomplete-missing-target"](tmp_path / "incomplete")
        return result["partial" if gate_id == "P2-G5-04" else "expired"]
    if gate_id == "P2-G5-06":
        adapter = P1A["_adapter"](tmp_path / "exact")
        snapshot = adapter.snapshot("s1", P1A["FIXTURES"]["base"])
        target = P1A["_by_name"](snapshot, "Submit")
        version = P1A["_sid"](snapshot)
        return adapter.assess_version_precondition(
            "s1",
            expected_version=version,
            observed_version=version,
            version_scope="object",
            scope_ref=str(target["scope_ref"]),
            target_id=str(target["id"]),
        )
    if gate_id == "P2-G5-07":
        raw = copy.deepcopy(P1A["FIXTURES"]["base"])
        raw["ax"]["nodes"].append(
            {
                "ax_id": "ax-local-only",
                "physical_id": None,
                "frame_token": None,
                "kind": "text",
                "attributes": {"role": "InlineTextBox", "name": "Local only"},
                "state": {"exists": True},
            }
        )
        adapter = P1A["_adapter"](tmp_path / "unstable")
        snapshot = adapter.snapshot("s1", raw)
        local = next(
            obj
            for obj in snapshot["objects"]
            if obj["attributes"].get("name") == "Local only"
        )
        version = P1A["_sid"](snapshot)
        return adapter.assess_version_precondition(
            "s1",
            expected_version=version,
            observed_version=version,
            version_scope="object",
            scope_ref=str(local["scope_ref"]),
            target_id=str(local["id"]),
        )
    raise AssertionError(gate_id)


def _eye_request(gate_id: str, input_document: dict[str, Any]) -> dict[str, Any]:
    object_changed = _single(input_document, "object.changed_fields")
    resource_changed = _single(input_document, "resource.changed_fields")
    return {
        "answer_cap": 128,
        "case_ref": gate_id,
        "version_scope": str(_single(input_document, "version.scope")),
        "expected_availability": str(
            _single(input_document, "version.expected_availability")
        ),
        "observed_availability": str(
            _single(input_document, "version.observed_availability")
        ),
        "scope_relation": _scope_relation(input_document),
        "identity_stable": _single(input_document, "identity.stable") is True,
        "version_equal": _single(input_document, "version.expected")
        == _single(input_document, "version.observed"),
        "page_same": _single(input_document, "lineage.page_same") is True,
        "document_same": _single(input_document, "lineage.document_same") is True,
        "target_present": _single(input_document, "observation.target_present") is True,
        "coverage_complete": _coverage_complete(input_document),
        "object_changed": isinstance(object_changed, list) and bool(object_changed),
        "resource_changed": isinstance(resource_changed, list) and bool(resource_changed),
    }


def _run_n3_shadow(gate_id: str, input_document: dict[str, Any]) -> dict[str, Any]:
    P1C["verify_backend_identity"]()
    P1D["verify_p1d_parser_identity"]()
    node = shutil.which("node")
    assert node is not None
    request_bytes = (
        json.dumps(_eye_request(gate_id, input_document), separators=(",", ":")) + "\n"
    ).encode()
    with tempfile.TemporaryDirectory(prefix="smc-p2-g5-version-") as raw_home:
        proc = subprocess.run(
            P1C["_sandbox_command"](node, G5_VERSION_BRIDGE),
            input=request_bytes,
            capture_output=True,
            check=False,
            timeout=20,
            cwd=VALIDATOR_ROOT,
            env=P1C["_sanitized_env"](Path(raw_home)),
        )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    assert proc.stderr == b""
    receipt = json.loads(proc.stdout.decode())
    assert receipt["schema"] == "smc.p2_g5_version_eye_bridge_receipt.v0.1"
    assert receipt["ok"] is True
    assert receipt["validation_status"] == "accepted"
    assert receipt["rules_sha256"] == G5_VERSION_RULES_SHA256
    assert receipt["query_sha256"] == G5_VERSION_QUERY_SHA256
    assert "--restricted" in receipt["eye_args"]
    assert receipt["eye_args"][-4:] == ["./data.n3", "./rules.n3", "--query", "./query.n3"]
    return receipt


@pytest.mark.parametrize("gate", _version_gates(), ids=lambda gate: gate["gate_id"])
def test_g5_version_python_typed_and_restricted_n3_shadow(
    gate: dict[str, Any], tmp_path: Path
) -> None:
    gate_id = str(gate["gate_id"])
    case = build_case(gate)
    typed = evaluate_rulepack(
        rulepack_document=case.rulepack,
        input_document=case.input_document,
    )
    oracle = _production_oracle(gate_id, tmp_path)
    eye = _run_n3_shadow(gate_id, case.input_document)

    assert typed["status"] == "complete"
    values = _typed_values(typed)
    eye_values = {str(key): value for key, value in eye["relations"]}

    assert values["version.result"] == oracle["result"]
    assert values["version.reason"] == oracle["reason"]
    assert values["version.comparable"] == oracle["comparable"]
    assert values["version.automatic_refresh_performed"] is False
    assert values["version.silent_rebind_performed"] is False

    assert eye_values["versionResult"] == oracle["result"]
    assert eye_values["versionReason"] == oracle["reason"]
    if oracle["comparable"] is None:
        assert "versionComparable" not in eye_values
    else:
        assert eye_values["versionComparable"] == str(oracle["comparable"]).lower()
    assert eye_values["automaticRefreshPerformed"] == "false"
    assert eye_values["silentRebindPerformed"] == "false"


def test_g5_version_incomplete_missing_target_never_becomes_stale() -> None:
    gate = next(gate for gate in _version_gates() if gate["gate_id"] == "P2-G5-04")
    case = build_case(gate)
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    values = _typed_values(result)
    assert values["version.result"] == "indeterminate"
    assert values["version.reason"] == "target_not_observed_incomplete"
    assert values["version.comparable"] is True


def test_g5_version_expiry_never_refreshes_or_rebinds() -> None:
    gate = next(gate for gate in _version_gates() if gate["gate_id"] == "P2-G5-05")
    case = build_case(gate)
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    values = _typed_values(result)
    assert values["version.result"] == "indeterminate"
    assert values["version.automatic_refresh_performed"] is False
    assert values["version.silent_rebind_performed"] is False


def test_g5_version_unstable_identity_cannot_match_even_when_version_is_equal() -> None:
    gate = next(gate for gate in _version_gates() if gate["gate_id"] == "P2-G5-07")
    case = build_case(gate)
    mutated = copy.deepcopy(case.input_document)
    observed = _single(mutated, "version.expected")
    next(fact for fact in mutated["facts"] if fact["predicate"] == "version.observed")[
        "value"
    ] = observed
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=mutated)
    values = _typed_values(result)
    assert values["version.result"] == "indeterminate"
    assert values["version.reason"] == "target_identity_unstable"


def test_g5_version_unobserved_scope_stays_indeterminate() -> None:
    gate = next(gate for gate in _version_gates() if gate["gate_id"] == "P2-G5-02")
    case = build_case(gate)
    mutated = copy.deepcopy(case.input_document)
    next(fact for fact in mutated["facts"] if fact["predicate"] == "target.scope_ref")[
        "value"
    ] = "scope:not-observed"
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=mutated)
    values = _typed_values(result)
    assert values["version.result"] == "indeterminate"
    assert values["version.reason"] == "scope_not_observed"


def test_g5_version_same_input_is_byte_deterministic_and_provenance_is_mechanical() -> None:
    gate = next(gate for gate in _version_gates() if gate["gate_id"] == "P2-G5-01")
    case = build_case(gate)
    first = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    second = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )
    asserted = {str(fact["fact_id"]) for fact in case.input_document["facts"]}
    derived = {str(fact["fact_id"]): fact for fact in first["derived_facts"]}
    for derivation in first["derivations"]:
        assert set(derivation["input_fact_refs"]) <= asserted | set(derived)
        for output_ref in derivation["output_fact_refs"]:
            fact = derived[str(output_ref)]
            assert fact["provenance"]["kind"] == "mechanically_derived"
            assert fact["context"]["domain"] == "browser"
            assert not str(fact["predicate"]).startswith("runtime.")


def test_g5_version_bridge_has_no_dynamic_rule_query_or_effect_surface() -> None:
    source = G5_VERSION_BRIDGE.read_text(encoding="utf-8")
    assert "request.rules" not in source
    assert "request.query" not in source
    assert "rules.n3" in source
    assert "query.n3" in source
    assert "--restricted" in source
    assert "refresh(" not in source
    assert "dispatch(" not in source
    assert "rebind(" not in source
