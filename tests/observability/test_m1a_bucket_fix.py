"""可观测性 M1a：aggregate 分桶加 sync_window_poll 独立桶（G1 修复）.

现状缺陷（docs/ANALYSIS-20261014-observability-m0-findings.md §3-G1）：
窗口通道样本 consumed_via="sync_window_poll"（engine L2080/L2094 写入，
interrupt_receipt 恒 False——tests/phase6/test_m3_metrics.py L131-132 断言）
落聚合 else 分支 → 误归 natural_boundary，两桶同时失真。

修复后口径（M0 评审 B6/B7）：6 桶全列；判序位置=llm_stream_interrupt 之后、
interrupt_receipt 之前（精确值优先于布尔标记，防跨轮残值）。
"""
from __future__ import annotations

from llm_loop.web.human_turn_queue import HumanTurnQueue

BASE = 1000.0


def _item(qid, *, consumed_via="", interrupt_receipt=False, effect=2.0,
          session="s1"):
    it = {
        "session_id": session,
        "queue_id": qid,
        "status": "interject_received",
        "created_at": BASE,
        "interject_requested_at": BASE + 0.003,
        "received_at": BASE + effect,
        "message": "m",
    }
    if consumed_via:
        it["consumed_via"] = consumed_via
    if interrupt_receipt:
        it["interrupt_receipt"] = True
    return it


def test_sync_window_poll_independent_bucket(tmp_path):
    """red 主断言：sync_window_poll 样本独立成桶，不落 natural_boundary。"""
    hq = HumanTurnQueue(str(tmp_path / "q"))
    for i in range(6):  # ≥5 使 insufficient_sample=False，口径清晰
        hq._items.append(
            _item(f"swp-{i}", consumed_via="sync_window_poll", effect=0.05)
        )
    for i in range(4):  # 对照组：真 natural_boundary（round_start）
        hq._items.append(
            _item(f"nb-{i}", consumed_via="round_start", effect=3.0)
        )
    agg = hq.aggregate_interject_metrics("s1")
    # 逐项归属：sync 样本不得误归 natural_boundary
    for row in agg["items"]:
        if row["queue_id"].startswith("swp-"):
            assert row["bucket"] == "sync_window_poll", row
        else:
            assert row["bucket"] == "natural_boundary", row
    # 分桶汇总：独立键、n 正确、两侧互不污染
    buckets = agg["buckets"]
    assert "sync_window_poll" in buckets, buckets.keys()
    assert buckets["sync_window_poll"]["n"] == 6
    assert buckets["sync_window_poll"]["insufficient_sample"] is False
    assert buckets["natural_boundary"]["n"] == 4
    # 分位数互不冒充：sync P50≈50ms 量级，natural≈3000ms 量级
    assert buckets["sync_window_poll"]["p50_t_effect_ms"] < 100
    assert buckets["natural_boundary"]["p50_t_effect_ms"] > 1000


def test_bucket_full_set_regression(tmp_path):
    """6 桶全列回归：既有五桶归属不变 + 新桶就位（V1）。"""
    hq = HumanTurnQueue(str(tmp_path / "q"))
    cases = [
        ("i-0", {"interrupt_receipt": True}, "interruptible"),
        ("nb-0", {"consumed_via": "round_start"}, "natural_boundary"),
        ("ls-0", {"consumed_via": "final_gate"}, "llm_stream"),
        ("lsi-0", {"consumed_via": "llm_stream_interrupt"}, "llm_stream_interrupt"),
        ("swp-0", {"consumed_via": "sync_window_poll"}, "sync_window_poll"),
        ("idle-0", {"consumed_via": "gap_harvest"}, "idle"),
        ("old-0", {}, "natural_boundary"),  # 老数据无戳记：缺省兜底不变
    ]
    for qid, kwargs, _ in cases:
        hq._items.append(_item(qid, **kwargs))
    agg = hq.aggregate_interject_metrics("s1")
    got = {r["queue_id"]: r["bucket"] for r in agg["items"]}
    for qid, _, expected in cases:
        assert got[qid] == expected, (qid, got[qid], expected)
    for b in ("interruptible", "natural_boundary", "llm_stream",
              "llm_stream_interrupt", "sync_window_poll", "idle"):
        assert b in agg["buckets"], agg["buckets"].keys()
        assert agg["buckets"][b]["n"] == (2 if b == "natural_boundary" else 1)


def test_negative_latency_not_filtered(tmp_path):
    """V1：负时延样本如实展示不滤（时钟回拨/多源时钟，B2 裁决）。"""
    hq = HumanTurnQueue(str(tmp_path / "q"))
    hq._items.append(_item("neg-0", consumed_via="sync_window_poll",
                           effect=-0.5))  # received_at < created_at
    agg = hq.aggregate_interject_metrics("s1")
    assert agg["n"] == 1
    assert agg["items"][0]["t_effect_ms"] < 0
    assert agg["buckets"]["sync_window_poll"]["n"] == 1
