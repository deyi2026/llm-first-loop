"""P0-B 程序反馈语义分离验收测试（2026-08-28 用户批准，方案见
.codeartsdoer/specs/err1210_locating/P0-B-program-feedback-separation.md）。

覆盖三处小修的行为契约：
- B1 engine 收尾 source 判定（前缀语义，与 B2/B3 同源常量）
- B2 build 协议边界（提交视图移除故障细节但保留 assistant role，存储原文不动）
- B3 extractor 过滤（程序反馈不进长期记忆提取）
"""
from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.feedback.honesty import PROGRAM_FEEDBACK_PREFIXES


def test_b1_prefix_semantics():
    """前缀清单语义: 程序反馈文本命中，正常回答不命中（B1/B2/B3 共用判定源）."""
    # The list is an extensible single source of truth; test semantic coverage rather
    # than freezing its cardinality as new program exits are added.
    assert PROGRAM_FEEDBACK_PREFIXES
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


def test_b2_projection_uses_constant_protocol_boundary_and_storage_untouched(tmp_path: Path):
    """B2 supersession: retire program detail but preserve assistant protocol shape."""
    from llm_loop.core.prompt_eligibility import PROGRAM_FINAL_PROTOCOL_BOUNDARY
    from tests.unit.test_injection_fingerprint import _engine

    engine, sess = _engine(tmp_path)
    sess.messages.extend(
        [
            Message(role="user", content="OLD-UNRESOLVED-TASK", source=MessageSource.USER),
            Message(
                role="assistant",
                content="[停滞熔断] SECRET-OLD-FAULT-DETAIL",
                source=MessageSource.USER,
            ),
            Message(role="user", content="继续", source=MessageSource.USER),
        ]
    )
    engine._current_turn_ref = 2
    built = engine._build_llm_messages(
        sess, [], max_chars=200_000, planned_label="zhipu/glm-5"
    )
    contents = [str(d.get("content", "")) for d in built]
    assert "SECRET-OLD-FAULT-DETAIL" not in str(built)
    idx = contents.index(PROGRAM_FINAL_PROTOCOL_BOUNDARY)
    assert built[idx]["role"] == "assistant"
    assert built[idx - 1]["role"] == "user"
    assert built[idx + 1]["role"] == "user"
    assert built[idx + 1]["content"] == "继续"
    # Storage remains exact historical truth; only provider projection is minimized.
    assert sess.messages[-2].content == "[停滞熔断] SECRET-OLD-FAULT-DETAIL"


def test_b2_metadata_program_origin_projects_same_constant_boundary(tmp_path: Path):
    from llm_loop.core.prompt_eligibility import PROGRAM_FINAL_PROTOCOL_BOUNDARY
    from tests.unit.test_injection_fingerprint import _engine

    engine, sess = _engine(tmp_path)
    sess.messages.append(
        Message(
            role="assistant",
            content="DYNAMIC-PROGRAM-DETAIL-WITHOUT-LEGACY-PREFIX",
            source=MessageSource.SYSTEM,
            metadata={"answer_origin": "program", "run_end_reason": "llm_error"},
        )
    )
    built = engine._build_llm_messages(
        sess, [], max_chars=200_000, planned_label="zhipu/glm-5"
    )
    assert "DYNAMIC-PROGRAM-DETAIL-WITHOUT-LEGACY-PREFIX" not in str(built)
    assert any(d.get("content") == PROGRAM_FINAL_PROTOCOL_BOUNDARY for d in built)
    assert sess.messages[-1].content == "DYNAMIC-PROGRAM-DETAIL-WITHOUT-LEGACY-PREFIX"
