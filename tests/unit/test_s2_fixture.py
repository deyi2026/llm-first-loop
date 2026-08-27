import json
from pathlib import Path

from scripts.calib.fixtures_s2 import INITIAL_PACKETS_S2, ORACLES_S2, SOURCES_S2

ROOT = Path(__file__).resolve().parents[2]


def test_s2_seeds_and_sources_are_complete():
    assert (
        set(INITIAL_PACKETS_S2)
        == set(ORACLES_S2)
        == set(SOURCES_S2)
        == {f"E{i:02d}" for i in range(1, 9)}
    )
    for seed, o in ORACLES_S2.items():
        assert o["novel_signal"]["source"] in SOURCES_S2[seed]
        assert set(o["expected_sources"]) <= set(SOURCES_S2[seed])
        assert len(INITIAL_PACKETS_S2[seed]["sources"]) >= 2


def test_s2_matrix_is_balanced_and_secondary_sample_stratified():
    m = json.loads((ROOT / "data/calib/s2_matrix_v1.json").read_text())
    rows = m["rows"]
    assert len(rows) == 48
    for p in ["minimax", "deepseek"]:
        for v in ["V0-Baseline", "V1-Contract", "V2-Full"]:
            rr = [r for r in rows if r["provider"] == p and r["variant"] == v]
            assert len(rr) == 8
            selected = [x for x in m["secondary_review_runs"] if any(r["run_id"] == x for r in rr)]
            assert len(selected) == 2
