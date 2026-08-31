"""T5 closure oracle（GPT 复审六项缺口对应，2026-08-27）.

1. two-session interleave: turn_ref per-session 分桶，A/B 交错不串台
2. status budget isolation: _last_budget_info per-session（A 不见 B 的预算）
3. experience session isolation: 工具名去重从会话消息派生——他会的注入不拦本会首次
4. retrieval exactly once: 同 turn 12 次重入 → search/mark_injected/消息各恰 1（操作幂等）
5. budget single source: detail 与 _effective 恒等（单源 resolver 结构锁）
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from llm_loop.core.loop.engine import LoopEngine
from llm_loop.core.loop.tool_exec import _ToolExecMixin
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.run_context import current_session_id

_EXP_MD = """---
title: web_fetch 抓取最短路径
scenario: web_fetch 抓网页失败需换路径
root_cause: 反爬/JS 壳
solution: 用 curl 直取 HTML 再解析
evidence: test
tags: [web_fetch, 抓取]
source: {}
status: active
created_at: "2026-08-16T00:00:00+08:00"
updated_at: "2026-08-16T00:00:00+08:00"
---
"""


class _MemStore:
    def __init__(self, entries: list) -> None:
        self._entries = entries
        self.injected: list = []

    def search(self, keywords, top_k=5, session_id=""):
        hits = [e for e in self._entries if any(k in e.content for k in keywords)]
        return hits[:top_k]

    def mark_injected(self, entries):
        self.injected.extend(entries)


class _CountingStore(_MemStore):
    """操作幂等 oracle 用——记录 search/mark_injected 调用次数."""

    def __init__(self, entries: list) -> None:
        super().__init__(entries)
        self.search_calls = 0
        self.mark_calls = 0

    def search(self, *a, **k):
        self.search_calls += 1
        return super().search(*a, **k)

    def mark_injected(self, entries):
        self.mark_calls += 1
        return super().mark_injected(entries)


def _entry(eid: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=eid,
        content=content,
        type="fact",
        scope="global",
        source_session_id="",
        inject_policy="auto",
    )


def _engine(store) -> LoopEngine:
    eng = object.__new__(LoopEngine)
    eng.memory = store
    eng.semantic_retriever = None
    eng.runtime = None
    eng.settings = SimpleNamespace(memory_top_k=5)
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
    eng._run_states = {}
    eng._run_states_guard = threading.Lock()
    eng._last_active_sid = ""
    return eng


def _sess(sid: str = "s1") -> SimpleNamespace:
    return SimpleNamespace(messages=[], session_id=sid)


def _snapshots(sess) -> list:
    return [
        m
        for m in sess.messages
        if (m.metadata or {}).get("injection_kind") == "memory_snapshot"
    ]


class _TipStub(_ToolExecMixin):
    def __init__(self, exp_dir: str | Path, turn_ref=None) -> None:
        self.settings = SimpleNamespace(
            tool_experience_inject=True,
            experiences_dir=str(exp_dir),
            skills_dir="nonexistent_skills",
        )
        self.messages = []
        self.events = []
        self._tip_tail_messages = []
        self._current_turn_ref = turn_ref
        self._cache_last_model_by_session = {}
        self._cache_last_model = ""
        type(self)._skills_cache = (0.0, [])

    def _append_message_event(self, sess, msg) -> None:
        self.events.append(msg)


def _make_exp_dir(tmp_path: Path) -> Path:
    d = tmp_path / "experiences"
    d.mkdir()
    (d / "EXPERIENCE-test-web-fetch.md").write_text(_EXP_MD, encoding="utf-8")
    return d


def test_two_session_turn_ref_isolation():
    """A(turn=10)/B(turn=3) 交错赋值，回 A 仍读 10（RunState 分桶非实例全局）."""
    eng = _runstate_engine(_MemStore([]))
    tok = current_session_id.set("A")
    eng._current_turn_ref = 10
    current_session_id.reset(tok)
    tok = current_session_id.set("B")
    eng._current_turn_ref = 3
    current_session_id.reset(tok)
    tok = current_session_id.set("A")
    assert eng._current_turn_ref == 10
    current_session_id.reset(tok)
    tok = current_session_id.set("B")
    assert eng._current_turn_ref == 3
    current_session_id.reset(tok)


def test_status_budget_session_isolation():
    """A 的 _last_budget_info 不被 B 覆盖（300K/8K 各归各会话）."""
    eng = _runstate_engine(_MemStore([]))
    tok = current_session_id.set("A")
    eng._last_budget_info = {"effective_budget": 300000, "limited_by": "provider_budget"}
    current_session_id.reset(tok)
    tok = current_session_id.set("B")
    eng._last_budget_info = {"effective_budget": 8000, "limited_by": "tool_round_clamp"}
    current_session_id.reset(tok)
    tok = current_session_id.set("A")
    assert eng._last_budget_info["effective_budget"] == 300000
    assert eng._last_budget_info["limited_by"] == "provider_budget"
    current_session_id.reset(tok)
    tok = current_session_id.set("B")
    assert eng._last_budget_info["effective_budget"] == 8000
    current_session_id.reset(tok)


def test_experience_tip_session_isolation(tmp_path):
    """E08: generic experience catalog creates no prompt state in any session."""
    d = _make_exp_dir(tmp_path)
    a = _TipStub(d, turn_ref=1)
    _ToolExecMixin._inject_experience_tips(a, a, ["web_fetch"])
    assert a.messages == []
    b = _TipStub(d, turn_ref=1)
    _ToolExecMixin._inject_experience_tips(b, b, ["web_fetch"])
    _ToolExecMixin._inject_experience_tips(b, b, ["web_fetch", "other_tool"])
    assert b.messages == []

def test_retrieval_exactly_once_on_reentry():
    """同 turn 12 次重入 → 消息/search/mark_injected 各恰 1（操作幂等）."""
    store = _CountingStore([_entry("e1", "deploy restart 镜像回滚")])
    eng = _engine(store)
    sess = _sess()
    for _ in range(12):
        eng._inject_turn_memory_snapshot(sess, "deploy restart 镜像回滚", turn_ref=0)
    assert len(_snapshots(sess)) == 1
    assert store.search_calls == 1  # 检索恰一次（重入不重查）
    assert store.mark_calls == 1  # memory 使用统计不污染


def test_budget_single_source_no_drift():
    """detail 与 _effective 恒等（T5 单源 resolver 结构锁——防漂移回潮）."""
    eng = _engine(_MemStore([]))
    eng.settings = SimpleNamespace(history_max_chars=50000, memory_top_k=5)
    eng.llm_pool = None
    eng._runtime_history_budget = lambda: 50000
    eng._provider_chars_per_token = lambda *a, **k: 0.6
    eng._current_context_limit = lambda *a, **k: None
    detail = eng._effective_history_budget_detail("deepseek/x")
    eff = eng._effective_history_budget("deepseek/x")
    assert detail["effective_budget"] == eff == 50000
    assert detail["limited_by"] == "global_budget"
    # 窗口限制分支：65536 × 0.6 × 0.5 = 19660 < 50000
    eng._current_context_limit = lambda *a, **k: 65536
    detail2 = eng._effective_history_budget_detail("deepseek/x")
    eff2 = eng._effective_history_budget("deepseek/x")
    assert detail2["effective_budget"] == eff2 == 19660
    assert detail2["limited_by"] == "model_window"
    assert detail2["model_window_budget"] == 19660
