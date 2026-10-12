"""validator.check 崩溃时 fail-open：最终回答不丢，失败可观测。

背景: engine.py 调用点原先裸调 self.validator.check()——声明校验属
advisory 层（T38: 程序只提供事实提醒，不强制更正），其内部异常
（如 _audit 落盘失败）不应拖垮已产出的最终回答。修复后：异常被包含，
回答如实透传，warning 日志 + action trace（declaration.check /
validator_error）留痕，跳过不一致提醒。

对照: 正常路径（validator 正常工作、命中不一致）由
test_validator_declaration*.py 与 build_test_engine 系列隐式覆盖。
"""

from __future__ import annotations

import logging


class _CrashValidator:
    """duck typing DeclarationValidator 协议，check() 必崩。"""

    def check(self, final_answer: str, tool_msgs: list) -> object:
        raise RuntimeError("audit write exploded")


def test_validator_crash_failopen_keeps_answer(build_test_engine, caplog) -> None:
    """validator.check 崩溃 → 回答完好 + 日志/action trace 留痕（fail-open）。"""
    engine, _fake = build_test_engine([{"content": "最终回答完好"}])
    engine.validator = _CrashValidator()  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING, logger="llm_loop.core.loop.engine"):
        result = engine.run(engine.session.create(), "请回答")

    # ① 已产出的最终回答不被 advisory 层异常拖垮
    assert result.final_answer == "最终回答完好"
    # ② 失败不静默：warning 日志留痕
    assert any("validator.check" in r.message for r in caplog.records)
    # ③ action trace 留痕（conftest fake_settings 未关闭 self_inspection → enabled）
    trace = engine.status._action_trace  # noqa: SLF001
    hits = [
        t
        for t in trace
        if getattr(t, "phase", None) == "declaration.check"
        and getattr(t, "action_type", None) == "validator_error"
    ]
    assert hits and "audit write exploded" in hits[0].detail
