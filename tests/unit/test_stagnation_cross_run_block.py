"""EVO-20260902-loopbreaker: 执行前死循环拦截 + 跨 run 停滞延续测试.

实测缺陷背景: 停滞计数按 run 重置，"每轮 run 重复 2~4 次同指纹调用即被
[program-final] 收束"的死循环永不达事后熔断阈值(5) → 跨 run 延续 + 第 3 次执行前拦截。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from llm_loop.core.loop.engine_services.run_state import RunStateManager
from llm_loop.core.loop.engine_services.tool_cycle import ToolCycleService
from llm_loop.core.loop.tool_exec import _STAGNATION_BLOCK_AT, partition_stagnation_block


def _fingerprint(tc) -> str:
    return f"{tc.name}|{_STAGNATION_BLOCK_AT and sorted(tc.arguments.items())}"


# ---------- partition_stagnation_block（纯函数） ----------

def test_partition_allows_first_two_blocks_third():
    calls = [SimpleNamespace(name="get_tool_schema", arguments={"tool_name": "x"}) for _ in range(3)]
    allowed, blocked = partition_stagnation_block(
        calls, {"fp": None, "count": 0}, lambda tc: f"{tc.name}|x"
    )
    assert len(allowed) == _STAGNATION_BLOCK_AT - 1
    assert len(blocked) == 1 and blocked[0][1] == _STAGNATION_BLOCK_AT


def test_partition_seeds_from_cross_run_carry():
    """上一 run 已累计 2 次 → 本 run 首次同指纹即达 3，执行前拦截（核心回归）."""
    tc = SimpleNamespace(name="get_tool_schema", arguments={"tool_name": "task_frontier"})
    allowed, blocked = partition_stagnation_block(
        [tc], {"fp": "get_tool_schema|x", "count": _STAGNATION_BLOCK_AT - 1},
        lambda t: "get_tool_schema|x",
    )
    assert allowed == [] and len(blocked) == 1


def test_partition_resets_on_different_fingerprint():
    tc = SimpleNamespace(name="read_file", arguments={"path": "/a"})
    allowed, blocked = partition_stagnation_block(
        [tc], {"fp": "get_tool_schema|x", "count": 2}, lambda t: "read_file|a"
    )
    assert len(allowed) == 1 and blocked == []


def test_partition_mixed_batch_keeps_declaration_order():
    a = SimpleNamespace(name="t", arguments={"k": 1})
    b = SimpleNamespace(name="t", arguments={"k": 2})
    calls = [a, b, a, a, a]
    allowed, blocked = partition_stagnation_block(
        calls, {"fp": None, "count": 0}, lambda t: f"{t.name}|{t.arguments['k']}"
    )
    # 指纹序列 t1,t2,t1,t1,t1 → 第 5 个 (t1 连续第 3 次) 拦截
    assert [c.arguments["k"] for c in allowed] == [1, 2, 1, 1]
    assert len(blocked) == 1 and blocked[0][0].arguments["k"] == 1


# ---------- 跨 run 延续（_track_stagnation 写回 + 播种语义） ----------

class _StubEngine(ToolCycleService):
    """最小引擎替身（同 test_loop_stagnation 模式）."""

    def __init__(self):
        self._host = self
        self._run_state_mgr = RunStateManager()
        self.events = []
        self.actions = []

    def _run_state(self):
        return self._run_state_mgr.bucket()

    def _append_message_event(self, sess, msg):
        self.events.append(msg)

    def _record_action(self, phase, action, detail):
        self.actions.append((phase, action, detail))


def test_track_stagnation_writes_carry_fields():
    eng, sess = _StubEngine(), SimpleNamespace(messages=[])
    tc = SimpleNamespace(name="get_tool_schema", arguments={"tool_name": "task_frontier"})
    for _ in range(2):
        eng._track_stagnation(tc, sess, [])
    bucket = eng._run_state()
    assert bucket.stagnation_carry_count == 2
    assert bucket.stagnation_carry_fp == eng._stagnation_fingerprint(tc)
    # 换指纹 → carry 重置
    other = SimpleNamespace(name="read_file", arguments={"path": "/b"})
    eng._track_stagnation(other, sess, [])
    assert bucket.stagnation_carry_count == 1
    assert bucket.stagnation_carry_fp == eng._stagnation_fingerprint(other)


def test_cross_run_loop_now_blocked():
    """实测病理复现: 每 run 重复 2 次即被收束 → 修复后第 3 次（跨 run）被拦截."""
    eng, sess = _StubEngine(), SimpleNamespace(messages=[])
    tc = SimpleNamespace(name="get_tool_schema", arguments={"tool_name": "task_frontier"})
    fp = eng._stagnation_fingerprint
    bucket = eng._run_state()

    def _start_run():  # engine.run 开始播种语义（engine.py EVO-20260902-loopbreaker 段）
        bucket.stagnation_state = {
            "fp": bucket.stagnation_carry_fp,
            "count": bucket.stagnation_carry_count,
            "reminded": False, "empty_count": 0, "empty_reminded": False,
        }

    _start_run()  # run 1
    for _ in range(2):
        eng._track_stagnation(tc, sess, [])
    _start_run()  # run 2（修复前计数归零逃逸；修复后延续=2）
    allowed, blocked = partition_stagnation_block([tc], bucket.stagnation_state, fp)
    assert allowed == [] and len(blocked) == 1
