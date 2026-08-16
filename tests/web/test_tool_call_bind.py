"""P3-1 工具调用与回执显式绑定（tool_call_id 配对卡片）Web 测试（design 2.5.2 T1-T9）.

覆盖：配对纯函数/渲染函数落地、历史映射保留 tool_call_id、未配对如实标注、
sanitize 白名单未放宽、既有渲染零回归、P2-1 消费保留、声明暂存写入、
后端契约零改动、历史接口 tool_call_id 透传回归。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_loop.web import build_app

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "llm_loop" / "web" / "static" / "app.js"
STYLE_CSS = ROOT / "src" / "llm_loop" / "web" / "static" / "style.css"


@pytest.fixture(scope="module")

def style_css_src() -> str:
    return STYLE_CSS.read_text(encoding="utf-8")


def _make_client(engine):
    return TestClient(build_app(engine=engine))


# ── T1: 配对逻辑存在性静态断言 ──


def test_pairing_functions_present(app_js_src, style_css_src):
    """配对纯函数/渲染函数/样式类均已落地."""
    for fn in ("buildToolPairIndex", "parseToolResultStatus", "renderToolPairCard", "renderArchiveButton"):
        assert f"function {fn}" in app_js_src, f"{fn} 未定义"
    assert "tool-pair-card" in app_js_src
    assert ".tool-pair-card" in style_css_src


# ── T2: 历史映射保留 tool_call_id ──


def test_history_mapping_keeps_tool_call_id(app_js_src):
    """loadSessionMessages/loadEarlierHistory 映射保留回执侧配对键."""
    assert "toolCallId: m.tool_call_id || null" in app_js_src


# ── T3: 未配对标注文案与样式 ──


def test_unpaired_miss_notes(app_js_src, style_css_src):
    """孤儿回执/未配对声明如实标注 + .tool-pair-miss-note 样式."""
    assert "未找到对应调用" in app_js_src
    assert "无对应回执" in app_js_src
    assert ".tool-pair-miss-note" in style_css_src
    assert "tool-pair-miss-note" in app_js_src


# ── T4: sanitize 白名单未放宽 ──


def test_sanitize_whitelist_not_relaxed(app_js_src):
    """XSS 白名单未放宽（复用 test_round4_stream_ux 模式）."""
    m = re.search(r"MD_ALLOWED_TAGS\s*=\s*new Set\(\[([^\]]+)\]", app_js_src)
    assert m, "MD_ALLOWED_TAGS 定义未找到"
    tags = m.group(1)
    for dangerous in ("script", "iframe", "style", "object", "embed"):
        assert dangerous not in tags, f"白名单含危险标签 {dangerous}"


# ── T5: 既有独立渲染保留 ──


def test_existing_rendering_kept(app_js_src):
    """既有独立折叠渲染保留，配对条件不成立时回退路径完整."""
    assert "function renderToolMessage" in app_js_src
    assert "function renderToolCalls" in app_js_src
    assert "renderToolMessage(msg, wrap" in app_js_src  # 回退路径引用


# ── T6: P2-1 消费未删除 ──


def test_p2_1_consumption_kept(app_js_src):
    """P2-1 tool_round 流式进展既有行为零回归."""
    assert "onToolRound" in app_js_src
    assert 'evt.type === "tool_round"' in app_js_src
    assert "function renderToolRoundProgress" in app_js_src


# ── T7: 声明暂存写入 ──


def test_declaration_index_staging(app_js_src):
    """state.declarationIndex 字段 + done 后写入逻辑存在."""
    assert "declarationIndex: new Map()" in app_js_src
    assert "state.declarationIndex" in app_js_src
    # done 分支写入声明事实（session_id 键控）
    assert "state.declarationIndex.get(data.session_id)" in app_js_src
    assert "sessionDecls.set(tc.id" in app_js_src


# ── T8: 后端契约零改动断言 ──


def test_message_item_contract_unchanged(build_test_engine):
    """历史接口 MessageItem 响应字段集不变（无新增字段）."""
    from llm_loop.core.message import Message, MessageSource, ToolResultStatus
    from llm_loop.core.session import Session

    engine, _ = build_test_engine([])
    session = Session(session_id="sess-contract")
    session.messages.append(Message(role="tool", content="[状态: success] ok",
                                    source=MessageSource.TOOL, tool_call_id="call-c1",
                                    status=ToolResultStatus.SUCCESS, tool_name="read_file"))
    engine.session.save(session)
    client = _make_client(engine)
    resp = client.get("/api/v1/sessions/sess-contract/messages")
    for m in resp.json()["messages"]:
        # M51/M52/M53: 模型+token+工具声明字段（2026-08-16 页脚/出产物扩展，属计划内契约变更）
        assert set(m.keys()) <= {
            "role", "content", "tool_call_id", "reasoning_content",
            "model_used", "tokens_in", "tokens_out", "tokens_cache_hit", "tool_calls",
        }


def test_sse_event_types_unchanged(build_test_engine, tmp_path):
    """SSE 事件类型集合仍为既有五类（无新增/修改事件）."""
    from llm_loop.core.message import ToolCall
    from llm_loop.llm.client import LLMResponse, StreamDelta

    f = tmp_path / "t.txt"
    f.write_text("x", encoding="utf-8")

    class _Fake:
        model = "fake-model"
        timeout_s = 120.0
        thinking_mode = True
        reasoning_effort = "high"
        thinking_supported = True

        def __init__(self, responses):
            self._r = list(responses)
            self.calls = []

        def chat(self, messages, tools, *, timeout_s=None, model=None):
            return self._r.pop(0)

        def chat_stream(self, messages, tools, *, timeout_s=None, model=None):
            resp = self._r.pop(0)
            for ch in (resp.content or ""):
                yield StreamDelta(text=ch)
            return resp

    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = _Fake([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="read_file",
                                                     arguments={"path": str(f)})], provider="fake"),
        LLMResponse(content="done", tool_calls=[], provider="fake"),
    ])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "read"})
    types = set()
    for block in resp.text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                types.add(json.loads(line[6:])["type"])
    assert types <= {"answer_delta", "reasoning_delta", "tool_round", "done", "error"}


# ── T9: 历史接口 tool_call_id 透传集成回归 ──


def test_message_item_tool_call_id_passthrough(build_test_engine):
    """历史接口 tool 消息 tool_call_id 透传回归（回执侧配对键数据可得）."""
    from llm_loop.core.message import Message, MessageSource, ToolResultStatus
    from llm_loop.core.session import Session

    engine, _ = build_test_engine([])
    session = Session(session_id="sess-passthrough")
    session.messages.append(Message(role="tool", content="[状态: success] ok",
                                    source=MessageSource.TOOL, tool_call_id="call-t9",
                                    status=ToolResultStatus.SUCCESS, tool_name="read_file"))
    engine.session.save(session)
    client = _make_client(engine)
    resp = client.get("/api/v1/sessions/sess-passthrough/messages")
    tool_msgs = [m for m in resp.json()["messages"] if m["role"] == "tool"]
    assert tool_msgs, "历史接口应含 tool 消息"
    assert tool_msgs[0]["tool_call_id"] == "call-t9"
