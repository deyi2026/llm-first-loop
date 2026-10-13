"""Phase6 遗留处置 L1：流式检查点 peek fail-open（对齐 §4.4 保守降级）。

溯源双编号：docs/phase6-sync-async-design.md §9「M4 交付报告遗留候选」登记的
流式裸调 peek；本遗留处置批 L1 修复。契约（phase4-effect-latency-design §4.4）：
peek 失败不收割。同步窗口侧已由 phase4 test_d 锁定；本场景锁定流式侧：
流内检查点 peek 管道故障 → 流自然结束（不收割、不 error、无半截行），
插话由 final_gate 兜底消费，续跑轮历史含插话文本（与 S17-M4 保守路径同形态）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from llm_loop.core.loop.runner import BackgroundRunner  # noqa: E402
from llm_loop.web import build_app  # noqa: E402
from tests.phase4.test_m0_scenarios import (  # noqa: E402
    INTERJECT_TEXT,
    _hq_item,
    _hq_of,
    _wait_run_done,
)
from tests.phase5.test_m2_stream_interrupt import (  # noqa: E402
    STREAM_FINAL,
    STREAM_FULL,
    _Injector,
    _deltas,
)


def test_stream_peek_failure_fails_open(build_test_engine):
    """流式检查点 peek 管道故障 → run 正常完成，插话由 final_gate 兜底消费."""
    engine, fake = build_test_engine(
        [{"content": STREAM_FULL}, {"content": STREAM_FINAL}]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    inj = _Injector(client, sid, runner)
    fake.enable_stream(
        {
            "deltas": _deltas(20),
            "delta_delay_s": 0.05,
            "on_delta_n": {3: inj.hook},
        }
    )

    def _boom(_sid):
        raise RuntimeError("peek plumbing failure (stream fail-open test)")

    # 模拟 peek 管道故障：注入管道（queue/interject 端点）不依赖此方法，
    # 仍可正常投递；受影响的只有各检查点的到达探视。
    runner.interjections_pending = _boom
    try:
        _h, q = runner.start(sid, "请流式回答")
        inj.run_inject()
        final = _wait_run_done(q, timeout=30)

        # 核心断言：peek 故障 fail-open——run 正常完成而非 error 冒泡
        assert final.get("type") == "done", final

        # 流内不收割（检查点 peek 失败视为无插话）→ final_gate 兜底消费
        item = _hq_item(_hq_of(client, engine), sid, inj.queue_id) or {}
        assert item.get("status") == "interject_received", item
        assert item.get("consumed_via") == "final_gate", item

        # 流自然结束：无 llm_interrupted 半截行（对照 S17-M1 打断形态）
        sess = engine.session.load(sid)
        halves = [
            m for m in sess.messages
            if getattr(m, "metadata", None) and m.metadata.get("llm_interrupted")
        ]
        assert not halves, f"peek 失败不得产生半截行（应流自然结束）: {halves}"

        # final_gate 收割后 continue same run：续跑轮历史含插话文本
        assert len(fake.calls) >= 2, f"应续跑第二轮，实际 {len(fake.calls)}"
        next_msgs = fake.calls[1]["messages"]
        joined = "".join(
            str(m.get("content") or "") if isinstance(m, dict) else str(getattr(m, "content", "") or "")
            for m in next_msgs
        )
        assert INTERJECT_TEXT in joined, "final_gate 消费后续跑轮历史应含插话文本"

        # 终答=续跑轮完整响应（非半截、非第一轮流文本——该轮被 final_gate 拦截丢弃）
        _fa = getattr(final.get("result"), "final_answer", "") or final.get("final_answer", "")
        assert _fa == STREAM_FINAL, f"终答应为续跑轮完整响应，实际: {_fa!r}"
    finally:
        runner.cancel(sid)
