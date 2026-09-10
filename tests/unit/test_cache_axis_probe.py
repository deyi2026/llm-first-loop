"""轴埋点（契约 §8 步 2）单元测试：加性、fail-open、与门禁解耦。"""
from __future__ import annotations

import pytest

from llm_loop.core.cache_health import CacheHealthMonitor
from llm_loop.core.prompt_build.stages import base_assembly as ba


def _noop_inject(base, prefix_len, session_id):  # noqa: ANN001, ANN202
    return base, prefix_len


def _assemble(*, system_prompt: str, tool_prefix_fp: str) -> ba.BaseAssemblyResult:
    return ba.run_base_assembly(
        base=[],
        system_prompt=system_prompt,
        session_id="axis-probe-test",
        sess_message_count=0,
        sess_anchor=None,
        inject_interop=_noop_inject,
        cache_monitor=CacheHealthMonitor(),
        tool_prefix_fp=tool_prefix_fp,
    )


@pytest.fixture(autouse=True)
def _reset():
    ba.reset_axis_probe()
    yield
    ba.reset_axis_probe()


def test_probe_tools_axis_attributed() -> None:
    _assemble(system_prompt="SYS-1", tool_prefix_fp="tools-1")
    _assemble(system_prompt="SYS-1", tool_prefix_fp="tools-2")
    stats = ba.axis_change_stats()
    assert stats["tools_axis"] == 1
    assert stats["system_axis"] == 0 and stats["both_axis"] == 0


def test_probe_system_axis_attributed() -> None:
    _assemble(system_prompt="SYS-1", tool_prefix_fp="tools-1")
    _assemble(system_prompt="SYS-2", tool_prefix_fp="tools-1")
    stats = ba.axis_change_stats()
    assert stats["system_axis"] == 1 and stats["tools_axis"] == 0


def test_probe_both_axis_and_unchanged() -> None:
    _assemble(system_prompt="SYS-1", tool_prefix_fp="tools-1")
    _assemble(system_prompt="SYS-2", tool_prefix_fp="tools-2")
    _assemble(system_prompt="SYS-2", tool_prefix_fp="tools-2")
    stats = ba.axis_change_stats()
    assert stats["both_axis"] == 1 and stats["prefix_unchanged"] == 1


def test_probe_decoupled_from_gate_state() -> None:
    """门禁与埋点互不依赖：tools 独变在门禁（当前主仓组合语义）计 drift，但埋点归因 tools。"""
    m = CacheHealthMonitor()
    ba.run_base_assembly(
        base=[], system_prompt="SYS-1", session_id="axis-decouple",
        sess_message_count=0, sess_anchor=None,
        inject_interop=_noop_inject, cache_monitor=m, tool_prefix_fp="tools-1",
    )
    ba.run_base_assembly(
        base=[], system_prompt="SYS-1", session_id="axis-decouple",
        sess_message_count=0, sess_anchor=None,
        inject_interop=_noop_inject, cache_monitor=m, tool_prefix_fp="tools-2",
    )
    assert ba.axis_change_stats()["tools_axis"] == 1
