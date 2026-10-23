"""门禁：M2 任务闭环（`T-M2-6`）。

覆盖 RTM：TOL-01/04/05/16、REC-02、EVD-02、SCN-03、INP-01/06。

门禁断言：
- 端到端跑通「提出需求 → 真实只读工具执行 → 口头反馈 → 插话纠正 → 断线续接」；
- **禁用假工具回包**（真实 `read_file` 读取隔离 workspace 校验值）；
- 认领去重（重复 100 次只派一次）、恢复（`claimed` 不重派）、`outcome_unknown` 可核；
- 桥接基于 `committed` 发起、仍经**唯一入口**。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from llm_loop.realtime.committed_input import (
    CommittedInput,
    CommittedInputBridge,
    ReceiptStage,
    TaskController,
)
from llm_loop.realtime.task_bridge import (
    EngineDispatchResult,
    InMemoryClaimStore,
    TaskBridge,
    ToolCallMapping,
    ToolCallState,
)
from llm_loop.realtime.tool_orchestrator import ToolCallPlan, ToolOrchestrator
from llm_loop.realtime.turn_aggregator import TurnIntent


class RecordingQueue:
    def __init__(self) -> None:
        self.active = False
        self.started: list[tuple[str, str, str]] = []
        self.interjected: list[tuple[str, str, str, str]] = []

    def has_active_run(self, session_id: str) -> bool:
        return self.active

    def enqueue(self, *, session_id: str, run_generation: str, turn_id: str, text: str) -> str:
        raise NotImplementedError  # 闭环门禁只走 start_task / interject

    def interject(self, *, session_id: str, run_generation: str, turn_id: str, text: str) -> str:
        self.interjected.append((session_id, turn_id, run_generation, text))
        return "interject-ref-1"

    def start_task(self, *, session_id: str, turn_id: str, text: str) -> str:
        self.started.append((session_id, turn_id, text))
        self.active = True
        return "task-ref-1"

    def task_state(self, session_id: str) -> dict:
        return {"run_generation": "run-gen-1", "task_state": "running"}

    def cancel(self, *, session_id: str, expected_run_generation: str) -> tuple[str, str]:
        return ("completed", "cancelled")


class RealReadFileEngine:
    """真实引擎派发：调用现有 `ReadFileTool` 读取隔离 workspace 内真实文件（无 mock 回包）。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[ToolCallMapping] = []
        self.read_texts: list[str] = []

    def dispatch_once(self, mapping: ToolCallMapping) -> EngineDispatchResult:
        self.calls.append(mapping)
        from llm_loop.core.message import ToolResultStatus
        from llm_loop.tools.builtin.read_file import ReadFileTool

        result = ReadFileTool().execute(path=str(self.path))
        self.read_texts.append(result.content or "")
        ok = getattr(result.status, "value", result.status) == ToolResultStatus.SUCCESS.value
        return EngineDispatchResult(
            execution_id=f"real-exec-{len(self.calls)}",
            round_no=1,
            state=ToolCallState.SUCCEEDED if ok else ToolCallState.FAILED,
        )


def _plan(**over: object) -> ToolCallPlan:
    base: dict[str, object] = {
        "media_session_id": "media-1",
        "session_id": "sess-1",
        "turn_id": "turn-1",
        "tool_call_id": "call-1",
        "tool_name": "read_file",
        "run_generation": "run-gen-1",
    }
    base.update(over)
    return ToolCallPlan(**base)  # type: ignore[arg-type]


