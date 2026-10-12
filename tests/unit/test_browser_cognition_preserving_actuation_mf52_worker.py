from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "evals/browser_smc_cognition_preserving_actuation_mf52"
sys.path.insert(0, str(EVAL))
spec = importlib.util.spec_from_file_location("mf52_worker", EVAL / "worker.py")
assert spec is not None and spec.loader is not None
worker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = worker
spec.loader.exec_module(worker)


def _append_tool_event(path: Path, doc: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "type": "message.appended",
        "payload": {
            "role": "tool",
            "tool_name": "browser_semantic_operation",
            "content": json.dumps(doc),
        },
    }
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")


def test_compact_navigate_boundary_event_is_not_classified_as_undeclared(tmp_path: Path) -> None:
    sid = "s-navigate"
    _append_tool_event(
        tmp_path / "event_logs" / f"{sid}.jsonl",
        {
            "schema": "smc.browser_semantic_operation_compact_receipt.v0.1",
            "status": "completed",
            "boundary_events": ["navigation_started"],
            "task_completion": "not_evaluated",
            "automatic_retry": False,
        },
    )
    facts = worker._operation_message_facts(tmp_path, sid)
    assert facts["operation_receipt_count"] == 1
    assert facts["operation_unparsed_result_count"] == 0
    assert "undeclared_boundary_continuation_count" not in facts
    assert "undeclared_boundary_halt_count" not in facts


def test_full_receipt_is_authority_for_undeclared_boundary_continuation(tmp_path: Path) -> None:
    root = tmp_path / "browser_semantic_operation" / "owner"
    root.mkdir(parents=True)
    doc = {
        "schema": "smc.browser_semantic_operation_full_receipt.v0.1",
        "content": {
            "execution_status": "halted",
            "halt_reason": "undeclared_structural_transition",
            "clauses": [
                {
                    "index": 1,
                    "kind": "mutate",
                    "verb": "click",
                    "action_receipt": {"boundary_events": ["new_page"]},
                }
            ],
        },
    }
    (root / "r.json").write_text(json.dumps(doc), encoding="utf-8")
    facts = worker._full_operation_receipt_facts(tmp_path)
    assert facts["undeclared_boundary_halt_count"] == 1
    assert facts["undeclared_boundary_continuation_count"] == 0
