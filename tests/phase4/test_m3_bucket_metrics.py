"""Phase4 M3 度量验收：四桶分桶归属 + 每桶 ≥5 样本 + 对照基线.

对应 docs/phase4-effect-latency-design.md §7：
- interruptible（在途打断）      S13 构造 ×5：sleep 2.0 + 0.3s 注入 → 目标 P50≤500/P95≤1000
- natural_boundary（自然边界）  S15-A 构造 ×5：sleep 1.6 + 1.45s 注入（自然完成轮转）
- llm_stream（LLM 流内）        S16 构造 ×5：final 生成窗口注入（终答边界 CBF）
- idle（空窗/序列间隙）         S16-M1 构造 ×5：工具间隙收割 → 目标 P50≤50
分桶事实源：hq 条目 consumed_via/interrupt_receipt 戳记（engine 消费点机械打点，
无墙钟注入）；报告落 reports/phase4/m3/（PHASE4_M3_REPORT_DIR 可覆盖）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import ToolCall
from llm_loop.web import build_app
from tests.phase4.test_m0_scenarios import (
    INTERJECT_TEXT,
    _hq_item,
    _hq_of,
    _interject,
    _pct,
    _wait_run_done,
    _wait_tool_started,
)

M3_DIR = Path(os.path.abspath(os.environ.get("PHASE4_M3_REPORT_DIR", "reports/phase4/m3")))
M3_DIR.mkdir(parents=True, exist_ok=True)


def _sample_run(engine, client, runner, sid, *, inject_delay=None,
                 inject_on_llm_call=None, fake=None, anchor_locked=False):
    """单样本：启 run → 工具启动后注入 → 等 done → 返回 hq 条目."""
    base_calls = len(fake.calls) if (fake is not None) else 0
    _h, q = runner.start(sid, "go")
    if inject_on_llm_call:
        # LLM 生成窗口锚：等本 run 第 N 次 chat 开始后注入（窗口由 callable sleep 构造；
        # 计数相对 run 起点，避免跨 run 累计错锚）
        target = base_calls + inject_on_llm_call
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and len(fake.calls) < target:
            time.sleep(0.005)
        time.sleep(0.25)
    else:
        anchor = "phase4_locked_sleep" if anchor_locked else "execute_command"
        attr = "_active" if anchor_locked else "_active_procs"
        assert _wait_tool_started(engine, anchor, attr)
        time.sleep(inject_delay)
    gen = (runner.get_handle(sid) or {}).get("run_generation")
    assert gen, "run 应在途"
    r1 = client.post("/api/v1/chat/queue",
                     json={"session_id": sid, "message": INTERJECT_TEXT})
    assert r1.status_code == 202
    queue_id = r1.json()["queue_id"]
    r2 = _interject(client, sid, queue_id, gen)
    assert r2.status_code == 202
    final = _wait_run_done(q, timeout=30)
    assert final.get("type") == "done", final
    item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
    assert item.get("status") == "interject_received", item
    return item


def _bucket(build_test_engine, n=5, mode="interruptible"):
    """一个会话跑 n 个独立 run，各产生一个插话条目；返回聚合."""
    responses = []
    for i in range(n):
        if mode == "interruptible":
            responses.append({"content": "go",
                              "tool_calls": [ToolCall(id=f"m3i-{i}", name="execute_command",
                                                      arguments={"command": "sleep 2.0"})]})
            responses.append({"content": "final"})
            inject_delay = 0.3
        elif mode == "natural_boundary":
            # sleep 1.55：完成落在判定片 (1.4,1.6) 内部——到达无论早晚均自然完成
            # （1.6 会与判定唤醒对齐成刀刃，负载下翻转到打断分支）
            responses.append({"content": "go",
                              "tool_calls": [ToolCall(id=f"m3n-{i}", name="execute_command",
                                                      arguments={"command": "sleep 1.55"})]})
            responses.append({"content": "final"})
            inject_delay = 1.45
        elif mode == "llm_stream":
            from llm_loop.llm.client import LLMResponse

            def _slow_final(idx=i):
                time.sleep(1.5)
                return LLMResponse(content=f"final-win-{idx}", tool_calls=[], provider="fake")

            responses.append({"content": "go",
                              "tool_calls": [ToolCall(id=f"m3l-{i}", name="execute_command",
                                                      arguments={"command": "sleep 1.0"})]})
            responses.append(_slow_final)
            responses.append({"content": "final-post-cbf"})
            inject_delay = 0.05
        else:  # idle（T1b 口径）：到达即空窗——c1 尾部注入（完成前 ~40ms 到达），
            #       收割点=c1→c2 段间隙，t_effect=到达→间隙收割（≤50ms 目标场景）。
            #       c1/c2 均锁工具：M2 打断通道对锁工具双重保守（非闭集+revocable=False）。
            responses.append({"content": "go",
                              "tool_calls": [
                                  ToolCall(id=f"m3d-{i}a", name="phase4_locked_sleep",
                                           arguments={"seconds": 0.8}),
                                  ToolCall(id=f"m3d-{i}b", name="phase4_locked_sleep",
                                           arguments={"seconds": 2.0}),
                              ]})
            responses.append({"content": "final"})
            inject_delay = 0.76

    inject_on_llm = 2 if mode == "llm_stream" else None
    engine, fake = build_test_engine(responses)
    if mode == "idle":
        from tests.phase4.test_m0_scenarios import _LockedSleepTool
        engine.registry.register(_LockedSleepTool())
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    items = []
    try:
        for i in range(n):
            print(f"[m3dbg] sample {mode}#{i+1} llm_before={len(fake.calls)}", flush=True)
            it = _sample_run(engine, client, runner, sid, inject_delay=inject_delay,
                             inject_on_llm_call=inject_on_llm, fake=fake,
                             anchor_locked=(mode == "idle"))
            print(f"[m3dbg] sample {mode}#{i+1} ok llm_after={len(fake.calls)} via={it.get('consumed_via')}", flush=True)
            items.append(it)
    finally:
        runner.cancel(sid)
    effs = [round((it.get("received_at") - it.get("created_at")) * 1000, 1) for it in items]
    vias = [it.get("consumed_via") for it in items]
    irpts = [bool(it.get("interrupt_receipt")) for it in items]
    return {
        "bucket_construct": mode, "n": n, "t_effect_samples": effs,
        "p50": _pct(effs, 0.50), "p95": _pct(effs, 0.95),
        "consumed_via": vias, "interrupt_receipts": irpts,
    }


def _idle_bucket_sampled(build_test_engine, need=3, max_rounds=10, n=5):
    """idle 桶采样：命中 µs 级间隙本身是随机量，机制门槛不能建在命中率上。

    Phase4-M3 修复（2026-10-22；定时 CI 39689641019 红：idle hit=2/5）。
    idle 构造靠外部 HTTP 注入去撞「工具已完成、下一轮未开」的间隙：注入线程的
    调度抖动直接决定本样本是 gap_harvest 还是 round_start——这是采样运气，不是机制。
    机制验收是「命中间隙时收割 ≤50ms」+「错失如实归属、零假打断」，与命中率无关。
    故：命中不足则有界补采样，补齐后仍不足才 FAIL；轮次/命中/错失/命中率全部
    落 M3_ACCEPTANCE.json，不再把命中率藏进 assert。
    上限取 10 轮的依据：CI 39689641019 实测单轮命中 2/5（p≈0.4），单轮凑够 3 个
    命中的概率仅 ≈0.32，补 10 轮后仍不足的概率 0.683^10 ≈ 2%；本机常态 p≈0.8，
    通常首轮即满足（实测 sampling_rounds=1, hit_rate=0.8, 机制时延 31.9ms）。
    """
    merged = _bucket(build_test_engine, n, "idle")
    rounds = 1
    while True:
        hits = sum(v == "gap_harvest" for v in merged["consumed_via"])
        if hits >= need or rounds >= max_rounds:
            merged["sampling_rounds"] = rounds
            merged["gap_harvest_hits"] = hits
            merged["needed_hits"] = need
            merged["missed_boundary"] = sum(
                v == "round_start" for v in merged["consumed_via"]
            )
            merged["other_via"] = sorted(
                v for v in merged["consumed_via"] if v not in ("gap_harvest", "round_start")
            )
            merged["hit_rate"] = round(hits / merged["n"], 3)
            return merged
        extra = _bucket(build_test_engine, n, "idle")
        rounds += 1
        for key in ("t_effect_samples", "consumed_via", "interrupt_receipts"):
            merged[key] = merged[key] + extra[key]
        merged["n"] = merged["n"] + extra["n"]
        merged["p50"] = _pct(merged["t_effect_samples"], 0.50)
        merged["p95"] = _pct(merged["t_effect_samples"], 0.95)


def test_m3_four_buckets(build_test_engine):
    out = {}
    out["interruptible"] = _bucket(build_test_engine, 5, "interruptible")
    out["natural_boundary"] = _bucket(build_test_engine, 5, "natural_boundary")
    out["llm_stream"] = _bucket(build_test_engine, 5, "llm_stream")
    out["idle"] = _idle_bucket_sampled(build_test_engine)

    # 机械归属断言（consumed_via/interrupt_receipt 与桶构造一致）
    assert all(out["interruptible"]["interrupt_receipts"]), out["interruptible"]
    assert all(v == "round_start" for v in out["interruptible"]["consumed_via"]), out["interruptible"]
    assert not any(out["natural_boundary"]["interrupt_receipts"]), out["natural_boundary"]
    assert all(v == "round_start" for v in out["natural_boundary"]["consumed_via"]), out["natural_boundary"]
    # Phase6 M1 后：同步 LLM 窗口内插话默认被窗口轮询截获（via=sync_window_poll，
    # 新口径即设计 §5.6 T1 度量依据）；final_gate 归属保留给晚到/关闸回退。
    assert all(v == "sync_window_poll" for v in out["llm_stream"]["consumed_via"]), out["llm_stream"]
    # idle 桶为「到达-边界」竞速构造（外部 HTTP 注入对 µs 级间隙有 ±抖动）：
    # 命中间隙的样本测收割机制时延（via=gap_harvest，目标 ≤50ms）；错失边界的样本
    # 落入 round_start 轮转消费（如实归属、不打断零误标）。
    # 命中数由 _idle_bucket_sampled 有界补采样保证（采样运气 ≠ 机制）；
    # 补采样用尽仍不足 need → 此时才是机制真没命中。
    idle_hits = [v == "gap_harvest" for v in out["idle"]["consumed_via"]]
    assert sum(idle_hits) >= out["idle"]["needed_hits"], out["idle"]
    assert not out["idle"]["other_via"], out["idle"]
    idle_p50 = _pct(
        [t for t, hit in zip(out["idle"]["t_effect_samples"], idle_hits, strict=False) if hit],
        0.50,
    )
    assert idle_p50 <= 50, (idle_p50, out["idle"])
    out["idle"]["mechanism_p50_t_effect_ms"] = idle_p50
    assert not any(out["llm_stream"]["interrupt_receipts"] + out["idle"]["interrupt_receipts"])

    # 达标断言（§7 目标桶）
    assert out["interruptible"]["p50"] <= 500 and out["interruptible"]["p95"] <= 1000, out["interruptible"]
    # idle 机制时延口径 = 上方 mechanism_p50_t_effect_ms（hit-only，≤50ms）。
    # 全样本 p50 会混入合法错失样本（t_effect≈工具时长≈2000ms），不是机制指标；
    # 补采样后其算术值必然跨过 50，故仅留作诊断字段、不设门槛
    # （原断言只在恰好命中≥3/5 时才偶然成立）。

    # 对照 M0 基线
    try:
        _repo = Path(__file__).resolve().parents[2]
        base = json.loads((_repo / "reports/phase4/m0" / "S13.json").read_text())
        baseline_p50 = base.get("t_effect_p50_ms") or base.get("p50")
    except Exception:
        baseline_p50 = None
    out["baseline_compare"] = {
        "S13_baseline_p50_ms": baseline_p50,
        "S13_m3_p50_ms": out["interruptible"]["p50"],
        "improvement_x": (
            round(baseline_p50 / out["interruptible"]["p50"], 1)
            if baseline_p50 and out["interruptible"]["p50"] else None
        ),
    }
    # 验收工件护栏（终局评审 P2-1/P0-1 机制）：默认不覆写已存在的验收快照
    # （PHASE4_OVERWRITE_REPORTS=1 强制重测）——防调试重跑静默漂移交付数字。
    if not (M3_DIR / "M3_ACCEPTANCE.json").exists() or os.environ.get(
        "PHASE4_OVERWRITE_REPORTS"
    ) == "1":
        (M3_DIR / "M3_ACCEPTANCE.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: (v.get("p50"), v.get("p95"), v.get("n")) for k, v in out.items()
                      if isinstance(v, dict) and "p50" in v}), flush=True)


def test_m3_aggregate_endpoint_buckets(build_test_engine):
    """metrics 端点暴露分桶字段（routes /interject-metrics → aggregate buckets）."""
    res = _bucket(build_test_engine, 2, "interruptible")
    assert res["p50"] is not None
    # 直接核 aggregate 结构（端点按 session 聚合并原样回传 buckets）
    import tempfile

    from llm_loop.web.human_turn_queue import HumanTurnQueue
    with tempfile.TemporaryDirectory() as td:
        hq = HumanTurnQueue(td)
        agg = hq.aggregate_interject_metrics("no-such-session")
    # Phase5 M2（§2.2.3）：桶集合扩展 llm_stream_interrupt（流内打断收割，
    # 判序最前独立统计）——Phase4 四桶语义不变。
    # 可观测性 M1a（2026-10-14）：桶集合扩展 sync_window_poll（Phase6 M1 同步
    # 窗口轮询收割独立成桶，ANALYSIS-20261014 §3-G1/评审 B7）——六桶全列口径。
    assert "buckets" in agg and set(agg["buckets"]) == {
        "interruptible", "natural_boundary", "llm_stream",
        "llm_stream_interrupt", "sync_window_poll", "idle"}
    assert all("insufficient_sample" in v for v in agg["buckets"].values())
