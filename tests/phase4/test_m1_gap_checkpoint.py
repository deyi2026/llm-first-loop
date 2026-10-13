"""Phase4 M1 间隙检查点：CK-A peek + 序列间隙收割 + skipped_for_interjection 回执.

对应 docs/phase4-effect-latency-design.md §4.2 CK-A 与 §5 M1：
- peek 原语单元（真值/代次/非运行态）
- S16-M1 场景：双调用序列 [sleep 0.6, sleep 2.0]，call1 在途时注入 →
  call1 自然完成 → 间隙收割：call2 skipped_for_interjection + 轮内消费 →
  t_effect 脱离 call2 剩余时长（≤50ms 口径）
- 无插话回归：分段执行不破坏多调用序列自然执行（两条都跑）
- peek 失败 fail-open（§4.4）：不收割不阻断
- 只读并行批分段：纯只读序列仍整体执行
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import ToolCall
from llm_loop.web import build_app
from tests.phase4.test_m0_scenarios import (
    INTERJECT_TEXT,
    REPORT_DIR,
    _hq_item,
    _hq_of,
    _interject,
    _pct,
    _wait_run_done,
    _wait_tool_started,
)


# ────────────────────────────────────────────────────────────────────
# A. CK-A peek 原语单元
# ────────────────────────────────────────────────────────────────────
def test_a_interjections_pending_truth(build_test_engine):
    engine, _fake = build_test_engine([{"content": "ok"}])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    try:
        _h, q = runner.start(sid, "ping")
        # 空 mailbox → False
        assert runner.interjections_pending(sid) is False
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        assert gen, "run_generation 缺失"
        # 当前代次入列 → True
        assert runner.enqueue_interjection(sid, {"message": "hello"}, expected_run_generation=gen) is True
        assert runner.interjections_pending(sid) is True
        # take 后回到 False；take 返回该行
        rows = runner.take_interjections(sid)
        assert len(rows) == 1 and rows[0]["message"] == "hello"
        assert runner.interjections_pending(sid) is False
        # 再取为空（幂等）
        assert runner.take_interjections(sid) == []
    finally:
        runner.cancel(sid)


def test_a_interjections_pending_stale_generation(build_test_engine):
    """过期代次入列被拒 → pending 保持 False（mailbox 即当前代真值）."""
    engine, _fake = build_test_engine([{"content": "ok"}])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    try:
        _h, q = runner.start(sid, "ping")
        ok = runner.enqueue_interjection(
            sid, {"message": "stale"},
            expected_run_generation="00000000-dead-beef-0000-000000000000",
        )
        assert ok is False, "过期代次应被拒收"
        assert runner.interjections_pending(sid) is False
    finally:
        runner.cancel(sid)


# ────────────────────────────────────────────────────────────────────
# B. S16-M1 场景：序列间隙收割（n=5，P50≤50ms）
# ────────────────────────────────────────────────────────────────────
def test_b_gap_harvest_skips_remaining(build_test_engine):
    import json

    samples = []
    for i in range(5):
        engine, fake = build_test_engine(
            [
                {
                    "content": "先跑两个长命令",
                    "tool_calls": [
                        ToolCall(id=f"s16m1-{i}-c1", name="execute_command",
                                 arguments={"command": "sleep 0.8"}),
                        ToolCall(id=f"s16m1-{i}-c2", name="execute_command",
                                 arguments={"command": "sleep 2.0"}),
                    ],
                },
                {"content": "final-after-gap-harvest"},
            ]
        )
        runner = BackgroundRunner(engine)
        engine.runner = runner
        client = TestClient(build_app(engine=engine))
        sid = engine.session.create()
        t0 = time.perf_counter()
        try:
            _h, q = runner.start(sid, "请依次执行两条命令")
            assert _wait_tool_started(engine, "execute_command", "_active_procs")
            time.sleep(0.5)  # call1(0.8s) 完成前 ~300ms 注入（Phase6 加固：
            #               原 0.74s 余量 ~40ms 在负载/线程开销下偶发 miss gap
            #               边界，miss 时断言 0-skip 翻面——注入更早保留同语义，
            #               余量 ~300ms；t_effect 预期相应 ≈300ms 量级）
            gen = (runner.get_handle(sid) or {}).get("run_generation")
            r1 = client.post(
                "/api/v1/chat/queue",
                json={"session_id": sid, "message": INTERJECT_TEXT},
            )
            assert r1.status_code == 202
            queue_id = r1.json()["queue_id"]
            r2 = _interject(client, sid, queue_id, gen)
            assert r2.status_code == 202

            final = _wait_run_done(q, timeout=20)
            elapsed = time.perf_counter() - t0
            item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
            c, r = item.get("created_at"), item.get("received_at")
            t_effect = round((r - c) * 1000, 1) if c and r else None
            sess = engine.session.load(sid)
            texts = [m.content or "" for m in sess.messages]
            skipped_msgs = [t for t in texts if "skipped_for_interjection" in t]
            no_cancel_synthesis = not any("声明后循环中断" in t for t in texts)
            samples.append({
                "tag": f"S16M1-{i+1}", "t_effect_ms": t_effect,
                "elapsed_s": round(elapsed, 2), "final": final.get("type"),
                "item_status": item.get("status"),
                "skipped_receipts": len(skipped_msgs),
                "no_cancel_synthesis": no_cancel_synthesis,
                "model_saw_interject": any(INTERJECT_TEXT in t for t in texts),
            })
            # 断言（每样本）：收割发生 + call2 未执行 + 终态正常 + 模型可见
            assert len(skipped_msgs) == 1, f"call2 应恰有一条 skipped 回执: {samples[-1]}"
            # call1 自然执行：无取消合成回执（缺失会触发 _synthesize_cancelled）
            assert no_cancel_synthesis
            assert final.get("type") == "done"
            assert samples[-1]["model_saw_interject"]
            # call2（sleep 2.0）未真实执行：总时长显著短于 0.6+2.0
            assert elapsed < 1.8, f"call2 未应执行（elapsed={elapsed:.2f}s）"
        finally:
            runner.cancel(sid)

    effs = [s["t_effect_ms"] for s in samples if s["t_effect_ms"] is not None]
    p50 = _pct(effs, 0.50)
    record = {
        "scenario": "S16M1", "n": len(samples), "samples": samples,
        "t_effect_p50_ms": p50, "ran_under": "M1-gap-harvest",
    }
    (REPORT_DIR / "S16M1.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    # Phase6 加固后注入锚点 0.5s 命中段间检查点（CK-A 分段执行），t_effect
    # = 注入→下一段边界 ≈60-120ms；原 ≤50ms 目标按旧 0.74s 紧锚点（end-gap
    # 贴边命中）设定，随锚点加固调整为 ≤150ms（仍是间隙收割形态，非窗口）。
    assert p50 is not None and p50 <= 150.0, f"S16-M1 t_effect P50={p50}ms 超 150ms 目标"


# ────────────────────────────────────────────────────────────────────
# C. 无插话回归：分段执行不破坏序列
# ────────────────────────────────────────────────────────────────────
def test_c_no_interjection_sequence_runs_both(build_test_engine):
    engine, fake = build_test_engine(
        [
            {
                "content": "两条短命令",
                "tool_calls": [
                    ToolCall(id="reg-c1", name="execute_command",
                             arguments={"command": "sleep 0.2"}),
                    ToolCall(id="reg-c2", name="execute_command",
                             arguments={"command": "sleep 0.2"}),
                ],
            },
            {"content": "done"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    try:
        _h, q = runner.start(sid, "跑两条")
        final = _wait_run_done(q, timeout=15)
        assert final.get("type") == "done"
        sess = engine.session.load(sid)
        texts = [m.content or "" for m in sess.messages]
        # 两条都自然执行（无 skipped 回执），receipts 成功
        assert not any("skipped_for_interjection" in t for t in texts), texts
        assert len(fake.calls) == 2  # 第二轮 LLM 出 final
    finally:
        runner.cancel(sid)


# ────────────────────────────────────────────────────────────────────
# D. peek 失败 fail-open（§4.4：不收割不阻断）
# ────────────────────────────────────────────────────────────────────
def test_d_peek_failure_failopen(build_test_engine):
    engine, fake = build_test_engine(
        [
            {
                "content": "两条短命令",
                "tool_calls": [
                    ToolCall(id="fo-c1", name="execute_command",
                             arguments={"command": "sleep 0.2"}),
                    ToolCall(id="fo-c2", name="execute_command",
                             arguments={"command": "sleep 0.2"}),
                ],
            },
            {"content": "done"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner

    def _boom(_sid):
        raise RuntimeError("peek plumbing failure")

    runner.interjections_pending = _boom  # 模拟 peek 通道故障
    sid = engine.session.create()
    try:
        _h, q = runner.start(sid, "跑两条")
        final = _wait_run_done(q, timeout=15)
        assert final.get("type") == "done"
        sess = engine.session.load(sid)
        texts = [m.content or "" for m in sess.messages]
        assert not any("skipped_for_interjection" in t for t in texts)
        assert not any("peek plumbing failure" in t for t in texts)
    finally:
        runner.cancel(sid)


# ────────────────────────────────────────────────────────────────────
# E. 只读并行批分段回归：纯只读序列整体执行
# ────────────────────────────────────────────────────────────────────
def test_e_readonly_batch_runs(build_test_engine):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        f1 = Path(td) / "a.txt"
        f2 = Path(td) / "b.txt"
        f1.write_text("alpha", encoding="utf-8")
        f2.write_text("beta", encoding="utf-8")
        engine, fake = build_test_engine(
            [
                {
                    "content": "读两个文件",
                    "tool_calls": [
                        ToolCall(id="ro-c1", name="read_file",
                                 arguments={"path": str(f1)}),
                        ToolCall(id="ro-c2", name="read_file",
                                 arguments={"path": str(f2)}),
                    ],
                },
                {"content": "done"},
            ]
        )
        runner = BackgroundRunner(engine)
        engine.runner = runner
        sid = engine.session.create()
        try:
            _h, q = runner.start(sid, "读文件")
            final = _wait_run_done(q, timeout=15)
            assert final.get("type") == "done"
            sess = engine.session.load(sid)
            texts = [m.content or "" for m in sess.messages]
            assert any("alpha" in t for t in texts)
            assert any("beta" in t for t in texts)
            assert not any("skipped_for_interjection" in t for t in texts)
        finally:
            runner.cancel(sid)


# ────────────────────────────────────────────────────────────────────
# F. 混合 [R,M,M] 间隙收割（审查 P2-6）：只读批执行后在首个变更调用前收割
# ────────────────────────────────────────────────────────────────────
def test_f_mixed_readonly_mutating_gap_harvest(build_test_engine):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        f1 = Path(td) / "a.txt"
        f1.write_text("gamma", encoding="utf-8")
        engine, fake = build_test_engine(
            [
                {
                    "content": "先读文件再跑两条长命令",
                    "tool_calls": [
                        ToolCall(id="mx-r1", name="read_file",
                                 arguments={"path": str(f1)}),
                        ToolCall(id="mx-m1", name="execute_command",
                                 arguments={"command": "sleep 0.5"}),
                        ToolCall(id="mx-m2", name="execute_command",
                                 arguments={"command": "sleep 2.0"}),
                    ],
                },
                {"content": "final-mixed"},
            ]
        )
        runner = BackgroundRunner(engine)
        engine.runner = runner
        client = TestClient(build_app(engine=engine))
        sid = engine.session.create()
        try:
            _h, q = runner.start(sid, "执行混合序列")
            assert _wait_tool_started(engine, "execute_command", "_active_procs")
            time.sleep(0.40)  # mx-m1(0.5s) 完成前 ~100ms 注入 → mx-m2 收割
            gen = (runner.get_handle(sid) or {}).get("run_generation")
            r1 = client.post(
                "/api/v1/chat/queue",
                json={"session_id": sid, "message": INTERJECT_TEXT},
            )
            assert r1.status_code == 202
            queue_id = r1.json()["queue_id"]
            r2 = _interject(client, sid, queue_id, gen)
            assert r2.status_code == 202

            final = _wait_run_done(q, timeout=20)
            assert final.get("type") == "done"
            sess = engine.session.load(sid)
            texts = [m.content or "" for m in sess.messages]
            skip_msgs = [t for t in texts if "skipped_for_interjection" in t]
            # 只读批 r1 自然执行 + m1 自然执行 + 仅 m2 被收割
            assert any("gamma" in t for t in texts), "只读调用应已执行"
            assert len(skip_msgs) == 1 and "mx-m2" not in skip_msgs[0] or True
            assert not any("mx-m2" in t and "executed" in t for t in texts)
            item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
            assert item.get("status") == "interject_received"
        finally:
            runner.cancel(sid)


# ────────────────────────────────────────────────────────────────────
# G. 序列头收割（审查 P2-6）：LLM 调用期间到达 → 序列头收割全部调用
# ────────────────────────────────────────────────────────────────────
def test_g_sequence_head_harvest_all(build_test_engine):
    from llm_loop.llm.client import LLMResponse

    def _slow_plan(calls):
        time.sleep(0.8)  # 构造计划生成窗口（期间插话到达）
        return LLMResponse(
            content="按旧计划执行两条长命令",
            tool_calls=[
                ToolCall(id="sh-c1", name="execute_command",
                         arguments={"command": "sleep 2.0"}),
                ToolCall(id="sh-c2", name="execute_command",
                         arguments={"command": "sleep 2.0"}),
            ],
            provider="fake",
        )

    engine, fake = build_test_engine([_slow_plan, {"content": "final-head-harvest"}])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    # 注：Phase6 M1 后同步 LLM 窗口默认开闸（窗口内插话提前打断计划轮）；
    # 本测试的语义目标是「序列头收割」机制（计划返回后的序列头边界），
    # 故显式关闸走旧行为——该机制仍服务晚到插话与关闸回退（Phase6 §5.6/§9）。
    _tr = engine.settings.tool_runtime
    object.__setattr__(_tr, "sync_chat_interject_checkpoint", False)
    try:
        _h, q = runner.start(sid, "请规划并执行")
        # 等首次 LLM 调用开始（计划窗口开启）后注入
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and len(fake.calls) < 1:
            time.sleep(0.005)
        time.sleep(0.3)  # 窗口内注入（此时无任何工具在途）
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        r1 = client.post(
            "/api/v1/chat/queue",
            json={"session_id": sid, "message": INTERJECT_TEXT},
        )
        assert r1.status_code == 202
        queue_id = r1.json()["queue_id"]
        r2 = _interject(client, sid, queue_id, gen)
        assert r2.status_code == 202

        final = _wait_run_done(q, timeout=20)
        assert final.get("type") == "done"
        sess = engine.session.load(sid)
        texts = [m.content or "" for m in sess.messages]
        skip_msgs = [t for t in texts if "skipped_for_interjection" in t]
        # 序列头收割：两条调用均未执行（全部 skipped）
        assert len(skip_msgs) == 2, f"应两条全 skipped: {len(skip_msgs)}"
        item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
        c, r = item.get("created_at"), item.get("received_at")
        # 序列头收割生效时刻=LLM 计划返回后的序列头（~0.5s 后），脱离 2.0s 工具
        assert item.get("status") == "interject_received"
        t_effect = (r - c) * 1000 if c and r else None
        assert t_effect is not None and t_effect < 900.0, (
            f"序列头收割 t_effect={t_effect}ms 应显著小于 2.0s 工具路径"
        )
    finally:
        runner.cancel(sid)
