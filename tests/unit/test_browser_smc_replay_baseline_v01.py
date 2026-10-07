"""Unit tests for the M6 replay baseline aggregation (FR-5c/Q6).

Locks the pre-registered metric definitions on a synthetic mixed-era corpus:
legacy receipts (no guard/wait/diff_summary) must stay in not_recorded buckets
and never fold into verdict counts; new-era receipts classify guard
pass/pass_exempted/reject_timeout, wait settled/timeout, and receipt
diff_summary comparable classes; diff resolution handles doc_missing and the
anomaly cap.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "browser_smc_replay_baseline_v01"
    / "replay_baseline.py"
)
_spec = importlib.util.spec_from_file_location("replay_baseline", _SCRIPT)
rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rb)


def _receipt(seq: int, **overrides) -> dict:
    row = {
        "schema": "smc.action_receipt.v0.1",
        "action_id": f"sact-{seq:04d}",
        "receipt_id": f"rcp_x_{seq:04d}",
        "receipt_seq": seq,
        "status": "ok",
        "verb": "click",
        "before_version": "bsnap-1-from0000",
        "after_version": "bsnap-1-to0000",
        "completeness": {"complete": False, "reasons": []},
        "observed_effects": {
            "diff_ref": "grounding://browser/v0.1/bsnap-1-to0000/diff/bsnap-1-from0000",
            "provisional": True,
        },
        "retry": {"attempt_count": 1, "automatic_retry_performed": False, "reason": None},
    }
    row.update(overrides)
    return row


def _diff_doc(comparable: bool, reason: str | None = None) -> dict:
    cd = {
        "from_version": "bsnap-1-from0000",
        "to_version": "bsnap-1-to0000",
        "comparable": comparable,
    }
    if reason is not None:
        cd["reason"] = reason
    return {"schema": "smc.browser_diff_grounding.v0.1", "canonical_diff": cd}


def _corpus() -> dict:
    actions = [
        # legacy ok: 2 captures, comparable diff
        {"session": "s1", "action_hash": "a1", "rows": [_receipt(1)]},
        # new-era ok: guard pass (no exemption), wait settled, summary comparable
        {
            "session": "s1",
            "action_hash": "a2",
            "rows": [
                _receipt(1, status="running", before_version=None, after_version=None, observed_effects={"diff_ref": None, "provisional": True}),
                _receipt(
                    2,
                    guard={"schema": "smc.browser_guard_verdict.v0.1", "verdict": "pass"},
                    wait={"schema": "smc.browser_wait_verdict.v0.1", "verdict": "settled"},
                    observed_effects={
                        "diff_ref": "grounding://browser/v0.1/bsnap-1-to0001/diff/bsnap-1-from0001",
                        "provisional": False,
                        "diff_summary": {"schema": "smc.browser_diff_summary.v0.1", "comparable": True},
                    },
                ),
            ],
        },
        # new-era ok: guard pass + exempted (FR-1 exemption observable), wait timeout
        {
            "session": "s1",
            "action_hash": "a3",
            "rows": [
                _receipt(
                    2,
                    before_version="bsnap-1-from0002",
                    after_version="bsnap-1-to0002",
                    guard={
                        "schema": "smc.browser_guard_verdict.v0.1",
                        "verdict": "pass",
                        "exempted": True,
                        "exemption_reason": "version_mismatch_semantics_stable",
                    },
                    wait={"schema": "smc.browser_wait_verdict.v0.1", "verdict": "timeout"},
                    observed_effects={
                        "diff_ref": "grounding://browser/v0.1/bsnap-1-to0002/diff/bsnap-1-from0002",
                        "provisional": False,
                        "diff_summary": {"schema": "smc.browser_diff_summary.v0.1", "comparable": False},
                    },
                ),
            ],
        },
        # guard reject (timeout): pre-capture rejection, 0 captures
        {
            "session": "s1",
            "action_hash": "a4",
            "rows": [
                _receipt(
                    1,
                    status="rejected",
                    before_version=None,
                    after_version=None,
                    guard={
                        "schema": "smc.browser_guard_verdict.v0.1",
                        "verdict": "reject",
                        "reason": "guard_timeout:TimeoutError",
                    },
                    completeness={"complete": False, "reasons": ["guard_rejected"]},
                    observed_effects={"diff_ref": None, "provisional": True},
                ),
            ],
        },
        # failed with diff doc missing
        {
            "session": "s2",
            "action_hash": "a5",
            "rows": [
                _receipt(
                    2,
                    status="failed",
                    before_version="bsnap-1-from0009",
                    after_version="bsnap-1-to0009",
                    retry={"attempt_count": 1, "automatic_retry_performed": False, "reason": "dispatch_error:RuntimeError"},
                    completeness={"complete": False, "reasons": ["dispatch_outcome_ambiguous"]},
                    observed_effects={
                        "diff_ref": "grounding://browser/v0.1/bsnap-1-to0009/diff/bsnap-1-from0009",
                        "provisional": True,
                    },
                ),
            ],
        },
    ]
    diffs = {
        ("bsnap-1-from0000", "bsnap-1-to0000"): _diff_doc(True),
        ("bsnap-1-from0001", "bsnap-1-to0001"): _diff_doc(True),
        ("bsnap-1-from0002", "bsnap-1-to0002"): _diff_doc(False, "document_generation_changed;scope_changed"),
    }
    return {
        "actions": actions,
        "diffs": diffs,
        "cards": [
            {"schema": "x", "content": json.dumps({"execution_status": "halted"})},
            {"schema": "x", "content": json.dumps({"execution_status": "clauses_exhausted"})},
        ],
        "sessions": ["s1", "s2"],
        "malformed_receipt_rows": 0,
        "malformed_diff_docs": 0,
        "malformed_cards": 0,
        "sources": {"receipts_root": "x", "diffs_root": "y", "ops_root": "z"},
    }


def test_action_status_and_captures() -> None:
    report = rb.aggregate(_corpus())
    assert report["verdicts"]["action_status"] == {"failed": 1, "ok": 3, "rejected": 1}
    cps = report["captures_per_step"]
    assert cps["n"] == 5
    assert cps["histogram"] == {0: 1, 2: 4}
    assert cps["mean"] == 1.6
    assert cps["by_status"]["rejected"]["histogram"] == {0: 1}


def test_guard_era_honest_buckets() -> None:
    report = rb.aggregate(_corpus())
    guard = report["verdicts"]["guard"]
    assert guard["recorded"] == {"pass": 1, "pass_exempted": 1, "reject_timeout": 1}
    assert guard["not_recorded"] == 2  # legacy ok + legacy failed (no guard key)


def test_wait_era_honest_buckets() -> None:
    report = rb.aggregate(_corpus())
    wait = report["verdicts"]["wait"]
    assert wait["recorded"] == {"settled": 1, "timeout": 1}
    assert wait["not_recorded"] == 3


def test_diff_comparability_with_doc_missing() -> None:
    report = rb.aggregate(_corpus())
    dc = report["diff_comparability"]
    assert dc["comparable"] == 2
    assert dc["not_comparable"] == 1
    assert dc["doc_missing"] == 1
    assert dc["not_available_no_diff_ref"] == 1
    assert dc["ratio"] == round(2 / 3, 4)
    assert dc["not_comparable_reasons"] == {"document_generation_changed": 1, "scope_changed": 1}


def test_receipt_diff_summary_classes() -> None:
    report = rb.aggregate(_corpus())
    ds = report["receipt_diff_summary"]
    assert ds["recorded"] == {"comparable_false": 1, "comparable_true": 1}
    assert ds["not_recorded"] == 3


def test_anomalies_report_only() -> None:
    report = rb.aggregate(_corpus())
    anomalies = report["anomalies"]
    assert len(anomalies["failed_actions"]) == 1
    assert anomalies["failed_actions"][0]["retry_reason"] == "dispatch_error:RuntimeError"
    assert anomalies["not_comparable_diffs_capped"][0]["reason"] == "document_generation_changed;scope_changed"
    assert "no automatic" in anomalies["policy"]


def test_terminal_row_is_max_seq() -> None:
    action = {
        "session": "s",
        "action_hash": "a",
        "rows": [_receipt(2, status="ok"), _receipt(1, status="running")],
    }
    assert rb.terminal_row(action)["status"] == "ok"


def test_rejection_and_failure_classes() -> None:
    report = rb.aggregate(_corpus())
    assert report["verdicts"]["rejection_classes"] == {"guard_rejected": 1}
    assert report["verdicts"]["failure_reasons"] == {"dispatch_error": 1}
