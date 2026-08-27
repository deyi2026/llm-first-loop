"""P0-B 程序反馈语义分离验收测试（2026-08-28 用户批准，方案见
.codeartsdoer/specs/err1210_locating/P0-B-program-feedback-separation.md）。

覆盖三处小修的行为契约：
- B1 engine 收尾 source 判定（前缀语义，与 B2/B3 同源常量）
- B2 build 投影标记（提交视图加前缀，存储原文不动）
- B3 extractor 过滤（程序反馈不进长期记忆提取）
"""
from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.feedback.honesty import PROGRAM_FEEDBACK_PREFIXES


def test_b1_prefix_semantics():
    """前缀清单语义: 程序反馈文本命中，正常回答不命中（B1/B2/B3 共用判定源）."""
    assert len(PROGRAM_FEEDBACK_PREFIXES) == 10
    pf_samples = [
        "[LLM 调用异常] 事实: LLM 调用失败。\n原因: HTTP 400。",
        "[停滞熔断] 事实: 已连续 5 次以相同参数调用工具。",
        "[已达轮数上限] 事实: 已达到最大循环轮数。",
        "[缓存守卫拦截] 稳定段指纹不符。",
        "[上下文超限] 本次请求载荷约 123 tokens。",
        "[上下文压缩] 历史已折叠。",
        "[搜索空结果提醒] 连续 2 次未命中。",
        "[程序异常] 会话保存失败。",
        "（已停止——用户点击停止按钮，本轮回答终止）",
    ]
    for s in pf_samples:
        assert s.startswith(PROGRAM_FEEDBACK_PREFIXES), s[:30]
    assert not "正常模型回答：结论是 X。".startswith(PROGRAM_FEEDBACK_PREFIXES)
    assert not "".startswith(PROGRAM_FEEDBACK_PREFIXES)


def test_b3_extractor_filters():
    """B3: 程序反馈 assistant 消息不进 _build_history_text（记忆提取输入）."""
    from llm_loop.memory.extractor import MemoryExtractor

    ex = object.__new__(MemoryExtractor)  # 纯方法，无状态依赖
    msgs = [
        Message(role="user", content="继续", source=MessageSource.USER),
        Message(role="assistant", content="[LLM 调用异常] 事实: 调用失败。", source=MessageSource.USER),
        Message(role="assistant", content="正常回答：结论 X。", source=MessageSource.USER),
        Message(role="user", content="[上下文压缩] 这是 user 角色同前缀文本（不应过滤）", source=MessageSource.USER),
    ]
    text = ex._build_history_text(msgs)
    assert "LLM 调用异常" not in text  # assistant 程序反馈被滤
    assert "正常回答：结论 X。" in text
    assert "这是 user 角色同前缀文本" in text  # 仅滤 assistant，user 不误伤


def test_b2_projection_marks_and_storage_untouched(tmp_path: Path):
    """B2: 投影副本加 [程序反馈·非模型回答] 前缀；存储原文不动（含存量 USER source）."""
    from tests.unit.test_injection_fingerprint import _engine

    engine, sess = _engine(tmp_path)
    sess.messages.append(
        Message(role="assistant", content="[停滞熔断] 事实: 已连续 5 次。", source=MessageSource.USER)
    )  # 存量形态（B1 落库前 source 仍 USER）
    built = engine._build_llm_messages(sess, [], max_chars=200_000, planned_label="zhipu/glm-5")
    marked = [d for d in built if "停滞熔断" in str(d.get("content", ""))]
    assert marked, "程序反馈消息未进投影（投影完整性）"
    assert all(str(d["content"]).startswith("[程序反馈·非模型回答]") for d in marked)
    # 存储原文不动（replace 语义副本，非原地改）
    assert sess.messages[-1].content.startswith("[停滞熔断]")
    assert "[程序反馈·非模型回答]" not in sess.messages[-1].content
