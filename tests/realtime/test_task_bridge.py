"""T-CONTRACT-1 / T-CONTRACT-2：唯一执行链与工具幂等单元测试。

覆盖 RTM：TOL-01/02/03/04/05/06/08/16、REC-02/06、IDN-01、CMP-01/02。

关键断言：
- T10：同一调用重复 100 次，引擎**只派发一次**；
- 稳定去重键**不是参数哈希**：新轮次相同参数不被误拦；
- 原子认领 + 重启恢复：`claimed` → 已知状态、**不重派**；
- 崩溃窗口 → `outcome_unknown`、禁止盲重试；
- 唯一执行链：桥接**只提交任务**，工具**只在引擎内**派发，双层标识显式绑定。
"""

from __future__ import annotations

import inspect

import pytest

from llm_loop.realtime import task_bridge as tb
from llm_loop.realtime.task_bridge import (
    ClaimRecord,
    EngineDispatchResult,
    InMemoryClaimStore,
    TaskBridge,
    ToolCallMapping,
    ToolCallState,
    ToolDispatchRequest,
    make_call_key,
)


class FakeEngine:
    def __init__(self, state: ToolCallState = ToolCallState.SUCCEEDED, *, raises: bool = False) -> None:
        self.calls: list[ToolCallMapping] = []
        self.state = state
        self.raises = raises

    def dispatch_once(self, mapping: ToolCallMapping) -> EngineDispatchResult:
        self.calls.append(mapping)
        if self.raises:
            raise RuntimeError("engine boom")
        return EngineDispatchResult(
            execution_id=f"exec-{len(self.calls)}", round_no=len(self.calls), state=self.state
        )


class FakeSubmitter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit(self, *, session_id: str, run_generation: str, turn_id: str, text: str) -> str:
        self.calls.append(
            {"session_id": session_id, "run_generation": run_generation, "turn_id": turn_id, "text": text}
        )
        return "task-ref-1"


def _bridge(**over: object) -> tuple[TaskBridge, InMemoryClaimStore, FakeEngine, FakeSubmitter]:
    store = InMemoryClaimStore()
    engine = FakeEngine()
    submitter = FakeSubmitter()
    kwargs: dict[str, object] = {"claim_store": store, "engine": engine, "submitter": submitter}
    kwargs.update(over)
    return TaskBridge(**kwargs), store, engine, submitter  # type: ignore[arg-type]


def _request(**over: object) -> ToolDispatchRequest:
    base: dict[str, object] = {
        "media_session_id": "media-1",
        "session_id": "sess-1",
        "turn_id": "turn-1",
        "tool_call_id": "call-abc",
        "tool_name": "read_file",
        "run_generation": "run-gen-1",
    }
    base.update(over)
    return ToolDispatchRequest(**base)  # type: ignore[arg-type]


class TestStableCallKey:
    def test_key_is_stable_for_same_identity(self):
        a = make_call_key(media_session_id="m", turn_id="t", tool_call_id="c")
        b = make_call_key(media_session_id="m", turn_id="t", tool_call_id="c")
        assert a == b

    def test_key_is_not_parameter_hash(self):
        # 键由调用标识 + 轮次派生，不含工具参数内容
        key = make_call_key(media_session_id="m", turn_id="t", tool_call_id="c")
        assert "read_file" not in key
        assert "path" not in key

    def test_new_turn_same_parameters_yield_new_key(self):
        k1 = make_call_key(media_session_id="m", turn_id="t1", tool_call_id="c1")
        k2 = make_call_key(media_session_id="m", turn_id="t2", tool_call_id="c2")
        assert k1 != k2

    def test_rejects_unbounded_identity(self):
        with pytest.raises(ValueError):
            make_call_key(media_session_id="", turn_id="t", tool_call_id="c")


class TestSingleExecutionChain:
    def test_submit_only_submits_task_never_dispatches_tool(self):
        bridge, _, engine, submitter = _bridge()
        receipt = bridge.submit_committed_input(
            session_id="sess-1", run_generation="run-gen-1", turn_id="turn-1", text="只分析最后一条"
        )
        assert receipt.accepted is True
        assert submitter.calls[0]["turn_id"] == "turn-1"
        assert engine.calls == []  # 提交任务不触发工具派发

    def test_dispatch_gives_engine_the_double_binding(self):
        bridge, _, engine, _ = _bridge()
        result = bridge.dispatch_tool(_request())
        assert result.dispatched is True
        sent = engine.calls[0]
        assert sent.tool_call_id == "call-abc"  # 外层保持
        assert sent.turn_id == "turn-1"
        # 引擎执行标识由引擎返回后由桥接绑定为内层
        assert result.record.mapping.engine_execution_id == "exec-1"
        assert result.record.mapping.round_no == 1
        assert result.record.mapping.tool_call_id == "call-abc"

    def test_bridge_module_does_not_import_tool_registry(self):
        source = inspect.getsource(tb)
        assert "tools.registry" not in source
        assert "ToolRegistry" not in source
        # 桥接不得持有工具执行能力：只依赖注入的 EngineToolDispatcher
        assert "read_file" not in source


