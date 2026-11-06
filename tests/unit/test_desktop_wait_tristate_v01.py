# D-01 桌面等待三态观测与否定覆盖（M1 TASK-15377274-002，DESIGN v1.1 §5.2/§8）
"""红→绿契约：本文件先于修复提交，在基线 7ae768519 上逐条失败；修复后全绿。

- 三态观测：evaluate 返回 True/False/None(unknown)——AX 读不到不再折叠为 False（§5.8）。
- 否定域（§5.2）：absent / exists+expected=false 的成立需要帧覆盖证明；
  不可用帧、裸节点序列（覆盖未知）、截断未覆盖目标子树 → unknown，不满足且重置 settle。
- 终态区分 timeout / unavailable（全程观测不可用）。
- "等消失"型谓词回执携带 scope（coverage: full/partial/unknown [+covered_root]）。
"""

from __future__ import annotations

from llm_loop.desktop.models import AxNode
from llm_loop.desktop.waiting import WaitPredicate, evaluate, wait_for


class FakeClock:
    """sleep 推进假钟：确定性、零真实等待。"""

    def __init__(self, step_ms: int = 50) -> None:
        self._now = 0.0
        self._step = step_ms / 1000.0

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += max(seconds, self._step)


def _node(
    ax_ref: str = "0.1",
    *,
    focused: bool = False,
    enabled: bool | None = True,
    value: str | None = None,
) -> AxNode:
    return AxNode(
        ax_ref=ax_ref,
        role="AXButton",
        subrole=None,
        title="按钮",
        value=value,
        focused=focused,
        pos_pt=None,
        size_pt=None,
        enabled=enabled,
    )


def _frames(seq):
    """按调用次序吐帧，用完停驻最后一帧。"""
    state = {"i": 0}
    seq = list(seq)

    def snapshot():
        idx = min(state["i"], len(seq) - 1)
        state["i"] += 1
        return seq[idx]

    return snapshot, lambda: state["i"]


# ---------- T-01 fail-closed：不可观测不得证明否定 ----------

def test_t01_bare_empty_frames_never_prove_absence():
    """§8.2 直连复现的等价形式：裸空序列=覆盖未知，absent 不得满足。

    基线（红）：satisfied=True——AX 不可用被当成"元素已消失"。
    """
    out = wait_for(
        lambda: [],
        "0.1",
        WaitPredicate(kind="absent", settle_ms=0),
        within_ms=300,
        interval_ms=50,
        clock=FakeClock().now,
        sleep=FakeClock().sleep,
    )
    assert out.satisfied is False, "裸空序列=覆盖未知，absent 必须 unknown（fail-closed）"
    assert out.state != "satisfied"


def test_t01_unavailable_frames_absent_unknown_state_unavailable():
    from llm_loop.desktop.waiting import ObservationFrame

    out = wait_for(
        lambda: ObservationFrame(available=False),
        "0.1",
        WaitPredicate(kind="absent", settle_ms=0),
        within_ms=300,
        interval_ms=50,
        clock=FakeClock().now,
        sleep=FakeClock().sleep,
    )
    assert out.satisfied is False
    assert out.state == "unavailable"


def test_t01_positive_predicate_all_unavailable_is_unavailable_state():
    from llm_loop.desktop.waiting import ObservationFrame

    out = wait_for(
        lambda: ObservationFrame(available=False),
        "0.1",
        WaitPredicate(kind="exists"),
        within_ms=300,
        interval_ms=50,
        clock=FakeClock().now,
        sleep=FakeClock().sleep,
    )
    assert out.satisfied is False
    assert out.state == "unavailable"


