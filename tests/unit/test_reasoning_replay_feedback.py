from __future__ import annotations

import json

import pytest

from llm_loop.feedback.honesty import llm_error_text
from llm_loop.llm.errors import LLMHTTPError

_MESSAGE = "The `reasoning_content` in the thinking mode must be passed back to the API."


def test_reasoning_replay_rejection_reports_protocol_cause():
    body = json.dumps({"error": {"message": _MESSAGE + " (request_id: test)",
                                 "type": "invalid_request_error"}})
    error = LLMHTTPError("HTTP 400: " + body, status_code=400, body=body, provider="deepseek")
    text = llm_error_text(error)
    assert "思考内容回传" in text
    assert "请求结构" in text
    assert "检查网络/Key/模型名配置" not in text
    assert str(error) in text


@pytest.mark.parametrize("status,body", [
    (500, json.dumps({"error": {"message": _MESSAGE}})),
    (400, json.dumps({"error": {"message": "Invalid model"}})),
    (400, "not JSON"),
    (400, json.dumps({"error": "reasoning_content"})),
])
def test_other_http_failures_keep_existing_feedback(status, body):
    error = LLMHTTPError("HTTP failure", status_code=status, body=body, provider="deepseek")
    assert "思考内容回传" not in llm_error_text(error)
