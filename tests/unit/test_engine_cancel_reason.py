"""取消原因标记贯穿单元测试（T3，tasks 2.6）：检查点捕获 → LoopResult → run.end 事件."""

from __future__ import annotations

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.llm.client import LLMResponse


def test_sync_run_cancel_reason_flows_to_result_and_run_end(build_test_engine, tmp_path):
    from llm_loop.event_log.store import EventStore

    engine, fake = build_test_engine([])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    event_store = EventStore(tmp_path / "events")
    engine._event_store = event_store
    sid = engine.session.create()

    def _first_then_cancel(calls):
        assert runner.cancel(sid) is True  # /stop 到达（sync run 进行中）
        return LLMResponse(content="中途", tool_calls=[], provider="fake")

    fake._responses = [_first_then_cancel, {"content": "不应到达"}]
    result = engine.run(sid, "任务 X")

    assert result.final_answer.startswith("（已停止")
    assert result.cancel_reason == "user_stop"
    assert len(fake.calls) == 1  # 取消后无新 LLM 轮
    events = event_store.read(sid)
    run_ends = [e for e in events if e.type == "run.end"]
    assert run_ends, "run.end 事件应落盘"
    assert run_ends[-1].payload["reason"] == "cancelled"
    assert run_ends[-1].payload["cancel_reason"] == "user_stop"


def test_completed_run_has_empty_cancel_reason(build_test_engine, tmp_path):
    from llm_loop.event_log.store import EventStore

    engine, fake = build_test_engine([{"content": "done"}])
    engine.runner = BackgroundRunner(engine)
    engine._event_store = EventStore(tmp_path / "events")
    sid = engine.session.create()
    result = engine.run(sid, "hello")
    assert result.cancel_reason == ""
    events = engine._event_store.read(sid)
    run_ends = [e for e in events if e.type == "run.end"]
    assert run_ends[-1].payload["reason"] == "completed"
    assert run_ends[-1].payload["cancel_reason"] == ""
