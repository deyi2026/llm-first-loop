"""antidrift 批 3: R1 唤醒 subject_refs 事实段 + R6 复活 restart 中断事实行（T3-3~T3-7）.

R1 红线：仅差量事实、零结论性措辞；对象不存在/解析失败 → 如实"现状不可解析"；整体 fail-open。
R6 红线：只读扫描 actions 目录；无命中/不可读 → None 不伪造；复活策略零改动。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from llm_loop.core.loop.events import _EventsMixin, render_restart_interrupt_fact
from llm_loop.core.scheduler import ScheduleEntry
from llm_loop.event_log.model import Event
from llm_loop.factory import _render_subject_refs_facts
from llm_loop.runtime.service_control import (
    ManagedServiceDeployment,
    ManagedServiceDeploymentStore,
    ServiceControlAction,
)
from llm_loop.tools.builtin.job_registry import JobEntry, JobRegistry

_CONCLUSION_WORDS = ("放弃", "失效", "建议", "应当终止", "已完成使命")


def _write_deployment(data_dir: Path, generation: int) -> None:
    runtime = Path(data_dir) / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    dep = ManagedServiceDeployment(
        schema="managed-service-deployment/v1",
        deployment_id="dep-1",
        generation=generation,
        git_head="a" * 40,
        code_root="/tmp/code",
        runtime_root="/tmp/runtime",
        webui_artifact_sha256="b" * 64,
    )
    (runtime / "managed_service_deployment.json").write_text(
        json.dumps(dep.to_dict()), encoding="utf-8"
    )


def _write_restart_action(
    data_dir: Path, action_id: str, updated_at_iso: str, *, status: str = "succeeded"
) -> None:
    store = ManagedServiceDeploymentStore(data_dir)
    store.actions_dir.mkdir(parents=True, exist_ok=True)
    action = ServiceControlAction(
        schema="service-control-action/v1",
        action_id=action_id,
        action="restart",
        target="web",
        deployment_id="dep-1",
        deployment_generation=1,
        requester_session_id="sess-1",
        status=status,
        created_at=updated_at_iso,
        updated_at=updated_at_iso,
    )
    (store.actions_dir / f"{action_id}.json").write_text(
        json.dumps(action.to_dict()), encoding="utf-8"
    )


def _install_registry(monkeypatch, reg: JobRegistry) -> None:
    monkeypatch.setattr(JobRegistry, "instance", classmethod(lambda cls: reg))


class _FakeEventStore:
    enabled = True

    def __init__(self, events):
        self._events = list(events)

    def read(self, session_id):
        return list(self._events)


def _event(seq, etype, ts_iso, payload=None):
    return Event(
        event_id=f"e{seq}",
        session_id="sess-1",
        seq=seq,
        type=etype,
        ts=ts_iso,
        payload=payload or {},
    )


def test_t3_3_subject_refs_delta_facts_only(tmp_path, monkeypatch):
    """T3-3: job 终态=killed、generation 66→68 → 唤醒事实段仅差量词，负向断言禁结论性措辞."""
    reg = JobRegistry()
    with reg._lock:
        reg._jobs["job-k1"] = JobEntry(
            id="job-k1",
            command="cmd",
            session_id="sess-1",
            killed=True,
            done=True,
            finished_at=1758600000.0,
        )
    _install_registry(monkeypatch, reg)
    _write_deployment(tmp_path, generation=68)
    entry = ScheduleEntry(
        sid="sched-1",
        message="m",
        trigger_at=0.0,
        subject_refs=[
            {"type": "job_id", "id": "job-k1"},
            {"type": "expected_generation", "id": "66"},
        ],
    )
    text = _render_subject_refs_facts(entry, tmp_path)
    assert "job_id=job-k1 终态=killed(" in text
    assert "desired_generation 66→68" in text
    # 零结论性措辞：负向断言针对事实行（头部"非建议"免责声明与 jobs_facts 先例同款，不计入）
    fact_lines = text.splitlines()[1:]
    for word in _CONCLUSION_WORDS:
        assert fact_lines
        assert all(word not in ln for ln in fact_lines)


def test_t3_4_missing_subjects_marked_independently(tmp_path, monkeypatch):
    """T3-4: refs 指向对象不存在 → 如实"现状不可解析"；混合 refs 逐条独立报告，渲染不抛异常（唤醒照常）."""
    _install_registry(monkeypatch, JobRegistry())
    _write_deployment(tmp_path, generation=68)
    iso = datetime.now().astimezone().isoformat()
    _write_restart_action(tmp_path, "act-ok", iso)
    entry = ScheduleEntry(
        sid="sched-2",
        message="m",
        trigger_at=0.0,
        subject_refs=[
            {"type": "job_id", "id": "job-missing"},
            {"type": "action_id", "id": "act-missing"},
            {"type": "action_id", "id": "act-ok"},
        ],
    )
    text = _render_subject_refs_facts(entry, tmp_path)
    lines = [ln for ln in text.splitlines() if ln]
    assert "job_id=job-missing 现状不可解析（对象不存在）" in text
    assert "action_id=act-missing 现状不可解析（对象不存在）" in text
    assert "action_id=act-ok 状态=succeeded(" in text
    assert len(lines) == 4  # 头部 + 3 条逐条独立


def test_t3_5_resolver_exception_fail_open(tmp_path, monkeypatch):
    """T3-5: 解析器注入异常 → 不上抛（唤醒照常）；refs 非法/空 → 空段（不追加）."""
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(JobRegistry, "instance", staticmethod(_boom))
    entry = ScheduleEntry(
        sid="sched-3",
        message="m",
        trigger_at=0.0,
        subject_refs=[{"type": "job_id", "id": "job-x"}],
    )
    text = _render_subject_refs_facts(entry, tmp_path)
    assert "job_id=job-x 现状不可解析（RuntimeError）" in text

    assert _render_subject_refs_facts(SimpleNamespace(subject_refs="not-a-list"), tmp_path) == ""
    assert _render_subject_refs_facts(SimpleNamespace(subject_refs=[]), tmp_path) == ""


def test_t3_6_restart_fact_in_death_window(tmp_path):
    """T3-6: 死亡窗口内 restart 动作 → 单行事实行且时刻与动作记录一致；窗口外 → None."""
    iso = datetime.now().astimezone().isoformat()
    _write_restart_action(tmp_path, "act-r1", iso)
    now = time.time()
    fact = render_restart_interrupt_fact(
        tmp_path, window_start_ts=now - 600, window_end_ts=now + 1
    )
    assert fact == f"run 因共享服务重启中断于 {iso}"
    assert (
        render_restart_interrupt_fact(
            tmp_path, window_start_ts=now - 600, window_end_ts=now - 300
        )
        is None
    )


def test_t3_6_resume_state_attaches_restart_fact(tmp_path):
    """T3-6: 最后 run.end 后有未结算执行事实 + 窗口内 restart → 恢复 state 含 restart_interrupt_fact."""
    now = time.time()
    run_end_ts = datetime.fromtimestamp(now - 100).astimezone().isoformat()
    declared_ts = datetime.fromtimestamp(now - 50).astimezone().isoformat()
    action_iso = datetime.now().astimezone().isoformat()
    _write_restart_action(tmp_path, "act-r2", action_iso)
    svc = _EventsMixin.__new__(_EventsMixin)
    svc._event_store = _FakeEventStore(
        [
            _event(1, "run.end", run_end_ts),
            _event(
                2,
                "tool.execution.declared",
                declared_ts,
                {"execution_id": "exec-1", "round": 1, "tool_call_id": "c1", "tool_name": "t"},
            ),
        ]
    )
    svc.settings = SimpleNamespace(data_dir=str(tmp_path))
    state = svc._prepare_open_interruption_resume("sess-1")
    assert state is not None
    assert state["restart_interrupt_fact"] == f"run 因共享服务重启中断于 {action_iso}"


def test_t3_7_restart_fact_fail_open(tmp_path):
    """T3-7: 窗口内无 restart → 无事实行；目录不存在/损坏 JSON → None 不伪造；state 不附键."""
    now = time.time()
    assert (
        render_restart_interrupt_fact(tmp_path / "nope", window_start_ts=0.0, window_end_ts=now)
        is None
    )
    empty_dir = tmp_path / "data2"
    empty_dir.mkdir()
    assert render_restart_interrupt_fact(empty_dir, window_start_ts=0.0, window_end_ts=now) is None

    store = ManagedServiceDeploymentStore(empty_dir)
    store.actions_dir.mkdir(parents=True, exist_ok=True)
    (store.actions_dir / "bad.json").write_text("{not-json", encoding="utf-8")
    assert render_restart_interrupt_fact(empty_dir, window_start_ts=0.0, window_end_ts=now) is None

    svc = _EventsMixin.__new__(_EventsMixin)
    svc._event_store = _FakeEventStore(
        [
            _event(1, "run.end", datetime.fromtimestamp(now - 100).astimezone().isoformat()),
            _event(
                2,
                "tool.execution.declared",
                datetime.fromtimestamp(now - 50).astimezone().isoformat(),
                {"execution_id": "exec-2", "round": 1, "tool_call_id": "c2", "tool_name": "t"},
            ),
        ]
    )
    svc.settings = SimpleNamespace(data_dir=str(tmp_path / "clean"))
    state = svc._prepare_open_interruption_resume("sess-1")
    assert state is not None
    assert "restart_interrupt_fact" not in state
