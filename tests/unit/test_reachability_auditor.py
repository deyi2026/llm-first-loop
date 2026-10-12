"""P1-B regression: reachability is observability, not a rule auditor."""

from __future__ import annotations

from pathlib import Path


def test_reachability_auditor_selection_module_is_absent():
    root = Path(__file__).resolve().parents[2]
    assert not (root / "src/llm_loop/tools/capability_requirements.py").exists()


def test_production_has_no_selection_audit_events():
    root = Path(__file__).resolve().parents[2] / "src" / "llm_loop"
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in root.rglob("*.py"))
    for marker in ("capability.reachability", "capability.rule_review", "tool.promotion"):
        assert marker not in text
