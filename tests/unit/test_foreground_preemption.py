"""P0-B 前台真抢占的机械验证：admission 触发的租约撤销与 mid-call 反思弃置。

Governor 侧：撤销只绑定"前台类 admission 尝试 + 外部 probe active"；
probe 被动翻转或背景类请求不得撤销任何租约。
Plane 侧：mid-call 前台激活 → 立即 requeue(preempted_by_foreground)、释放租约、
弃置 worker；straggler 只自行结算 provider call，永不写 journal/MethodStore。
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from llm_loop.methods.learning_journal import LearningJournal
from llm_loop.methods.learning_plane import LearningPlane
from llm_loop.resources.contracts import (
    AdmissionOutcome,
    AdmissionRequest,
    ExecutionClass,
    ResourceKey,
    ResourceScopeKind,
    ServicePriority,
)
from llm_loop.resources.governor import ResourceGovernor


def _key(tag: str = "rt") -> ResourceKey:
    return ResourceKey("test", ResourceScopeKind.RUNTIME, f"preempt-{tag}")


_ROLES = {
    "task": (ExecutionClass.FOREGROUND_TASK, ServicePriority.P0_FOREGROUND),
    "subagent": (ExecutionClass.SUBAGENT, ServicePriority.P1_ACTIVE_TASK_AUXILIARY),
    "learning": (ExecutionClass.BACKGROUND_LEARNING, ServicePriority.P3_BACKGROUND_LEARNING),
}


def _request(role: str, request_id: str, keys: tuple[ResourceKey, ...]) -> AdmissionRequest:
    exec_class, priority = _ROLES[role]
    return AdmissionRequest(
        request_id=request_id,
        owner_ref=request_id,
        execution_class=exec_class,
        service_priority=priority,
        provider_id="test",
        model_id="m",
        resource_keys=keys,
        submitted_at=1.0,
    )


@pytest.mark.parametrize("role", ["task", "subagent"])
def test_foreground_admission_revokes_overlapping_background_lease(role: str):
    busy = {"value": False}
    key = _key()
    governor = ResourceGovernor(foreground_probe=lambda: busy["value"])
    governor.set_concurrency_limit(key, 1)

    learning = governor.try_acquire(_request("learning", "l1", (key,)))
    assert learning.lease is not None

    busy["value"] = True  # 前台 run 激活；下一次前台类 admission 触发撤销
    foreground = governor.try_acquire(_request(role, "f1", (key,)))
    assert foreground.outcome is AdmissionOutcome.ADMITTED
    assert foreground.lease is not None

    assert governor.active_leases() == (foreground.lease,)
    assert governor.in_flight(key) == 1
    assert governor.release(learning.lease) is False  # 被抢占者的释放走幂等 False
    assert governor.in_flight(key) == 1
    assert governor.release(foreground.lease) is True


def test_probe_flip_alone_and_background_attempts_never_revoke():
    busy = {"value": False}
    key = _key()
    governor = ResourceGovernor(foreground_probe=lambda: busy["value"])
    governor.set_concurrency_limit(key, 2)

    first = governor.try_acquire(_request("learning", "l1", (key,)))
    assert first.lease is not None

    busy["value"] = True
    second = governor.try_acquire(_request("learning", "l2", (key,)))
    assert second.outcome is AdmissionOutcome.DEFERRED  # barrier 生效
    assert governor.active_leases() == (first.lease,)  # 观测/背景尝试不撤销
    assert governor.in_flight(key) == 1


def test_non_overlapping_background_lease_survives_foreground_admission():
    busy = {"value": False}
    key_a, key_b = _key("a"), _key("b")
    governor = ResourceGovernor(foreground_probe=lambda: busy["value"])
    governor.set_concurrency_limit(key_a, 1)
    governor.set_concurrency_limit(key_b, 1)

    learning = governor.try_acquire(_request("learning", "l1", (key_a,)))
    assert learning.lease is not None
    busy["value"] = True
    foreground = governor.try_acquire(_request("task", "f1", (key_b,)))
    assert foreground.outcome is AdmissionOutcome.ADMITTED
    assert set(lease.lease_id for lease in governor.active_leases()) == {
        learning.lease.lease_id,
        foreground.lease.lease_id,
    }


def test_probe_inactive_admission_does_not_revoke():
    busy = {"value": False}
    key = _key()
    governor = ResourceGovernor(foreground_probe=lambda: busy["value"])
    governor.set_concurrency_limit(key, 2)
    learning = governor.try_acquire(_request("learning", "l1", (key,)))
    task = governor.try_acquire(_request("task", "t1", (key,)))
    assert task.outcome is AdmissionOutcome.ADMITTED
    assert set(lease.lease_id for lease in governor.active_leases()) == {
        learning.lease.lease_id,
        task.lease.lease_id,
    }


def _engine_stub() -> SimpleNamespace:
    return SimpleNamespace(
        registry=object(),
        runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(),
        _sync_active=set(),
        settings=SimpleNamespace(method_reflection_timeout_s=120.0),
    )


def test_learning_plane_preempts_inflight_reflection_and_requeues(tmp_path, monkeypatch):
    """mid-call 前台激活 → 立刻弃置反思、requeue、释放租约；straggler 只自结算。"""
    journal = LearningJournal(tmp_path / "learning_journal.jsonl")
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1", source_model="provider/model")
    assert job is not None

    busy = {"value": False}
    plane = LearningPlane(
        journal=journal,
        episode_store=SimpleNamespace(
            get=lambda *_a, **_k: {"messages": [{"role": "assistant", "content": "done"}]}
        ),
        method_store=SimpleNamespace(),
        engine=_engine_stub(),
        model_resolver=lambda _m: object(),
        resource_governor=ResourceGovernor(foreground_probe=lambda: busy["value"]),
        resource_target_resolver=lambda _model: ("provider", "model"),
        poll_interval_s=1.0,
        quiet_period_s=0.0,
        preempt_poll_s=0.02,
    )

    entered = threading.Event()
    release = threading.Event()

    def blocked_reflection(**_kwargs):
        entered.set()
        release.wait(timeout=10)
        return SimpleNamespace(
            attempted=True,
            reason="schema_ok",
            candidate_payload={"name": "n", "description": "d", "body": "b"},
        )

    monkeypatch.setattr(
        "llm_loop.methods.learning_plane.reflect_on_episode", blocked_reflection
    )

    box: dict[str, object] = {}
    t = threading.Thread(target=lambda: box.update(r=plane._try_execute(job)))
    t.start()
    assert entered.wait(timeout=5)  # 传输已真实开始

    busy["value"] = True  # 前台到来：mid-call 抢占
    t.join(timeout=5)
    assert box.get("r") is False

    after = journal.job(job.job_id)
    assert after is not None and after.state == "queued" and after.attempt == 1
    lines = (tmp_path / "learning_journal.jsonl").read_text().splitlines()
    assert any('"requeued"' in ln and "preempted_by_foreground" in ln for ln in lines)
    assert plane._resource_governor.active_leases() == ()  # 租约已让出
    assert plane._straggler_busy() is True  # 弃置 worker 仍在排空

    busy["value"] = False
    job2 = journal.enqueue("episode:s1:4:zzz", session_id="s1", source_model="provider/model")
    assert job2 is not None
    assert plane._try_execute(job2) is False  # straggler 未排空前不得叠加传输
    assert journal.job(job2.job_id).attempt == 0

    release.set()
    deadline = time.time() + 5
    while plane._straggler_busy() and time.time() < deadline:
        time.sleep(0.01)
    assert not plane._straggler_busy()
    # 弃置 worker 结算后也绝不写 journal（job 仍 queued）
    assert journal.job(job.job_id).state == "queued"

    plane._method_store = SimpleNamespace(
        save_candidate=lambda **_kw: SimpleNamespace(method_ref="method:stub")
    )
    assert plane._try_execute(job2) is True  # 排空后恢复学习
    assert journal.job(job2.job_id).state == "saved"
