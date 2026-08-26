from __future__ import annotations
import json
from pathlib import Path

from scripts.calib.fixtures_a1 import INITIAL_PACKETS_A1, ORACLES_A1, SOURCE_LIMIT_A1
from scripts.calib.treatments import build_system_prompt, build_task_prompt
from scripts.calib.treatments_a1 import A1_VARIANTS, build_system_prompt_a1
from scripts.calib.runner_a1 import execute_run_a1

ROOT = Path(__file__).resolve().parent.parent.parent
MATRIX = ROOT / "data/calib/a1_matrix_v1.json"


def test_a1_shape():
    assert len(INITIAL_PACKETS_A1) == 8
    assert len(A1_VARIANTS) == 7
    assert SOURCE_LIMIT_A1 == 2


def test_a1_fixture_expected_sources_are_available():
    for seed, oracle in ORACLES_A1.items():
        assert seed in INITIAL_PACKETS_A1
        available = set(INITIAL_PACKETS_A1[seed]["sources"])
        assert 1 <= len(oracle["expected_sources"]) <= 2
        assert set(oracle["expected_sources"]) <= available
        assert oracle["novel_signal"]["source"] in available


def test_a1_has_no_candidate_truth_hint():
    for p in INITIAL_PACKETS_A1.values():
        assert p["candidate_truth"].startswith("未提供")


def test_a1_treatment_reference_identity():
    assert build_system_prompt_a1("A0-Baseline") == build_system_prompt("V0-Baseline")
    assert build_system_prompt_a1("A1-Contract") == build_system_prompt("V1-Contract")
    assert build_system_prompt_a1("A6-Full-Reference") == build_system_prompt("V2-Full")


def test_a1_component_treatments_are_contract_plus_one_block():
    contract = build_system_prompt_a1("A1-Contract")
    for v in A1_VARIANTS[2:6]:
        p = build_system_prompt_a1(v)
        assert p.startswith(contract)
        assert len(p) > len(contract)
        assert len(p) < len(build_system_prompt_a1("A6-Full-Reference"))


def test_a1_task_prompt_is_variant_blind():
    for seed in INITIAL_PACKETS_A1:
        prompts = {build_task_prompt(seed, INITIAL_PACKETS_A1) for _ in A1_VARIANTS}
        assert len(prompts) == 1


def test_a1_matrix_is_complete_and_paired():
    mx = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert mx["randomization_seed"] == 202608261001
    assert len(mx["rows"]) == 112
    keys = {(r["provider"], r["seed"], r["variant"]) for r in mx["rows"]}
    assert len(keys) == 112
    for provider in ["minimax", "deepseek"]:
        for seed in INITIAL_PACKETS_A1:
            assert {r["variant"] for r in mx["rows"] if r["provider"] == provider and r["seed"] == seed} == set(A1_VARIANTS)


def test_a1_secondary_review_is_preselected_one_per_provider_variant():
    mx = json.loads(MATRIX.read_text(encoding="utf-8"))
    selected = set(mx["secondary_review_runs"])
    assert len(selected) == 14
    by_id = {r["run_id"]: r for r in mx["rows"]}
    for provider in ["minimax", "deepseek"]:
        for variant in A1_VARIANTS:
            hits = [rid for rid in selected if by_id[rid]["provider"] == provider and by_id[rid]["variant"] == variant]
            assert len(hits) == 1


def test_a1_dry_runner_restores_historical_prompt_builder():
    import scripts.calib.runner as base
    before = base.build_system_prompt
    o = execute_run_a1("A1-DRY-TEST", "F01", "A2-Contract-DRU", dry=True, provider="minimax", data=type("D", (), {
        "ORACLES": ORACLES_A1,
        "INITIAL_PACKETS": INITIAL_PACKETS_A1,
        "SOURCE_LIMIT": 2,
        "UNAVAILABLE_RESPONSE": "SOURCE_NOT_AVAILABLE",
        "LIMIT_EXCEEDED_RESPONSE": "SOURCE_LIMIT_EXCEEDED",
        "lookup_source": staticmethod(lambda seed, source: __import__('scripts.calib.fixtures_a1', fromlist=['lookup_source_a1']).lookup_source_a1(seed, source)),
    })())
    assert o["status"] == "COMPLETED"
    assert base.build_system_prompt is before
