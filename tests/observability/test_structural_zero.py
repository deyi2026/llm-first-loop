"""可观测性 M1c 修订：桶块结构性零口径（§9 落地）.

依据 docs/ANALYSIS-20261014-observability-m0-findings.md §9：两桶 n=0 的成因
是部署拓扑使然而非采样不足——sync_window_poll（通道退役，不存在）、
llm_stream（流式检查点先占，竞速窗 <350ms，健康形态）。后端为口径单一来源，
每桶下发 structural_zero/zero_reason；n>0 时字段仍在（拓扑属性与样本数
无关），前端仅在 n=0 时据此替换「无样本」文案。
"""
from __future__ import annotations

from llm_loop.web.human_turn_queue import HumanTurnQueue

BASE = 1000.0


def _item(qid, *, consumed_via="", interrupt_receipt=False, effect=2.0):
    it = {
        "session_id": "s1",
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


def test_structural_zero_fields_on_all_buckets(tmp_path):
    """六桶全量带 structural_zero 布尔；恰好两桶 True 且 reason 非空。"""
    hq = HumanTurnQueue(str(tmp_path / "q"))
    agg = hq.aggregate_interject_metrics("s1")
    buckets = agg["buckets"]
    expected_true = {"sync_window_poll", "llm_stream"}
    for b, blk in buckets.items():
        assert isinstance(blk["structural_zero"], bool), (b, blk)
        assert blk["structural_zero"] is (b in expected_true), (b, blk)
        if blk["structural_zero"]:
            assert isinstance(blk["zero_reason"], str) and blk["zero_reason"], (b, blk)
        else:
            assert blk["zero_reason"] is None, (b, blk)


def test_structural_zero_reason_content(tmp_path):
    """reason 依据 §9 机制结论：退役/先占两类成因各自可辨识。"""
    hq = HumanTurnQueue(str(tmp_path / "q"))
    buckets = hq.aggregate_interject_metrics("s1")["buckets"]
    assert "退役" in buckets["sync_window_poll"]["zero_reason"]
    assert "先占" in buckets["llm_stream"]["zero_reason"]
    # 健康形态披露：与采样不足的区分是本口径的存在意义
    assert "采样不足" in buckets["llm_stream"]["zero_reason"]


def test_structural_zero_independent_of_sample_count(tmp_path):
    """n>0（历史残留样本）时字段不变——拓扑属性，不随样本数翻转。"""
    hq = HumanTurnQueue(str(tmp_path / "q"))
    hq._items.append(_item("swp-0", consumed_via="sync_window_poll", effect=0.05))
    buckets = hq.aggregate_interject_metrics("s1")["buckets"]
    assert buckets["sync_window_poll"]["n"] == 1
    assert buckets["sync_window_poll"]["structural_zero"] is True


def test_global_view_same_contract(tmp_path):
    """全局视图（M1b）与单 session 共用同一实现，契约一致。"""
    hq = HumanTurnQueue(str(tmp_path / "q"))
    buckets = hq.aggregate_interject_metrics_global()["buckets"]
    assert buckets["llm_stream"]["structural_zero"] is True
    assert buckets["sync_window_poll"]["structural_zero"] is True
    assert buckets["idle"]["structural_zero"] is False
