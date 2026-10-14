"""可观测性 M1b：全局聚合视图契约（hq 层 + HTTP 端点，V2）.

设计依据 docs/ANALYSIS-20261014-observability-m0-findings.md §5（B1/B5）§6-V2：
- 新增 GET /api/v1/chat/queue/metrics/global：跨 session 合并、6 桶三口径
  P50/P95、window_terminal_cap 标注；空数据 n=0/null 不造数；无逐条 items
  （合并视图不做 per-session 明细，明细走既有单 session 端点）。
- 既有单 session 端点契约零变化（session_id 必填等；回归另见
  tests/web/test_phase3_m2_metrics.py 与 tests/observability/test_m1a_bucket_fix.py）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.web import build_app
from llm_loop.web.human_turn_queue import TERMINAL_HISTORY_KEEP_N, HumanTurnQueue

BASE = 1000.0
BUCKETS = (
    "interruptible",
    "natural_boundary",
    "llm_stream",
    "llm_stream_interrupt",
    "sync_window_poll",
    "idle",
)


def _item(qid, *, consumed_via="", interrupt_receipt=False, effect=2.0, session="s1"):
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


# ── 单元：hq 层全局聚合 ─────────────────────────────────────────────


def test_global_empty_contract(tmp_path):
    """V2：空数据 → n=0 / 全 null / 窗口标注在位，不造数。"""
    hq = HumanTurnQueue(str(tmp_path / "q"))
    agg = hq.aggregate_interject_metrics_global()
    assert agg["scope"] == "global"
    assert agg["session_id"] is None
    assert agg["n"] == 0
    assert agg["sessions_in_window"] == 0
    assert agg["window_terminal_cap"] == TERMINAL_HISTORY_KEEP_N
    for key in (
        "p50_t_ack_ms",
        "p95_t_ack_ms",
        "p50_t_persist_ms",
        "p95_t_persist_ms",
        "p50_t_effect_ms",
        "p95_t_effect_ms",
        "p50_t_applied_ms",
        "p95_t_applied_ms",
    ):
        assert agg[key] is None, key
    for b in BUCKETS:
        assert agg["buckets"][b]["n"] == 0, b
        assert agg["buckets"][b]["p50_t_effect_ms"] is None
        assert agg["buckets"][b]["insufficient_sample"] is True
    assert "items" not in agg  # 合并视图无明细（B1）


def test_global_multi_session_merge(tmp_path):
    """V2：多 session 合并正确（桶/分位数跨 session 归并；单视图不受影响）."""
    hq = HumanTurnQueue(str(tmp_path / "q"))
    for i in range(3):
        hq._items.append(
            _item(f"s1-swp-{i}", consumed_via="sync_window_poll", effect=0.05, session="s1")
        )
    hq._items.append(_item("s2-swp-0", consumed_via="sync_window_poll", effect=0.06, session="s2"))
    for i in range(2):
        hq._items.append(_item(f"s2-nb-{i}", consumed_via="round_start", effect=3.0, session="s2"))
    # 干扰项：其它 session 的 denied 终态不混入（口径含混即失真）
    hq._items.append(
        {
            "session_id": "s3",
            "queue_id": "s3-denied",
            "status": "interject_denied",
            "created_at": BASE,
            "interject_requested_at": BASE + 0.001,
            "received_at": BASE + 9.0,
            "deny_reason": "x",
        }
    )
    agg = hq.aggregate_interject_metrics_global()
    assert agg["n"] == 6
    assert agg["sessions_in_window"] == 2  # denied 干扰不贡献 session
    # 桶合并：sync 跨 session n=4；natural n=2（s2 专属）
    assert agg["buckets"]["sync_window_poll"]["n"] == 4
    assert agg["buckets"]["natural_boundary"]["n"] == 2
    # 手工复算（最近邻序法）：sync t_effect=[50,50,50,60]→p50=50/p95=60
    assert agg["buckets"]["sync_window_poll"]["p50_t_effect_ms"] == 50.0
    assert agg["buckets"]["sync_window_poll"]["p95_t_effect_ms"] == 60.0
    # 全局三口径：t_ack 全样本 3.0ms；t_effect=[50,50,50,60,3000,3000]→p50=50/p95=3000
    assert agg["p50_t_ack_ms"] == 3.0
    assert agg["p50_t_effect_ms"] == 50.0
    assert agg["p95_t_effect_ms"] == 3000.0
    # 单 session 视图不受全局只读影响（同源不污染）
    s1 = hq.aggregate_interject_metrics("s1")
    assert s1["n"] == 3 and s1["buckets"]["sync_window_poll"]["n"] == 3
    assert "items" in s1


# ── 端点：V2 契约 ──────────────────────────────────────────────────


def test_global_endpoint_contract(build_test_engine):
    """V2：全局端点空/非空契约 + 既有单 session 端点契约零变化."""
    engine, _fake = build_test_engine([{"content": "final"}])
    client = TestClient(build_app(engine=engine))
    # 空数据契约
    r0 = client.get("/api/v1/chat/queue/metrics/global")
    assert r0.status_code == 200
    j0 = r0.json()
    assert j0["ok"] is True
    assert j0["scope"] == "global" and j0["n"] == 0
    assert j0["window_terminal_cap"] == 500
    assert j0["p50_t_effect_ms"] is None
    # 注入多 session 样本（端点按 data_dir 缓存同一 hq 实例）
    store = client.app.state.human_turn_queues
    key = str(Path(engine.settings.data_dir).expanduser().resolve())
    hq = store[key]
    for i in range(3):
        hq._items.append(
            _item(f"s1-swp-{i}", consumed_via="sync_window_poll", effect=0.05, session="s1")
        )
    for i in range(2):
        hq._items.append(_item(f"s2-nb-{i}", consumed_via="round_start", effect=3.0, session="s2"))
    r1 = client.get("/api/v1/chat/queue/metrics/global")
    assert r1.status_code == 200
    j1 = r1.json()
    assert j1["n"] == 5 and j1["sessions_in_window"] == 2
    assert j1["buckets"]["sync_window_poll"]["n"] == 3
    assert j1["buckets"]["natural_boundary"]["n"] == 2
    assert "items" not in j1
    # 既有单 session 端点：session_id 仍必填（422），响应仍含 items 明细
    r2 = client.get("/api/v1/chat/queue/metrics")
    assert r2.status_code == 422
    r3 = client.get("/api/v1/chat/queue/metrics", params={"session_id": "s1"})
    assert r3.status_code == 200
    j3 = r3.json()
    assert j3["ok"] is True and j3["n"] == 3 and len(j3["items"]) == 3
    assert j3["items"][0]["bucket"] == "sync_window_poll"
