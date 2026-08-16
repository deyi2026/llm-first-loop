"""M52 Token 用量统计测试（founder 2026-08-11 需求: 参考 OpenClaw token 统计）.

覆盖:
- client 层: SSE 末 chunk usage 解析 / 缺失时 0（不伪造）
- loop 层: 多轮工具循环累加 / 默认 0
- format_tokens 人性化显示
- 飞书 footer 附带 token 用量 / Web ChatResponse 透传

全部 Mock, 零真实网络。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from llm_loop.core.loop import format_tokens
from llm_loop.llm.client import LLMClient, LLMResponse
from llm_loop.llm.errors import LLMHTTPError  # noqa: F401 — 保持与 fallback 测试一致

from .test_model_attribution import _make_engine, _make_pool, _settings  # noqa: F401

# ── client 层: usage 解析 ──


class _FakeStreamCtx:
    """模拟 httpx.Client.stream 上下文（与 test_llm_client.py 同模式）."""

    reason_phrase = "OK"

    def __init__(self, lines, status_code: int = 200, body: bytes = b"") -> None:
        self._lines = lines
        self.status_code = status_code
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body

    def iter_lines(self):
        yield from self._lines


def _client() -> LLMClient:
    return LLMClient(api_key="k", base_url="https://fake.local/v1", model="fake-model")


def test_client_parses_usage_chunk() -> None:
    """SSE 末 chunk 的 usage 被解析进 LLMResponse（M52）."""
    lines = [
        'data: {"choices": [{"delta": {"content": "回答"}, "finish_reason": "stop"}]}',
        'data: {"choices": [], "usage": {"prompt_tokens": 1234, "completion_tokens": 56, "total_tokens": 1290}}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.content == "回答"
    assert resp.prompt_tokens == 1234
    assert resp.completion_tokens == 56


def test_client_missing_usage_zeros() -> None:
    """provider 未返回 usage → 0/0（如实不伪造）."""
    lines = [
        'data: {"choices": [{"delta": {"content": "回答"}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.prompt_tokens == 0
    assert resp.completion_tokens == 0


# ── loop 层: 聚合 ──


def test_loop_aggregates_tokens_across_rounds(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """工具循环多轮 LLM 调用 → token 累加（M52）."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default_fake_responses = [
        # 第 1 轮: 工具调用（read_file 不存在路径, 失败也无所谓, 循环继续）
        LLMResponse(
            content=None,
            tool_calls=[SimpleNamespace(id="c1", name="read_file", arguments='{"path":"/nonexistent"}')],
            provider="fake",
            prompt_tokens=100,
            completion_tokens=10,
            prompt_cache_hit_tokens=50,
        ),
        # 第 2 轮: 最终回答
        LLMResponse(
            content="完成",
            tool_calls=[],
            provider="fake",
            prompt_tokens=200,
            completion_tokens=20,
            prompt_cache_hit_tokens=70,
        ),
    ]
    from .test_model_attribution import _FakeLLMClient

    default_fake = _FakeLLMClient("deepseek-v4-flash")
    default_fake.queue(default_fake_responses)
    pool = _make_pool(settings, default_fake)
    engine = _make_engine(tmp_path, pool, settings)

    result = engine.run(engine.session.create(), "读文件")
    assert result.final_answer == "完成"
    assert result.tokens_in == 300  # 100 + 200 累加
    assert result.tokens_out == 30  # 10 + 20 累加
    assert result.tokens_cache_hit == 120  # 50 + 70 累加（M58 缓存命中）


def test_loop_tokens_default_zero(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """响应无 usage → LoopResult tokens 为 0（不伪造）."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    from .test_model_attribution import _FakeLLMClient

    default_fake = _FakeLLMClient("deepseek-v4-flash")
    default_fake.queue([LLMResponse(content="回答", tool_calls=[], provider="fake")])
    pool = _make_pool(settings, default_fake)
    engine = _make_engine(tmp_path, pool, settings)

    result = engine.run(engine.session.create(), "你好")
    assert result.tokens_in == 0
    assert result.tokens_out == 0


# ── format_tokens ──


def test_format_tokens() -> None:
    """人性化显示: 0/999/1234/1500000."""
    assert format_tokens(0) == "0"
    assert format_tokens(999) == "999"
    assert format_tokens(1234) == "1.2k"
    assert format_tokens(1500000) == "1500.0k"


# ── 飞书 footer ──


def test_feishu_footer_includes_tokens(tmp_path) -> None:
    """飞书回复 footer: 模型 + token 用量同一行."""
    from llm_loop.core.session import SessionStore
    from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
    from llm_loop.feishu.session_map import SessionMap

    session_store = SessionStore(str(tmp_path / "sessions"))

    class _StubEngine:
        session = session_store

        def run(self, sid, text):
            return SimpleNamespace(
                session_id=sid,
                final_answer="回答",
                verification_note=None,
                rounds=1,
                tool_calls=[],
                truncated=False,
                model_used="deepseek/deepseek-v4-flash",
                tokens_in=1234,
                tokens_out=340,
            )

    session_map = SessionMap(session_store, path=str(tmp_path / "map.json"))
    replies: list[tuple[str, str, str]] = []
    handler = FeishuMessageHandler(
        _StubEngine(),
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
    )
    handler.handle(
        FeishuMessage(
            message_id="om_t1", sender_id="ou_u", chat_id="oc_c", msg_type="text", text="hi"
        )
    )
    assert replies[0][1].endswith("—— deepseek/deepseek-v4-flash · 1.2k入/340出")


# ── Web 端 ──


def test_web_chat_response_carries_tokens(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/v1/chat 响应含 tokens_in/tokens_out."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    from fastapi.testclient import TestClient

    from llm_loop.web import build_app

    from .test_model_attribution import _FakeLLMClient

    settings = _settings(tmp_path)
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    default_fake.queue(
        [LLMResponse(content="回答", tool_calls=[], provider="fake", prompt_tokens=50, completion_tokens=8)]
    )
    pool = _make_pool(settings, default_fake)
    engine = _make_engine(tmp_path, pool, settings)

    client = TestClient(build_app(engine=engine))
    resp = client.post("/api/v1/chat", json={"message": "你好"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tokens_in"] == 50
    assert body["tokens_out"] == 8
