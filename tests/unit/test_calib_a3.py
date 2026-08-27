from __future__ import annotations

import json
from pathlib import Path

from scripts.calib.fixtures_a3 import (
    INITIAL_PACKETS_A3,
    ORACLES_A3,
    SOURCE_LIMIT_A3,
    TWO_SOURCE_SEEDS_A3,
)
from scripts.calib.runner_a3 import (
    A3_VARIANTS,
    build_system_prompt_a3,
    execute_run_a3,
    guard_config_for,
)
from scripts.calib.treatments import build_task_prompt

ROOT = Path(__file__).resolve().parent.parent.parent
MATRIX = ROOT / "data/calib/a3_matrix_v1.json"


def test_shape():
    assert len(INITIAL_PACKETS_A3) == 8 and len(A3_VARIANTS) == 4 and SOURCE_LIMIT_A3 == 2


def test_new_seed_ids():
    assert set(INITIAL_PACKETS_A3) == {f"I{i:02d}" for i in range(1, 9)}


def test_sources_and_two_source_controls():
    assert {"I03", "I04", "I07"} == TWO_SOURCE_SEEDS_A3
    for s, o in ORACLES_A3.items():
        avail = set(INITIAL_PACKETS_A3[s]["sources"])
        assert 1 <= len(o["expected_sources"]) <= 2
        assert set(o["expected_sources"]) <= avail
        assert o["novel_signal"]["source"] in avail
        assert (len(o["expected_sources"]) == 2) == (s in TWO_SOURCE_SEEDS_A3)


def test_no_truth_hint():
    for p in INITIAL_PACKETS_A3.values():
        assert p["candidate_truth"].startswith("未提供")


def test_all_treatments_prompt_identical():
    assert len({build_system_prompt_a3(v) for v in A3_VARIANTS}) == 1


def test_guard_configs_distinct():
    assert len({guard_config_for(v) for v in A3_VARIANTS}) == 4


def test_variant_blind_task():
    for s in INITIAL_PACKETS_A3:
        assert len({build_task_prompt(s, INITIAL_PACKETS_A3) for _ in A3_VARIANTS}) == 1


def test_matrix():
    m = json.loads(MATRIX.read_text())
    assert len(m["rows"]) == 64 and m["randomization_seed"] == 202608261500
    assert len({(r["provider"], r["seed"], r["variant"]) for r in m["rows"]}) == 64
    for p in ["minimax", "deepseek"]:
        for s in INITIAL_PACKETS_A3:
            assert {
                r["variant"] for r in m["rows"] if r["provider"] == p and r["seed"] == s
            } == set(A3_VARIANTS)


def test_secondary_preselected():
    m = json.loads(MATRIX.read_text())
    sel = set(m["secondary_review_runs"])
    by = {r["run_id"]: r for r in m["rows"]}
    assert len(sel) == 8
    for p in ["minimax", "deepseek"]:
        for v in A3_VARIANTS:
            assert sum(by[x]["provider"] == p and by[x]["variant"] == v for x in sel) == 1


def test_dry_all_variants_complete_and_preserve_required_sources():
    import scripts.calib.fixtures_a3 as f

    data = type(
        "D",
        (),
        {
            "ORACLES": ORACLES_A3,
            "INITIAL_PACKETS": INITIAL_PACKETS_A3,
            "SOURCE_LIMIT": 2,
            "UNAVAILABLE_RESPONSE": "SOURCE_NOT_AVAILABLE",
            "LIMIT_EXCEEDED_RESPONSE": "SOURCE_LIMIT_EXCEEDED",
            "lookup_source": staticmethod(f.lookup_source_a3),
        },
    )()
    for v in A3_VARIANTS:
        o = execute_run_a3(f"DRY-{v}", "I03", v, dry=True, provider="minimax", data=data)
        assert o["status"] == "COMPLETED"
        assert o["tool_execution_count"] == 2
        assert o["requested_sources"] == ORACLES_A3["I03"]["expected_sources"]
