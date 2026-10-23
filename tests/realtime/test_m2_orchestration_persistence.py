"""M2（`T-M2-3` / `T-M2-4`）：工具编排闭环与持久化/恢复测试。

覆盖 RTM：TOL-09/10/11/12/16、EVD-02、REC-01/02/05/08/10/11/13。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from llm_loop.realtime.realtime_persistence import (
    EXCLUDED_FROM_JOURNAL,
    LocalSessionRebuilder,
    PersistedFact,
    PersistedFactKind,
    PersistenceFailurePosition,
    RealtimeFactStore,
    decide_stale_draft,
    persistence_failure_disposition,
)
from llm_loop.realtime.task_bridge import (
    EngineDispatchResult,
    InMemoryClaimStore,
    TaskBridge,
    ToolCallMapping,
    ToolCallState,
)
from llm_loop.realtime.tool_orchestrator import ToolCallPlan, ToolOrchestrator


class FakeSubmitter:
    def submit(self, **kw: object) -> str:
        return "task-1"


class FakeEngine:
    def __init__(self, *, state: ToolCallState = ToolCallState.SUCCEEDED, raises: bool = False) -> None:
        self.calls: list[ToolCallMapping] = []
        self.state = state
        self.raises = raises

    def dispatch_once(self, mapping: ToolCallMapping) -> EngineDispatchResult:
        self.calls.append(mapping)
        if self.raises:
            raise RuntimeError("engine boom")
        return EngineDispatchResult(execution_id=f"exec-{len(self.calls)}", round_no=1, state=self.state)


class RealReadFileEngine:
    """真实引擎派发：经现有 `ReadFileTool` 读取隔离 workspace 内的真实文件。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[ToolCallMapping] = []

    def dispatch_once(self, mapping: ToolCallMapping) -> EngineDispatchResult:
        self.calls.append(mapping)
        from llm_loop.core.message import ToolResultStatus
        from llm_loop.tools.builtin.read_file import ReadFileTool

        result = ReadFileTool().execute(path=str(self.path))
        ok = getattr(result.status, "value", result.status) == ToolResultStatus.SUCCESS.value
        return EngineDispatchResult(
            execution_id=f"real-exec-{len(self.calls)}",
            round_no=1,
            state=ToolCallState.SUCCEEDED if ok else ToolCallState.FAILED,
        )


def _bridge(engine: object) -> TaskBridge:
    return TaskBridge(claim_store=InMemoryClaimStore(), engine=engine, submitter=FakeSubmitter())


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


class TestToolOrchestration:
    def test_read_file_goes_through_single_entry_once(self):
        engine = FakeEngine()
        orchestrator = ToolOrchestrator(_bridge(engine))
        first = orchestrator.initiate(_plan())
        second = orchestrator.initiate(_plan())  # 同键重复
        assert first.dispatched is True
        assert second.dispatched is False
        assert len(engine.calls) == 1  # 唯一入口 + 恰一次

    def test_tool_outside_bridge_surface_is_denied(self):
        engine = FakeEngine()
        orchestrator = ToolOrchestrator(_bridge(engine))
        result = orchestrator.initiate(_plan(tool_name="write_file"))
        assert result.dispatched is False
        assert result.reason == "tool_not_in_bridge_surface"
        assert engine.calls == []

    def test_model_veto_prevents_dispatch(self):
        engine = FakeEngine()

        class Veto:
            def allow(self, plan: ToolCallPlan) -> bool:
                return False

        orchestrator = ToolOrchestrator(_bridge(engine), veto=Veto())
        result = orchestrator.initiate(_plan())
        assert result.dispatched is False
        assert result.reason == "vetoed"
        assert engine.calls == []

    def test_announce_only_on_real_receipt(self):
        engine = FakeEngine()
        orchestrator = ToolOrchestrator(_bridge(engine))
        announced: list[str] = []
        assert orchestrator.announce(orchestrator.initiate(_plan()), announce=announced.append) is True
        assert announced == ["succeeded"]
        # 未派发 → 不播报
        assert orchestrator.announce(orchestrator.initiate(_plan()), announce=announced.append) is False

    def test_outcome_unknown_is_not_announced_as_result(self):
        engine = FakeEngine(raises=True)
        orchestrator = ToolOrchestrator(_bridge(engine))
        result = orchestrator.initiate(_plan())
        assert result.state is ToolCallState.OUTCOME_UNKNOWN
        announced: list[str] = []
        assert orchestrator.announce(result, announce=announced.append) is False
        assert announced == []

    def test_real_read_file_roundtrip_in_isolated_workspace(self, tmp_path: Path):
        value = "RTM-TOL-09-" + uuid.uuid4().hex
        diag = tmp_path / "isolated_diag.txt"
        diag.write_text(f"probe_written_value={value}\n", encoding="utf-8")

        engine = RealReadFileEngine(diag)
        orchestrator = ToolOrchestrator(_bridge(engine))
        result = orchestrator.initiate(_plan())
        assert result.dispatched is True
        assert result.state is ToolCallState.SUCCEEDED
        assert len(engine.calls) == 1


