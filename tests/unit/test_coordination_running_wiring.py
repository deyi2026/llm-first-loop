"""DESIGN-20261103 N1 T-0.3/T-0.4: coordination_status 的 running 段接线.

覆盖:
- children 按 owner session 归属：自己的出完整 child_id，他人的只出脱敏行+计数
- 在飞判据 = handle.state == "running"（集合成员资格不能当在飞判据）
- jobs 同一口径：自己的列命令，他人的只计数
- top-N 截断自证（不静默丢在跑的活）
- 未装配事实源 → 显式「未装配」degraded，不冒充「无运行」
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id as _sid
from llm_loop.introspection.tools_goal import run_coordination_status
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.job_registry import JobEntry

SELF = "sess-self-n1"
OTHER = "sess-other-n1-长id"


@pytest.fixture(autouse=True)
def _bind():
    token = _sid.set(SELF)
    yield
    _sid.reset(token)


def _child(child_id: str, parent: str, state: str = "running", depth: int = 1):
    return SimpleNamespace(
        child_id=child_id, parent_id=parent, state=state, depth=depth
    )


class _FakeRunner:
    def __init__(self, handles):
        self._handles = list(handles)
        self.calls = 0

    def all_active_children(self):
        self.calls += 1
        return list(self._handles)


class _FakeJobs:
    def __init__(self, jobs):
        self._jobs = list(jobs)

    def active_all(self):
        return tuple(self._jobs)


def _job(job_id: str, owner: str, *, command: str = "sleep 1", done: bool = False):
    return JobEntry(
        id=job_id,
        command=command,
        done=done,
        session_id=owner,
        executor="shell",
        started_at=1_700_000_000.0,
    )


def _host(tmp_path, *, runner=None, jobs=None):
    return SimpleNamespace(
        audit_dir=str(tmp_path),
        ctx=SimpleNamespace(subagent_runner=runner, job_registry=jobs),
    )


def test_children_owner_scope_and_masking(tmp_path):
    runner = _FakeRunner(
        [
            _child("child-mine-1", SELF),
            _child("child-other-1", OTHER),
        ]
    )
    res = run_coordination_status(None, _host(tmp_path, runner=runner), {"window_hours": 0})
    assert res.status == ToolResultStatus.SUCCESS
    text = res.content
    # 归属口径必须出现在回执里（Q39(b)）
    assert "children_scope=owner_session" in text
    assert "children=2(1 mine+1 others)" in text
    assert "child child-mine-1 state=running" in text
    # 他人 child 不出完整 id（Q13）
    assert "child-other-1" not in text
    assert "mine=False" in text
    assert runner.calls == 1


def test_unwired_sources_say_unwired_not_empty(tmp_path):
    res = run_coordination_status(None, _host(tmp_path), {"window_hours": 0})
    assert res.status == ToolResultStatus.SUCCESS
    assert "degraded: running.children: 未装配" in res.content
    assert "degraded: running.jobs: 未装配" in res.content
    # 未装配不得被读成「无 child 在跑」
    assert "不代表没有 child 在跑" in res.content


def test_jobs_mine_listed_others_counted(tmp_path):
    jobs = _FakeJobs(
        [
            _job("job_mine", SELF, command="pytest -q"),
            _job("job_other", OTHER, command="secret-cmd"),
            _job("job_done", SELF, command="echo done", done=True),
        ]
    )
    res = run_coordination_status(None, _host(tmp_path, jobs=jobs), {"window_hours": 0})
    text = res.content
    assert "job_mine exec=shell" in text
    assert "pytest -q" in text
    assert "secret-cmd" not in text
    assert "jobs=1(1 mine+1 others)" in text


def test_top_n_truncation_is_self_evident(tmp_path):
    runner = _FakeRunner([_child(f"c-{i:02d}", SELF) for i in range(13)])
    res = run_coordination_status(None, _host(tmp_path, runner=runner), {"window_hours": 0})
    text = res.content
    assert "children=10(13 mine+0 others)" in text
    assert "running.children_truncated: 呈现 10+0 / 共 13+0" in text
    assert "c-12" not in text


def test_all_active_children_filters_by_state():
    """真实 runner 方法：只返 state=="running"，终态 handle 不得混入."""
    runner = SubAgentRunner.__new__(SubAgentRunner)
    runner._children_guard = threading.RLock()
    runner._handles = {
        "b": _child("b", SELF, state="running"),
        "a": _child("a", SELF, state="running"),
        "c": _child("c", SELF, state="done"),
        "d": _child("d", SELF, state="failed"),
    }
    assert [h.child_id for h in runner.all_active_children()] == ["a", "b"]


def test_factory_injects_running_sources(tmp_path):
    """装配点注入：真实 build_engine 后 running 段不再是「未装配」."""
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        self_inspection_enabled=False,
        extract_enabled=False,
    )
    engine = build_engine(settings)  # type: ignore[no-any-return]
    ctx = engine.correction_ctx
    assert ctx.subagent_runner is engine.subagent_runner
    assert ctx.job_registry is not None

    host = SimpleNamespace(audit_dir=str(settings.audit_dir), ctx=ctx)
    res = run_coordination_status(ctx, host, {"window_hours": 0})
    assert res.status == ToolResultStatus.SUCCESS
    assert "未装配 subagent_runner" not in res.content
    assert "未装配 job_registry" not in res.content
    assert "children_scope=owner_session" in res.content


def test_g7_running_wiring_writes_nothing(tmp_path):
    """G7: running 段接线后仍然零写——账本文件与 mtime 都不变."""
    import os

    from llm_loop.introspection.goal import GoalStore

    audit = tmp_path / "audit"
    store = GoalStore(audit)
    store.create("目标一", session_id=SELF)  # 落一份真实账本（goals.jsonl）
    assert (audit / "goals.jsonl").is_file()

    def _snap():
        return {
            p.name: (p.stat().st_mtime_ns, p.stat().st_size)
            for p in sorted(audit.rglob("*"))
            if p.is_file()
        }

    runner = _FakeRunner([_child("c-1", SELF), _child("c-2", OTHER)])
    jobs = _FakeJobs([_job("job_mine", SELF)])
    before = _snap()
    for _ in range(3):
        res = run_coordination_status(
            None, _host(audit, runner=runner, jobs=jobs), {"window_hours": 0}
        )
        assert res.status == ToolResultStatus.SUCCESS
    assert _snap() == before
    assert os.stat(audit).st_mtime_ns  # 目录仍在（非空断言，防 vacuous）