class TestEndToEndTaskLoop:
    def test_requirement_to_real_tool_to_feedback_to_correction(self, tmp_path: Path):
        value = "RTM-TOL-09-" + uuid.uuid4().hex
        diag = tmp_path / "isolated_diag.txt"
        diag.write_text(f"probe_written_value={value}\n", encoding="utf-8")

        queue = RecordingQueue()
        engine = RealReadFileEngine(diag)
        store = InMemoryClaimStore()
        bridge = TaskBridge(claim_store=store, engine=engine, submitter=queue)

        # 1) 提出需求：已提交输入（TASK_SUBMIT）恰一次进队列
        input_bridge = CommittedInputBridge(queue)
        outcome = input_bridge.submit(
            "sess-1",
            CommittedInput(turn_id="turn-1", text="帮我读一下诊断文件", intent=TurnIntent.TASK_SUBMIT),
        )
        assert outcome.receipt.stage is ReceiptStage.APPLIED
        assert queue.started == [("sess-1", "turn-1", "帮我读一下诊断文件")]

        # 2) 真实只读工具执行（桥接基于 committed 编排发起、经唯一入口）
        orchestrator = ToolOrchestrator(bridge)
        result = orchestrator.initiate(_plan())
        assert result.dispatched is True
        assert result.state is ToolCallState.SUCCEEDED
        assert len(engine.calls) == 1  # 唯一入口一次
        assert value in engine.read_texts[0]  # 真实回执含运行时写入的校验值（非预置/Mock）

        # 3) 口头反馈：仅真实回执才播报
        announced: list[str] = []
        assert orchestrator.announce(result, announce=announced.append) is True
        assert announced == ["succeeded"]

        # 4) 插话纠正：精确代次
        controller = TaskController(queue, interjector=queue)
        receipt = controller.submit_correction(
            "sess-1", run_generation="run-gen-1", turn_id="turn-1", text="改成只读第二行"
        )
        assert receipt.stage is ReceiptStage.APPLIED
        assert queue.interjected[-1][3] == "改成只读第二行"

    def test_no_mock_fallback_readback_value_must_match(self, tmp_path: Path):
        # 写入值与读取值不一致即失败（防预置答案冒充）
        value = "RTM-TOL-09-" + uuid.uuid4().hex
        diag = tmp_path / "diag.txt"
        diag.write_text(f"probe_written_value={value}\n", encoding="utf-8")
        engine = RealReadFileEngine(diag)
        bridge = TaskBridge(claim_store=InMemoryClaimStore(), engine=engine, submitter=RecordingQueue())
        orchestrator = ToolOrchestrator(bridge)
        assert orchestrator.initiate(_plan()).state is ToolCallState.SUCCEEDED
        assert value in engine.read_texts[0]


class TestClaimIdempotencyAndRecovery:
    def test_hundred_duplicates_dispatch_once(self, tmp_path: Path):
        diag = tmp_path / "diag.txt"
        diag.write_text("x\n", encoding="utf-8")
        engine = RealReadFileEngine(diag)
        store = InMemoryClaimStore()
        bridge = TaskBridge(claim_store=store, engine=engine, submitter=RecordingQueue())
        orchestrator = ToolOrchestrator(bridge)
        plan = _plan()
        for _ in range(100):
            orchestrator.initiate(plan)
        assert len(engine.calls) == 1  # 重复 100 次只派一次

    def test_claimed_call_is_not_redelivered_on_resume(self, tmp_path: Path):
        diag = tmp_path / "diag.txt"
        diag.write_text("x\n", encoding="utf-8")
        engine = RealReadFileEngine(diag)
        store = InMemoryClaimStore()
        bridge = TaskBridge(claim_store=store, engine=engine, submitter=RecordingQueue())
        mapping = _plan().to_request().to_mapping()
        store.claim_if_absent(mapping)  # 模拟上次已认领未完成
        resume = bridge.resume_call(mapping.call_key)
        assert resume.exists is True
        assert resume.state is ToolCallState.CLAIMED
        assert resume.redispatch is False
        assert engine.calls == []

    def test_outcome_unknown_is_verifiable(self, tmp_path: Path):
        class BoomEngine:
            def dispatch_once(self, mapping: ToolCallMapping) -> EngineDispatchResult:
                raise RuntimeError("engine crash")

        store = InMemoryClaimStore()
        bridge = TaskBridge(claim_store=store, engine=BoomEngine(), submitter=RecordingQueue())
        orchestrator = ToolOrchestrator(bridge)
        result = orchestrator.initiate(_plan())
        assert result.state is ToolCallState.OUTCOME_UNKNOWN
        # 可核：状态可查、且不盲重试
        lookup = store.lookup(result.record.mapping.call_key)
        assert lookup is not None and lookup.state is ToolCallState.OUTCOME_UNKNOWN
        announced: list[str] = []
        assert orchestrator.announce(result, announce=announced.append) is False
