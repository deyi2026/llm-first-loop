"""缺口②-3: 任务注册表（依赖范围准入）——闭表 + 范围属性.

准入范围是声明事实：web 屏障只阻塞依赖 web 的入口，不外溢到 learning；
learning 屏障只挡 learning 任务。未登记任务种类拒绝服务，防止调用点临时
自定服务名。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.runtime.admission_barrier import (
    TASK_ADMISSION_DEPENDENCIES,
    AdmissionBarrierRegistry,
    task_admission_barrier,
)


def test_closed_table_covers_all_entry_points() -> None:
    assert set(TASK_ADMISSION_DEPENDENCIES) == {
        "web_chat",
        "web_chat_stream",
        "web_queue_dispatch",
        "web_schedule_wake",
        "feishu_message",
        "learning_job",
    }
    for kind, services in TASK_ADMISSION_DEPENDENCIES.items():
        assert services, f"{kind} 必须声明非空依赖"


def test_unknown_task_kind_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        task_admission_barrier(tmp_path, "ad_hoc_task")


def test_web_barrier_scopes_to_web_tasks_only(tmp_path: Path) -> None:
    AdmissionBarrierRegistry(tmp_path).establish("web", operation_id="op-web")
    assert task_admission_barrier(tmp_path, "web_chat") is not None
    assert task_admission_barrier(tmp_path, "web_chat_stream") is not None
    assert task_admission_barrier(tmp_path, "web_queue_dispatch") is not None
    assert task_admission_barrier(tmp_path, "web_schedule_wake") is not None
    # 依赖范围属性：learning 不依赖 web 进程，feishu 同理——不外溢
    assert task_admission_barrier(tmp_path, "learning_job") is None
    assert task_admission_barrier(tmp_path, "feishu_message") is None


def test_learning_barrier_scopes_to_learning_jobs(tmp_path: Path) -> None:
    AdmissionBarrierRegistry(tmp_path).establish("learning", operation_id="op-l")
    barrier = task_admission_barrier(tmp_path, "learning_job")
    assert barrier is not None
    assert barrier.operation_id == "op-l"
    assert task_admission_barrier(tmp_path, "web_chat") is None
    assert task_admission_barrier(tmp_path, "feishu_message") is None


def test_no_barrier_means_idle(tmp_path: Path) -> None:
    assert task_admission_barrier(tmp_path, "web_chat") is None
    assert task_admission_barrier(tmp_path, "learning_job") is None
