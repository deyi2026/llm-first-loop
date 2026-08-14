"""M52: web 端显示完善——分层截断"查看完整原文" + 异常状态醒目."""

from __future__ import annotations

from pathlib import Path

import pytest


def read_all_js():
    from pathlib import Path
    _d = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "web" / "static"
    _fs = ["modules/state.js","modules/markdown-math.js","modules/tool-render.js","modules/message-render.js","modules/stream-chat.js","modules/app-core.js","modules/responsive.js","modules/session-list.js","modules/command-upload-model.js","app.js"]
    return chr(10).join((_d / f).read_text(encoding="utf-8") for f in _fs if (_d / f).exists())


STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "web" / "static"


@pytest.fixture(scope="module")
def app_js() -> str:
    return read_all_js()


@pytest.fixture(scope="module")
def style_css() -> str:
    return (STATIC_DIR / "style.css").read_text(encoding="utf-8")


# ── 前端静态断言 ──

def test_full_output_button_present(app_js):
    """分层截断回执有"查看完整原文"按钮 + 按 tool_call_id 取档案端点."""
    assert "查看完整原文" in app_js
    assert "[工具输出已分层]" in app_js
    assert "/archive/" in app_js and "tool_call_id" in app_js
    assert "原文不可用" in app_js  # 失败如实提示，不空白


def test_error_highlight_frontend(app_js, style_css):
    """异常回执（error/安全硬阻断/程序异常）→ ⚠️ + 红色样式；架构上报消息高亮."""
    assert "tool-call-toggle-error" in app_js
    assert "安全硬阻断" in app_js and "程序异常" in app_js
    assert "message-alert" in app_js
    assert ".tool-call-toggle-error" in style_css
    assert ".message-alert" in style_css
    assert ".tool-call-full-btn" in style_css


# ── 后端：MessageItem 透出 tool_call_id + 档案端点 ──

def test_message_item_has_tool_call_id():
    from llm_loop.web.schemas import MessageItem

    item = MessageItem(role="tool", content="x", tool_call_id="call-1")
    assert item.model_dump()["tool_call_id"] == "call-1"


def test_archive_get_by_tool_call_id(tmp_path):
    from llm_loop.memory.archive import ArchiveStore

    store = ArchiveStore(tmp_path)
    store.archive("s1", role="tool", source="tool", content="完整原文" * 100,
                  tool_name="execute_command", tool_call_id="call-abc", status="oversize")
    entry = store.get_by_tool_call_id("s1", "call-abc")
    assert entry is not None and entry["content"].startswith("完整原文")
    assert store.get_by_tool_call_id("s1", "call-nonexistent") is None
    assert store.get_by_tool_call_id("s1", "") is None
    assert store.get_by_tool_call_id("no-such-session", "call-abc") is None


def test_archive_endpoint(build_test_engine):
    """端点：归档可取回 / 未归档 404 / 会话不存在 404."""
    from fastapi.testclient import TestClient

    from llm_loop.web import build_app

    engine, _ = build_test_engine([])
    from llm_loop.core.session import Session

    engine.session.save(Session(session_id="sess-m52"))
    store = engine.archive
    store.archive("sess-m52", role="tool", source="tool", content="FULL-OUTPUT-BODY",
                  tool_name="execute_command", tool_call_id="call-full", status="oversize")

    client = TestClient(build_app(engine=engine))

    r = client.get("/api/v1/sessions/sess-m52/archive/call-full")
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "FULL-OUTPUT-BODY"
    assert body["tool_name"] == "execute_command"
    assert body["chars"] == len("FULL-OUTPUT-BODY")

    r404 = client.get("/api/v1/sessions/sess-m52/archive/call-nope")
    assert r404.status_code == 404
    assert "未归档" in r404.json()["detail"] or "无完整原文" in r404.json()["detail"]

    r_no_sess = client.get("/api/v1/sessions/ghost-sess/archive/call-full")
    assert r_no_sess.status_code == 404
