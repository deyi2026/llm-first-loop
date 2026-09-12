from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = Path(__file__).with_name("smx_focused_v1_2.json")
PLAN = Path(__file__).with_name("smx_focused_plan_v1_2.json")
DIFF = Path(__file__).with_name("smx_focused_v1_2_diff_from_v1_1.json")
V11_PLAN_ROWS_CANON_SHA256 = "cdac602f6e5b757ec1ee869eebc67c7506ac5f84fbc7ee8b9c55d223fe081414"
V11_CAUSAL_DESIGN_CANON_SHA256 = "7ea2738f77f9fb2de5e4b89d3025981e9f49a80a867f9a48f499d89c5695bdf0"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canon_sha(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def test_smx_focused_v12_protocol_shape_is_frozen() -> None:
    doc = _read(SPEC)
    assert doc["protocol"] == "agentpilot-smx-focused-v1.2"
    assert doc["status"] == "frozen_not_executed"
    assert doc["supersedes"]["protocol"] == "agentpilot-smx-focused-v1.1"
    assert doc["supersedes"]["disposition"] == "deprecated_superseded"
    assert doc["planned_runs"] == 30
    assert doc["repeats"] == 3
    assert len(doc["tasks"]) == 5
    assert len(doc["arms"]) == 2


def test_smx_focused_v12_source_hashes_match_current_tree() -> None:
    for rel, expected in _read(SPEC)["source_sha256"].items():
        actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        assert actual == expected, rel


def test_smx_focused_v12_plan_is_complete_balanced_and_hashed() -> None:
    doc = _read(SPEC)
    plan_bytes = PLAN.read_bytes()
    assert hashlib.sha256(plan_bytes).hexdigest() == doc["execution_plan_sha256"]
    plan = json.loads(plan_bytes)
    assert plan["protocol"] == "agentpilot-smx-focused-v1.2"
    rows = plan["rows"]
    assert len(rows) == 30
    assert [r["plan_index"] for r in rows] == list(range(30))
    blocks: dict[tuple[str, int], list[str]] = {}
    for row in rows:
        blocks.setdefault((row["task_id"], row["repeat"]), []).append(row["arm"] )
    assert len(blocks) == 15
    assert all(sorted(arms) == ["lfl_smx_off", "lfl_smx_on"] for arms in blocks.values())
    first_arms = [rows[i]["arm"] for i in range(0, len(rows), 2)]
    assert sorted((first_arms.count("lfl_smx_off"), first_arms.count("lfl_smx_on"))) == [7, 8]


def test_smx_focused_v12_causal_design_and_plan_rows_are_v11_identical() -> None:
    doc = _read(SPEC)
    plan = _read(PLAN)
    semantic_keys = [
        "arms", "invalidation", "planned_runs", "repeats",
        "required_execution_manifest", "schema", "seed", "tasks",
    ]
    semantic = {k: doc[k] for k in semantic_keys}
    assert _canon_sha(plan["rows"]) == V11_PLAN_ROWS_CANON_SHA256
    assert _canon_sha(semantic) == V11_CAUSAL_DESIGN_CANON_SHA256
    assert doc["differential_invariants"]["v1_1_plan_rows_canonical_sha256"] == V11_PLAN_ROWS_CANON_SHA256
    assert doc["differential_invariants"]["v1_2_plan_rows_canonical_sha256"] == V11_PLAN_ROWS_CANON_SHA256
    assert doc["differential_invariants"]["v1_1_causal_design_canonical_sha256"] == V11_CAUSAL_DESIGN_CANON_SHA256
    assert doc["differential_invariants"]["v1_2_causal_design_canonical_sha256"] == V11_CAUSAL_DESIGN_CANON_SHA256


def test_smx_focused_v12_differential_proof_is_narrow_and_self_consistent() -> None:
    proof = _read(DIFF)
    spec = _read(SPEC)
    assert proof["from"]["protocol"] == "agentpilot-smx-focused-v1.1"
    assert proof["to"]["protocol"] == "agentpilot-smx-focused-v1.2"
    assert proof["causal_design"]["identical"] is True
    assert proof["plan_rows"]["identical"] is True
    assert proof["plan_rows"]["row_count"] == 30
    assert proof["changed_source_files"] == ["evals/pilot/analyze.py"]
    assert proof["changed_source_count"] == 1
    assert proof["unchanged_source_count"] == 17
    assert proof["governance_assertions"]["v1_2_model_run_authorized"] is False
    rows = {r["path"]: r for r in proof["source_hashes"]}
    assert set(rows) == set(spec["source_sha256"])
    for rel, expected in spec["source_sha256"].items():
        assert rows[rel]["v1_2_sha256"] == expected
    assert rows["evals/pilot/analyze.py"]["status"] == "changed"
    assert all(r["status"] == "same" for p, r in rows.items() if p != "evals/pilot/analyze.py")


def test_smx_focused_v12_analyzer_uses_actual_continuity_key() -> None:
    source = (ROOT / "evals/pilot/analyze.py").read_text(encoding="utf-8")
    assert 'r.get("resume_session_continuity")' in source
    assert 'r.get("session_continuity")' not in source
