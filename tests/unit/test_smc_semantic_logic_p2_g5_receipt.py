from __future__ import annotations

import ast
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
RULES_PATH = ROOT / "src/llm_loop/semantic_logic/rules.py"
RED_HARNESS = runpy.run_path(str(ROOT / "tests/unit/test_smc_semantic_logic_p2_red.py"))
P1A = runpy.run_path(str(ROOT / "tests/unit/test_smc_semantic_logic_p1a.py"))
P1C = runpy.run_path(str(VALIDATOR_ROOT / "harness.py"))
P1D = runpy.run_path(str(ROOT / "tools/semantic_logic/p1d_qualification.py"))

RED = RED_HARNESS["RED"]
build_case = RED_HARNESS["build_case"]
G5_RECEIPT_BRIDGE = VALIDATOR_ROOT / "p2_g5_receipt_bridge.mjs"

G5_RECEIPT_RULES_SHA256 = "0e851e07f6743dc24c6af6015c09538970b0dbfc790cf10ea747f025298b62d5"
G5_RECEIPT_QUERY_SHA256 = "b7527e9cc3263045170946ae48597a5756a879f303f69adcd88a51e35d1367ef"


def _receipt_gates() -> list[dict[str, Any]]:
    gates = [
        gate
        for gate in RED["cases"]
        if str(gate["gate_id"]) in {f"P2-G5-{index:02d}" for index in range(8, 14)}
    ]
    assert [gate["gate_id"] for gate in gates] == [f"P2-G5-{index:02d}" for index in range(8, 14)]
    return gates


def _single(input_document: dict[str, Any], predicate: str) -> Any | None:
    values = [
        fact.get("value")
        for fact in input_document["facts"]
        if fact["predicate"] == predicate
    ]
    return values[0] if len(values) == 1 else None


def _receipt_rows(input_document: dict[str, Any]) -> list[dict[str, Any]]:
    predicates = {
        "receipt.action_id",
        "receipt.seq",
        "receipt.status",
        "receipt.history_watermark",
    }
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for fact in input_document["facts"]:
        predicate = str(fact["predicate"])
        if predicate not in predicates:
            continue
        subject = str(fact["subject"])
        if subject not in grouped:
            grouped[subject] = {"subject": subject}
            order.append(subject)
        grouped[subject][predicate] = fact.get("value")
    rows = [grouped[subject] for subject in order]
    assert rows
    assert all(set(row) == predicates | {"subject"} for row in rows)
    return rows


def _python_oracle(input_document: dict[str, Any]) -> dict[str, Any]:
    rows = _receipt_rows(input_document)
    action_ids = [str(row["receipt.action_id"]) for row in rows]
    seqs = [int(row["receipt.seq"]) for row in rows]
    watermarks = [int(row["receipt.history_watermark"]) for row in rows]
    statuses = [str(row["receipt.status"]) for row in rows]
    sequence_monotonic = (
        len(set(action_ids)) == 1
        and all(left < right for left, right in zip(seqs, seqs[1:], strict=False))
        and all(
            seq <= watermark
            for seq, watermark in zip(seqs, watermarks, strict=True)
        )
        and max(seqs) == max(watermarks)
    )
    transition_valid = True
    previous: str | None = None
    for status in statuses:
        if previous is None:
            previous = status
            continue
        if previous == "running":
            if status not in {"ok", "failed", "rejected"}:
                transition_valid = False
                break
        elif status != "rejected":
            transition_valid = False
            break
        previous = status

    reservation = _single(input_document, "runtime.reservation_result")
    dispatch_count = _single(input_document, "runtime.dispatch_count")
    automatic_retry = _single(input_document, "receipt.retry.automatic_retry_performed")
    provisional = _single(input_document, "receipt.observed_effects.provisional")
    assert isinstance(reservation, bool)
    assert isinstance(dispatch_count, int) and not isinstance(dispatch_count, bool)
    assert isinstance(automatic_retry, bool)
    assert isinstance(provisional, bool)
    single_dispatch = dispatch_count <= 1
    no_retry = not automatic_retry
    reservation_consistent = reservation or "rejected" in statuses
    invariant_ok = (
        sequence_monotonic
        and transition_valid
        and single_dispatch
        and no_retry
        and reservation_consistent
    )
    return {
        "sequence_monotonic": sequence_monotonic,
        "transition_valid": transition_valid,
        "terminal_status": statuses[-1] if statuses[-1] in {"ok", "failed", "rejected"} else None,
        "single_dispatch_preserved": single_dispatch,
        "no_automatic_retry": no_retry,
        "effect_evidence_status": "provisional" if provisional else "non_provisional",
        "invariant_status": "ok" if invariant_ok else "violation",
    }


def _typed_values(result: dict[str, Any]) -> dict[str, Any]:
    return {
        str(fact["predicate"]): fact.get("value")
        for fact in result["derived_facts"]
        if str(fact["predicate"]).startswith("receipt.")
    }


