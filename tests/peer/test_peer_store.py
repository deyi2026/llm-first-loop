"""存储层行为：并发不丢更新、CAS、幂等、fail-closed、密钥权限。"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from llm_loop.peer.admission import AdmissionStore
from llm_loop.peer.errors import InvalidTaskTransitionError, PeerError
from llm_loop.peer.models import (
    AdmissionRecord,
    GrantRecord,
    NodeRecord,
    TaskRecord,
    iso,
    now_local,
)
from llm_loop.peer.store import PeerStore

NOW = iso(now_local())


def _node(node_id: str) -> NodeRecord:
    return NodeRecord(node_id, "d", "executor", "http://127.0.0.1:8903", "none", "paired", NOW)


def _grant(grant_id: str = "g1", *, max_tasks_total: int = 2) -> GrantRecord:
    return GrantRecord(
        grant_id,
        "n1",
        {"human_id": "h", "channel": "web"},
        NOW,
        "2030-01-01T00:00:00Z",
        "active",
        ("fs.read",),
        ("/",),
        1,
        max_tasks_total,
    )


def _task(task_id: str = "task-1", *, state: str = "submitted") -> TaskRecord:
    return TaskRecord(
        task_id,
        f"eff-{task_id}",
        "n1",
        "fs.read",
        {"path": "/tmp/x"},
        (),
        30,
        state,
        "idempotent",
        False,
        NOW,
        NOW,
    )


def test_concurrent_writes_lose_nothing(tmp_path: Path) -> None:
    store = PeerStore(tmp_path / "peer")

    def worker(tag: str) -> None:
        for index in range(10):
            store.upsert_node(_node(f"{tag}-{index}"))

    threads = [threading.Thread(target=worker, args=(f"w{num}",)) for num in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(store.list_nodes()) == 40
    assert store.generation("nodes") == 40


def test_consume_grant_cas_and_exhaustion(tmp_path: Path) -> None:
    store = PeerStore(tmp_path / "peer")
    store.upsert_node(_node("n1"))
    store.issue_grant(_grant())
    assert store.consume_grant("g1", expected_tasks_used=0).tasks_used == 1
    with pytest.raises(PeerError) as stale:
        store.consume_grant("g1", expected_tasks_used=0)
    assert stale.value.reason_code == "idempotency_conflict"
    assert store.consume_grant("g1", expected_tasks_used=1).tasks_used == 2
    with pytest.raises(PeerError) as exhausted:
        store.consume_grant("g1", expected_tasks_used=2)
    assert exhausted.value.reason_code == "grant_exhausted"


def test_duplicate_grant_rejected(tmp_path: Path) -> None:
    store = PeerStore(tmp_path / "peer")
    store.issue_grant(_grant())
    with pytest.raises(PeerError) as conflict:
        store.issue_grant(_grant())
    assert conflict.value.reason_code == "idempotency_conflict"


def test_task_state_machine_and_cas(tmp_path: Path) -> None:
    store = PeerStore(tmp_path / "peer")
    store.put_task(_task())
    running = store.put_task(_task(state="admitted"), expected_state="submitted")
    assert running.state == "admitted"
    with pytest.raises(PeerError) as stale:
        store.put_task(_task(state="queued"), expected_state="submitted")
    assert stale.value.reason_code == "idempotency_conflict"
    store.put_task(_task(state="queued"), expected_state="admitted")
    store.put_task(_task(state="running"), expected_state="queued")
    done = store.put_task(_task(state="succeeded"), expected_state="running")
    assert done.state == "succeeded"
    with pytest.raises(PeerError):
        store.put_task(_task(state="running"), expected_state="succeeded")


def test_illegal_transition_is_program_error(tmp_path: Path) -> None:
    store = PeerStore(tmp_path / "peer")
    store.put_task(_task())
    with pytest.raises(InvalidTaskTransitionError):
        store.put_task(_task(state="succeeded"), expected_state="submitted")


def test_admission_is_immutable(tmp_path: Path) -> None:
    store = PeerStore(tmp_path / "peer")
    admissions = AdmissionStore(tmp_path / "peer")
    record = AdmissionRecord("adm-1", "task-1", "n1", "fs.read", "eff-1", "denied", NOW, "d" * 64)
    assert admissions.write(record) == record
    assert admissions.get_by_task("task-1") == record
    assert admissions.get("adm-1") == record
    tampered = AdmissionRecord("adm-2", "task-1", "n1", "fs.read", "eff-1", "admitted", NOW, "d" * 64)
    with pytest.raises(PeerError) as conflict:
        admissions.write(tampered)
    assert conflict.value.reason_code == "idempotency_conflict"
    assert admissions.get_by_task("task-1").verdict == "denied"
    assert store.get_task("task-1") is None


def test_corrupt_admission_record_fails_closed_without_leaking_path(tmp_path: Path) -> None:
    admissions = AdmissionStore(tmp_path / "peer")
    path = admissions.dir / "task-corrupt.json"
    path.write_text('{"admission_id": "adm-1"}', encoding="utf-8")
    with pytest.raises(PeerError) as caught:
        admissions.get_by_task("task-corrupt")
    assert caught.value.reason_code == "executor_internal_error"
    assert str(tmp_path) not in caught.value.detail


def test_unreadable_admission_record_does_not_leak_path(tmp_path: Path) -> None:
    """read_text 抛 OSError 的分支：detail 只带类型名，不带本地路径。

    这条钉的是"泄露"本身——把 detail 改回 f"...{exc}" 时 IsADirectoryError 的
    错误串含绝对路径，本用例必红。
    """
    admissions = AdmissionStore(tmp_path / "peer")
    (admissions.dir / "task-dir.json").mkdir()
    with pytest.raises(PeerError) as caught:
        admissions.get_by_task("task-dir")
    assert caught.value.reason_code == "executor_internal_error"
    assert "IsADirectoryError" in caught.value.detail
    assert str(tmp_path) not in caught.value.detail


def test_corrupt_doc_fails_closed(tmp_path: Path) -> None:
    store = PeerStore(tmp_path / "peer")
    (tmp_path / "peer" / "tasks.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(PeerError) as broken:
        store.list_tasks()
    assert broken.value.reason_code == "executor_internal_error"


def test_secret_file_mode_is_0600(tmp_path: Path) -> None:
    store = PeerStore(tmp_path / "peer")
    store.write_secret("n1", "s" * 32)
    mode = (tmp_path / "peer" / "secrets" / "n1.key").stat().st_mode & 0o777
    assert mode == 0o600
    assert store.read_secret("n1") == "s" * 32
    assert store.read_secret("n2") is None


def test_unknown_doc_name_rejected(tmp_path: Path) -> None:
    store = PeerStore(tmp_path / "peer")
    with pytest.raises(ValueError):
        store.generation("secrets")


def test_doc_payload_has_generation(tmp_path: Path) -> None:
    PeerStore(tmp_path / "peer")
    payload = json.loads((tmp_path / "peer" / "nodes.json").read_text(encoding="utf-8"))
    assert payload == {"schema": "lfl.peer.v1", "generation": 0, "items": []}


def test_put_task_max_running_rejects_when_slot_taken(tmp_path: Path) -> None:
    """配额裁决下沉到锁内：已有 1 个未终局任务时，第 2 个提交必须被拒。"""
    store = PeerStore(tmp_path / "peer")
    store.upsert_node(_node("n1"))
    store.put_task(_task("task-1"))
    store.put_task(_task("task-1", state="admitted"), expected_state="submitted")

    with pytest.raises(PeerError) as denied:
        store.put_task(_task("task-2"), max_running=1)
    assert denied.value.reason_code == "quota_concurrency_exceeded"
    assert store.get_task("task-2") is None


def test_put_task_max_running_is_atomic_under_concurrency(tmp_path: Path) -> None:
    """换成"先 count 再 put"的实现时，本用例会放进 2 个以上（8 线程只有 1 个名额）。"""
    store = PeerStore(tmp_path / "peer")
    store.upsert_node(_node("n1"))
    outcomes: list[str] = []
    guard = threading.Lock()

    def worker(index: int) -> None:
        try:
            store.put_task(_task(f"task-{index}"), max_running=1)
        except PeerError as exc:
            result = exc.reason_code
        else:
            result = "admitted"
        with guard:
            outcomes.append(result)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("admitted") == 1
    assert outcomes.count("quota_concurrency_exceeded") == 7
    assert len(store.list_tasks(node_id="n1")) == 1
