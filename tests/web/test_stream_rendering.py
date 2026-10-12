"""Web 流式渲染静态断言测试（spec 5.3.1 / design §2.4.3 / tasks 3.3）.

断言:
1. app.js 含 fakeTypewriter 函数（方案 A 前端假流式落地）
2. 假流式最终渲染内容 = 完整 final_answer（分片拼接等价，不丢内容）
3. ChatResponse 九字段零改动（schemas.py 对比，spec 4.5.1）
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "llm_loop" / "web" / "static" / "app.js"
SCHEMAS = ROOT / "src" / "llm_loop" / "web" / "schemas.py"

CHAT_RESPONSE_FIELDS = [
    "session_id",
    "final_answer",
    "verification_note",
    "rounds",
    "tool_calls",
    "truncated",
    "model_used",
    "tokens_in",
    "tokens_out",
    "tokens_cache_hit",
]



class TestStreamRendering:
    def test_fake_typewriter_defined(self, app_js_src: str):
        assert "function fakeTypewriter" in app_js_src

    def test_chunked_slicing(self, app_js_src: str):
        # 分片逻辑：按 chunkChars 逐片 slice
        assert "slice(0, pos)" in app_js_src

    def test_final_content_equals_full_answer(self, app_js_src: str):
        # 分片拼接等价：完成时用完整 answerHtml（不丢内容，spec 5.3.1 规则 6）
        assert "done ? answerHtml : answerHtml.slice(0, pos)" in app_js_src

    def test_fail_open_no_blank(self, app_js_src: str):
        # 渲染失败降级纯文本（不空白）
        assert "node.textContent = part" in app_js_src

    def test_typewriter_called_in_render_messages(self, app_js_src: str):
        assert "fakeTypewriter(body, msg.content" in app_js_src

    def test_no_react_import(self, app_js_src: str):
        assert "import React" not in app_js_src
        assert 'from "react"' not in app_js_src


class TestChatResponseContract:
    def test_chat_response_fields_unchanged(self):
        schemas = SCHEMAS.read_text(encoding="utf-8")
        # 九字段（M51 model_used + M52 tokens_in/out 扩展）零改动
        for f in CHAT_RESPONSE_FIELDS:
            assert f in schemas, f"ChatResponse 缺字段 {f}"