def _production_shape(gate_id: str, tmp_path: Path) -> dict[str, Any] | None:
    fixture_id = {
        "P2-G5-08": "S5-running-terminal-sequence",
        "P2-G5-09": "S5-duplicate-action-id",
        "P2-G5-10": "S5-transport-ambiguity-no-replay",
        "P2-G5-11": "S5-running-terminal-sequence",
    }.get(gate_id)
    if fixture_id is None:
        return None
    output = P1A["CASE_BUILDERS"][fixture_id](tmp_path / gate_id)
    receipts = output["receipts"]
    return {
        "seqs": [int(receipt["receipt_seq"]) for receipt in receipts],
        "statuses": [str(receipt["status"]) for receipt in receipts],
        "same_action": len({str(receipt["action_id"]) for receipt in receipts}) == 1,
        "dispatch_count": int(output["dispatch_count"]),
        "no_automatic_retry": all(
            (receipt.get("retry") or {}).get("automatic_retry_performed") is False
            for receipt in receipts
        ),
        "terminal_provisional": (receipts[-1].get("observed_effects") or {}).get("provisional")
        is True,
        "result_status": str(
            (output.get("result") or output.get("duplicate") or {}).get("status") or ""
        ),
        "terminal_retry_reason": (receipts[-1].get("retry") or {}).get("reason"),
    }


def _eye_request(gate_id: str, input_document: dict[str, Any]) -> dict[str, Any]:
    reservation_result = _single(input_document, "runtime.reservation_result")
    dispatch_count = _single(input_document, "runtime.dispatch_count")
    automatic_retry = _single(
        input_document, "receipt.retry.automatic_retry_performed"
    )
    provisional = _single(input_document, "receipt.observed_effects.provisional")
    assert isinstance(reservation_result, bool)
    assert isinstance(dispatch_count, int) and not isinstance(dispatch_count, bool)
    assert isinstance(automatic_retry, bool)
    assert isinstance(provisional, bool)
    return {
        "answer_cap": 128,
        "case_ref": gate_id,
        "receipts": [
            {
                "action_id": str(row["receipt.action_id"]),
                "seq": int(row["receipt.seq"]),
                "status": str(row["receipt.status"]),
                "history_watermark": int(row["receipt.history_watermark"]),
            }
            for row in _receipt_rows(input_document)
        ],
        "reservation_result": reservation_result,
        "dispatch_count": dispatch_count,
        "automatic_retry_performed": automatic_retry,
        "provisional": provisional,
    }


def _run_n3_shadow(gate_id: str, input_document: dict[str, Any]) -> dict[str, Any]:
    P1C["verify_backend_identity"]()
    P1D["verify_p1d_parser_identity"]()
    node = shutil.which("node")
    assert node is not None
    request_bytes = (
        json.dumps(_eye_request(gate_id, input_document), separators=(",", ":")) + "\n"
    ).encode()
    with tempfile.TemporaryDirectory(prefix="smc-p2-g5-receipt-") as raw_home:
        proc = subprocess.run(
            P1C["_sandbox_command"](node, G5_RECEIPT_BRIDGE),
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
    assert receipt["schema"] == "smc.p2_g5_receipt_eye_bridge_receipt.v0.1"
    assert receipt["ok"] is True
    assert receipt["validation_status"] == "accepted"
    assert receipt["rules_sha256"] == G5_RECEIPT_RULES_SHA256
    assert receipt["query_sha256"] == G5_RECEIPT_QUERY_SHA256
    assert "--restricted" in receipt["eye_args"]
    assert receipt["eye_args"][-4:] == ["./data.n3", "./rules.n3", "--query", "./query.n3"]
    return receipt


@pytest.mark.parametrize("gate", _receipt_gates(), ids=lambda gate: gate["gate_id"])
def test_g5_receipt_python_typed_and_restricted_n3_shadow(
    gate: dict[str, Any], tmp_path: Path
) -> None:
    gate_id = str(gate["gate_id"])
    case = build_case(gate)
    before = json.dumps(case.input_document, sort_keys=True, separators=(",", ":"))
    typed = evaluate_rulepack(
        rulepack_document=case.rulepack,
        input_document=case.input_document,
    )
    after = json.dumps(case.input_document, sort_keys=True, separators=(",", ":"))
    assert before == after
    assert typed["status"] == "complete"
    oracle = _python_oracle(case.input_document)
    values = _typed_values(typed)
    eye = _run_n3_shadow(gate_id, case.input_document)
    eye_values = {str(key): value for key, value in eye["relations"]}

    mapping = {
        "receipt.sequence_monotonic": ("sequence_monotonic", "sequenceMonotonic"),
        "receipt.transition_valid": ("transition_valid", "transitionValid"),
        "receipt.terminal_status": ("terminal_status", "terminalStatus"),
        "receipt.single_dispatch_preserved": (
            "single_dispatch_preserved",
            "singleDispatchPreserved",
        ),
        "receipt.no_automatic_retry": ("no_automatic_retry", "noAutomaticRetry"),
        "receipt.effect_evidence_status": (
            "effect_evidence_status",
            "effectEvidenceStatus",
        ),
        "receipt.invariant_status": ("invariant_status", "invariantStatus"),
    }
    for predicate, (oracle_key, eye_key) in mapping.items():
        expected = oracle[oracle_key]
        assert values[predicate] == expected
        assert eye_values[eye_key] == (
            str(expected).lower() if isinstance(expected, bool) else str(expected)
        )

    production = _production_shape(gate_id, tmp_path)
    if production is not None:
        rows = _receipt_rows(case.input_document)
        assert production["seqs"] == [row["receipt.seq"] for row in rows]
        assert production["statuses"] == [row["receipt.status"] for row in rows]
        assert production["same_action"] is True
        assert production["dispatch_count"] == _single(
            case.input_document, "runtime.dispatch_count"
        )
        assert production["no_automatic_retry"] is True
        assert production["terminal_provisional"] is True
    if gate_id == "P2-G5-09":
        assert production is not None
        assert production["result_status"] == "rejected"
        assert production["terminal_retry_reason"] == "duplicate_action_id"
    if gate_id == "P2-G5-10":
        assert production is not None
        assert production["result_status"] == "failed"
        assert str(production["terminal_retry_reason"]).startswith("dispatch_error:")


def test_g5_receipt_terminal_to_running_is_violation_without_reordering() -> None:
    gate = next(gate for gate in _receipt_gates() if gate["gate_id"] == "P2-G5-09")
    case = build_case(gate)
    mutated = copy.deepcopy(case.input_document)
    third_status = [
        fact for fact in mutated["facts"] if fact["predicate"] == "receipt.status"
    ][-1]
    assert third_status["value"] == "rejected"
    third_status["value"] = "running"
    rows_before = _receipt_rows(mutated)
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=mutated)
    rows_after = _receipt_rows(mutated)
    values = _typed_values(result)
    assert rows_after == rows_before
    assert values["receipt.sequence_monotonic"] is True
    assert values["receipt.transition_valid"] is False
    assert values["receipt.invariant_status"] == "violation"


