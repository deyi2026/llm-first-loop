"""Phase5 M3：流式打断度量验收（G1/G2 门，设计 §7）。

- G1：llm_stream_interrupt 桶 n≥10，P50≤500ms、P95≤900ms（S17-M1 场景形态）。
- G2：保守路径（开关关闭）llm_stream 桶 n≥10，P50≤1550ms（S17-M4 场景形态）。
产出 reports/phase5/m3/M3_ACCEPTANCE.json + m3-acceptance.md。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from llm_loop.core.loop.runner import BackgroundRunner  # noqa: E402
from llm_loop.web import build_app  # noqa: E402
from tests.phase4.test_m0_scenarios import (  # noqa: E402
    _hq_item,
    _hq_of,
    _wait_run_done,
)
from tests.phase5.test_m2_stream_interrupt import _deltas, _Injector  # noqa: E402

N = 10
REPORT = Path(__file__).resolve().parents[2] / "reports" / "phase5" / "m3"


def _pct(samples: list[float], q: float) -> float:
    xs = sorted(samples)
    k = max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1)))))
    return round(xs[k], 1)


def _run_bucket(build_test_engine, *, checkpoint_on: bool, n: int = N) -> dict:
    # 开关经 settings.tool_runtime（frozen dataclass）按引擎实例注入
    samples, vias, receipts = [], [], []
    for i in range(n):
        engine, fake = build_test_engine(
            [{"content": "STREAM-FULL"}, {"content": "final-after"}]
        )
        if not checkpoint_on:
            object.__setattr__(
                engine.settings.tool_runtime,
                "llm_stream_interject_checkpoint",
                False,
            )
        runner = BackgroundRunner(engine)
        engine.runner = runner
        client = TestClient(build_app(engine=engine))
        sid = engine.session.create()
        inj = _Injector(client, sid, runner)
        fake.enable_stream(
            {
                "deltas": _deltas(24),
                "delta_delay_s": 0.05,
                "on_delta_n": {6: inj.hook},
            }
        )
        _h, q = runner.start(sid, "请长篇回答")
        inj.run_inject()
        final = _wait_run_done(q, timeout=30)
        assert final.get("type") == "done", f"样本{i} run 未正常结束"
        item = _hq_item(_hq_of(client, engine), sid, inj.queue_id) or {}
        assert item.get("status") == "interject_received", f"样本{i} 未被消费"
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
    }


def test_m3_g1_g2_metrics(build_test_engine):
    g1 = _run_bucket(build_test_engine, checkpoint_on=True)
    assert all(v == "llm_stream_interrupt" for v in g1["consumed_via"]), g1
    assert not any(g1["interrupt_receipts"]), "新桶 interrupt_receipt 恒 False"
    assert g1["p50"] <= 500.0, f"G1 P50={g1['p50']}ms > 500ms"
    assert g1["p95"] <= 900.0, f"G1 P95={g1['p95']}ms > 900ms"

    g2 = _run_bucket(build_test_engine, checkpoint_on=False)
    assert all(v == "final_gate" for v in g2["consumed_via"]), g2
    assert g2["p50"] <= 1550.0, f"G2 P50={g2['p50']}ms > 1550ms"

    REPORT.mkdir(parents=True, exist_ok=True)
    payload = {
        "g1_llm_stream_interrupt": g1,
        "g2_llm_stream_conservative": g2,
        "gates": {
            "g1": {"p50_max_ms": 500.0, "p95_max_ms": 900.0,
                   "pass": g1["p50"] <= 500.0 and g1["p95"] <= 900.0},
            "g2": {"p50_max_ms": 1550.0, "pass": g2["p50"] <= 1550.0},
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (REPORT / "M3_ACCEPTANCE.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
    )
    md = [
        "# Phase5 M3 度量验收（G1/G2）",
        "",
        f"- G1 llm_stream_interrupt：n={g1['n']}，P50={g1['p50']}ms（门≤500）"
        f"，P95={g1['p95']}ms（门≤900）→ "
        f"{'PASS' if payload['gates']['g1']['pass'] else 'FAIL'}",
        f"- G2 llm_stream 保守（开关关闭）：n={g2['n']}，P50={g2['p50']}ms"
        f"（门≤1550）→ {'PASS' if payload['gates']['g2']['pass'] else 'FAIL'}",
        "",
        "样本明细见 M3_ACCEPTANCE.json；场景形态=S17-M1/M4（确定性注入钩子）。",
    ]
    (REPORT / "m3-acceptance.md").write_text("\n".join(md) + "\n")
