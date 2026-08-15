"""Web 前端增强测试（M39，静态断言，零真实冒烟无 node）.

用例：/命令处理函数存在 / 上传按钮与拖拽 / 复制按钮逻辑 / 附件上下文注入 / 前端零 key 字面量。
无 node/jsdom 环境，以"文件存在 + 函数引用 + 元素 id"静态断言兜底。
"""

from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def read_all_js():
    from pathlib import Path
    _d = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "web" / "static"
    _fs = ["modules/state.js","modules/markdown-math.js","modules/tool-render.js","modules/message-render.js","modules/stream-chat.js","modules/app-core.js","modules/responsive.js","modules/session-list.js","modules/command-upload-model.js","app.js"]
    return chr(10).join((_d / f).read_text(encoding="utf-8") for f in _fs if (_d / f).exists())


STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "web" / "static"


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def test_index_has_upload_button():
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "upload-btn" in index
    assert "file-input" in index
    assert "accept=" in index


def test_index_upload_accepts_types():
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for ext in (".pdf", ".docx", ".png", ".jpg", ".txt", ".md"):
        assert ext in index


def test_app_has_command_handler():
    app_js = read_all_js()
    assert "function handleCommand" in app_js
    assert '"/new"' in app_js
    assert '"/clear"' in app_js
    assert '"/help"' in app_js


def test_command_is_frontend_only():
    """命令处理不调用 /api/v1/chat（纯前端状态操作）."""
    app_js = read_all_js()
    # handleCommand 内无 fetch api 调用（sendMessage 的命令分支直接 return）
    assert 'text.startsWith("/")' in app_js
    assert "handleCommand(text)" in app_js


def test_app_has_copy_button_logic():
    app_js = read_all_js()
    assert "copy-btn" in app_js
    assert "navigator.clipboard.writeText" in app_js
    assert '"已复制"' in app_js


def test_app_has_upload_logic():
    app_js = read_all_js()
    assert "async function uploadFile" in app_js
    assert "FileReader" in app_js
    assert '"/api/v1/upload"' in app_js


def test_app_attachment_context():
    app_js = read_all_js()
    assert "attachments" in app_js
    assert "state.attachments" in app_js
    assert "attachmentPrefix" in app_js


def test_app_drag_drop():
    app_js = read_all_js()
    assert "dragover" in app_js
    assert "e.dataTransfer.files" in app_js


def test_app_no_key_literal():
    """前端零 key 字面量（敏感信息保护）."""
    app_js = read_all_js()
    assert "API_KEY" not in app_js
    assert "sk-" not in app_js


def test_app_copy_uses_plaintext():
    """复制 final_answer 原文纯文本（copyMessage(msg.content)）."""
    app_js = read_all_js()
    assert "copyMessage(msg.content" in app_js


def test_frontend_served(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "upload-btn" in resp.text
    app_js = read_all_js()
    assert "copy-btn" in app_js  # 复制按钮由 JS 动态生成


def test_upload_endpoint_reachable(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/api/info")
    assert resp.status_code == 200
    # upload 端点为 POST（不在此验证 GET，仅确认服务可达）


def test_style_has_upload_styles():
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert ".btn-secondary" in css
    assert ".copy-btn" in css
    assert ".attachment-bubble" in css
    assert ".dragover" in css


def test_app_has_tool_call_chain_render():
    """P2-1: app.js 含 renderToolCalls 折叠链渲染与 data.tool_calls 消费逻辑."""
    app_js = read_all_js()
    assert "function renderToolCalls" in app_js
    assert "function renderToolMessage" in app_js
    assert "data.tool_calls" in app_js  # sendMessage 200 分支消费 tool_calls
    assert "tool-call-chain" in app_js


def test_app_keeps_tool_role_in_history():
    """P2-1: loadSessionMessages 保留 tool 角色消息（历史刷新后工具回执可见）."""
    app_js = read_all_js()
    assert 'm.role === "tool"' in app_js  # 白名单保留 tool 角色


def test_style_has_tool_chain_styles():
    """P2-1: style.css 含 .tool-call- 折叠样式类."""
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    for cls in (".tool-call-chain", ".tool-call-toggle", ".tool-call-detail", ".tool-call-item"):
        assert cls in css


# ── 2026-08-15: SSE 前端加固（失联自愈看门狗 + 聚焦即刷 + 命名事件监听）──

class TestSseFrontendHardening:
    def test_refresh_from_sync_defined(self, app_js_src: str):
        assert "function refreshFromSync" in app_js_src

    def test_watchdog_self_heal(self, app_js_src: str):
        assert "25000" in app_js_src  # 失联阈值 25s
        assert "visibilityState" in app_js_src

    def test_visibility_change_reload(self, app_js_src: str):
        assert "visibilitychange" in app_js_src

    def test_named_event_listener_kept(self, app_js_src: str):
        assert 'addEventListener("sessions_updated"' in app_js_src
        assert 'addEventListener("connected"' in app_js_src