def test_g5_receipt_automatic_retry_is_reported_not_normalized() -> None:
    gate = next(gate for gate in _receipt_gates() if gate["gate_id"] == "P2-G5-10")
    case = build_case(gate)
    mutated = copy.deepcopy(case.input_document)
    retry_fact = next(
        fact
        for fact in mutated["facts"]
        if fact["predicate"] == "receipt.retry.automatic_retry_performed"
    )
    retry_fact["value"] = True
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=mutated)
    values = _typed_values(result)
    assert retry_fact["value"] is True
    assert values["receipt.no_automatic_retry"] is False
    assert values["receipt.invariant_status"] == "violation"


def test_g5_receipt_dispatch_count_violation_never_rewrites_runtime_fact() -> None:
    gate = next(gate for gate in _receipt_gates() if gate["gate_id"] == "P2-G5-13")
    case = build_case(gate)
    runtime_fact = next(
        fact
        for fact in case.input_document["facts"]
        if fact["predicate"] == "runtime.dispatch_count"
    )
    assert runtime_fact["value"] == 2
    result = evaluate_rulepack(
        rulepack_document=case.rulepack,
        input_document=case.input_document,
    )
    assert runtime_fact["value"] == 2
    values = _typed_values(result)
    assert values["receipt.single_dispatch_preserved"] is False
    assert values["receipt.invariant_status"] == "violation"
    assert not any(
        str(fact["predicate"]).startswith("runtime.") for fact in result["derived_facts"]
    )


def test_g5_receipt_ok_never_mints_task_or_goal_completion() -> None:
    gate = next(gate for gate in _receipt_gates() if gate["gate_id"] == "P2-G5-11")
    case = build_case(gate)
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    predicates = {str(fact["predicate"]) for fact in result["derived_facts"]}
    assert "task_complete" not in predicates
    assert "goal_complete" not in predicates


def test_g5_receipt_same_input_is_byte_deterministic_and_provenance_is_mechanical() -> None:
    gate = next(gate for gate in _receipt_gates() if gate["gate_id"] == "P2-G5-09")
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


def test_g5_receipt_rules_module_has_no_runtime_effect_authority_import() -> None:
    tree = ast.parse(RULES_PATH.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(name.startswith("llm_loop.browser.action") for name in imported)
    assert not any(name.startswith("llm_loop.core.tool_execution_journal") for name in imported)


def test_g5_receipt_bridge_has_no_dynamic_rule_query_or_effect_surface() -> None:
    source = G5_RECEIPT_BRIDGE.read_text(encoding="utf-8")
    assert "request.rules" not in source
    assert "request.query" not in source
    assert "rules.n3" in source
    assert "query.n3" in source
    assert "--restricted" in source
    for forbidden in ("reserve(", "dispatch(", "append(", "retry("):
        assert forbidden not in source
