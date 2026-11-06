# R-05（M1 修订批次，外部审查 2026-11-06 复核 §4）：available=False 的帧携带
# 残留/部分节点时，不得对肯定谓词（exists/focused/enabled）产生新的成功结论。
"""红→绿契约：基线 5e295e1e0 上前两条失败；修复后全绿。

ObservationFrame 公开说明："available=False：这一帧 AX 读不到，什么都不证明"。
D-01 修复只覆盖了空帧 absent（proves_absence），残留节点的肯定谓词路径漏了。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_desktop_wait_tristate_v01 import _frames, _node

from llm_loop.desktop.waiting import ObservationFrame, WaitPredicate, wait_for


def _no_sleep(_s: float) -> None:
    pass


def _clock_t(t: list[float]):
    return lambda: t[0]


def test_r05_unavailable_frame_with_residue_never_satisfies_positive_predicates():
    residue = _node(focused=True, enabled=True)  # 残留节点声称 focused/enabled
    for kind, expected in (("exists", True), ("focused", True), ("enabled", True)):
        out = wait_for(
            lambda: ObservationFrame(available=False, nodes=[residue]),
            residue.ax_ref,
            WaitPredicate(kind=kind, expected=expected, settle_ms=0),
            within_ms=500,
            interval_ms=50,
            sleep=_no_sleep,
        )
        assert out.satisfied is False, f"{kind} 被不可用帧的残留节点误证"
        assert out.state == "unavailable"
        assert out.observed.get("stale") is True  # 残留数据保留但标 stale


def test_r05_available_after_unavailable_recovers_and_satisfies():
    node = _node(focused=True)
    seq, _ = _frames([
        ObservationFrame(available=False, nodes=[node]),  # 残留但不可用
        ObservationFrame(nodes=[node]),                    # 恢复可用且成立
    ])
    out = wait_for(
        seq,
        node.ax_ref,
        WaitPredicate(kind="focused", expected=True, settle_ms=0),
        within_ms=1000,
        interval_ms=50,
        sleep=_no_sleep,
    )
    assert out.satisfied is True  # 不可用帧不产生结论，恢复后正常满足
    assert out.observed.get("stale") is None  # 终帧可用，observed 干净


def test_r05_unavailable_frame_resets_settle_window():
    # settle=300ms。帧序：A(成立,0ms) → U(残留成立节点,100ms) → A(成立,200ms+)。
    # 修复前：U 帧残留节点 focused=True → held 不重置 → 300ms 即 satisfied（4 次轮询）。
    # 修复后：U 帧 unknown → held 重置 → 从 200ms 重新累计 → 500ms satisfied（6 次轮询）。
    node = _node(focused=True)
    t = [0.0]

    def clock() -> float:
        return t[0]

    def snapshot():
        frame = ObservationFrame(
            nodes=[node],
            available=(round(t[0] / 100) % 2 > 0 or round(t[0] / 100) == 4),
        )
        t[0] += 100.0
        return frame

    out = wait_for(
        snapshot,
        node.ax_ref,
        WaitPredicate(kind="focused", expected=True, settle_ms=300),
        within_ms=2000,
        interval_ms=0,
        clock=clock,
        sleep=_no_sleep,
    )
    # 帧时刻：0ms(A) 100ms(U) 200ms(A) 300ms(U) 400ms(A) 500ms(U)…修复后 settle 只能
    # 在连续可用且成立的帧上累计；A 帧从不连续（中间夹 U），held 永不达标 → timeout。
    assert out.satisfied is False, "settle 窗口跨不可用帧累计 = 误证稳定性"
