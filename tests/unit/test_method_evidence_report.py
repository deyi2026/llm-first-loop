from __future__ import annotations

import json
from pathlib import Path

from llm_loop.methods.evidence_report import build_report


def _card(root: Path, name: str, status: str, body: str = "body") -> None:
    path = root / name / "METHOD.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nmethod_id: {name}\nstatus: {status}\n---\n{body}\n", encoding="utf-8")


def test_body_status_is_excluded_and_seed_pool_stays_separate(tmp_path: Path) -> None:
    runtime, seed = tmp_path / "runtime", tmp_path / "seed"
    _card(runtime, "held", "hold", "old evidence\nstatus: candidate")
    _card(runtime, "retired", "retired")
    _card(seed, "held", "active")
    report = build_report(runtime, seed)
    assert report["runtime"]["valid_cards"] == 2
    assert report["runtime"]["statuses"] == {"hold": 1, "retired": 1}
    assert report["runtime"]["body_status_lines_excluded"] == 1
    assert report["seed"]["statuses"] == {"active": 1}


def test_declared_use_is_neither_execution_nor_verified_benefit(tmp_path: Path) -> None:
    _card(tmp_path, "m1", "candidate")
    entry = {"method_ref": "method:m1", "decision": "applied", "application_proven": True,
             "episode_ref": "episode:s:1:a", "method_content_hash": "abc"}
    (tmp_path / "usage.jsonl").write_text(json.dumps(entry) + "\nbad json\n[]\n", encoding="utf-8")
    report = build_report(tmp_path)
    assert report["declarations"]["valid_rows"] == 1
    assert report["declarations"]["invalid_lines"] == [2, 3]
    assert report["funnel"]["decision"] == {"state": "partial", "count": 1}
    assert report["funnel"]["executed"]["count"] is None
    assert report["funnel"]["benefit"]["count"] is None


def test_missing_ledger_and_invalid_card_are_explicit(tmp_path: Path) -> None:
    _card(tmp_path, "bad", "made_up")
    report = build_report(tmp_path)
    assert report["runtime"]["files"] == 1
    assert report["runtime"]["invalid"] == ["bad/METHOD.md"]
    assert report["declarations"]["state"] == "missing"
    assert report["funnel"]["decision"]["state"] == "missing"
    assert report["funnel"]["decision"]["count"] is None
