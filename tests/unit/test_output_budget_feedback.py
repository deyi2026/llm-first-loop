"""Real GLM reasoning exhaustion must be reported as an output limit."""

import pytest

from llm_loop.feedback.honesty import llm_error_text
from llm_loop.llm.errors import LLMEmptyResponseError, LLMTimeoutError


@pytest.mark.parametrize("finish_reason", ["length", "max_tokens", "MAX_TOKENS"])
def test_reasoning_exhaustion_reports_output_budget(finish_reason):
    error = LLMEmptyResponseError(
        "已投递思考 47359 字符",
        provider="glm",
        finish_reason=finish_reason,
        prompt_tokens=15612,
        completion_tokens=16000,
        reasoning_tokens=15998,
        provider_truncated=True,
    )
    text = llm_error_text(error)
    assert "输出预算耗尽" in text
    assert "16000" in text and "15998" in text
    assert "正文" in text and "工具调用" in text
    assert "提高" in text and "输出预算" in text
    assert "已投递思考 47359 字符" in text
    assert "瞬态抖动" not in text and "请直接重试" not in text
    assert "已有工具执行结果" in text


def test_length_without_usage_does_not_invent_token_counts():
    text = llm_error_text(LLMEmptyResponseError("empty", finish_reason="length"))
    assert "输出预算耗尽" in text
    assert "用量未报告" in text
    assert "思考 0" not in text


@pytest.mark.parametrize("finish_reason", ["", "stop", "content_filter"])
def test_unproven_empty_response_is_not_labelled_budget_exhaustion(finish_reason):
    text = llm_error_text(LLMEmptyResponseError(
        "empty", finish_reason=finish_reason, completion_tokens=16000,
    ))
    assert "输出预算耗尽" not in text
    assert "模型返回空响应" in text


def test_timeout_keeps_its_own_diagnosis():
    text = llm_error_text(LLMTimeoutError("request timeout"))
    assert "超时" in text
    assert "输出预算耗尽" not in text
