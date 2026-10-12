"""取消伴生 LLMError 归因隔离单元测试（T4，tasks 2.6；2.4 defect 回归）.

归因拦截置于 except LLMError 最前端：取消标记置位后无论何时抛出中断异常均按
取消收口，不进 guard/overflow/err1210/fallback/R9/故障反馈任何真实故障路径；
对照组（无标记）行为与现状一致（fail-safe 零回归）。
"""

from __future__ import annotations

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.llm.errors import LLMError

_STOP_TEXT_PREFIX = "（已停止"


def test_cancelled_llm_error_attributed_to_cancel(build_test_engine):
    engine, fake = build_test_engine([])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()

    def _raise_cancelled(calls):
        assert runner.cancel(sid) is True  # /stop 已受理（标记先于异常置位）
        raise LLMError("Operation canceled")

    fake._responses = [_raise_cancelled, {"content": "重试轮不应到达"}]
    result = engine.run(sid, "任务 X")

    assert result.final_answer.startswith(_STOP_TEXT_PREFIX)
    assert result.cancel_reason == "user_stop"
    assert "[程序异常]" not in result.final_answer
    assert len(fake.calls) == 1  # 无重试/err1210 恢复/fallback/auto-continue 轮


def test_cancelled_llm_error_variant_text_also_attributed(build_test_engine):
    engine, fake = build_test_engine([])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()

    def _raise_variant(calls):
        runner.cancel(sid)
        raise LLMError("Model unloaded")  # 文本漂移变体（标记位判定，禁止文本匹配）

    fake._responses = [_raise_variant]
    result = engine.run(sid, "任务")
    assert result.final_answer.startswith(_STOP_TEXT_PREFIX)
    assert result.cancel_reason == "user_stop"
    assert len(fake.calls) == 1


def test_uncancelled_llm_error_keeps_existing_behavior(build_test_engine):
    engine, fake = build_test_engine([])
    engine.runner = BackgroundRunner(engine)
    sid = engine.session.create()

    def _raise_uncancelled(calls):
        raise LLMError("Operation canceled")  # 无取消标记 → 真实故障路径（现状）

    fake._responses = [_raise_uncancelled, {"content": "对照完成"}]
    result = engine.run(sid, "任务")
    assert result.cancel_reason == ""
    assert not result.final_answer.startswith(_STOP_TEXT_PREFIX)
    assert len(fake.calls) >= 1
