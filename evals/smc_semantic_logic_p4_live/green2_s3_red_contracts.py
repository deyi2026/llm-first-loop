"""Deterministic pre-GREEN probes for P4-LIVE GREEN-2 slice G2-S3."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from llm_loop.browser.action import BrowserActionReceiptStore  # noqa: E402
from llm_loop.browser.action_ref_execution import ActionRefExecutionBridgeStore  # noqa: E402
from llm_loop.core.tool_execution_journal import ToolExecutionJournal  # noqa: E402

EXPECTED_PATH = Path(__file__).with_name("GREEN2-S3-EXPECTED-FAILURES.v0.1.json")
RECOVERY_MODULE = "llm_loop.browser.action_ref_recovery"


@dataclass(frozen=True)
class S3ProbeResult:
    row_id: str
    contract_satisfied: bool
    failure_code: str
    detail: str
    facts: dict[str, Any]


def load_expected_failures() -> dict[str, dict[str, str]]:
    doc = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    return {str(row["id"]): dict(row) for row in doc["rows"]}


S3_RED_IDS = tuple(load_expected_failures())


def _recovery_module_facts() -> dict[str, Any]:
    spec = importlib.util.find_spec(RECOVERY_MODULE)
    facts = {
        "recovery_module_present": spec is not None,
        "correlator_present": False,
        "decision_present": False,
        "has_search_or_rebind_surface": False,
    }
    if spec is None:
        return facts
    module = importlib.import_module(RECOVERY_MODULE)
    facts["correlator_present"] = hasattr(module, "ActionRefCrashCorrelator")
    facts["decision_present"] = hasattr(module, "ActionRefRecoveryDecision")
    source = inspect.getsource(module)
    facts["has_search_or_rebind_surface"] = any(
        token in source
        for token in (
            "selector",
            "similarity",
            "latest_target",
            "successor",
            "search_target",
            "rebind_target",
        )
    )
    return facts


def probe_r16_receipt_cursor() -> S3ProbeResult:
    bridge_has_cursor_write = hasattr(ActionRefExecutionBridgeStore, "prepare_receipt_cursor")
    bridge_has_cursor_load = hasattr(ActionRefExecutionBridgeStore, "load_receipt_cursor")
    s1_no_running = hasattr(
        ActionRefExecutionBridgeStore, "classify_prepared_without_browser_running"
    )
    receipt_exact_history = hasattr(BrowserActionReceiptStore, "list_action")
    satisfied = bridge_has_cursor_write and bridge_has_cursor_load and s1_no_running and receipt_exact_history
    return S3ProbeResult(
        row_id="G2S3-R16-RECEIPT-CURSOR",
        contract_satisfied=satisfied,
        failure_code="contract_present" if satisfied else "actionref_exact_receipt_cursor_absent",
        detail="S3 requires an immutable execution-specific receipt baseline before Browser entry",
        facts={
            "s1_prepared_no_running_classifier_present": s1_no_running,
            "browser_exact_action_history_present": receipt_exact_history,
            "bridge_receipt_cursor_write_present": bridge_has_cursor_write,
            "bridge_receipt_cursor_load_present": bridge_has_cursor_load,
        },
    )


def probe_r17_running_correlation() -> S3ProbeResult:
    recovery = _recovery_module_facts()
    recover_source = inspect.getsource(ToolExecutionJournal.recover)
    journal_hook = "action_ref_recovery" in recover_source or "action_ref_correl" in recover_source
    satisfied = bool(
        recovery["recovery_module_present"]
        and recovery["correlator_present"]
        and recovery["decision_present"]
        and not recovery["has_search_or_rebind_surface"]
        and journal_hook
    )
    return S3ProbeResult(
        row_id="G2S3-R17-RUNNING-CORRELATION",
        contract_satisfied=satisfied,
        failure_code="contract_present" if satisfied else "actionref_running_crash_correlator_absent",
        detail="Outer WAL recover lacks an exact ActionRef Browser-running correlation hook",
        facts={**recovery, "tool_journal_actionref_recovery_hook_present": journal_hook},
    )


def probe_r18_terminal_correlation() -> S3ProbeResult:
    recovery = _recovery_module_facts()
    recover_source = inspect.getsource(ToolExecutionJournal.recover)
    recovery_source = ""
    if recovery["recovery_module_present"]:
        recovery_source = inspect.getsource(importlib.import_module(RECOVERY_MODULE))
    exact_terminal_settlement = (
        "action_ref_recovery" in recover_source
        and "browser_terminal_exact" in recovery_source
        and "terminal_receipt" in recovery_source
        and "auto_reexecuted" in recovery_source
    )
    satisfied = bool(
        recovery["recovery_module_present"]
        and recovery["correlator_present"]
        and not recovery["has_search_or_rebind_surface"]
        and exact_terminal_settlement
    )
    return S3ProbeResult(
        row_id="G2S3-R18-TERMINAL-CORRELATION",
        contract_satisfied=satisfied,
        failure_code="contract_present" if satisfied else "actionref_terminal_wal_recovery_absent",
        detail="Outer WAL recover cannot yet settle from the exact bound terminal Browser receipt",
        facts={**recovery, "tool_journal_exact_terminal_settlement_present": exact_terminal_settlement},
    )


PROBES = {
    "G2S3-R16-RECEIPT-CURSOR": probe_r16_receipt_cursor,
    "G2S3-R17-RUNNING-CORRELATION": probe_r17_running_correlation,
    "G2S3-R18-TERMINAL-CORRELATION": probe_r18_terminal_correlation,
}


def run_probe(row_id: str) -> S3ProbeResult:
    try:
        return PROBES[row_id]()
    except Exception as exc:  # noqa: BLE001 - harness faults cannot qualify RED.
        return S3ProbeResult(
            row_id=row_id,
            contract_satisfied=False,
            failure_code="harness_error",
            detail=f"{type(exc).__name__}: {exc}",
            facts={"exception_type": type(exc).__name__},
        )
