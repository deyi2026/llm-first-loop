"""v0.6.5 tool_call.arguments 解析回归防护（2026-08-15 现场修复）.

背景：v0.6.5 客户端重写时本地重定义了 ToolCallDeltaAggregator 且 finish() 不解析
arguments（原版从 llm/schemas.py 导入，finish 含 json.loads 归一）→ 真实 provider
返回的 JSON 字符串 arguments 原样进入注册表 → 全部工具调用被 "[参数错误] 参数必须为
JSON 对象" 拒绝（第 12 连败根因）。本测试补盲区：真实流式字符串 → 引擎端到端执行。
"""

from __future__ import annotations

from llm_loop.llm.client import LLMClient
from llm_loop.llm.schemas import ToolCallDeltaAggregator
from llm_loop.tools.registry import ToolRegistry, ToolResultStatus


def test_schemas_aggregator_normalizes_arguments_to_dict():
    """schemas.finish：JSON 字符串 → dict；非法 JSON → _raw_arguments 兜底（不崩）."""
    agg = ToolCallDeltaAggregator()
    agg.add_delta({"index": 0, "id": "c1", "function": {"name": "read_file", "arguments": "{\"path\":"}})
    agg.add_delta({"index": 0, "function": {"arguments": "\"a.txt\"}"}})
    calls = agg.finish()
    assert calls[0]["arguments"] == {"path": "a.txt"}
    assert calls[0]["_arguments_raw"] == '{"path":"a.txt"}'


def test_aggregator_malformed_falls_back_honest():
    """非法 JSON → _raw_arguments 携带原文（引擎层据此如实反馈，不静默不崩溃）."""
    agg = ToolCallDeltaAggregator()
    agg.add_delta({"index": 0, "id": "c1", "function": {"name": "x", "arguments": "{broken json"}})
    calls = agg.finish()
    assert calls[0]["arguments"] == {"_raw_arguments": "{broken json"}


def test_full_loop_string_arguments_executes_tool(build_test_engine, tmp_path):
    """端到端：真实客户端（mock SSE，arguments 为 JSON 字符串）→ 工具真实执行。

    回归根因路径全覆盖：SSE 字符串 arguments → schemas 聚合器 json.loads 归一 →
    注册表收到 dict → read_file 真实执行（若回归复现则为 "[参数错误] 参数必须为 JSON 对象"）。
    """
    from unittest import mock as _mock


    target = tmp_path / "data.txt"
    target.write_text("内容X", encoding="utf-8")

    class _FakeStream:
        def __init__(self):
            self.status_code = 200
            self.reason_phrase = "OK"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self):
            import json as _json

            # 真实 provider 形态：function.arguments 为 JSON 字符串
            args_str = _json.dumps({"path": str(target)})
            chunk = {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_r1",
                                    "function": {"name": "read_file", "arguments": args_str},
                                }
                            ]
                        }
                    }
                ]
            }
            yield "data: " + _json.dumps(chunk)
            yield 'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}'
            yield "data: [DONE]"

        def read(self):
            return b""

    engine, fake = build_test_engine([])
    with _mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStream()
        real = LLMClient(
            api_key="k",
            base_url="https://fake.local/v1",
            model="m",
            timeout_s=30.0,
            wire_protocol="openai",
        )
        # build_test_engine 装配了 llm_pool（FakeLLM 为 default_client）——替换 pool 默认客户端
        engine.llm = real
        if engine.llm_pool is not None:
            engine.llm_pool.default_client = real
        sid = engine.session.create()
        result = engine.run(sid, "读文件")
    assert result.final_answer is not None
    tool_msgs = [m for m in engine.session.load(sid).messages if m.role == "tool"]
    assert tool_msgs, "工具未被调用（arguments 解析回归）"
    assert "内容X" in tool_msgs[-1].content
    assert "参数必须为 JSON 对象" not in tool_msgs[-1].content


def test_registry_rejects_non_dict_honestly():
    """注册表防线仍在：非 dict arguments → 如实参数错误（不回执成功）."""
    from llm_loop.core.message import ToolCall

    reg = ToolRegistry()
    reg.register(_FakeEchoTool())
    r = reg.execute(ToolCall(id="c1", name="echo", arguments="not-a-dict"))
    assert r.status == ToolResultStatus.FAILURE
    assert "参数必须为 JSON 对象" in r.content


class _FakeEchoTool:
    name = "echo"
    description = "回显"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}}

    def execute(self, **kwargs):
        from llm_loop.core.message import ToolResult, ToolResultStatus

        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"echo:{kwargs.get('text')}",
            tool_call_id="",
            tool_name=self.name,
        )
