"""轮次耗尽处理测试（R8.24-B B-2.1/B-D6 重写：硬边界直接结束）.

旧行为（2026-08-15 决策轮）：耗尽时注入 [轮次决策请求]，花第 N+1 轮 LLM
调用请 AI 归因/续跑。
新行为（R8.24-B B-D6，总审计 P0-6）: 到达 round 硬限 → 直接结束/暂停 +
UI 终态提示（用户可继续），第 N+1 轮 LLM call=0（B-G4）；
决策轮/预警注入路径删除，模型可见面零 [轮次决策请求]/[轮数预警]。
旧决策轮行为保留历史参照：max_iterations_decision_message 函数体与
test_decision_message_structure 反例自证。
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall


def _read_call(i: int) -> ToolCall:
    return ToolCall(id=f"call_{i}", name="read_file", arguments={"path": "/nonexistent/x.txt"})


def test_exhaustion_hard_stop_zero_extra_llm_call(build_test_engine):
    """B-G4: 到达 budget 直接硬停——无决策轮、第 N+1 次 LLM call=0、终态纯事实."""
    engine, fake = build_test_engine(
        [{"tool_calls": [_read_call(i)]} for i in range(1, 7)]
    )
    object.__setattr__(engine.settings, "max_iterations", 3)
    sid = engine.session.create()
    result = engine.run(sid, "读文件")

    assert len(fake.calls) == 3  # 恰好 budget 次（决策轮会多一次）
    assert "已达轮数上限" in result.final_answer
    assert "read_file" in result.final_answer  # 轨迹事实在场
    sess = engine.session.load(sid)
    assert not any("[轮次决策请求]" in (m.content or "") for m in sess.messages)


def test_exhaustion_hard_stop_no_decision_message(build_test_engine):
    """决策消息零注入（sess.messages 干净）；终态含"用户可继续"提示（默认开关）."""
    engine, fake = build_test_engine(
        [{"tool_calls": [_read_call(i)]} for i in range(1, 7)]
    )
    object.__setattr__(engine.settings, "max_iterations", 2)
    sid = engine.session.create()
    result = engine.run(sid, "读文件")

    sess = engine.session.load(sid)
    decision_msgs = [m for m in sess.messages if "[轮次决策请求]" in (m.content or "")]
    assert len(decision_msgs) == 0
    warning_msgs = [m for m in sess.messages if "[轮数预警]" in (m.content or "")]
    assert len(warning_msgs) == 0
    assert "继续" in result.final_answer  # LFL_E18_HARD_STOP=1 默认提示行
    # 存储面终态只留协议占位（B-D7/B-D11），全文经 LoopResult 交付
    from llm_loop.core.prompt_eligibility import PROGRAM_FINAL_PROTOCOL_BOUNDARY

    last_assistant = [m for m in sess.messages if m.role == "assistant"][-1]
    assert last_assistant.content == PROGRAM_FINAL_PROTOCOL_BOUNDARY


def test_exhaustion_hard_stop_user_continues_in_new_run(build_test_engine):
    """硬停后用户继续（衔接 E 包 task_active 语义）: 新 run 正常接续（历史保留）."""
    engine, fake = build_test_engine(
        [
            {"tool_calls": [_read_call(i)]} for i in range(1, 4)
        ]
        + [{"content": "接续后的完成回答"}]
    )
    object.__setattr__(engine.settings, "max_iterations", 2)
    sid = engine.session.create()
    first = engine.run(sid, "读文件")
    assert "已达轮数上限" in first.final_answer

    second = engine.run(sid, "继续")
    assert second.final_answer == "接续后的完成回答"


def test_decision_message_structure():
    """反例自证: 退役决策消息函数体保留历史参照（生产调用点为零——静态断言
    见 test_runtime_zero_prompt_static.py）。"""
    from llm_loop.feedback.honesty import max_iterations_decision_message

    msg = max_iterations_decision_message(40, 40)
    assert msg.role == "system"
    assert "[轮次决策请求]" in msg.content
    assert "工具使用错误" in msg.content or "空转" in msg.content
    assert "正常" in msg.content
    assert "adjust_strategy" in msg.content
    assert "500" in msg.content
    assert "40" in msg.content
