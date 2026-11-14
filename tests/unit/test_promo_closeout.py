"""promo_closeout.py 回归（D8 审查 R2：幂等重跑 + 收口豁免写侧严格形状）。

覆盖：
- R2 P1：合法幂等重跑不得被写后读门误判 FAIL（跳过路径 write_verify=一致）。
- R2 P1(b)：幂等路径的 --publish-action-id 豁免标记照常写入（不被 gate 吞）。
- R2 P2-1：幂等重跑不重写回执（generated_at 不变 → 台账 sha 与盘上一致）。
- R2 P2-3：豁免标记写侧与读取侧同一严格形状（[A-Za-z0-9._-]+）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROMO_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "promo_closeout.py"


def _public_receipt(tmp_path):
    p = tmp_path / "public.json"
    p.write_text(
        json.dumps(
            {
                "title_match": True,
                "key_strings_all_hit": True,
                "fig_captions_all_hit": True,
                "dims_all_match": True,
                "has_ai_decl": True,
                "tag_count": 2,
                "item_id": "x",
                "url": "https://example.test/a",
                "verified_at": "2026-11-12T18:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )
    return str(p)


def _run_promo(tmp_path, *extra):
    md = tmp_path / "a.md"
    md.write_text("# 标题\n正文", encoding="utf-8")
    return subprocess.run(
        [
            sys.executable, str(PROMO_SCRIPT),
            "--date", "20261112", "--shift", "t1",
            "--md", str(md), "--public-receipt", _public_receipt(tmp_path),
            "--out-dir", str(tmp_path / "receipts"),
            "--data-dir", str(tmp_path / "data"),
            *extra,
        ],
        capture_output=True, text=True, check=False,
    )


def test_idempotent_rerun_keeps_receipts_and_passes_gate(tmp_path):
    """R2 P1：合法幂等重跑不得被写后读门误判 FAIL；R2 P2-1：回执不重写。"""
    r1 = _run_promo(tmp_path)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    receipts = tmp_path / "receipts"
    jp = next(receipts.glob("*-closeout.json"))
    first_bytes = jp.read_bytes()
    ledger = json.loads((receipts / "closeout-ledger.json").read_text(encoding="utf-8"))
    assert "20261112-t1" in ledger

    r2 = _run_promo(tmp_path)
    assert r2.returncode == 0, r2.stdout + r2.stderr  # 原 P1：误判 FAIL 退出 1
    assert "idempotent=True" in r2.stdout
    # P2-1：回执字节级不变（generated_at 未被刷新 → 存储 sha 与盘上一致）
    assert next(receipts.glob("*-closeout.json")).read_bytes() == first_bytes
    ledger2 = json.loads((receipts / "closeout-ledger.json").read_text(encoding="utf-8"))
    assert ledger2["20261112-t1"]["receipt_sha256"] == ledger["20261112-t1"]["receipt_sha256"]


def test_idempotent_rerun_still_writes_dismissal(tmp_path):
    """R2 P1(b)：幂等路径的 --publish-action-id 豁免标记照常写入（不被 gate 吞）。"""
    r1 = _run_promo(tmp_path)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    r3 = _run_promo(tmp_path, "--publish-action-id", "act.20261112.a1")
    assert r3.returncode == 0, r3.stdout + r3.stderr
    marker = tmp_path / "data" / "state" / "publish_closeout" / "act.20261112.a1.json"
    assert marker.is_file()


def test_dismissal_write_side_strict_shape(tmp_path):
    """R2 P2-3：豁免标记写侧与读取侧同一严格形状。"""
    from llm_loop.runtime.service_control import write_publish_closeout_dismissal

    assert write_publish_closeout_dismissal(str(tmp_path), "act.1", by="test") is True
    assert write_publish_closeout_dismissal(str(tmp_path), "a/b", by="test") is False
    assert write_publish_closeout_dismissal(str(tmp_path), "../x", by="test") is False
    assert write_publish_closeout_dismissal(str(tmp_path), "", by="test") is False
