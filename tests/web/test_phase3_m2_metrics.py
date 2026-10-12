"""Phase3 M2 生效时延度量（G2）：三口径聚合 + P50/P95 + Web 暴露.

口径（Phase3 §7.1，全部由持久化时间戳机械推导）：
- t_ack_ms     = interject_requested_at - created_at（入队→受理）
- t_persist_ms = received_at - interject_requested_at（受理→进入会话历史）
- t_effect_ms  = received_at - created_at（端到端生效）
- t_applied_ms = applied_at - created_at（入队→首个动作）
denied/requeued 不混入统计（口径含混即失真）。
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import ToolCall
from llm_loop.web import build_app
from llm_loop.web.human_turn_queue import HumanTurnQueue


def _wait_tool_started(engine, timeout=3.0):
    tool = engine.registry.get("execute_command")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if getattr(tool, "_active_procs", None):
            return True
        time.sleep(0.01)
    return False


def _wait_done(q, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            ev = q.get_nowait()
        except Exception:  # noqa: BLE001
            time.sleep(0.02)
            continue
        if ev.get("type") in ("done", "error"):
            return ev
    return {"type": "timeout"}


def _hq_of(client, engine):
    store = getattr(client.app.state, "human_turn_queues", None) or {}
    data_dir = str(Path(engine.settings.data_dir).expanduser().resolve())
    return store.get(data_dir) or next(iter(store.values()))


# ── 纯单元：口径与百分位数学 ────────────────────────────────────────
def test_aggregate_unit_math(tmp_path):
    hq = HumanTurnQueue(str(tmp_path / "q"))
    # 手工构造已知时间戳的终态项（绕过时钟，纯口径验证）
    base = 1000.0
    for i, (ack, effect, applied) in enumerate(
        [(0.002, 2.5, 2.7), (0.003, 3.0, None), (0.004, 3.5, 3.8)]
    ):
        it = {
            "session_id": "s1",
            "queue_id": f"q{i}",
            "status": "interject_received",
            "created_at": base,
            "interject_requested_at": base + ack,
            "received_at": base + effect,
            "message": "m",
        }
        if applied:
            it["applied_at"] = base + applied
        hq._items.append(it)
    # 干扰项：denied/requeued 不入统计
    hq._items.append(
        {
            "session_id": "s1",
            "queue_id": "q-denied",
            "status": "interject_denied",
            "created_at": base,
            "interject_requested_at": base + 0.001,
            "received_at": base + 9.0,
            "deny_reason": "x",
        }
    )
    hq._items.append(
        {
            "session_id": "s1",
            "queue_id": "q-requeued",
            "status": "queued",
            "requeued_from": "interject_run_ended",
            "created_at": base,
            "interject_requested_at": base + 0.001,
            "received_at": None,
        }
    )
    hq._save()

    agg = hq.aggregate_interject_metrics("s1")
    assert agg["n"] == 3
    acks = sorted(r["t_ack_ms"] for r in agg["items"])
    assert acks == [2.0, 3.0, 4.0]
    assert agg["p50_t_ack_ms"] == 3.0
    assert agg["p95_t_ack_ms"] == 4.0  # 最近邻序：ceil(0.95*3)=3
    # t_persist = effect - ack（口径自洽：ack+persist=effect）
    for r in agg["items"]:
        assert abs(r["t_ack_ms"] + r["t_persist_ms"] - r["t_effect_ms"]) < 0.2, r
    # t_applied 仅 applied 项有值；百分位只对有值样本
    applied_vals = [r["t_applied_ms"] for r in agg["items"] if r["t_applied_ms"]]
    assert sorted(applied_vals) == [2700.0, 3800.0]
    assert agg["p50_t_applied_ms"] == 2700.0
    # 空会话不造数
    empty = hq.aggregate_interject_metrics("no-such")
    assert empty["n"] == 0 and empty["p50_t_ack_ms"] is None


# ── 集成：端到端 run 后端点可查 ────────────────────────────────────
def test_metrics_endpoint_after_live_interject(build_test_engine):
    engine, _fake = build_test_engine(
        [
            {
                "content": "慢",
                "tool_calls": [
                    ToolCall(id="m2c1", name="execute_command", arguments={"command": "sleep 2"})
                ],
            },
            {"content": "final"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    try:
        _h, q = runner.start(sid, "跑一步")
        assert _wait_tool_started(engine)
        r1 = client.post(
            "/api/v1/chat/queue", json={"session_id": sid, "message": "度量这条插话"}
        )
        qid = r1.json()["queue_id"]
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        r2 = client.post(
            "/api/v1/chat/queue/interject",
            json={"session_id": sid, "queue_id": qid, "run_generation": gen},
        )
        assert r2.status_code == 202
        final = _wait_done(q)
        assert final["type"] == "done"

        r3 = client.get("/api/v1/chat/queue/metrics", params={"session_id": sid})
        assert r3.status_code == 200
        agg = r3.json()
        assert agg["ok"] is True and agg["n"] == 1
        item = agg["items"][0]
        assert item["grade"] == "applied"  # M1 分级与 M2 度量同源
        assert 0 < item["t_ack_ms"] < 200, item  # 受理毫秒级
        assert item["t_effect_ms"] > 1000, item  # 轮边界等待（工具 2s）→ 生效秒级
        assert item["t_persist_ms"] > 0
        assert item["t_applied_ms"] is not None
        assert abs(item["t_ack_ms"] + item["t_persist_ms"] - item["t_effect_ms"]) < 0.5
        # P50/P95 与单样本一致
        assert agg["p50_t_effect_ms"] == item["t_effect_ms"]
        assert agg["p95_t_effect_ms"] == item["t_effect_ms"]
    finally:
        runner.cancel(sid)


# ── 对照数据采集：3 run 样本 → reports/phase3/m2/metrics.json ──────
def test_m2_capture_three_runs(build_test_engine, tmp_path):
    """采集 M1+M2 代码下的三口径样本（对照表数据源；断言仅机械健全性）."""
    import json
    from pathlib import Path

    engine, _fake = build_test_engine(
        [
            item
            for i in range(3)
            for item in (
                {
                    "content": "慢",
                    "tool_calls": [
                        ToolCall(
                            id=f"m2cc{i}",
                            name="execute_command",
                            arguments={"command": "sleep 2"},
                        )
                    ],
                },
                {"content": "final"},
            )
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    # P2-8 卫生修复：默认写 tmp（全量测试不再弄脏工作树）；显式设 PHASE3_REPORT_DIR
    # 时写仓库内报告目录（对照表数据源采集，见 docs/phase3-m2-metrics.md）。
    import os

    env_dir = os.environ.get("PHASE3_REPORT_DIR", "")
    out = Path(env_dir) if env_dir else tmp_path / "m2"
    out.mkdir(parents=True, exist_ok=True)
    try:
        for i in range(3):
            # 等上一轮 handle 清理完成（session_busy 会让 start 返回 (None,None)）
            deadline = time.monotonic() + 5.0
            while runner.get_handle(sid) is not None and time.monotonic() < deadline:
                time.sleep(0.05)
            _h, q = runner.start(sid, f"run {i}")
            assert _h is not None and q is not None, f"run {i} 启动失败（session_busy 或 disabled）"
            assert _wait_tool_started(engine), f"run {i} 工具未启动"
            r1 = client.post(
                "/api/v1/chat/queue", json={"session_id": sid, "message": f"采集插话{i}"}
            )
            qid = r1.json()["queue_id"]
            gen = (runner.get_handle(sid) or {}).get("run_generation")
            client.post(
                "/api/v1/chat/queue/interject",
                json={"session_id": sid, "queue_id": qid, "run_generation": gen},
            )
            _wait_done(q)
            time.sleep(0.1)
        agg = client.get("/api/v1/chat/queue/metrics", params={"session_id": sid}).json()
        assert agg["n"] == 3, agg
        (out / "metrics.json").write_text(
            json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        runner.cancel(sid)
