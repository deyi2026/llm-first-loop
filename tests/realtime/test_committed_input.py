"""M2（`T-M2-1` / `T-M2-2`）：已提交输入恰一次进队列与三能力控制测试。

覆盖 RTM：INP-01/02/06/07/09、AUD-07、STP-01/02/03/04/05/06/07、TOL-10、SES-07、SCN-02。
"""

from __future__ import annotations

from llm_loop.realtime.committed_input import (
    CancelDisposition,
    CommittedInput,
    CommittedInputBridge,
    ReceiptStage,
    TaskController,
    settle_three_stops,
)
from llm_loop.realtime.turn_aggregator import TurnIntent


class FakeQueue:
    def __init__(self, *, active: bool = False) -> None:
        self.active = active
        self.calls: list[tuple] = []

    def has_active_run(self, session_id: str) -> bool:
        return self.active

    def enqueue(self, *, session_id: str, run_generation: str, turn_id: str, text: str) -> str:
        self.calls.append(("enqueue", session_id, turn_id, text))
        return "q-1"

    def interject(self, *, session_id: str, run_generation: str, turn_id: str, text: str) -> str:
        self.calls.append(("interject", session_id, turn_id, run_generation, text))
        return "i-1"

    def start_task(self, *, session_id: str, turn_id: str, text: str) -> str:
        self.calls.append(("start_task", session_id, turn_id, text))
        return "t-1"


class FakeControl:
    def __init__(self, *, state: dict | None = None, cancel_result=("completed", "cancelled"), cancel_raises=False) -> None:
        self.state = state or {"run_generation": "rg-1", "task_state": "idle"}
        self.cancel_result = cancel_result
        self.cancel_raises = cancel_raises

    def task_state(self, session_id: str) -> dict:
        return dict(self.state)

    def cancel(self, *, session_id: str, expected_run_generation: str):
        if self.cancel_raises:
            raise KeyError(expected_run_generation)
        return self.cancel_result


def _input(intent: TurnIntent, *, run_generation: str = "", notice: str = "") -> CommittedInput:
    return CommittedInput(
        turn_id="turn-1", text="文本", intent=intent, run_generation=run_generation, precision_notice=notice
    )


class TestSubmitRouting:
    def test_task_submit_starts_task_when_no_active_run(self):
        queue = FakeQueue(active=False)
        bridge = CommittedInputBridge(queue)
        outcome = bridge.submit("sess-1", _input(TurnIntent.TASK_SUBMIT))
        assert outcome.receipt.stage is ReceiptStage.APPLIED
        assert outcome.dispatched_to == "start_task"
        assert queue.calls[0][0] == "start_task"

    def test_task_submit_interjects_when_active_run(self):
        queue = FakeQueue(active=True)
        bridge = CommittedInputBridge(queue)
        outcome = bridge.submit("sess-1", _input(TurnIntent.TASK_SUBMIT, run_generation="rg-1"))
        assert outcome.dispatched_to == "interject"

    def test_dialogue_is_received_not_submitted_as_task(self):
        queue = FakeQueue()
        bridge = CommittedInputBridge(queue)
        outcome = bridge.submit("sess-1", _input(TurnIntent.DIALOGUE))
        assert outcome.receipt.stage is ReceiptStage.RECEIVED
        assert outcome.dispatched_to == "dialogue"
        assert queue.calls == []  # 普通对话不提交任务

    def test_correction_requires_run_generation(self):
        bridge = CommittedInputBridge(FakeQueue(active=True))
        outcome = bridge.submit("sess-1", _input(TurnIntent.CORRECTION))
        assert outcome.receipt.stage is ReceiptStage.DENIED
        assert outcome.receipt.reason == "correction_requires_run_generation"

    def test_correction_without_active_run_denied(self):
        bridge = CommittedInputBridge(FakeQueue(active=False))
        outcome = bridge.submit("sess-1", _input(TurnIntent.CORRECTION, run_generation="rg-1"))
        assert outcome.receipt.stage is ReceiptStage.DENIED
        assert outcome.receipt.reason == "no_active_run_to_correct"


