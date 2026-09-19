from __future__ import annotations

import json
import runpy
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

import pytest

from llm_loop.semantic_logic.rules import evaluate_rulepack
from llm_loop.tools.builtin.browser_semantic_execute import (
    BrowserSemanticExecuteCompileError,
    BrowserSemanticExecuteTool,
)

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

PACK = RED_HARNESS["PACK"]
RED = RED_HARNESS["RED"]
build_case = RED_HARNESS["build_case"]
G1_BRIDGE = VALIDATOR_ROOT / "p2_g1_bridge.mjs"

G1_RULES_SHA256 = "34ff3609899feb7327b04e5dc29938e46e1341e85f2d93218c0d4eaa9a56310e"
G1_QUERY_SHA256 = "b8ea0d7e0365993ae769770c55ba6750d1397206b6000ddba6ea140d870fb87d"
SUCCESS_GATES = {"P2-G1-01", "P2-G1-02", "P2-G1-08"}

N3_TO_TYPED = {
    "bindingStatus": "binding.status",
    "versionScope": "binding.version_scope",
    "actionSchema": "action.schema",
    "actionDomain": "action.domain",
    "actionScopeRef": "action.scope_ref",
    "actionVerb": "action.verb",
    "actionTargetId": "action.target_id",
    "operationClass": "action.operation_class",
    "idempotencyClass": "action.idempotency_class",
    "atomicityClass": "action.atomicity_class",
    "actionExpectedVersion": "action.expected_version",
    "actionVersionScope": "action.version_scope",
    "actionVersionPrecondition": "action.version_precondition",
}


def _g1_gates() -> list[dict[str, Any]]:
    gates = [gate for gate in RED["cases"] if str(gate["gate_id"]).startswith("P2-G1-")]
    assert [gate["gate_id"] for gate in gates] == [f"P2-G1-{i:02d}" for i in range(1, 9)]
    return gates


