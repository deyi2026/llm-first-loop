"""lms-chat 协议测试（EVO-20260817 用户需求：本地模型走 /api/v1/chat + 工具上下文精简）.

覆盖: 消息→input 转换 / 工具描述文本注入 / 文本工具协议解析（围栏/杂文本/args 字符串化）/
上下文精简（只保留最近 N 条）/ 无工具时不注入.
纯函数测试（不依赖真实 HTTP；端点行为已 curl 实测）。
"""

from __future__ import annotations

from llm_loop.llm.client import LLMClient


def _client(**kw) -> LLMClient:
    kw.setdefault("api_key", "")
    kw.setdefault("base_url", "http://localhost:1234/v1")
    kw.setdefault("model", "qwen3.8-27b-mlx")
    kw.setdefault("wire_protocol", "lms-chat")
    return LLMClient(**kw)


def test_input_system_tools_tail():
    """system + 工具描述 + 最近 N 条历史 → input 数组."""
    c = _client()
    messages = [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "第一轮"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "现在几点了？"},
    ]
    tools = [{"type": "function", "function": {"name": "get_time", "description": "获取当前时间", "parameters": {"type": "object", "properties": {}}}}]
    out = c._to_lms_input(messages, tools)
    assert len(out) == 1 and out[0]["type"] == "text"
    text = out[0]["content"]
    assert "[系统] 你是助手" in text
    assert "[可用工具]" in text and "get_time" in text
    assert "[用户] 现在几点了？" in text
    assert "调用工具时，仅输出一行 JSON" in text


def test_input_tail_trim():
    """工具轮只保留最近 LMS_CHAT_TAIL 条（不发全部历史）."""
    c = _client()
    messages = [{"role": "system", "content": "S"}] + [
        {"role": "user", "content": f"第{i}轮"} for i in range(30)
    ]
    out = c._to_lms_input(messages, [])
    text = out[0]["content"]
    assert "第0轮" not in text  # 最旧已裁剪
    assert "第29轮" in text


def test_no_tools_no_inject():
    """无工具时不注入 [可用工具] 段."""
    c = _client()
    out = c._to_lms_input([{"role": "user", "content": "hi"}], [])
    assert "[可用工具]" not in out[0]["content"]


def test_parse_simple_json():
    """整条输出即 JSON 工具调用."""
    calls = LLMClient._parse_text_tool_calls('{"tool": "get_time", "args": {}}')
    assert calls == [{"name": "get_time", "arguments": {}}]


def test_parse_fenced_and_noise():
    """```json 围栏 + 前后杂文本仍能解析."""
    calls = LLMClient._parse_text_tool_calls(
        '好的，我来查一下：\n```json\n{"tool": "get_time", "args": {}}\n```\n结果如下'
    )
    assert calls == [{"name": "get_time", "arguments": {}}]


def test_parse_args_string():
    """args 为 JSON 字符串时自动解析."""
    calls = LLMClient._parse_text_tool_calls('{"tool": "search", "args": "{\\"q\\": \\"x\\"}"}')
    assert calls == [{"name": "search", "arguments": {"q": "x"}}]


def test_parse_invalid_fail_open():
    """非法 JSON / 无 tool 键 → 空列表（当普通回答，不崩溃）."""
    assert LLMClient._parse_text_tool_calls("今天天气不错") == []
    assert LLMClient._parse_text_tool_calls('{"args": {}}') == []


def test_msg_text_roles():
    """消息文本化：user/assistant(tool_calls)/tool 角色前缀标记."""
    assert LLMClient._lms_msg_text({"role": "user", "content": "hi"}) == "[用户] hi"
    assert LLMClient._lms_msg_text({"role": "assistant", "content": "ok"}) == "[助手] ok"
    assert LLMClient._lms_msg_text({"role": "assistant", "content": "查一下", "tool_calls": [{"function": {"name": "get_time", "arguments": {}}}]}) == '[助手] 查一下 [调用工具 get_time 参数 {}]'
    assert LLMClient._lms_msg_text({"role": "tool", "name": "get_time", "content": "2026-08-17"}) == "[工具结果 get_time] 2026-08-17"
