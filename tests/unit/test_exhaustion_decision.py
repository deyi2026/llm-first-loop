"""轮次耗尽决策轮测试（2026-08-15 用户需求）.

旧行为：rounds >= max_iterations → 罐装 [已达轮数上限] 直接终止。
新行为：耗尽时注入一次 [轮次决策请求]，请 AI 归因——
  ① 工具使用错误/空转 → 如实归因 + 正确做法 + 当前结论收尾（不调大轮数）；
  ② 正常任务推进 → adjust_strategy 调大 max_iterations（≤500）续跑。
决策轮后 AI 未调大且仍耗竭 → 回到罐装如实终止（程序兜底边界不变）。
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall


def _read_call(i: int) -> ToolCall:
    return ToolCall(id=f"call_{i}", name="read_file", arguments={"path": "/nonexistent/x.txt"})


def test_exhaustion_decision_then_continue_via_adjust(build_test_engine):
    """正常推进路径：耗尽 → 决策轮 AI 调大 max_iterations → 续跑至完成."""
    engine, fake = build_test_engine(
        [
            {"tool_calls": [_read_call(1)]},
            {"tool_calls": [_read_call(2)]},
            {"tool_calls": [_read_call(3)]},
            # 决策轮：AI 判断正常推进 → adjust_strategy 调大
            {
                "tool_calls": [
                    ToolCall(
                        id="call_adj",
                        name="adjust_strategy",
                        arguments={"strategy": {"max_iterations": 10}},
                    )
                ]
            },
            {"content": "任务完成：已读齐全部文件。"},
        ]
    )
    object.__setattr__(engine.settings, "max_iterations", 3)
    sid = engine.session.create()
    result = engine.run(sid, "读文件")

    assert result.final_answer == "任务完成：已读齐全部文件。"
    assert "已达轮数上限" not in result.final_answer
    sess = engine.session.load(sid)
    assert any("[轮次决策请求]" in (m.content or "") for m in sess.messages), "未注入决策请求"
    # adjust_strategy 生效（续跑的事实证据）
    assert engine.correction_ctx.strategy.get("max_iterations") == 10


def test_exhaustion_decision_attribution_end(build_test_engine):
    """错误归因路径：决策轮 AI 纯文本归因收尾 → 回答即归因文本，决策请求仅注入一次."""
    engine, fake = build_test_engine(
        [
            {"tool_calls": [_read_call(1)]},
            {"tool_calls": [_read_call(2)]},
            {"tool_calls": [_read_call(3)]},
            # 决策轮：AI 归因（工具使用错误）并给当前结论
            {"content": "归因：我反复用了错误路径读取（工具使用错误）；正确做法是先列目录确认文件名。当前结论：目标内容未能获取。"},
        ]
    )
    object.__setattr__(engine.settings, "max_iterations", 3)
    sid = engine.session.create()
    result = engine.run(sid, "读文件")

    assert result.final_answer.startswith("归因：")
    sess = engine.session.load(sid)
    decision_msgs = [m for m in sess.messages if "[轮次决策请求]" in (m.content or "")]
    assert len(decision_msgs) == 1, "决策请求应恰好注入一次"
    assert "已达轮数上限" not in result.final_answer  # AI 已归因收尾，不再叠加罐装反馈


def test_exhaustion_decision_misuse_falls_back(build_test_engine):
    """兜底：决策轮 AI 不调大也不收尾（继续调普通工具）→ 罐装如实终止."""
    engine, fake = build_test_engine(
        [{"tool_calls": [_read_call(i)]} for i in range(15)]
    )
    object.__setattr__(engine.settings, "max_iterations", 3)
    sid = engine.session.create()
    result = engine.run(sid, "读文件")

    assert "已达轮数上限" in result.final_answer
    sess = engine.session.load(sid)
    decision_msgs = [m for m in sess.messages if "[轮次决策请求]" in (m.content or "")]
    assert len(decision_msgs) == 1


def test_decision_message_structure():
    """决策请求消息三要素：两种情形列举 + 各自处置（adjust 上限 500 / 归因收尾）."""
    from llm_loop.feedback.honesty import max_iterations_decision_message

    msg = max_iterations_decision_message(40, 40)
    assert msg.role == "system"
    assert "[轮次决策请求]" in msg.content
    assert "工具使用错误" in msg.content or "空转" in msg.content
    assert "正常" in msg.content
    assert "adjust_strategy" in msg.content
    assert "500" in msg.content
    assert "40" in msg.content