def _values(input_document: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for fact in input_document["facts"]:
        predicate = str(fact["predicate"])
        if predicate in result:
            raise AssertionError(f"unexpected duplicate input predicate: {predicate}")
        result[predicate] = fact.get("value")
    return result


def _derived_values(result: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for fact in result["derived_facts"]:
        predicate = str(fact["predicate"])
        if predicate in values:
            raise AssertionError(f"duplicate derived predicate: {predicate}")
        values[predicate] = fact.get("value")
    return values


class _FakePerception:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def hydrate(self, session_id: str, grounding_ref: str) -> dict[str, Any]:
        assert session_id == "sid-p2-g1"
        assert grounding_ref == self._values["request.target_ref"]
        availability = self._values["grounding.availability"]
        if availability != "available":
            return {"availability": availability, "reason": str(availability)}
        if self._values["grounding.kind"] == "object":
            content: dict[str, Any] = {
                "semantic_object": {
                    "grounding_ref": self._values["grounding.projection_ref"],
                    "id": self._values["grounding.target_id"],
                    "scope_ref": self._values["grounding.scope_ref"],
                    "observed_version": self._values["grounding.observed_version"],
                }
            }
        else:
            content = {
                "schema": "smc.browser_resource_grounding.v0.1",
                "kind": "page",
                "grounding_ref": self._values["grounding.projection_ref"],
                "scope_ref": self._values["grounding.scope_ref"],
                "observed_version": self._values["grounding.observed_version"],
            }
        return {"availability": "available", "content": content}


def _python_oracle(values: dict[str, Any]) -> dict[str, Any]:
    tool = BrowserSemanticExecuteTool(
        perception=cast(Any, _FakePerception(values)),
        action_adapter=cast(Any, object()),
        session_id_getter=lambda: "sid-p2-g1",
    )
    request = {
        "verb": values["request.verb"],
        "target_ref": values["request.target_ref"],
        "args": values["request.args"],
    }
    return tool.compile_request("sid-p2-g1", request)


def _n3_values(values: dict[str, Any]) -> dict[str, str]:
    return {
        "availability": str(values["grounding.availability"]),
        "grounding_kind": str(values["grounding.kind"]),
        "grounding_ref": str(values["grounding.ref"]),
        "observed_version": str(values["grounding.observed_version"]),
        "projection_ref": str(values["grounding.projection_ref"]),
        "scope_ref": str(values["grounding.scope_ref"]),
        "target_id": str(values["grounding.target_id"]),
        "target_ref": str(values["request.target_ref"]),
        "verb": str(values["request.verb"]),
    }


def _run_n3_shadow(gate_id: str, values: dict[str, Any]) -> dict[str, Any]:
    P1C["verify_backend_identity"]()
    P1D["verify_p1d_parser_identity"]()
    node = shutil.which("node")
    assert node is not None
    request = {
        "answer_cap": 64,
        "case_ref": gate_id,
        "values": _n3_values(values),
    }
    request_bytes = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="smc-p2-g1-") as raw_home:
        home = Path(raw_home)
        proc = subprocess.run(
            P1C["_sandbox_command"](node, G1_BRIDGE),
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
    assert receipt["schema"] == "smc.p2_g1_eye_bridge_receipt.v0.1"
    assert receipt["ok"] is True
    assert receipt["case_ref"] == gate_id
    assert receipt["rules_sha256"] == G1_RULES_SHA256
    assert receipt["query_sha256"] == G1_QUERY_SHA256
    assert "--restricted" in receipt["eye_args"]
    assert receipt["eye_args"][-4:] == ["./data.n3", "./rules.n3", "--query", "./query.n3"]
    return receipt


@LIVE_BACKEND
@pytest.mark.parametrize("gate", _g1_gates(), ids=lambda gate: gate["gate_id"])
def test_g1_python_typed_and_restricted_n3_shadow(gate: dict[str, Any]) -> None:
    gate_id = str(gate["gate_id"])
    case = build_case(gate)
    values = _values(case.input_document)
    typed = evaluate_rulepack(
        rulepack_document=case.rulepack,
        input_document=case.input_document,
    )
    assert typed["status"] == "complete"
    typed_values = _derived_values(typed)
    n3 = _run_n3_shadow(gate_id, values)
    n3_values = {str(key): value for key, value in n3["relations"]}

    if gate_id in SUCCESS_GATES:
        python_action = _python_oracle(values)
        assert typed_values["binding.status"] == "bound"
        for predicate in PACK["rules"][1]["output_predicates"]:
            action_field = predicate.removeprefix("action.")
            assert predicate in typed_values
            assert action_field in python_action
            assert typed_values[predicate] == python_action[action_field]
        for n3_key, typed_key in N3_TO_TYPED.items():
            assert n3_values[n3_key] == str(typed_values[typed_key])
        # EYE validates the semantic binding/fixed action contract, while exact action-id
        # hashing is independently checked against the production Python compiler above.
        assert "actionId" not in n3_values
    else:
        with pytest.raises(BrowserSemanticExecuteCompileError):
            _python_oracle(values)
        assert typed_values["binding.status"] == "indeterminate"
        assert n3_values.get("bindingStatus") != "bound"
        assert not any(key.startswith("action") for key in n3_values)


def test_g1_derived_provenance_is_mechanical_and_cannot_claim_reservation() -> None:
    gate = _g1_gates()[0]
    case = build_case(gate)
    result = evaluate_rulepack(
        rulepack_document=case.rulepack,
        input_document=case.input_document,
    )
    assert result["status"] == "complete"
    assert result["derivations"]
    asserted_ids = {str(fact["fact_id"]) for fact in case.input_document["facts"]}
    derived_by_id = {str(fact["fact_id"]): fact for fact in result["derived_facts"]}
    pack_rules = {str(rule["rule_id"]): rule for rule in case.rulepack["rules"]}
    derivation_ids = {str(item["derivation_id"]) for item in result["derivations"]}
    assert len(derivation_ids) == len(result["derivations"])
    for derivation in result["derivations"]:
        rule_id = str(derivation["rule_ref"]).split("@", 1)[0]
        assert rule_id in pack_rules
        assert derivation["rule_hash"] == pack_rules[rule_id]["rule_hash"]
        assert set(derivation["input_fact_refs"]) <= asserted_ids | set(derived_by_id)
        assert set(derivation["output_fact_refs"]) <= set(derived_by_id)
        assert derivation["output_fact_refs"]
        for output_ref in derivation["output_fact_refs"]:
            fact = derived_by_id[str(output_ref)]
            assert fact["provenance"]["derivation_ref"] == derivation["derivation_id"]
            assert fact["provenance"]["rule_ref"] == derivation["rule_ref"]
            assert fact["provenance"]["input_fact_refs"] == derivation["input_fact_refs"]
    for fact in result["derived_facts"]:
        assert fact["provenance"]["kind"] == "mechanically_derived"
        assert fact["provenance"]["derivation_ref"]
        assert fact["provenance"]["rule_ref"]
        assert fact["provenance"]["input_fact_refs"]
        assert not str(fact["predicate"]).startswith("runtime.")
        assert "reservation" not in str(fact["predicate"])
        assert "dispatch" not in str(fact["predicate"])


def test_g1_same_input_is_byte_deterministic() -> None:
    gate = _g1_gates()[0]
    case = build_case(gate)
    first = evaluate_rulepack(
        rulepack_document=case.rulepack,
        input_document=case.input_document,
    )
    second = evaluate_rulepack(
        rulepack_document=case.rulepack,
        input_document=case.input_document,
    )
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )


def test_g1_bridge_has_no_dynamic_rule_or_query_input_surface() -> None:
    source = G1_BRIDGE.read_text(encoding="utf-8")
    assert "request.rules" not in source
    assert "request.query" not in source
    assert "rules.n3" in source
    assert "query.n3" in source
    assert "--restricted" in source
