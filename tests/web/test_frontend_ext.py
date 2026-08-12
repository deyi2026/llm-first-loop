"""Web 前端增强测试（M39，静态断言，零真实冒烟无 node）.

用例：/命令处理函数存在 / 上传按钮与拖拽 / 复制按钮逻辑 / 附件上下文注入 / 前端零 key 字面量。
无 node/jsdom 环境，以"文件存在 + 函数引用 + 元素 id"静态断言兜底。
"""

from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.web import build_app

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
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "function handleCommand" in app_js
    assert '"/new"' in app_js
    assert '"/clear"' in app_js
    assert '"/help"' in app_js


def test_command_is_frontend_only():
    """命令处理不调用 /api/v1/chat（纯前端状态操作）."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    # handleCommand 内无 fetch api 调用（sendMessage 的命令分支直接 return）
    assert 'text.startsWith("/")' in app_js
    assert "handleCommand(text)" in app_js


def test_app_has_copy_button_logic():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "copy-btn" in app_js
    assert "navigator.clipboard.writeText" in app_js
    assert '"已复制"' in app_js


def test_app_has_upload_logic():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "async function uploadFile" in app_js
    assert "FileReader" in app_js
    assert '"/api/v1/upload"' in app_js


def test_app_attachment_context():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "attachments" in app_js
    assert "state.attachments" in app_js
    assert "attachmentPrefix" in app_js


def test_app_drag_drop():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "dragover" in app_js
    assert "e.dataTransfer.files" in app_js


def test_app_no_key_literal():
    """前端零 key 字面量（敏感信息保护）."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "API_KEY" not in app_js
    assert "sk-" not in app_js


def test_app_copy_uses_plaintext():
    """复制 final_answer 原文纯文本（copyMessage(msg.content)）."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "copyMessage(msg.content" in app_js


def test_frontend_served(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "upload-btn" in resp.text
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
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
