"""Phase6 M0：同步 chat 通道打断基线度量（现状，未改造）。

场景形态（设计 §2 现状事实）：
- B1：无 chat_stream 客户端（FakeLLM 同步形态）阻塞窗口内插话 → 只能等
  final_gate 收割，t_effect ≈ 剩余窗口（窗口形态，非检查点形态）。
- B2：阻塞窗口内 Stop → 取消仅在 chat 返回后被观察（stop_effect ≈ 剩余窗口）。

产出 reports/phase6/m0/BASELINE.json + baseline.md。
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

N = 5
WINDOW_S = 1.2      # 模拟 web 同步 chat 阻塞窗口（deepseek transport turn_timeout 上界 120s 的缩小形态）
INJECT_AT_S = 0.3   # 窗口内注入时刻
REPORT = Path(__file__).resolve().parents[2] / "reports" / "phase6" / "m0"


def _pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return round(s[k], 1)


def _blocking_response(window_started: threading.Event, window_s: float):
    def _item(_calls) -> LLMResponse:
        window_started.set()
        time.sleep(window_s)
        return LLMResponse(content="SYNC-FULL-ANSWER-PLACEHOLDER", tool_calls=[], provider="fake")
    return _item


def test_m0_sync_channel_baseline(build_test_engine):
    """B1 插话窗口形态 + B2 Stop 窗口形态，n=5。"""
    b1_samples, b1_vias = [], []
    for i in range(N):
        window_started = threading.Event()
        engine, fake = build_test_engine(
            [
                _blocking_response(window_started, WINDOW_S),
                {"content": "final-after-interject"},
            ]
        )
        runner = BackgroundRunner(engine)
        engine.runner = runner
        client = TestClient(build_app(engine=engine))
        sid = engine.session.create()
        _h, q = runner.start(sid, "请长篇回答")
        assert window_started.wait(timeout=10), f"B1样本{i} 同步窗口未开始"
        time.sleep(INJECT_AT_S)
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        r1 = client.post(
            "/api/v1/chat/queue",
            json={"session_id": sid, "message": INTERJECT_TEXT},
        )
        assert r1.status_code == 202, r1.status_code
        queue_id = r1.json()["queue_id"]
        r2 = _interject(client, sid, queue_id, gen)
        assert r2.status_code == 202, r2.status_code
        final = _wait_run_done(q, timeout=30)
        assert final.get("type") == "done", f"B1样本{i} run 未正常结束: {final}"
        item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
        assert item.get("status") == "interject_received", f"B1样本{i} 未被消费: {item}"
        te = (item["received_at"] - item["created_at"]) * 1000.0
        b1_samples.append(round(te, 1))
        b1_vias.append(item.get("consumed_via"))
        runner.cancel(sid)

    b2_samples, b2_finals = [], []
    for i in range(N):
        window_started = threading.Event()
        engine, fake = build_test_engine([_blocking_response(window_started, WINDOW_S)])
        runner = BackgroundRunner(engine)
        engine.runner = runner
        client = TestClient(build_app(engine=engine))
        sid = engine.session.create()
        _h, q = runner.start(sid, "请长篇回答")
        assert window_started.wait(timeout=10), f"B2样本{i} 同步窗口未开始"
        time.sleep(INJECT_AT_S)
        t0 = time.monotonic()
        runner.cancel(sid)
        final = _wait_run_done(q, timeout=30)
        stop_effect_ms = (time.monotonic() - t0) * 1000.0
        b2_samples.append(round(stop_effect_ms, 1))
        b2_finals.append(final.get("type"))

    payload = {
        "scenario": {
            "window_s": WINDOW_S,
            "inject_at_s": INJECT_AT_S,
            "expected_remaining_ms": round((WINDOW_S - INJECT_AT_S) * 1000, 1),
        },
        "b1_sync_interject_final_gate": {
            "n": N,
            "t_effect_samples": b1_samples,
            "p50": _pct(b1_samples, 0.5),
            "consumed_via": b1_vias,
        },
        "b2_sync_stop_window": {
            "n": N,
            "stop_effect_samples": b2_samples,
            "p50": _pct(b2_samples, 0.5),
            "final_event_types": b2_finals,
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "BASELINE.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    # 基线形态断言：窗口形态（t_effect / stop_effect 接近剩余窗口 ~900ms），
    # 而非检查点形态（Phase5 G1 实测 P50 3.7ms 量级）。
    assert all(v == "final_gate" for v in b1_vias), b1_vias
    assert payload["b1_sync_interject_final_gate"]["p50"] > 700.0, (
        f"B1 基线应呈窗口形态（>700ms），实测 {payload['b1_sync_interject_final_gate']['p50']}ms"
    )
    assert payload["b2_sync_stop_window"]["p50"] > 700.0, (
        f"B2 基线应呈窗口形态（>700ms），实测 {payload['b2_sync_stop_window']['p50']}ms"
    )