class TestPersistenceBoundary:
    def test_interim_subtitles_and_audio_chunks_are_rejected(self):
        store = RealtimeFactStore()
        for excluded in ("interim_caption", "audio_chunk"):
            try:
                store.persist(PersistedFact(PersistedFactKind.COMMITTED_INPUT, "sess-1", excluded, {}))
            except ValueError:
                continue
            raise AssertionError(f"{excluded} must not enter the journal")
        assert "audio_chunk" in EXCLUDED_FROM_JOURNAL

    def test_committed_input_and_tool_fact_are_persisted(self):
        store = RealtimeFactStore()
        store.persist(PersistedFact(PersistedFactKind.COMMITTED_INPUT, "sess-1", "k1", {"text": "第一句"}))
        store.persist(PersistedFact(PersistedFactKind.TOOL_FACT, "sess-1", "tool-1", {"status": "succeeded"}))
        assert len(store.facts("sess-1", kind=PersistedFactKind.COMMITTED_INPUT)) == 1
        assert len(store.facts("sess-1", kind=PersistedFactKind.TOOL_FACT)) == 1


class TestPersistenceFailureByPosition:
    def test_before_dispatch_does_not_confirm(self):
        assert (
            persistence_failure_disposition(PersistenceFailurePosition.BEFORE_DISPATCH)
            == "do_not_confirm_dispatched"
        )

    def test_after_dispatch_keeps_facts_and_marks_unknown(self):
        assert (
            persistence_failure_disposition(PersistenceFailurePosition.AFTER_DISPATCH)
            == "keep_facts_and_mark_outcome_unknown"
        )

    def test_optional_diagnostic_preserves_confirmed_state(self):
        assert (
            persistence_failure_disposition(PersistenceFailurePosition.OPTIONAL_DIAGNOSTIC)
            == "ignore_and_preserve_confirmed_state"
        )


class TestLocalRecovery:
    def test_recovery_rebuilds_locally_without_exactly_once(self):
        store = RealtimeFactStore()
        store.persist(PersistedFact(PersistedFactKind.COMMITTED_INPUT, "sess-1", "k1", {"text": "已提交输入"}))
        store.persist(PersistedFact(PersistedFactKind.TASK_LINK, "sess-1", "link-1", {}))
        bundle = store.recovery_bundle("sess-1")
        plan = LocalSessionRebuilder().rebuild(bundle)
        assert plan.recovery_mode == "local_rebuild_only"
        assert plan.committed_inputs == ("已提交输入",)
        assert plan.task_links == ("link-1",)
        assert plan.exactness == "at_least_once_no_exactly_once_guarantee"


class TestStaleDraft:
    def test_unchanged_page_allows_auto(self):
        decision = decide_stale_draft(captured_page_epoch=3, current_page_epoch=3)
        assert decision.requires_explicit_commit is False

    def test_changed_page_requires_explicit_commit(self):
        decision = decide_stale_draft(captured_page_epoch=3, current_page_epoch=4)
        assert decision.requires_explicit_commit is True
        assert "do_not_auto_execute" in decision.reason