class TestExactlyOnce:
    def test_duplicate_submit_does_not_reenqueue(self):
        queue = FakeQueue(active=False)
        bridge = CommittedInputBridge(queue)
        first = bridge.submit("sess-1", _input(TurnIntent.TASK_SUBMIT))
        second = bridge.submit("sess-1", _input(TurnIntent.TASK_SUBMIT))
        assert first.receipt.duplicate is False
        assert second.receipt.duplicate is True
        assert second.receipt.reason == "already_submitted"
        assert len(queue.calls) == 1  # 恰一次进队列

    def test_different_turns_are_independent(self):
        queue = FakeQueue(active=False)
        bridge = CommittedInputBridge(queue)
        bridge.submit("sess-1", _input(TurnIntent.TASK_SUBMIT))
        bridge.submit(
            "sess-1",
            CommittedInput(turn_id="turn-2", text="第二句", intent=TurnIntent.TASK_SUBMIT),
        )
        assert len(queue.calls) == 2


class TestDegradedMarker:
    def test_conservative_final_marks_degraded(self):
        assert _input(TurnIntent.TASK_SUBMIT, notice="精度受限").degraded is True
        assert _input(TurnIntent.TASK_SUBMIT).degraded is False


class TestThreeAbilities:
    def test_query_task_pulls_real_state_without_resending(self):
        control = FakeControl()
        controller = TaskController(control, interjector=FakeQueue())
        state = controller.query_task("sess-1", run_generation="rg-1")
        assert state["queried_run_generation"] == "rg-1"

    def test_submit_correction_conflict_on_generation_mismatch(self):
        control = FakeControl(state={"run_generation": "rg-9", "task_state": "running"})
        controller = TaskController(control, interjector=FakeQueue(active=True))
        receipt = controller.submit_correction("sess-1", run_generation="rg-1", turn_id="t1", text="改一下")
        assert receipt.stage is ReceiptStage.DENIED
        assert receipt.reason == "run_generation_conflict"

    def test_submit_correction_applied_on_match(self):
        control = FakeControl(state={"run_generation": "rg-1", "task_state": "running"})
        controller = TaskController(control, interjector=FakeQueue(active=True))
        receipt = controller.submit_correction("sess-1", run_generation="rg-1", turn_id="t1", text="改一下")
        assert receipt.stage is ReceiptStage.APPLIED

    def test_request_cancel_conflict_is_409_semantics(self):
        control = FakeControl(cancel_result=("conflict", "running"))
        controller = TaskController(control, interjector=FakeQueue())
        result = controller.request_cancel("sess-1", run_generation="rg-old")
        assert result.disposition is CancelDisposition.CONFLICT
        assert result.terminal_state == "running"

    def test_request_cancel_reports_real_terminal_state(self):
        control = FakeControl(cancel_result=("completed", "cancelled"))
        controller = TaskController(control, interjector=FakeQueue())
        result = controller.request_cancel("sess-1", run_generation="rg-1")
        assert result.disposition is CancelDisposition.COMPLETED
        assert result.terminal_state == "cancelled"

    def test_request_cancel_unknown_generation_not_found(self):
        control = FakeControl(cancel_raises=True)
        controller = TaskController(control, interjector=FakeQueue())
        result = controller.request_cancel("sess-1", run_generation="rg-missing")
        assert result.disposition is CancelDisposition.NOT_FOUND

    def test_request_cancel_without_generation_not_found(self):
        controller = TaskController(FakeControl(), interjector=FakeQueue())
        assert controller.request_cancel("sess-1", run_generation="").disposition is CancelDisposition.NOT_FOUND


class TestThreeStopsSeparated:
    def test_stops_are_separated_not_merged(self):
        settlement = settle_three_stops(
            local_playback="completed", reply_cancel="requested", task_cancel="not_applicable"
        )
        assert settlement.local_playback == "completed"
        assert settlement.reply_cancel == "requested"
        assert settlement.task_cancel == "not_applicable"

    def test_requested_only_does_not_claim_completion(self):
        settlement = settle_three_stops(
            local_playback="not_applicable", reply_cancel="requested", task_cancel="requested"
        )
        assert settlement.requested_only() is True

    def test_mixed_states_not_requested_only(self):
        settlement = settle_three_stops(
            local_playback="completed", reply_cancel="requested", task_cancel="requested"
        )
        assert settlement.requested_only() is False


class TestBoundedDedupCache:
    def test_dedup_cache_is_bounded(self):
        queue = FakeQueue(active=False)
        bridge = CommittedInputBridge(queue, max_tracked=2)
        for i in range(5):
            bridge.submit(
                "s1", CommittedInput(turn_id=f"t{i}", text="x", intent=TurnIntent.TASK_SUBMIT)
            )
        assert len(bridge._submitted) <= 2  # 有界，不无界增长

    def test_max_tracked_must_be_positive(self):
        import pytest as _pytest

        with _pytest.raises(ValueError):
            CommittedInputBridge(FakeQueue(), max_tracked=0)
