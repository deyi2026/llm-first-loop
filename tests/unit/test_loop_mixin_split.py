"""LoopEngine M53 拆分结构契约测试（P4-1，design §4.3）.

纯重构验证：新 Mixin 模块布局、re-export 原路径可导入、run_stream 三处委托、
engine.py 体量缩减。静态断言风格（无 mock、不触发完整引擎）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.core.loop.routing import _RoutingMixin

LOOP_DIR = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "core" / "loop"


@pytest.fixture(scope="module")
def engine_src() -> str:
    return (LOOP_DIR / "engine.py").read_text(encoding="utf-8")


def test_loop_mixin_split_layout():
    """新 Mixin 模块布局：类定义 + 文件级 pyright 豁免 + TYPE_CHECKING 循环规避."""
    for fname in ("routing.py", "tool_exec.py", "lifecycle.py"):
        src = (LOOP_DIR / fname).read_text(encoding="utf-8")
        mixin = {
            "routing.py": "_RoutingMixin",
            "tool_exec.py": "_ToolExecMixin",
            # R9-B5-W2-01: _LifecycleMixin 职责面迁 SessionLifecycle 后更名，编排入口留此
            "lifecycle.py": "_RunEntrypointMixin",
        }[fname]
        assert f"class {mixin}:" in src, f"{fname} 缺 {mixin} 类定义"
        assert "reportAttributeAccessIssue=false" in src, f"{fname} 缺 pyright 文件级豁免"
        assert "from llm_loop.core.loop.engine import LoopEngine" in src, f"{fname} 缺 TYPE_CHECKING 引用"


def test_loop_reexport_kept():
    """re-export: 迁移符号原路径可导入且取值/行为正确（REQ-REF-06）."""
    from llm_loop.core.loop.engine import (
        _CHARS_PER_TOKEN_EST,
        _CONTEXT_SAFETY_MARGIN,
        _json_dumps_args,
        _tool_args_summary,
    )

    # 2026-08-24 校准（拷问产出）: 2 → 0.6（实测大上下文 1.676 tok/char, 旧值低估 3.35 倍）
    assert _CHARS_PER_TOKEN_EST == 0.6
    assert _CONTEXT_SAFETY_MARGIN == 0.9
    assert _tool_args_summary({"path": "/tmp/file.txt"}) == '{"path": "/tmp/file.txt"}'
    assert _json_dumps_args({"a": 1}) == '{"a": 1}'


def test_run_stream_delegation_points(engine_src):
    """run_stream 三处委托调用全部就位（REQ-REF-02a）."""
    assert "self._route_model(" in engine_src
    assert "self._termination._handle_overflow(" in engine_src
    assert "yield from self._execute_tools(" in engine_src


def test_local_tool_allowlist_filter():
    """EVO-20260817: local provider 工具精简（固定白名单, 省 token 不影响推理）."""
    schemas = [
        {"name": "read_file"},
        {"name": "web_fetch"},
        {"name": "submit_evolution"},
        {"name": "switch_model"},
        {"name": "get_tool_schema"},
    ]
    kept = _RoutingMixin._filter_local_tools(None, schemas, "local/qwen3.8-27b-mlx")
    names = [t["name"] for t in kept]
    assert "read_file" in names and "web_fetch" in names and "get_tool_schema" in names
    assert "submit_evolution" not in names and "switch_model" not in names
    # 非 local provider 零回归
    kept2 = _RoutingMixin._filter_local_tools(None, schemas, "deepseek/deepseek-v4-flash")
    assert len(kept2) == len(schemas)
