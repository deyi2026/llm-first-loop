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


# ---------- §8 步 6b：请求前缀事件 ----------

def test_prefix_events_init_and_axes() -> None:
    """首轮记 init；随后 system/tools 变化各记一条对应事件。"""
    ba.reset_axis_probe()
    ba._probe_axis_change("s-evt", "sys-a", "tls-a")
    ba._probe_axis_change("s-evt", "sys-b", "tls-a")  # system 轴
    ba._probe_axis_change("s-evt", "sys-b", "tls-b")  # tools 轴
    events = ba.request_prefix_events()
    assert [e["axis"] for e in events] == ["init", "system", "tools"]
    assert events[1]["system_fp"] == "sys-b"[:8]
    assert events[1]["tools_fp"] == "tls-a"[:8]
    assert all({"ts", "session_id", "axis"} <= set(e) for e in events)


def test_prefix_events_unchanged_and_reset() -> None:
    """无变化记 unchanged；reset 后事件与计数一并清空。"""
    ba.reset_axis_probe()
    ba._probe_axis_change("s-u", "sys-a", "tls-a")
    ba._probe_axis_change("s-u", "sys-a", "tls-a")  # unchanged
    assert ba.request_prefix_events()[-1]["axis"] == "unchanged"
    ba.reset_axis_probe()
    assert ba.request_prefix_events() == []
    assert ba.axis_change_stats() == {
        "system_axis": 0,
        "tools_axis": 0,
        "both_axis": 0,
        "prefix_unchanged": 0,
    }


def test_prefix_events_limit_takes_recent() -> None:
    """limit 取最近 N 条，不改变缓冲本体。"""
    ba.reset_axis_probe()
    for i in range(5):
        ba._probe_axis_change("s-l", f"sys-{i}", "tls")
    recent = ba.request_prefix_events(limit=2)
    all_events = ba.request_prefix_events()
    assert recent == all_events[-2:]
    assert recent[0]["system_fp"] == "sys-3"[:8]
