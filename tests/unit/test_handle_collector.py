"""P1-B regression: automatic handle-to-tool selection is retired."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def test_handle_collector_module_is_retired():
    root = Path(__file__).resolve().parents[2]
    assert not (root / "src/llm_loop/tools/capability_requirements.py").exists()
    assert importlib.util.find_spec("llm_loop.tools.capability_requirements") is None


def test_run_state_has_no_handle_selection_state():
    from llm_loop.core.loop.runstate import _RunState

    state = _RunState()
    for field in (
        "capability_requirement_registry",
        "capability_reachability_auditor",
        "capability_called_last",
        "capability_rule_review",
        "capability_handle_source_state",
        "tool_promotion_state",
    ):
        assert not hasattr(state, field)


def test_production_does_not_probe_handles_to_choose_tools():
    root = Path(__file__).resolve().parents[2] / "src" / "llm_loop"
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in root.rglob("*.py"))
    for symbol in (
        "HandleCollector",
        "evolution_store_names",
        "job_registry_names",
        "active_evidence_names",
        "task_context_names_from_store",
    ):
        assert symbol not in text
