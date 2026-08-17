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
    for fname in ("routing.py", "overflow.py", "tool_exec.py"):
        src = (LOOP_DIR / fname).read_text(encoding="utf-8")
        mixin = {
            "routing.py": "_RoutingMixin",
            "overflow.py": "_OverflowMixin",
            "tool_exec.py": "_ToolExecMixin",
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

    assert _CHARS_PER_TOKEN_EST == 2
    assert _CONTEXT_SAFETY_MARGIN == 0.9
    assert _tool_args_summary({"path": "/tmp/file.txt"}) == '{"path": "/tmp/file.txt"}'
    assert _json_dumps_args({"a": 1}) == '{"a": 1}'


def test_run_stream_delegation_points(engine_src):
    """run_stream 三处委托调用全部就位（REQ-REF-02a）."""
    assert "self._route_model(" in engine_src
    assert "self._handle_overflow(" in engine_src
    assert "yield from self._execute_tools(" in engine_src


def test_complexity_reduction(engine_src):
    """engine.py 体量较拆分前（1087 行）显著下降（REQ-REF-04c）.

    基线: 拆分后 946 → HARNESS-02/04（request.meta 快照 + 预算预警）入主循环后 955
    → P2-4(2026-08-15) close() 生命周期接线后 1009（新增 18 行：LLM httpx 连接释放）。
    → 2026-08-15 轮次耗尽决策轮（[轮次决策请求] 一次性注入分支）后 1023（新增 14 行）。
    → P1-7(2026-08-15) 本地模型前缀稳定（注入标记×4 + 快照标记 + skip 传参 + 签名）后 1036（新增 13 行）。
    → P1-10(2026-08-15) 窗口锚定（provider 锚点读写 + 快照条件 + 锚点换算持久化）后 1058（新增 22 行）。
    → M51/M52(2026-08-16) 模型+token 持久化（最终回答 Message 构造扩展）后 1071（新增 13 行）。
    → 工作区(2026-08-16) 多工作区管理（workspace_root/workspace_store/set_workspace +
      run 入口 contextvar 注入）后 1102（新增 31 行）。
    → EVO-20260817-72fcd94a(2026-08-17) 缓存健康闭环 + 发送前门禁（逻辑抽独立模块
      core/cache_health.py 164 行，engine 仅接线）后 1125（新增 23 行：init 接线 + build
      预检/后检 + run 末注入）。
    仍低于拆分前, 守卫防再膨胀（>1135 应触发拆分评审）。
    """
    assert len(engine_src.splitlines()) < 1136


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
