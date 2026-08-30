"""GOAL-20260829-7483e375 T2: 分层前缀单测.

契约（docs/local/DESIGN-PREFIX-LAYERED-20260829.md §3）:
- 锚层字节跨轮冻结（同任务连续两轮渲染 diff=0）
- 动态层只增不减（尾部追加，已注入条目字节不变）
- 索引条目合法（无非标准键，80 字符截断，required 并入 description）
- 逃生门 get_tool_schema 恒在锚层
- prefix_layered 默认关（零回归基线）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from llm_loop.tools.prefix_layer import (  # noqa: E402
    ANCHOR_TOOLS,
    INDEX_DESC_CHARS,
    LayeredPrefixState,
    build_layered_schemas,
)
from llm_loop.tools.registry import ToolRegistry  # noqa: E402


def _make_tool(name: str, desc: str, required: list[str] | None = None, props: int = 4):
    props_d = {f"p{i}": {"type": "string", "description": "字段说明" * 8} for i in range(props)}
    if required:
        for r in required:
            props_d[r] = {"type": "string", "description": "必填字段说明" * 6}
    return NS(
        name=name,
        description=desc,
        parameters={"type": "object", "properties": props_d, "required": required or []},
    )


def _make_registry():
    r = ToolRegistry()
    for name in ANCHOR_TOOLS:
        r.register(_make_tool(name, f"{name} 工具。" + "描述长文" * 40, ["a", "b"]))
    r.register(_make_tool("web_fetch", "抓网页。" + "描述" * 60, ["url"]))
    r.register(_make_tool("web_search", "搜索。" + "描述" * 60))
    r.register(_make_tool("schedule", "定时提醒。" + "描述" * 60, ["message"]))
    r.register(_make_tool("unrelated_tool", "无关工具。" + "描述" * 60))
    return r


class TestAnchorByteStability:
    def test_same_task_two_rounds_identical_bytes(self):
        r = _make_registry()
        st = LayeredPrefixState()
        t1 = build_layered_schemas(r, "普通任务文本", st)
        r2 = build_layered_schemas(r, "普通任务文本", st)  # 第二轮（无新命中）
        assert json.dumps(t1, ensure_ascii=False) == json.dumps(r2, ensure_ascii=False)

    def test_anchor_prefix_bytes_stable_after_dynamic_append(self):
        """动态层追加后：列表条目级前缀稳定（旧条目字节不变），新工具仅尾部追加.

        注: JSON 数组序列化尾部追加不保字符串严格前缀（"]"→","），契约按
        条目级前缀断言（设计文档 §3 追加规则）。
        """
        r = _make_registry()
        st = LayeredPrefixState()
        first = build_layered_schemas(r, "帮我看看代码结构", st)
        # 第二轮任务文本命中新关键词 → web_fetch 追加
        second = build_layered_schemas(r, "再帮我抓取这个网页", st)
        assert second[: len(first)] == first, "追加式契约破坏：已注入条目发生变化"
        assert len(second) > len(first)
        assert second[-1]["name"] == "web_fetch"


class TestDynamicLayer:
    def test_keyword_select_hits(self):
        st = LayeredPrefixState()
        names = {"web_fetch", "web_search", "schedule", *ANCHOR_TOOLS}
        got = st.select_dynamic("抓取网页 http 链接，顺便搜索最新论文", names)
        assert "web_fetch" in got and "web_search" in got

    def test_anchor_tools_excluded_from_dynamic(self):
        st = LayeredPrefixState()
        names = {"web_fetch", "read_file", *ANCHOR_TOOLS}
        got = st.select_dynamic("读取 read_file 修改 edit_file", names)
        assert "read_file" not in got and "edit_file" not in got

    def test_injected_never_removed(self):
        r = _make_registry()
        st = LayeredPrefixState()
        first = build_layered_schemas(r, "定时提醒我", st)
        names_after = [t["name"] for t in first]
        assert "schedule" in names_after
        second = build_layered_schemas(r, "无关文本", st)  # 关键词消失
        names_second = [t["name"] for t in second]
        assert "schedule" in names_second, "动态层只增不减被破坏"

    def test_unknown_tool_skipped(self):
        st = LayeredPrefixState()
        got = st.select_dynamic("抓取网页", {"read_file"})  # web_fetch 不在注册表
        assert got == []


class TestIndexSchemas:
    def test_index_truncates_and_merges_required(self):
        r = _make_registry()
        idx = {t["name"]: t for t in r.index_schemas()}
        t = idx["web_fetch"]
        assert "必填: url" in t["description"]
        assert len(t["description"]) <= INDEX_DESC_CHARS + 40  # 截断+尾部必填说明
        assert t["parameters"] == {"type": "object"}  # 合法最小 schema

    def test_index_no_nonstandard_keys(self):
        r = _make_registry()
        for t in r.index_schemas():
            assert set(t.keys()) == {"name", "description", "parameters"}


class TestEscapeHatch:
    def test_get_tool_schema_in_anchor(self):
        r = _make_registry()
        st = LayeredPrefixState()
        out = build_layered_schemas(r, "任意任务", st)
        names = [t["name"] for t in out]
        assert "get_tool_schema" in names
        assert names[0] == "execute_command"  # 锚层顺序恒定


class TestZeroRegression:
    def test_prefix_layered_default_off(self):
        from llm_loop.config import Settings

        import os
        os.environ.pop("PREFIX_LAYERED", None)
        s = Settings.__dataclass_fields__["prefix_layered"].default if hasattr(
            Settings, "__dataclass_fields__"
        ) else None
        # dataclass 默认值断言（不依赖完整 Settings 构造）
        assert s is False

    def test_layered_smaller_than_full(self):
        """真实分布模拟（40 工具: 8 锚层 + 32 非锚层）下 layered < lazy < full."""
        r = ToolRegistry()
        for name in ANCHOR_TOOLS:
            r.register(_make_tool(name, f"{name} 工具。" + "描述长文" * 40, ["a", "b"]))
        for i in range(32):
            r.register(_make_tool(f"tool_{i:02d}", f"工具{i}。" + "描述" * 60, [f"k{i}"]))
        st = LayeredPrefixState()
        layered = len(json.dumps(build_layered_schemas(r, "任务", st), ensure_ascii=False))
        full = len(json.dumps(r.schemas(lazy=False), ensure_ascii=False))
        lazy = len(json.dumps(r.schemas(lazy=True), ensure_ascii=False))
        assert layered < lazy < full, (layered, lazy, full)


class TestEngineIsolation:
    def test_session_state_does_not_leak_between_sessions(self):
        """Web/Feishu 共享单 Engine 时，动态 schema 不能跨 session 污染。"""
        from llm_loop.core.loop.engine import LoopEngine

        engine = object.__new__(LoopEngine)
        engine._prefix_states = {}
        a = engine._prefix_state_for("session-a")
        b = engine._prefix_state_for("session-b")
        a.mark_injected(["web_fetch"])
        assert a.injected == ("web_fetch",)
        assert b.injected == ()
        assert engine._prefix_state_for("session-a") is a
        assert engine._prefix_state_for("session-b") is b

    def test_layered_schema_uses_current_turn_text(self):
        """同 session 新 user turn 必须能追加新工具，不能钉死首条历史 user。"""
        from llm_loop.core.loop.engine import LoopEngine

        engine = object.__new__(LoopEngine)
        engine._prefix_states = {}
        engine.registry = _make_registry()
        first = engine._layered_tool_schemas("session-a", "定时提醒我")
        second = engine._layered_tool_schemas("session-a", "再帮我抓取这个网页")
        def _full_count(rows, name):
            return sum(
                1
                for row in rows
                if row["name"] == name and "properties" in row.get("parameters", {})
            )

        # 非锚工具始终先有一条 index schema；动态命中时才在尾部追加 full schema。
        assert _full_count(first, "schedule") == 1
        assert _full_count(first, "web_fetch") == 0
        assert _full_count(second, "schedule") == 1
        assert _full_count(second, "web_fetch") == 1
        assert second[: len(first)] == first
