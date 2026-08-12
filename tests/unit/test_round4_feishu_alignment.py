"""方向 C 飞书能力对齐守护测试（spec 5.2 / design §2.4.2 / tasks 3.1）.

守护目标: 把 round4 方向 C 对齐结论（真流式不实施、前端概念无需移植、后端能力已复用）固化为
静态断言 + 契约不变守护，防止未来误移植 Web 前端概念或误改飞书推送契约。

断言:
1. feishu/handlers.py 仍走 engine.run（未引入 run_stream）—— 真流式不实施
2. feishu/handlers.py 含指令拦截 + _reply_chunked 分段 + StreamingCard 状态卡 —— 契约不变
3. feishu/handlers.py 不含 Web 前端概念（DOM 高亮/懒加载）—— 禁止移植前端概念
4. design.md 含「无需移植/可复用」结论 + 真流式收益取舍说明（卡片一次性渲染）
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FEISHU_HANDLERS = ROOT / "src" / "llm_loop" / "feishu" / "handlers.py"
DESIGN = ROOT / ".codeartsdoer" / "specs" / "ai_first_evolution_round4" / "design.md"


@pytest.fixture(scope="module")
def handlers_src() -> str:
    return FEISHU_HANDLERS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def design_src() -> str:
    return DESIGN.read_text(encoding="utf-8")


class TestFeishuAlignment:
    def test_uses_engine_run_not_run_stream(self, handlers_src: str):
        # 真流式不实施（spec 5.2 规则 2）
        assert "self._engine.run(" in handlers_src
        assert "run_stream" not in handlers_src

    def test_command_interception_unchanged(self, handlers_src: str):
        # 指令拦截契约不变（spec 5.2 规则 4）
        assert "/new" in handlers_src
        assert "/clear" in handlers_src
        assert "_try_handle_model_command" in handlers_src

    def test_chunked_reply_and_streaming_card(self, handlers_src: str):
        # 分段回复 + 状态卡契约不变（spec 5.2 规则 4）
        assert "_reply_chunked" in handlers_src
        assert "StreamingCard" in handlers_src

    def test_no_web_frontend_concepts(self, handlers_src: str):
        # 不移植 Web 前端概念（spec 5.2 规则 6）
        assert "highlightCodeBlock" not in handlers_src
        assert "loadEarlierHistory" not in handlers_src


class TestFeishuAlignmentDesign:
    def test_alignment_conclusion(self, design_src: str):
        # 对齐结论三类（spec 5.2 规则 1/2）
        assert "无需移植" in design_src
        assert "可复用" in design_src

    def test_streaming_benefit_tradeoff(self, design_src: str):
        # 真流式收益取舍说明（卡片一次性渲染）
        assert "真流式收益有限" in design_src or "真流式收益" in design_src
        assert "一次性渲染" in design_src or "卡片" in design_src
