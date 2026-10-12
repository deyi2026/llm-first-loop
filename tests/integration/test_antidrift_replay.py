"""antidrift 端到端重演（观测型，非门禁）——spec 验收倒数第三项.

场景：任务对象被取代 + 变体探索 + 队列插话压力（6.1 R2 分量）；
唤醒 refs 差量事实段（6.2 R1 分量）；复活中断事实行（6.2 R6 分量）。
仅断言事实供给到位，不断言模型决策；"≤2 轮转向/收口"仅为期望观察记录
（6.1 场景两次边界 continue 后收口），不作断言（spec 明示非门禁）。
"""

from __future__ import annotations

import time
from datetime import datetime
from types import SimpleNamespace

from llm_loop.core.loop.events import _EventsMixin
from llm_loop.core.message import ToolCall
from llm_loop.core.scheduler import ScheduleEntry
from llm_loop.factory import _render_subject_refs_facts
from llm_loop.llm.client import LLMResponse
from llm_loop.tools.builtin.job_registry import JobEntry, JobRegistry
from tests.unit.test_err1210_recovery import _mk
from tests.unit.test_subject_refs_facts import (
    _event,
    _FakeEventStore,
    _install_registry,
    _write_deployment,
    _write_restart_action,
)


def _tool_names(call: dict) -> list[str]:
    out: list[str] = []
    for item in call.get("tools") or []:
        if isinstance(item, dict) and item.get("name"):
            out.append(str(item["name"]))
            continue
        fn = item.get("function") if isinstance(item, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            out.append(str(fn["name"]))
    return out


def _capture_tools(fake) -> None:
    original = fake.chat

    def _chat(messages, tools, **kwargs):
        result = original(messages, tools, **kwargs)
        fake.calls[-1]["tools"] = tools
        return result

    fake.chat = _chat


def _read_resp(call_id: str, path: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id=call_id, name="read_file", arguments={"path": path})
        ],
        provider="fake",
    )


def _decide(call_id: str, unresolved: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                name="convergence_decide",
                arguments={"decision": "continue", "unresolved": unresolved},
            )
        ],
        provider="fake",
    )


def _receipt(engine, sid: str, call_id: str) -> str:
    persisted = engine.session.load(sid)
    matched = [
        m for m in persisted.messages if m.role == "tool" and m.tool_call_id == call_id
    ]
    assert len(matched) == 1
    return str(matched[0].content)


def test_antidrift_replay_repeated_signals_preserve_direct_tool_authority(tmp_path, monkeypatch):
    """Repeated exploration is observed, but concrete follow-up tools stay directly callable."""
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1", "/obj/a"),
            _read_resp("c2", "/obj/a"),
            _read_resp("c3", "/obj/a"),
            # After A repeats three times, switch directly to B.  No meta-router hop.
            _read_resp("c4", "/obj/b"),
            _read_resp("c5", "/obj/b"),
            _read_resp("c6", "/obj/b"),
            LLMResponse(content="重演后收口", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    engine.interjection_pressure_probe = lambda sid: {
        "count": 1,
        "oldest_enqueued_at": 1758600000.0,
    }
    sid = engine.session.create()
    result = engine.run(sid, "对象 A 复核任务")
    assert result.final_answer == "重演后收口"

    # The first round after A's repeated-call signal still exposes the real tool surface.
    assert "read_file" in _tool_names(fake.calls[3])
    assert "convergence_decide" not in _tool_names(fake.calls[3])

    persisted = engine.session.load(sid)
    c4 = [m for m in persisted.messages if m.role == "tool" and m.tool_call_id == "c4"]
    assert len(c4) == 1
    assert "reason_code=convergence_boundary" not in c4[0].content

    trace = str(engine.status.snapshot().get("action_trace", []))
    assert "convergence.observation" in trace
    assert "direct_tool_continued" in trace


def test_antidrift_replay_r1_wake_refs_delta_supplied(tmp_path, monkeypatch):
    """6.2 R1 分量: 唤醒 refs 差量事实段（job 终态/generation 前移）在 wake 投递上下文供给到位.

    观测型：断言事实段渲染与组装序（factory _deliver_schedule 同款：基础前缀 →
    refs 段追加于 jobs_facts 之后），不断言唤醒 run 的模型行为。
    """
    reg = JobRegistry()
    with reg._lock:
        reg._jobs["job-r1"] = JobEntry(
            id="job-r1",
            command="cmd",
            session_id="sess-replay",
            killed=True,
            done=True,
            finished_at=1758600000.0,
        )
    _install_registry(monkeypatch, reg)
    _write_deployment(tmp_path, generation=69)
    entry = ScheduleEntry(
        sid="sched-r1",
        message="复核对象与 generation",
        trigger_at=0.0,
        subject_refs=[
            {"type": "job_id", "id": "job-r1"},
            {"type": "expected_generation", "id": "67"},
        ],
    )
    refs = _render_subject_refs_facts(entry, tmp_path)
    assert "job_id=job-r1 终态=killed(" in refs
    assert "desired_generation 67→69" in refs

    wake_prompt = f"[定时续跑·先前真人授权的程序委派·非新真人输入] {entry.message}"
    if refs:
        wake_prompt = f"{wake_prompt}\n{refs}"
    assert wake_prompt.startswith("[定时续跑·先前真人授权的程序委派·非新真人输入]")
    assert refs in wake_prompt


def test_antidrift_replay_r6_restart_interrupt_fact_supplied(tmp_path):
    """6.2 R6 分量: 复活中断场景——死亡窗口内 restart 动作 → 中断事实行供给到位.

    观测型：断言 state 附带事实行（生产消费链路 events.py
    _prepare_interruption_resume → bucket.interruption_resume 的直接上游），
    不改变复活策略本身（fail-open 语义由 T3-7 锁定）。
    """
    now = time.time()
    run_end_iso = datetime.fromtimestamp(now - 100).astimezone().isoformat()
    declared_iso = datetime.fromtimestamp(now - 50).astimezone().isoformat()
    action_iso = datetime.now().astimezone().isoformat()
    _write_restart_action(tmp_path, "act-replay", action_iso)
    svc = _EventsMixin.__new__(_EventsMixin)
    svc._event_store = _FakeEventStore(
        [
            _event(1, "run.end", run_end_iso),
            _event(
                2,
                "tool.execution.declared",
                declared_iso,
                {
                    "execution_id": "exec-r",
                    "round": 2,
                    "tool_call_id": "c2",
                    "tool_name": "read_file",
                },
            ),
        ]
    )
    svc.settings = SimpleNamespace(data_dir=str(tmp_path))
    state = svc._prepare_open_interruption_resume("sess-1")
    assert state is not None
    assert state["restart_interrupt_fact"] == f"run 因共享服务重启中断于 {action_iso}"
