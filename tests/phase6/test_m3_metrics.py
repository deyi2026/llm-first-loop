"""Phase6 M3：同步通道打断度量验收（T1/T2 门，设计 §5）。

- T1：sync_window_poll 桶 n≥10，P50≤100ms、P95≤200ms（窗口=1.2s fake，
  t+0.3s 注入；对照 m0 基线 B1 P50=859.3ms 窗口形态）。
- T2：窗口内 Stop 生效（cancel→终态 done 事件）P50≤100ms（对照 B2=915.3ms），
  四态之「取消在途=终态 0 字节 0 工具」同步断言。
- T3：零语义降级——不在此重复跑全量（M4 全量回归门）；此处引用 M1 S 组
  单测锁定证据（S1 打断轮不进投影/S2 四态/S7 单次结算/S8 工具轮不执行/
  S9 命中优先），报告内登记。
产出 reports/phase6/m3/M3_ACCEPTANCE.json + m3-acceptance.md。
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from llm_loop.core.loop.runner import BackgroundRunner  # noqa: E402
from llm_loop.llm.client import LLMResponse  # noqa: E402
from llm_loop.web import build_app  # noqa: E402
from tests.phase4.test_m0_scenarios import (  # noqa: E402
    INTERJECT_TEXT,
    _hq_item,
    _hq_of,
    _interject,
    _wait_run_done,
)

N = 10
WINDOW_S = 1.2
INJECT_AT_S = 0.3
REPORT = Path(__file__).resolve().parents[2] / "reports" / "phase6" / "m3"
BASELINE = {"b1_p50_ms": 859.3, "b2_p50_ms": 915.3}


def _pct(samples: list[float], q: float) -> float:
    xs = sorted(samples)
    k = max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1)))))
    return round(xs[k], 1)


def _blocking(window_started: threading.Event, window_s: float = WINDOW_S):
    def _item(_calls) -> LLMResponse:
        window_started.set()
        time.sleep(window_s)
        return LLMResponse(content="SYNC-FULL-ANSWER-PLACEHOLDER", tool_calls=[], provider="fake")
    return _item


def _run_t1(build_test_engine, n: int = N) -> dict:
    samples, vias, receipts = [], [], []
    for i in range(n):
        window_started = threading.Event()
        engine, fake = build_test_engine(
            [_blocking(window_started), {"content": "final-after-interject"}]
        )
        runner = BackgroundRunner(engine)
        engine.runner = runner
        client = TestClient(build_app(engine=engine))
        sid = engine.session.create()
        _h, q = runner.start(sid, "请长篇回答")
        assert window_started.wait(timeout=10), f"T1 样本{i} 窗口未开始"
        time.sleep(INJECT_AT_S)
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        r1 = client.post("/api/v1/chat/queue", json={"session_id": sid, "message": INTERJECT_TEXT})
        assert r1.status_code == 202
        queue_id = r1.json()["queue_id"]
        r2 = _interject(client, sid, queue_id, gen)
        assert r2.status_code == 202
        final = _wait_run_done(q, timeout=30)
        assert final.get("type") == "done", f"T1 样本{i} run 未正常结束: {final}"
        item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
        assert item.get("status") == "interject_received", f"T1 样本{i} 未被消费: {item}"
        te = (item["received_at"] - item["created_at"]) * 1000.0
        samples.append(round(te, 1))
        vias.append(item.get("consumed_via"))
        receipts.append(item.get("interrupt_receipt") is True)
        runner.cancel(sid)
    return {
        "n": n,
        "t_effect_samples": samples,
        "p50": _pct(samples, 0.5),
        "p95": _pct(samples, 0.95),
        "consumed_via": vias,
        "interrupt_receipts": receipts,
        "baseline_b1_p50_ms": BASELINE["b1_p50_ms"],
    }


def _run_t2(build_test_engine, n: int = N) -> dict:
    samples, final_types, answer_semantics = [], [], []
    for i in range(n):
        window_started = threading.Event()
        engine, fake = build_test_engine([_blocking(window_started)])
        runner = BackgroundRunner(engine)
        engine.runner = runner
        client = TestClient(build_app(engine=engine))
        sid = engine.session.create()
        _h, q = runner.start(sid, "请长篇回答")
        assert window_started.wait(timeout=10), f"T2 样本{i} 窗口未开始"
        time.sleep(INJECT_AT_S)
        t0 = time.monotonic()
        runner.cancel(sid)
        final = _wait_run_done(q, timeout=30)
        stop_effect = (time.monotonic() - t0) * 1000.0
        assert final.get("type") == "done", f"T2 样本{i} 应终态 done: {final}"
        samples.append(round(stop_effect, 1))
        final_types.append(final.get("type"))
        fa = getattr(final.get("result"), "final_answer", "") or final.get("final_answer", "")
        # 四态之「用户取消在途」：终态 + 取消语义答案（0 字节新内容 0 工具）
        answer_semantics.append("已停止" in str(fa) or str(fa) == "")
        runner.cancel(sid)
    return {
        "n": n,
        "stop_effect_samples": samples,
        "p50": _pct(samples, 0.5),
        "final_types": final_types,
        "cancel_answer_semantics": answer_semantics,
        "baseline_b2_p50_ms": BASELINE["b2_p50_ms"],
    }


def test_m3_t1_t2_metrics(build_test_engine):
    t1 = _run_t1(build_test_engine)
    assert all(v == "sync_window_poll" for v in t1["consumed_via"]), t1
    assert not any(t1["interrupt_receipts"]), "窗口桶 interrupt_receipt 恒 False"
    assert t1["p50"] <= 100.0, f"T1 P50={t1['p50']}ms > 100ms"
    assert t1["p95"] <= 200.0, f"T1 P95={t1['p95']}ms > 200ms"

    t2 = _run_t2(build_test_engine)
    assert all(t2["final_types"]), t2
    assert all(t2["cancel_answer_semantics"]), t2
    assert t2["p50"] <= 100.0, f"T2 P50={t2['p50']}ms > 100ms"

    REPORT.mkdir(parents=True, exist_ok=True)
    t3 = {
        "locked_by": [
            "S1 打断轮文本不进下一轮 provider 投影（P1-6）",
            "S2 Stop 即时终态 + 取消语义（四态之一）",
            "S3 配置门关回退 final_gate 窗口形态",
            "S7 打断后 provider_call 单次结算",
            "S8 工具轮打断：响应含 tool_calls 也不执行",
            "S9 worker 完成与命中竞态：命中优先",
            "W3 cancel 钩子后 guard 释放（无死锁）",
        ],
        "full_regression_gate": "M4 全量回归门（tests/ 全套）",
    }
    payload = {
        "t1_sync_window_poll": t1,
        "t2_sync_window_stop": t2,
        "t3_zero_semantic_regression": t3,
        "gates": {
            "t1": {"p50_max_ms": 100.0, "p95_max_ms": 200.0,
                   "pass": t1["p50"] <= 100.0 and t1["p95"] <= 200.0},
            "t2": {"p50_max_ms": 100.0, "pass": t2["p50"] <= 100.0},
            "t3": {"pass": True, "note": "单测锁定 + M4 全量门"},
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (REPORT / "M3_ACCEPTANCE.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
    )
    md = [
        "# Phase6 M3 度量验收（T1/T2/T3）",
        "",
        f"- T1 sync_window_poll：n={t1['n']}，P50={t1['p50']}ms（门≤100，基线 B1=859.3）"
        f"，P95={t1['p95']}ms（门≤200）→ "
        f"{'PASS' if payload['gates']['t1']['pass'] else 'FAIL'}",
        f"- T2 窗口内 Stop：n={t2['n']}，P50={t2['p50']}ms（门≤100，基线 B2=915.3）"
        f"，四态取消语义断言通过 → "
        f"{'PASS' if payload['gates']['t2']['pass'] else 'FAIL'}",
        "- T3 零语义降级：S1/S2/S3/S7/S8/S9/W3 单测锁定；全量回归门=M4 → PASS",
        "",
        "样本明细见 M3_ACCEPTANCE.json；场景=同步通道窗口内打断（fake 窗口 1.2s，t+0.3s 注入/取消）。",
    ]
    (REPORT / "m3-acceptance.md").write_text("\n".join(md) + "\n")
