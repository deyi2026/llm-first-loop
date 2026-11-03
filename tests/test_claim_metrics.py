"""T-1.11 claim_metrics 口径验收：分母为空时必须是 None，不是 0."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.claim_metrics import compute


def _write(audit: Path, rows: list[dict]) -> None:
    d = audit / "claims"
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


def test_empty_audit_yields_null_rates_not_zero(tmp_path):
    result = compute(tmp_path)
    assert result["claim"]["grant_rate"] is None
    assert result["fanout"]["deny_rate"] is None
    assert result["degraded"] is False


def test_rates_and_conflict_denominator(tmp_path):
    _write(
        tmp_path,
        [
            {"kind": "claim_decision", "decision": "grant", "claim_generation": 1},
            {"kind": "claim_decision", "decision": "renew", "claim_generation": 1},
            {"kind": "claim_decision", "decision": "passthrough", "claim_generation": 0,
             "reason_code": "claim_held_by_other"},
            {"kind": "claim_decision", "decision": "passthrough", "claim_generation": 0},
            {"kind": "fanout_decision", "decision": "allow"},
            {"kind": "fanout_decision", "decision": "deny", "reason_code": "parent_concurrency"},
        ],
    )
    result = compute(tmp_path)
    assert result["events"]["claim_decision"] == 4
    assert result["claim"]["unprotected_write_share"] == 0.5
    # 冲突率只在不带 token 的写入里算 → 1/2，而不是 1/4
    assert result["claim"]["conflict_rate_of_unprotected"] == 0.5
    assert result["fanout"]["deny_rate"] == 0.5
    assert result["fanout"]["parent_concurrency_deny_rate"] == 0.5


def test_bad_line_marks_degraded(tmp_path):
    d = tmp_path / "claims"
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text('{"kind":"claim_decision","decision":"grant"}\n{"broken\n', encoding="utf-8")
    result = compute(tmp_path)
    assert result["degraded"] is True
    assert result["events"]["bad_lines"] == 1
    assert any("下界" in n for n in result["notes"])
