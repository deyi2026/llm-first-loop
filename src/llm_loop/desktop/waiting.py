# FR-05：桌面 AX 等待原语的纯状态机（DESIGN-20261104 §6.5）
"""把"轮询直到谓词成立"从工具层剥出来，好处是时间可注入、可单测。

设计要点（每条都对应一个真实失败模式）：
- **超时不是错误**：超时只是"在窗口内没观察到"，不能等同于"对象不存在"。
- **否定谓词要 settle**：`absent` / `expected=false` 若一命中就返回，会把
  "重绘瞬间的空窗"当成"已经消失"。必须持续成立满 settle_ms，中途回闪即重置。
- **时间用单调钟**：墙钟在 NTP 校时/休眠唤醒时会跳，deadline 会算错。
- **轮询次数硬上限**：backend 极快（fake 或缓存命中）时循环会空转烧 CPU。
- **三态观测与否定域（DESIGN v1.1 §5.2）**：谓词求值为 True/False/unknown；
  AX 不可用帧、裸节点序列（覆盖未知）、截断未覆盖目标子树都不能证明否定
  （absent / exists+expected=false），一律按 unknown 处理并重置 settle。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from llm_loop.desktop.models import AxNode

SatisfiedState = "satisfied"
TimeoutState = "timeout"
UnavailableState = "unavailable"

#: 轮询次数上限：到顶即按超时收口，防止 backend 极快时打转。
MAX_WAIT_POLLS = 400


@dataclass(frozen=True)
class ObservationFrame:
    """一帧观测：节点集 + 可用性 + 覆盖信息（否定域，DESIGN v1.1 §5.2）。

    - ``available=False``：这一帧 AX 读不到，什么都不证明。
    - ``truncated=True``：遍历被截断；只有目标落在 ``covered_root`` 子树内，
      这一帧才能证明目标"已消失"。
    - 未包帧的裸节点序列按"覆盖未知"处理（截断且无覆盖根）。
    """

    nodes: Sequence[AxNode] = ()
    available: bool = True
    truncated: bool = False
    covered_root: str | None = None

    def proves_absence(self, ax_ref: str) -> bool:
        """这一帧能否证明 ax_ref 目标已消失。"""
        if not self.available:
            return False
        if not self.truncated:
            return True
        if self.covered_root is None:
            return False
        return ax_ref == self.covered_root or ax_ref.startswith(self.covered_root + ".")


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

    @property
    def is_absence_predicate(self) -> bool:
        """成立依据是"目标已消失"的谓词：回执必须携带否定域 scope（§5.2）。"""
        return self.kind == "absent" or (self.kind == "exists" and not self.expected)


@dataclass(frozen=True)
class WaitOutcome:
    satisfied: bool
    state: str
    polls: int
    elapsed_ms: int
    observed: dict[str, Any]
    #: 否定域（§5.2）：仅"等消失"型谓词携带；说明结论基于多大覆盖范围。
    scope: dict[str, Any] | None = None


def find_node(nodes: Sequence[AxNode], ax_ref: str) -> AxNode | None:
    for node in nodes:
        if node.ax_ref == ax_ref:
            return node
    return None


def evaluate(node: AxNode | None, predicate: WaitPredicate) -> bool | None:
    """谓词求值（三态）。node 为 None 时只有 `absent`/等消失可能成立。

    - True/False：观测能证明成立/不成立。
    - None（unknown）：观测读不到（enabled/value 为 None）——既非成立也非
      不成立，禁止在任何序列化边界折叠成 False（§5.8）。unknown 由 wait_for
      侧重置 settle，不会被当成命中。
    """
    kind = predicate.kind
    if kind == "absent":
        return node is None
    if node is None:
        # `exists` + expected=false 的语义就是"等它消失"，缺失时成立；
        # 可证性（这帧是否覆盖目标所在子树）由 wait_for 的否定域判定把关。
        # 其它谓词在节点缺失时一律不成立（不是"读不到=满足"）。
        return kind == "exists" and not predicate.expected
    if kind == "exists":
        raw: bool | None = True
    elif kind == "focused":
        raw = bool(node.focused)
    elif kind == "enabled":
        # AXEnabled 读不到（None）时是 unknown：把未知当 True 会让调用方在
        # 真不可用时继续点，把未知当 False 会误报"已变不可用"（§5.8）。
        raw = node.enabled
    elif kind == "value_equals":
        if node.value is None or predicate.value is None:
            return None  # 值读不到：unknown，不是"不相等"
        raw = node.value == predicate.value
    elif kind == "value_contains":
        if node.value is None or predicate.value is None:
            return None
        raw = predicate.value in node.value
    else:
        return False
    # expected 统一在此取反：谓词求值只算"原始观测"，取反是谓词语义，不是观测语义。
    if raw is None:
        return None
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


def _as_frame(raw: Sequence[AxNode] | ObservationFrame) -> ObservationFrame:
    """裸节点序列=覆盖未知：不得证明否定（§5.2 否定域）。"""
    if isinstance(raw, ObservationFrame):
        return raw
    return ObservationFrame(nodes=raw, truncated=True, covered_root=None)


def _absence_scope(frame: ObservationFrame) -> dict[str, Any]:
    """否定域描述："消失"是在什么覆盖范围内被证明/未被证明的。"""
    if not frame.available:
        return {"coverage": "unknown"}
    if not frame.truncated:
        return {"coverage": "full"}
    if frame.covered_root is None:
        return {"coverage": "unknown", "truncated": True}
    return {"coverage": "partial", "covered_root": frame.covered_root}


def wait_for(
    snapshot: Callable[[], Sequence[AxNode] | ObservationFrame],
    ax_ref: str,
    predicate: WaitPredicate,
    *,
    within_ms: int,
    interval_ms: int,
    max_polls: int = MAX_WAIT_POLLS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> WaitOutcome:
    """轮询到谓词成立（并满足 settle）或超时。永不抛异常、永不无限循环。

    终态三值：satisfied / timeout / unavailable（全程观测不可用，§5.2）。
    "等消失"型谓词只有当帧覆盖目标所在子树时才可能满足；
    回执对这些谓词始终携带 scope（否定域）。
    """
    start = clock()
    deadline = start + max(0, within_ms) / 1000.0
    held_since: float | None = None
    polls = 0
    observed = observe((), ax_ref)
    satisfied = False
    saw_available = False
    last_frame: ObservationFrame | None = None
    interval_s = max(1, interval_ms) / 1000.0

    while True:
        frame = _as_frame(snapshot())
        polls += 1
        saw_available = saw_available or frame.available
        last_frame = frame
        observed = observe(frame.nodes, ax_ref)
        if not frame.available:
            # R-05（M1 修订批次，外部审查 §4）：available=False 的帧整体什么都不
            # 证明（ObservationFrame 公开说明）——残留/部分节点不得产生新的成功
            # 结论，absent 也不行（D-01 同源：不可观测不得误证消失）。observed
            # 保留残留数据但标 stale；unknown 由下方分支重置 settle。
            observed["stale"] = True
            node = None
            verdict = None
        else:
            node = find_node(frame.nodes, ax_ref)
            verdict = evaluate(node, predicate)
            if verdict is True and node is None and not frame.proves_absence(ax_ref):
                # "没找到"不等于"已消失"：这帧没覆盖到目标所在子树就什么都
                # 不证明（§5.2 否定域），按 unknown 处理并重置 settle。
                verdict = None
        now = clock()

        if verdict is True and not predicate.needs_settle:
            satisfied = True
            break
        if verdict is True:
            if held_since is None:
                held_since = now
            # settle 期间时钟可能没有推进（注入的假钟），所以按"已持续时长"判定，
            # 而不是再等一轮 sleep——否则假钟测试会永远等不到。
            if (now - held_since) * 1000.0 >= max(0, predicate.settle_ms):
                satisfied = True
                break
        else:
            # False 或 unknown 都重置 settle：稳定必须在"连续可观测成立"上累计。
            held_since = None

        if now >= deadline or polls >= max(1, max_polls):
            break
        # 睡到下一个小步，但不越过 deadline（避免最后一次多睡）。
        remaining = deadline - now
        sleep(min(interval_s, remaining) if remaining > 0 else 0)

    if satisfied:
        state: str = SatisfiedState
    elif last_frame is not None and not saw_available:
        state = UnavailableState
    else:
        state = TimeoutState
    return WaitOutcome(
        satisfied=satisfied,
        state=state,
        polls=polls,
        elapsed_ms=int(max(0.0, clock() - start) * 1000),
        observed=observed,
        scope=(
            _absence_scope(last_frame)
            if predicate.is_absence_predicate and last_frame is not None
            else None
        ),
    )
