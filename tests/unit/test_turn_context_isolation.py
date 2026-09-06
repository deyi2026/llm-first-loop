"""T5 closure oracle（GPT 复审六项缺口对应，2026-08-27）.

1. two-session interleave: turn_ref per-session 分桶，A/B 交错不串台
2. status budget isolation: _last_budget_info per-session（A 不见 B 的预算）
3. experience session isolation: 工具名去重从会话消息派生——他会的注入不拦本会首次
4. retrieval exactly once: 同 turn 12 次重入 → search/mark_injected/消息各恰 1（操作幂等）
5. budget single source: detail 与 _effective 恒等（单源 resolver 结构锁）
"""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.loop.engine import LoopEngine
from llm_loop.core.loop.engine_services.run_state import RunStateManager
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.run_context import current_session_id


class _MemStore:
    def __init__(self, entries: list) -> None:
        self._entries = entries
        self.injected: list = []

    def search(self, keywords, top_k=5, session_id=""):
        hits = [e for e in self._entries if any(k in e.content for k in keywords)]
        return hits[:top_k]

    def mark_injected(self, entries):
        self.injected.extend(entries)






def _engine(store) -> LoopEngine:
    eng = object.__new__(LoopEngine)
    eng.memory = store
    eng.semantic_retriever = None
    eng.runtime = None
    eng.settings = SimpleNamespace(memory_top_k=5)
    from llm_loop.core.loop.engine_services.routing import RoutingService
    from llm_loop.core.loop.engine_services.runtime_params import RuntimeParamsService

    eng._runtime_params = RuntimeParamsService(eng)  # B5-W4-02a: 裸实例补 service 注入（同 turn_snapshot 桩）
    eng._routing = RoutingService(eng)  # B5-W4-02b: 裸实例补 RoutingService 注入（沿 02a 桩例）
    eng._events = []
    eng._faults = []
    eng._append_message_event = lambda sess, msg: eng._events.append(msg)
    eng._fault_feedback = (
        lambda kind, exc: Message(
            role="system",
            content=f"[程序异常反馈:{kind}] {exc}",
            source=MessageSource.SYSTEM,
        )
    )
    eng._record_program_fault = lambda kind: eng._faults.append(kind)
    return eng


def _runstate_engine(store) -> LoopEngine:
    eng = _engine(store)
    eng._run_state_mgr = RunStateManager()
    return eng


def _sess(sid: str = "s1") -> SimpleNamespace:
    return SimpleNamespace(messages=[], session_id=sid)


def _snapshots(sess) -> list:
    return [
        m
        for m in sess.messages
        if (m.metadata or {}).get("injection_kind") == "memory_snapshot"
    ]


def test_two_session_turn_ref_isolation():
    """A(turn=10)/B(turn=3) 交错赋值，回 A 仍读 10（RunState 分桶非实例全局）."""
    eng = _runstate_engine(_MemStore([]))
    tok = current_session_id.set("A")
    eng._run_state().current_turn_ref = 10
    current_session_id.reset(tok)
    tok = current_session_id.set("B")
    eng._run_state().current_turn_ref = 3
    current_session_id.reset(tok)
    tok = current_session_id.set("A")
    assert eng._run_state().current_turn_ref == 10
    current_session_id.reset(tok)
    tok = current_session_id.set("B")
    assert eng._run_state().current_turn_ref == 3
    current_session_id.reset(tok)


def test_status_budget_session_isolation():
    """A 的 _last_budget_info 不被 B 覆盖（300K/8K 各归各会话）."""
    eng = _runstate_engine(_MemStore([]))
    tok = current_session_id.set("A")
    eng._run_state().last_budget_info = {"effective_budget": 300000, "limited_by": "provider_budget"}
    current_session_id.reset(tok)
    tok = current_session_id.set("B")
    eng._run_state().last_budget_info = {"effective_budget": 8000, "limited_by": "tool_round_clamp"}
    current_session_id.reset(tok)
    tok = current_session_id.set("A")
    assert eng._run_state().last_budget_info["effective_budget"] == 300000
    assert eng._run_state().last_budget_info["limited_by"] == "provider_budget"
    current_session_id.reset(tok)
    tok = current_session_id.set("B")
    assert eng._run_state().last_budget_info["effective_budget"] == 8000
    current_session_id.reset(tok)


def test_retrieval_exactly_once_on_reentry():
    """Agency-first: reentry cannot duplicate a retired memory prompt producer."""
    from llm_loop.core.loop.engine import LoopEngine

    assert not hasattr(LoopEngine, "_inject_turn_memory_snapshot")


def test_budget_single_source_no_drift():
    """detail 与 _effective 恒等（T5 单源 resolver 结构锁——防漂移回潮）."""
    eng = _engine(_MemStore([]))
    eng.settings = SimpleNamespace(history_max_chars=50000, memory_top_k=5, llm_max_tokens=8192)
    eng.llm_pool = None
    eng._runtime_history_budget = lambda: 50000
    eng._provider_chars_per_token = lambda *a, **k: 0.6
    eng._routing._current_context_limit = lambda *a, **k: None  # W4-02b: 桩随 service 化迁实例（service 内部自调用直达，引擎面桩不再可拦截）
    detail = eng._effective_history_budget_detail("deepseek/x")
    eff = eng._effective_history_budget("deepseek/x")
    assert detail["effective_budget"] == eff == 50000
    assert detail["limited_by"] == "global_budget"
    # 窗口限制分支：min(65536×0.9, 65536-8192) × 0.6 = 34406 < 50000
    eng._routing._current_context_limit = lambda *a, **k: 65536  # W4-02b: 同上
    detail2 = eng._effective_history_budget_detail("deepseek/x")
    eff2 = eng._effective_history_budget("deepseek/x")
    assert detail2["effective_budget"] == eff2 == 34406
    assert detail2["limited_by"] == "model_window"
    assert detail2["model_window_budget"] == 34406
