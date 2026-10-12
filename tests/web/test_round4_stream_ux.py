"""Web 流式体验打磨静态断言测试（spec 5.3.1~5.3.4 / design §2.4.3 / tasks 5.5）.

断言:
1. D1: isMessagesAtBottom 底部判定 + scrollHeight - scrollTop - clientHeight
2. D1: onDelta 渲染后仅底部态滚底（isMessagesAtBottom 条件）
3. D2: reader.read() 被 try/catch 包裹（读异常不 throw 穿透）
4. D2: streamChatRequest 返回 errorType（network/engine 区分）+ 重试入口
5. D3: error 事件为终态（break，不继续追加分片）
6. D4: final_answer 空时 pop()/「无文字回答」清理
7. 分片经 renderMarkdown 渲染（不 innerHTML 直接注入原始分片）
8. 零框架 + sanitize 白名单未放宽
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "llm_loop" / "web" / "static" / "app.js"



class TestScrollFollow:
    def test_is_messages_at_bottom_defined(self, app_js_src: str):
        assert "function isMessagesAtBottom" in app_js_src

    def test_bottom_detection_formula(self, app_js_src: str):
        assert "scrollHeight - " in app_js_src
        assert "clientHeight" in app_js_src
        assert "SCROLL_FOLLOW_THRESHOLD" in app_js_src

    def test_ondelta_scrolls_only_at_bottom(self, app_js_src: str):
        assert "isMessagesAtBottom()" in app_js_src


class TestStreamRetry:
    def test_reader_read_wrapped_in_try_catch(self, app_js_src: str):
        # 读异常被 try/catch 捕获，不 throw 穿透
        assert "await reader.read()" in app_js_src
        idx = app_js_src.index("await reader.read()")
        assert "try {" in app_js_src[max(0, idx - 60) : idx + 40]

    def test_error_type_field(self, app_js_src: str):
        assert "errorType: \"network\"" in app_js_src
        assert "errorType: \"engine\"" in app_js_src

    def test_retry_entry(self, app_js_src: str):
        assert "重试" in app_js_src
        assert "retry-btn" in app_js_src
        assert "runStreamChat(state.retryRequest" in app_js_src


class TestErrorBoundary:
    def test_error_event_is_terminal(self, app_js_src: str):
        # error 事件置 errorData 后 break（不继续追加分片）
        assert "errorData = evt.data" in app_js_src
        assert "finished = true; break" in app_js_src


class TestEmptyAnswerCleanup:
    def test_pop_empty_placeholder(self, app_js_src: str):
        assert "state.messages.pop()" in app_js_src

    def test_no_text_answer_placeholder(self, app_js_src: str):
        assert "（无文字回答）" in app_js_src


class TestSafetyAndFramework:
    def test_delta_rendered_via_markdown(self, app_js_src: str):
        # 分片经 renderMarkdown 渲染（不 innerHTML 直接注入原始分片）
        assert "renderMarkdown(acc)" in app_js_src

    def test_no_react_import(self, app_js_src: str):
        assert "import React" not in app_js_src
        assert 'from "react"' not in app_js_src

    def test_no_vue_import(self, app_js_src: str):
        assert 'from "vue"' not in app_js_src
        assert "require('vue')" not in app_js_src

    def test_no_new_cdn(self, app_js_src: str):
        assert "hljs" not in app_js_src

    def test_sanitize_whitelist_not_relaxed(self, app_js_src: str):
        m = re.search(r"MD_ALLOWED_TAGS\s*=\s*new Set\(\[([^\]]+)\]", app_js_src)
        assert m, "MD_ALLOWED_TAGS 定义未找到"
        tags = m.group(1)
        assert "script" not in tags
        assert "iframe" not in tags
        assert "style" not in tags
        assert "object" not in tags
        assert "embed" not in tags