class TestIdempotencyT10:
    def test_same_call_100_times_dispatches_once(self):
        bridge, _, engine, _ = _bridge()
        request = _request()
        results = [bridge.dispatch_tool(request) for _ in range(100)]
        assert len(engine.calls) == 1  # 引擎只派发一次
        assert results[0].dispatched is True
        assert all(r.dispatched is False for r in results[1:])
        assert all(r.state is ToolCallState.SUCCEEDED for r in results)

    def test_already_claimed_returns_known_state_without_redispatch(self):
        bridge, _, engine, _ = _bridge()
        bridge.dispatch_tool(_request())
        second = bridge.dispatch_tool(_request())
        assert second.dispatched is False
        assert second.reason == "already_claimed"
        assert second.state is ToolCallState.SUCCEEDED
        assert len(engine.calls) == 1

    def test_new_turn_same_parameters_is_not_blocked(self):
        bridge, _, engine, _ = _bridge()
        bridge.dispatch_tool(_request(turn_id="turn-1", tool_call_id="call-1"))
        bridge.dispatch_tool(_request(turn_id="turn-2", tool_call_id="call-2"))
        assert len(engine.calls) == 2  # 合法新轮次不被误拦


class TestClaimAndResume:
    def test_atomic_claim_if_absent(self):
        store = InMemoryClaimStore()
        mapping = _request().to_mapping()
        first = store.claim_if_absent(mapping)
        second = store.claim_if_absent(mapping)
        assert first.claimed is True
        assert second.claimed is False
        assert second.record.state is ToolCallState.CLAIMED

    def test_mark_updates_state_and_engine_binding(self):
        store = InMemoryClaimStore()
        mapping = _request().to_mapping()
        store.claim_if_absent(mapping)
        record = store.mark(mapping.call_key, ToolCallState.SUCCEEDED, engine_execution_id="exec-9", round_no=3)
        assert record.state is ToolCallState.SUCCEEDED
        assert record.mapping.engine_execution_id == "exec-9"
        assert record.mapping.round_no == 3
        assert record.mapping.tool_call_id == "call-abc"  # 外层不变

    def test_resume_claimed_does_not_redispatch(self):
        bridge, store, engine, _ = _bridge()
        mapping = _request().to_mapping()
        store.claim_if_absent(mapping)  # 模拟上次已认领但未完成
        resume = bridge.resume_call(mapping.call_key)
        assert resume.exists is True
        assert resume.state is ToolCallState.CLAIMED
        assert resume.redispatch is False
        assert engine.calls == []

    def test_resume_unknown_call_key(self):
        bridge, _, _, _ = _bridge()
        resume = bridge.resume_call("call:unknown")
        assert resume.exists is False
        assert resume.record is None
        assert resume.redispatch is False

    def test_crash_window_is_outcome_unknown_and_not_retried(self):
        engine = FakeEngine(raises=True)
        bridge, _, _, _ = _bridge(engine=engine)
        result = bridge.dispatch_tool(_request())
        assert result.state is ToolCallState.OUTCOME_UNKNOWN
        assert result.reason == "outcome_unknown"
        # 崩溃后同键再次到达：返回已知 unknown，不盲重试
        again = bridge.dispatch_tool(_request())
        assert again.dispatched is False
        assert again.state is ToolCallState.OUTCOME_UNKNOWN
        assert len(engine.calls) == 1


class TestGuards:
    def test_ownership_failure_blocks_dispatch(self):
        bridge, _, engine, _ = _bridge(ownership_check=lambda session_id, turn_id: False)
        result = bridge.dispatch_tool(_request())
        assert result.dispatched is False
        assert result.reason == "not_owned"
        assert engine.calls == []

    def test_authorization_failure_blocks_dispatch(self):
        bridge, store, engine, _ = _bridge(authorize=lambda mapping: False)
        result = bridge.dispatch_tool(_request())
        assert result.dispatched is False
        assert result.reason == "not_authorized"
        assert result.state is ToolCallState.FAILED
        assert engine.calls == []
        assert store.lookup(result.record.mapping.call_key).state is ToolCallState.FAILED

    def test_budget_stop_blocks_dispatch(self):
        bridge, _, engine, _ = _bridge(budget_admit=lambda mapping: False)
        result = bridge.dispatch_tool(_request())
        assert result.dispatched is False
        assert result.reason == "budget_stop"
        assert engine.calls == []

    def test_notifier_receives_final_record(self):
        seen: list[ClaimRecord] = []
        bridge, _, _, _ = _bridge(notifier=seen.append)
        bridge.dispatch_tool(_request())
        assert len(seen) == 1
        assert seen[0].state is ToolCallState.SUCCEEDED

    def test_is_terminal(self):
        assert TaskBridge.is_terminal(ToolCallState.SUCCEEDED) is True
        assert TaskBridge.is_terminal(ToolCallState.OUTCOME_UNKNOWN) is True
        assert TaskBridge.is_terminal(ToolCallState.CLAIMED) is False
        assert TaskBridge.is_terminal(ToolCallState.RUNNING) is False

    def test_mark_unknown_key_raises(self):
        with pytest.raises(KeyError):
            InMemoryClaimStore().mark("call:missing", ToolCallState.FAILED)


class TestNoOrphanClaimRecord:
    def test_ownership_failure_leaves_no_record_in_store(self):
        bridge, store, engine, _ = _bridge(ownership_check=lambda session_id, turn_id: False)
        result = bridge.dispatch_tool(_request())
        assert result.dispatched is False
        assert result.record is None  # 不产生游离认领记录
        assert store.lookup(_request().call_key) is None
        assert engine.calls == []
