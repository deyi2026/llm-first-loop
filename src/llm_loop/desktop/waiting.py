# FR-05：桌面 AX 等待原语的纯状态机（DESIGN-20261104 §6.5）
"""把"轮询直到谓词成立"从工具层剥出来，好处是时间可注入、可单测。

设计要点（每条都对应一个真实失败模式）：
- **超时不是错误**：超时只是"在窗口内没观察到"，不能等同于"对象不存在"。
- **否定谓词要 settle**：`absent` / `expected=false` 若一命中就返回，会把
  "重绘瞬间的空窗"当成"已经消失"。必须持续成立满 settle_ms，中途回闪即重置。
- **时间用单调钟**：墙钟在 NTP 校时/休眠唤醒时会跳，deadline 会算错。
- **轮询次数硬上限**：backend 极快（fake 或缓存命中）时循环会空转烧 CPU。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from llm_loop.desktop.models import AxNode

SatisfiedState = "satisfied"
TimeoutState = "timeout"

#: 轮询次数上限：到顶即按超时收口，防止 backend 极快时打转。
MAX_WAIT_POLLS = 400


@dataclass(frozen=True)
class WaitPredicate:
    """一次等待的谓词。kind 决定看哪个字段，expected 决定看成立还是不成立。"""

    kind: str
    expected: bool = True
    value: str | None = None
    settle_ms: int = 300

    @property
    def needs_settle(self) -> bool:
        """否定型谓词才需要 settle：肯定型命中即返回不会误判。"""
        return (not self.expected) or self.kind == "absent"


@dataclass(frozen=True)
class WaitOutcome:
    satisfied: bool
    state: str
    polls: int
    elapsed_ms: int
    observed: dict[str, Any]


def find_node(nodes: Sequence[AxNode], ax_ref: str) -> AxNode | None:
    for node in nodes:
        if node.ax_ref == ax_ref:
            return node
    return None


def evaluate(node: AxNode | None, predicate: WaitPredicate) -> bool:
    """谓词求值。node 为 None 时只有 `absent` 可能成立。

    注意：`enabled` 在节点存在但 AXEnabled 读不到（None）时**不成立**——
    把"读不到"当成 True 会让调用方在真的不可用时继续点。
    """
    kind = predicate.kind
    if kind == "absent":
        return node is None
    if node is None:
        # `exists` + expected=false 的语义就是"等它消失"，缺失时成立；
        # 其它谓词在节点缺失时一律不成立（不是"读不到=满足"）。
        return kind == "exists" and not predicate.expected
    if kind == "exists":
        raw = True
    elif kind == "focused":
        raw = bool(node.focused)
    elif kind == "enabled":
        # AXEnabled 读不到（None）时**两个方向都不成立**：把未知当 True 会让
        # 调用方在真不可用时继续点，把未知当 False 会误报"已变不可用"。
        if node.enabled is None:
            return False
        raw = node.enabled
    elif kind == "value_equals":
        raw = node.value is not None and node.value == predicate.value
    elif kind == "value_contains":
        raw = (
            node.value is not None
            and predicate.value is not None
            and predicate.value in node.value
        )
    else:
        return False
    # expected 统一在此取反：谓词求值只算"原始观测"，取反是谓词语义，不是观测语义。
    return raw if predicate.expected else not raw


def observe(nodes: Sequence[AxNode], ax_ref: str) -> dict[str, Any]:
    """回执里的 observed 块：读不到的一律 null，不把缺失写成 false。"""
    node = find_node(nodes, ax_ref)
    if node is None:
        return {
            "found": False,
            "role": None,
            "title": None,
            "focused": None,
            "enabled": None,
            "value_len": None,
        }
    return {
        "found": True,
        "role": node.role,
        "title": node.title,
        "focused": bool(node.focused),
        "enabled": node.enabled,
        "value_len": len(node.value) if node.value is not None else None,
    }


def wait_for(
    snapshot: Callable[[], Sequence[AxNode]],
    ax_ref: str,
    predicate: WaitPredicate,
    *,
    within_ms: int,
    interval_ms: int,
    max_polls: int = MAX_WAIT_POLLS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> WaitOutcome:
    """轮询到谓词成立（并满足 settle）或超时。永不抛异常、永不无限循环。"""
    start = clock()
    deadline = start + max(0, within_ms) / 1000.0
    held_since: float | None = None
    polls = 0
    observed = observe((), ax_ref)
    satisfied = False
    interval_s = max(1, interval_ms) / 1000.0

    while True:
        nodes = snapshot()
        polls += 1
        observed = observe(nodes, ax_ref)
        hit = evaluate(find_node(nodes, ax_ref), predicate)
        now = clock()

        if hit and not predicate.needs_settle:
            satisfied = True
            break
        if hit:
            if held_since is None:
                held_since = now
            # settle 期间时钟可能没有推进（注入的假钟），所以按"已持续时长"判定，
            # 而不是再等一轮 sleep——否则假钟测试会永远等不到。
            if (now - held_since) * 1000.0 >= max(0, predicate.settle_ms):
                satisfied = True
                break
        else:
            held_since = None

        if now >= deadline or polls >= max(1, max_polls):
            break
        # 睡到下一个小步，但不越过 deadline（避免最后一次多睡）。
        remaining = deadline - now
        sleep(min(interval_s, remaining) if remaining > 0 else 0)

    return WaitOutcome(
        satisfied=satisfied,
        state=SatisfiedState if satisfied else TimeoutState,
        polls=polls,
        elapsed_ms=int(max(0.0, clock() - start) * 1000),
        observed=observed,
    )
