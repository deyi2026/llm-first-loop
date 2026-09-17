from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = ROOT / "docs/SMC-SEMANTIC-LOGIC-P3-SHADOW-PROTOCOL-v0.1.json"
QUALIFICATION_PATH = ROOT / "tools/semantic_logic/p3_shadow_qualification.py"
PROTOCOL = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _qualification() -> dict[str, Any]:
    assert QUALIFICATION_PATH.is_file(), "P3 qualification helper is not implemented yet"
    return runpy.run_path(str(QUALIFICATION_PATH))


def test_p3_protocol_freezes_required_shadow_only_surface() -> None:
    assert PROTOCOL["schema"] == "smc.semantic_logic_p3_shadow_protocol.v0.1"
    assert PROTOCOL["status"] == "frozen_shadow_only"
    assert PROTOCOL["authority"] == "shadow_only"
    assert PROTOCOL["production_consumed"] is False
    assert PROTOCOL["provider_visible_change"] is False
    assert PROTOCOL["mutation_authority_change"] is False
    assert PROTOCOL["hidden_recapture_for_shadow"] is False
    categories = {str(case["category"]) for case in PROTOCOL["cases"]}
    assert set(PROTOCOL["required_categories"]) <= categories
    assert len(PROTOCOL["cases"]) == 14
    assert len({case["fixture_id"] for case in PROTOCOL["cases"]}) == 14
    assert PROTOCOL["comparison_contract"] == {
        "same_observation_only": True,
        "mismatch_is_red": True,
        "semantic_normalization_forbidden": True,
        "opaque_identity_exclusion_only": True,
        "required_shadow_result_fields": [
            "fixture_id",
            "gate_id",
            "baseline_ref",
            "oracle_result_hash",
            "shadow_result_hash",
            "equivalent",
            "mismatch_paths",
            "derivation_refs",
        ],
    }


def test_p3_shadow_qualification_is_equivalent_and_closed(tmp_path: Path) -> None:
    result = _qualification()["qualify_manifest"](PROTOCOL, tmp_path / "run")
    assert result["schema"] == "smc.semantic_logic_p3_shadow_result.v0.1"
    assert result["status"] == "PASS"
    assert result["authority"] == "shadow_only"
    assert result["production_consumed"] is False
    assert len(result["cases"]) == len(PROTOCOL["cases"])
    required = set(PROTOCOL["comparison_contract"]["required_shadow_result_fields"])
    for case in result["cases"]:
        assert required <= set(case)
        assert case["equivalent"] is True
        assert case["oracle_result_hash"] == case["shadow_result_hash"]
        assert case["mismatch_paths"] == []
        assert case["derivation_refs"]
        assert case["proof_coverage"] == 1.0
    assert result["metrics"] == {
        "case_count": 14,
        "equivalent_count": 14,
        "false_closure": 0,
        "silent_rebind": 0,
        "unknown_to_false": 0,
        "proof_coverage": 1.0,
    }


def test_p3_shadow_result_is_deterministic_across_fresh_stores(tmp_path: Path) -> None:
    qualify = _qualification()["qualify_manifest"]
    first = qualify(PROTOCOL, tmp_path / "a")
    second = qualify(PROTOCOL, tmp_path / "b")
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )


def test_p3_helper_is_qualification_only_and_adds_no_production_consumer() -> None:
    source = QUALIFICATION_PATH.read_text(encoding="utf-8") if QUALIFICATION_PATH.is_file() else ""
    assert "src/llm_loop/factory.py" not in source
    assert "register(" not in source
    assert "provider" not in source.lower()
    assert "task_complete" not in source
    assert "goal_complete" not in source
    consumers = []
    for path in (ROOT / "src/llm_loop").rglob("*.py"):
        if "semantic_logic" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "llm_loop.semantic_logic" in text or "from llm_loop import semantic_logic" in text:
            consumers.append(str(path.relative_to(ROOT)))
    assert consumers == []