def test_t01_absent_recovers_after_availability_restored():
    """不可用帧阻断判定；恢复为全覆盖空帧后可正常满足（不能永久卡死）。"""
    from llm_loop.desktop.waiting import ObservationFrame

    snap, calls = _frames(
        [ObservationFrame(available=False)] * 3 + [ObservationFrame(nodes=())] * 8
    )
    clock = FakeClock(step_ms=40)
    out = wait_for(
        snap,
        "0.1",
        WaitPredicate(kind="absent", settle_ms=40),
        within_ms=5000,
        interval_ms=40,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert out.satisfied is True
    assert calls() >= 5  # 经历不可用帧之后，恢复并重新累计 settle 才满足


def test_t01_exists_disappear_bare_frames_not_provable():
    """exists+expected=false（等它消失）是否定谓词：裸帧覆盖未知，不得满足。"""
    out = wait_for(
        lambda: [],
        "0.1",
        WaitPredicate(kind="exists", expected=False, settle_ms=0),
        within_ms=300,
        interval_ms=50,
        clock=FakeClock().now,
        sleep=FakeClock().sleep,
    )
    assert out.satisfied is False


# ---------- T-02 unknown 帧重置 settle 连续窗口 ----------

def test_t02_unknown_frame_resets_settle_window():
    """settle 必须在"连续成立"上累计；中间插入的 unknown 帧重置计时。

    时间线（假钟步进 100ms，settle=200ms）：
      node(False) → 空(True 起算 t=100) → 不可用(unknown 重置) → 空(重起算 t=300)
      → t=400 未满 → t=500 满足 ⇒ polls=6。若不重置，t=400 即满足（polls=5）。
    """
    from llm_loop.desktop.waiting import ObservationFrame

    node = ObservationFrame(nodes=[_node()])
    full = ObservationFrame(nodes=())
    unav = ObservationFrame(available=False)
    snap, calls = _frames([node, full, unav, full, full, full, full])
    clock = FakeClock(step_ms=100)
    out = wait_for(
        snap,
        "0.1",
        WaitPredicate(kind="absent", settle_ms=200),
        within_ms=5000,
        interval_ms=100,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert out.satisfied is True
    assert calls() >= 6, "unknown 帧必须重置 settle 窗口（不能跨不可见期累计）"


def test_t02_positive_hit_immediately_after_unknown():
    from llm_loop.desktop.waiting import ObservationFrame

    snap, _ = _frames(
        [
            ObservationFrame(available=False),
            ObservationFrame(nodes=[_node(focused=True)]),
        ]
    )
    out = wait_for(
        snap,
        "0.1",
        WaitPredicate(kind="focused"),
        within_ms=5000,
        interval_ms=50,
        clock=FakeClock().now,
        sleep=FakeClock().sleep,
    )
    assert out.satisfied is True
    assert out.polls == 2


# ---------- T-03 否定域 scope ----------

def test_t03_truncated_outside_covered_root_is_unknown():
    """目标不在已覆盖子树内：禁止外推为窗口级否定。"""
    from llm_loop.desktop.waiting import ObservationFrame

    frame = ObservationFrame(nodes=(), truncated=True, covered_root="0.2")
    out = wait_for(
        lambda: frame,
        "0.1.3",
        WaitPredicate(kind="absent", settle_ms=0),
        within_ms=300,
        interval_ms=50,
        clock=FakeClock().now,
        sleep=FakeClock().sleep,
    )
    assert out.satisfied is False
    assert out.scope is not None
    assert out.scope["coverage"] == "partial"
    assert out.scope["covered_root"] == "0.2"


def test_t03_target_inside_covered_root_proves_absence_with_scope():
    from llm_loop.desktop.waiting import ObservationFrame

    frame = ObservationFrame(nodes=(), truncated=True, covered_root="0.2")
    out = wait_for(
        lambda: frame,
        "0.2.1",
        WaitPredicate(kind="absent", settle_ms=0),
        within_ms=300,
        interval_ms=50,
        clock=FakeClock().now,
        sleep=FakeClock().sleep,
    )
    assert out.satisfied is True
    assert out.scope is not None
    assert out.scope["coverage"] == "partial"
    assert out.scope["covered_root"] == "0.2"


def test_t03_full_coverage_frame_scope_full():
    from llm_loop.desktop.waiting import ObservationFrame

    out = wait_for(
        lambda: ObservationFrame(nodes=()),
        "0.1",
        WaitPredicate(kind="absent", settle_ms=0),
        within_ms=300,
        interval_ms=50,
        clock=FakeClock().now,
        sleep=FakeClock().sleep,
    )
    assert out.satisfied is True
    assert out.scope is not None
    assert out.scope["coverage"] == "full"


def test_t03_bare_frames_scope_unknown():
    out = wait_for(
        lambda: [],
        "0.1",
        WaitPredicate(kind="absent", settle_ms=0),
        within_ms=300,
        interval_ms=50,
        clock=FakeClock().now,
        sleep=FakeClock().sleep,
    )
    assert out.scope is not None
    assert out.scope["coverage"] == "unknown"


# ---------- evaluate 三态（§5.8：未知不折叠为 False） ----------

def test_evaluate_tristate_unknown_not_false():
    assert evaluate(_node(enabled=None), WaitPredicate(kind="enabled")) is None
    assert (
        evaluate(_node(enabled=None), WaitPredicate(kind="enabled", expected=False))
        is None
    )
    assert evaluate(_node(value=None), WaitPredicate(kind="value_equals", value="x")) is None
    assert evaluate(_node(value=None), WaitPredicate(kind="value_contains", value="x")) is None


def test_evaluate_absent_and_disappear_node_level():
    assert evaluate(None, WaitPredicate(kind="absent")) is True
    assert evaluate(_node(), WaitPredicate(kind="absent")) is False
    assert evaluate(None, WaitPredicate(kind="exists", expected=False)) is True
