import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals.methodcard_rsi_v1 import grade_holdout as gh  # noqa: E402


def _cases():
    cases, sha = gh.load_cases()
    return {c["id"]: c for c in cases}, sha


def test_freeze_matches_current_file():
    _, sha = gh.load_cases()
    assert len(sha) == 64


def test_grader_accepts_synthetic_artifacts(tmp_path):
    cases, _ = _cases()
    for cid, case in cases.items():
        (tmp_path / f"{cid}.json").write_text(json.dumps(gh._synthesize(case), ensure_ascii=False), encoding="utf-8")
    res = gh.grade(tmp_path)
    assert res["passed"] == res["total"] == 20
    assert res["missing"] == []


def test_missing_artifact_fails(tmp_path):
    cases, _ = _cases()
    for cid, case in cases.items():
        if cid == "H03":
            continue
        (tmp_path / f"{cid}.json").write_text(json.dumps(gh._synthesize(case), ensure_ascii=False), encoding="utf-8")
    res = gh.grade(tmp_path)
    assert res["passed"] == 19
    assert res["missing"] == ["H03"]


def test_forbidden_phrase_detected():
    cases, _ = _cases()
    art = gh._synthesize(cases["H14"])
    art["note"] = "基本完成，rc=0 说明命令执行成功即通过"
    res = gh.check_one(cases["H14"], art)
    # H14 没有 regex_absent，换用 H01 的禁用语验证扫描面
    art2 = gh._synthesize(cases["H01"])
    art2["verdict"] = "应该生效"
    res2 = gh.check_one(cases["H01"], art2)
    assert any((not r["pass"]) and "禁用语" in r["detail"] for r in res2)
    assert all(r["pass"] for r in res if r["kind"] != "eq")


def test_ref_out_of_range_rejected():
    cases, _ = _cases()
    art = gh._synthesize(cases["H01"])
    art["evidence_refs"] = ["cache_manager.py:999"]
    res = gh.check_one(cases["H01"], art)
    ref = [r for r in res if r["kind"] == "ref_resolves"][0]
    assert ref["pass"] is False
    assert "行号越界" in ref["detail"]


def test_freeze_drift_refused(tmp_path, monkeypatch):
    freeze = json.loads((ROOT / "evals/methodcard_rsi_v1/FREEZE.json").read_text(encoding="utf-8"))
    freeze["sha256"] = "0" * 64
    bad = tmp_path / "FREEZE.json"
    bad.write_text(json.dumps(freeze), encoding="utf-8")
    monkeypatch.setattr(gh, "FREEZE", bad)
    with pytest.raises(SystemExit) as e:
        gh.load_cases()
    assert "FREEZE" in str(e.value)
