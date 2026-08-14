

def test_chat_stream_raises_on_sse_error_event():
    """P1-FEISHU: LM Studio SSE 错误事件不应被静默忽略.
    
    根因: chat_stream 只过滤 'data: ' 行,跳过 'event: error' 行;
    [system, system, ...] 触发 SSE 200 + event: error 错误时,旧代码
    返回空 content + 无 truncated → 用户看到'(空回答) + (回答被截断)' 假象。
    
    修复: 解析 data 后检测 chunk['error'] 字段 → 抛 LLMHTTPError 让循环层如实处理。
    """
    from unittest.mock import MagicMock, patch
    import httpx
    from llm_loop.llm.client import LLMClient, LLMHTTPError

    c = LLMClient(api_key="", base_url="http://test/v1", model="m", timeout_s=5)

    # 模拟 SSE 响应: HTTP 200 + event: error + data: {error:...}
    fake_lines = [
        "event: error",
        'data: {"error":{"code":500,"message":"Jinja Exception: System message must be at the beginning","type":"server_error"}}',
        "",
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/event-stream"}
    mock_resp.iter_lines.return_value = iter(fake_lines)

    with patch.object(httpx.Client, "stream") as mock_stream:
        # MagicMock context manager
        mock_stream.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_stream.return_value.__exit__ = MagicMock(return_value=False)

        with patch("llm_loop.llm.client.httpx.Client") as MockClient:
            MockClient.return_value.stream.return_value.__enter__ = MagicMock(return_value=mock_resp)
            MockClient.return_value.stream.return_value.__exit__ = MagicMock(return_value=False)

            raised = None
            try:
                list(c.chat_stream([{"role":"user","content":"hi"}], tools=[]))
            except LLMHTTPError as e:
                raised = e
            except Exception as e:
                raised = e

            assert isinstance(raised, LLMHTTPError), f"应抛 LLMHTTPError, 实际: {type(raised).__name__}: {raised}"
            assert raised.status_code == 500
            assert "System message" in raised.body or "Jinja" in raised.body
