# FR-05 等待原语纯状态机（DESIGN-20261104 §6.5）
"""时间全部注入，因此这些用例既快又确定——不 sleep、不依赖真实时钟。"""

from __future__ import annotations

from typing import Any

from llm_loop.desktop.models import AxNode
from llm_loop.desktop.waiting import (
    MAX_WAIT_POLLS,
    ObservationFrame,
    WaitPredicate,
    evaluate,
    observe,
    wait_for,
)


class FakeClock:
    """sleep 推进假时钟：真实实现里 deadline 由时间推进驱动，这里同样。"""

    def __init__(self, step_ms: int = 50, frozen: bool = False) -> None:
        self._now = 0.0
        self._step = step_ms / 1000.0
        self._frozen = frozen
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if not self._frozen:
            self._now += max(seconds, 0.0)


def _node(
    ax_ref: str = "0.1",
    *,
    focused: bool = False,
    value: str | None = None,
    enabled: bool | None = True,
) -> AxNode:
    return AxNode(
        ax_ref=ax_ref,
        role="AXTextField",
        subrole=None,
        title="输入框",
        value=value,
        focused=focused,
        pos_pt=None,
        size_pt=None,
        enabled=enabled,
    )


def _seq(*frames: list[AxNode]) -> Any:
    """按调用次序吐帧，用完之后一直吐最后一帧。"""
    state = {"i": 0}

    def snapshot() -> list[AxNode]:
        index = min(state["i"], len(frames) - 1)
        state["i"] += 1
        return frames[index]

    return snapshot


def test_immediate_hit_returns_satisfied_on_first_poll():
    """肯定型谓词命中即返回：不要为了"等稳定"白等一个 settle。"""
    clock = FakeClock()
    outcome = wait_for(
        lambda: [_node(focused=True)],
        "0.1",
        WaitPredicate(kind="focused"),
        within_ms=1000,
        interval_ms=50,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert outcome.satisfied is True
    assert outcome.state == "satisfied"
    assert outcome.polls == 1
    assert outcome.observed["found"] is True
    assert outcome.observed["focused"] is True


def test_exists_becomes_true_on_third_poll():
    clock = FakeClock()
    outcome = wait_for(
        _seq([], [], [_node()]),
        "0.1",
        WaitPredicate(kind="exists"),
        within_ms=1000,
        interval_ms=50,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert outcome.satisfied is True
    assert outcome.polls == 3


def test_timeout_is_not_an_error_and_respects_within_ms():
    """超时只是"窗口内没观察到"，不是失败——state=timeout、satisfied=false。"""
    clock = FakeClock()
    outcome = wait_for(
        lambda: [],
        "0.1",
        WaitPredicate(kind="exists"),
        within_ms=200,
        interval_ms=50,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert outcome.satisfied is False
    assert outcome.state == "timeout"
    assert outcome.elapsed_ms <= 200 + 1
    assert outcome.observed == {
        "found": False,
        "role": None,
        "title": None,
        "focused": None,
        "enabled": None,
        "value_len": None,
    }


def test_absent_requires_sustained_settle_not_instant_hit():
    """消失一帧不算消失：重绘空窗会误判。必须持续 settle_ms。"""
    clock = FakeClock(step_ms=50)
    # D-01 后 absent 需要"可证明覆盖"的帧：显式全覆盖空帧（§5.2 否定域）。
    frames = [
        ObservationFrame(nodes=[_node()]),
        ObservationFrame(nodes=[_node()]),
        ObservationFrame(nodes=[_node()]),
        ObservationFrame(nodes=[]),
        ObservationFrame(nodes=[]),
        ObservationFrame(nodes=[]),
        ObservationFrame(nodes=[]),
        ObservationFrame(nodes=[]),
    ]
    outcome = wait_for(
        _seq(*frames),
        "0.1",
        WaitPredicate(kind="absent", settle_ms=150),
        within_ms=1000,
        interval_ms=50,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert outcome.satisfied is True
    # 消失发生在第 4 次轮询（t=150ms），再持续 150ms 才成立 ⇒ 不早于第 7 次
    assert outcome.polls >= 7


def test_absent_flicker_resets_settle_window():
    """中途回闪必须重置计时，否则"闪一下又回来"会被判成已消失。"""
    clock = FakeClock(step_ms=50)
    frames = [
        ObservationFrame(nodes=[]),
        ObservationFrame(nodes=[]),
        ObservationFrame(nodes=[_node()]),
        ObservationFrame(nodes=[]),
        ObservationFrame(nodes=[]),
        ObservationFrame(nodes=[]),
        ObservationFrame(nodes=[]),
        ObservationFrame(nodes=[]),
        ObservationFrame(nodes=[]),
    ]
    outcome = wait_for(
        _seq(*frames),
        "0.1",
        WaitPredicate(kind="absent", settle_ms=100),
        within_ms=2000,
        interval_ms=50,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert outcome.satisfied is True
    # 回闪在 t=100ms，settle 100ms 需持续到 t>=200ms
    assert outcome.polls >= 6


def test_value_contains_hit_and_miss():
    hit = wait_for(
        lambda: [_node(value="已完成 3/3")],
        "0.1",
        WaitPredicate(kind="value_contains", value="3/3"),
        within_ms=200,
        interval_ms=50,
        clock=FakeClock().now,
        sleep=FakeClock().sleep,
    )
    assert hit.satisfied is True

    miss = wait_for(
        lambda: [_node(value="已完成 1/3")],
        "0.1",
        WaitPredicate(kind="value_contains", value="9/9"),
        within_ms=100,
        interval_ms=50,
        clock=FakeClock().now,
        sleep=FakeClock().sleep,
    )
    assert miss.satisfied is False


def test_enabled_unknown_is_not_treated_as_true():
    """AXEnabled 读不到（None）是 unknown：不当 True（真不可用时继续点），
    也不折叠成 False（§5.8，D-01 三态化迁移）。"""
    assert evaluate(_node(enabled=None), WaitPredicate(kind="enabled")) is None
    assert (
        evaluate(_node(enabled=None), WaitPredicate(kind="enabled", expected=False))
        is None
    )
    assert evaluate(_node(enabled=True), WaitPredicate(kind="enabled")) is True
    assert evaluate(_node(enabled=False), WaitPredicate(kind="enabled")) is False


def test_max_polls_caps_busy_loop_when_clock_frozen():
    """backend 极快/假钟不推进时必须靠轮询上限收口，不能空转。"""
    clock = FakeClock(frozen=True)
    outcome = wait_for(
        lambda: [],
        "0.1",
        WaitPredicate(kind="exists"),
        within_ms=60000,
        interval_ms=50,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert outcome.polls == MAX_WAIT_POLLS
    assert outcome.satisfied is False


def test_observe_reports_nulls_not_false_for_missing_node():
    observed = observe([], "0.404")
    assert observed["found"] is False
    assert observed["enabled"] is None


def test_evaluate_absent_only_true_when_node_missing():
    assert evaluate(None, WaitPredicate(kind="absent")) is True
    assert evaluate(_node(), WaitPredicate(kind="absent")) is False


def test_negative_expected_uses_settle_for_focused():
    """expected=false 的 focused 同样是"否定型"：必须持续不聚焦才成立。"""
    clock = FakeClock(step_ms=50)
    outcome = wait_for(
        lambda: [_node(focused=False)],
        "0.1",
        WaitPredicate(kind="focused", expected=False, settle_ms=100),
        within_ms=1000,
        interval_ms=50,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert outcome.satisfied is True
    assert outcome.polls >= 3
