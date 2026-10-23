"""输入轮次状态机与轮次分类（`T-CONTRACT-5`）。

对应需求：`RTM-INP-01/02/03/04/05/08/09`、`RTM-AUD-05/06`、`RTM-STP-03`。

状态机（`DESIGN v1.3 §2.1.3-B/H`、D26）：

    Collecting --speech-end--> AwaitingFinal --final-pass--> FinalPass
        --高精度可用--> Final / --不可用/超时--> ConservativeFinal
        --commit--> Committed（仅一次进队列）

硬约束：

- `delta` **只作显示**，**永不**驱动任务或进入 `committed`；
- `final` 按 `turn_id` + 修订号归并，**仅一次**进队列；
- 提前工具事件超时 → **明确未执行**且**不丢弃**该轮有效输入；
- 修正追加：**未执行**动作可更新，**已执行事实不改写**；迟到识别不反向改写；
- 长语音按**可回显语义轮次分段**提交，**禁止静默截断为尾部**，超容量**显式**暂停/拒绝并保留已确认部分。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from llm_loop.realtime.dual_asr_corrector import CorrectionOutcome, DualASRCorrector


class TurnState(StrEnum):
    COLLECTING = "collecting"
    AWAITING_FINAL = "awaiting_final"
    FINAL_PASS = "final_pass"
    FINAL = "final"
    CONSERVATIVE_FINAL = "conservative_final"
    COMMITTED = "committed"
    SUSPENDED_NOT_EXECUTED = "suspended_not_executed"


class TurnIntent(StrEnum):
    """提交后轮次分类（仅任务提交/纠正可由引擎相关路径处理）。

    分类器是**路由提示、非硬门**：结果可由模型纠正，不作为不可 veto 的裁决。
    """

    DIALOGUE = "dialogue"
    TASK_SUBMIT = "task_submit"
    QUERY = "query"
    CORRECTION = "correction"


_CORRECTION_MARKERS = ("不是", "我说的是", "更正", "改一下", "改成", "纠正", "重说")
_TASK_MARKERS = ("读", "打开", "查看", "列出", "分析", "检查", "搜索", "运行", "执行", "帮我做")
_QUERY_MARKERS = ("是什么", "为什么", "怎么", "是否", "哪一", "多少", "吗？", "吗?", "查询")


class TurnStateError(RuntimeError):
    """非法状态迁移。"""


class TurnCapacityError(ValueError):
    """分段数量超过容量；已确认部分保留。"""


@dataclass(frozen=True)
class CommittedTurn:
    turn_id: str
    text: str
    state: TurnState
    intent: TurnIntent
    precision_notice: str = ""
    segments: tuple[str, ...] = ()


@dataclass(frozen=True)
class NotExecutedTurn:
    """提前工具事件超时：明确未执行，且**保留**该轮有效输入。"""

    turn_id: str
    preserved_text: str
    reason: str


def default_classify(text: str) -> TurnIntent:
    stripped = (text or "").strip()
    if any(marker in stripped for marker in _CORRECTION_MARKERS):
        return TurnIntent.CORRECTION
    if any(marker in stripped for marker in _TASK_MARKERS):
        return TurnIntent.TASK_SUBMIT
    if any(marker in stripped for marker in _QUERY_MARKERS) or stripped.endswith(("?", "？")):
        return TurnIntent.QUERY
    return TurnIntent.DIALOGUE


class TurnAggregator:
    """单轮输入聚合与状态机。"""

    def __init__(
        self,
        corrector: DualASRCorrector,
        *,
        max_segments: int = 64,
        classifier: Callable[[str], TurnIntent] | None = None,
    ) -> None:
        if max_segments < 1:
            raise ValueError("max_segments must be >= 1")
        self._corrector = corrector
        self._max_segments = max_segments
        self._classifier = classifier or default_classify
        self._turn_id: str = ""
        self._state: TurnState | None = None
        self._display = ""
        self._final = ""
        self._notice = ""
        self._segments: list[str] = []
        self._committed = False
        self._executed = False

    @property
    def state(self) -> TurnState | None:
        return self._state

    @property
    def turn_id(self) -> str:
        return self._turn_id

    @property
    def display_text(self) -> str:
        """仅用于显示（流式字幕）；**不**作为最终输入。"""
        return self._display

    @property
    def final_text(self) -> str:
        return self._final

    @property
    def precision_notice(self) -> str:
        return self._notice

    @property
    def segments(self) -> tuple[str, ...]:
        return tuple(self._segments)

    def start(self, turn_id: str) -> None:
        if not turn_id:
            raise ValueError("turn_id is required")
        self._turn_id = turn_id
        self._state = TurnState.COLLECTING
        self._display = ""
        self._final = ""
        self._notice = ""
        self._segments = []
        self._committed = False
        self._executed = False

    def on_delta(self, text: str) -> None:
        """流式增量：**仅显示**。"""
        if self._state is not TurnState.COLLECTING:
            raise TurnStateError(f"delta not allowed in state {self._state}")
        self._display += text or ""

    def on_speech_end(self) -> None:
        """句末/松开：**只结束采集**，进入等待最终识别（`RTM-AUD-06`）。"""
        if self._state is not TurnState.COLLECTING:
            raise TurnStateError(f"speech-end not allowed in state {self._state}")
        self._state = TurnState.AWAITING_FINAL

    def final_pass(self, pcm_segment: bytes | None, *, timed_out: bool = False) -> None:
        """终稿校正：高精度重转写，或保守兜底（`RTM-INP-09`）。"""
        if self._state is not TurnState.AWAITING_FINAL:
            raise TurnStateError(f"final-pass not allowed in state {self._state}")
        self._state = TurnState.FINAL_PASS
        correction = self._corrector.correct(
            pcm_segment, delta_text=self._display, timed_out=timed_out
        )
        self._final = correction.text
        self._notice = correction.precision_notice
        self._state = (
            TurnState.CONSERVATIVE_FINAL
            if correction.outcome is CorrectionOutcome.CONSERVATIVE
            else TurnState.FINAL
        )

    def add_segment(self, text: str) -> None:
        """追加一个可回显语义分段；超容量**显式**报错并保留已确认部分。"""
        if len(self._segments) >= self._max_segments:
            raise TurnCapacityError("segment capacity exceeded; confirmed segments preserved")
        self._segments.append(text)

    def commit(self, *, classifier: Callable[[str], TurnIntent] | None = None) -> CommittedTurn:
        """提交轮次：**仅一次**进队列；使用**终稿**（不是 `delta`）。"""
        if self._committed:
            raise TurnStateError("turn already committed")
        if self._state not in (TurnState.FINAL, TurnState.CONSERVATIVE_FINAL):
            raise TurnStateError(f"cannot commit in state {self._state}")
        text = self._final
        intent = (classifier or self._classifier)(text)
        self._state = TurnState.COMMITTED
        self._committed = True
        return CommittedTurn(
            turn_id=self._turn_id,
            text=text,
            state=TurnState.COMMITTED,
            intent=intent,
            precision_notice=self._notice,
            segments=tuple(self._segments),
        )

    def suspend_tool_unexecuted(self, *, reason: str) -> NotExecutedTurn:
        """提前工具事件超时：明确未执行，且**不丢弃**该轮有效输入（`RTM-INP-04`）。"""
        self._state = TurnState.SUSPENDED_NOT_EXECUTED
        preserved = self._final or self._display
        return NotExecutedTurn(turn_id=self._turn_id, preserved_text=preserved, reason=reason)

    def apply_correction(self, text: str) -> bool:
        """修正追加：**未执行**前可更新；**已执行事实不改写**（`RTM-INP-05/08`）。"""
        if self._executed:
            return False
        self._final = text
        return True

    def mark_executed(self) -> None:
        """标记本轮动作已执行；此后修正不得反向改写已发生事实。"""
        self._executed = True
