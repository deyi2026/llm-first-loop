"""Offline A2A Task CAS: no Huawei platform, provider or production session."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from llm_loop.web import a2a_task_admission as admission
from llm_loop.web.a2a_task_admission import (
    A2aAdmissionCommitUncertainError,
    A2aAdmissionConflictError,
    A2aAdmissionDeniedError,
    A2aAdmissionUnavailableError,
    A2aTaskAdmissionStore,
    A2aTaskIngress,
)


def ingress(
    *,
    task: str = "task-a",
    principal: str = "verified-host-A",
    workspace: str = "workspace-a",
    payload: bytes = b"exact original message bytes",
) -> A2aTaskIngress:
    return A2aTaskIngress(
        task_id=task,
        principal_id=principal,
        context_id="ctx-1",
        client_session_id="client-1",
        agent_id="lfl-agent",
        workspace_scope=workspace,
        payload=payload,
    )


def test_first_reservation_is_durable_immutable_and_private(tmp_path: Path):
    store = A2aTaskAdmissionStore(tmp_path)
    request = ingress(payload="精确中文内容".encode())
    created = store.reserve(request)
    assert created.newly_reserved is True
    assert created.durable_record_confirmed
    assert created.request_sha256 == request.frozen()["request_sha256"]
    assert store.hydrate(request.task_id, request.principal_id, request.workspace_scope) == request.payload
    assert len(created.receipt_id) == 64
    assert created.as_arkts_contract() == {
        "taskId": request.task_id,
        "principalId": request.principal_id,
        "requestSha256": created.request_sha256,
        "receiptId": created.receipt_id,
        "newlyReserved": True,
        "durableRecordConfirmed": True,
    }
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
    source, lock = store._paths(request.task_id)
    assert stat.S_IMODE(source.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600
    assert not any(x.suffix == ".tmp" for x in store.directory.iterdir())


def test_restart_exact_duplicate_never_allows_new_human_turn(tmp_path: Path):
    old = A2aTaskAdmissionStore(tmp_path)
    first = old.reserve(ingress())
    new_instance = A2aTaskAdmissionStore(tmp_path)
    second = new_instance.reserve(ingress())
    assert second.newly_reserved is False
    assert second.receipt_id == first.receipt_id
    assert second.as_arkts_contract()["newlyReserved"] is False
    assert new_instance.hydrate("task-a", "verified-host-A", "workspace-a") == ingress().payload


@pytest.mark.parametrize(
    "change",
    [
        {"payload": b"different"},
        {"principal": "other-principal"},
        {"workspace": "other-workspace"},
        {"task": "same-context-new-task"},
    ],
)
def test_frozen_identity_rejects_changes_to_existing_task(tmp_path: Path, change):
    store = A2aTaskAdmissionStore(tmp_path)
    store.reserve(ingress())
    if "task" in change:
        # A different taskId is a different task; never aliases the original.
        fresh = store.reserve(ingress(**change))
        assert fresh.newly_reserved
    else:
        with pytest.raises(A2aAdmissionConflictError):
            store.reserve(ingress(**change))


def test_hydration_never_crosses_principal_or_workspace(tmp_path: Path):
    store = A2aTaskAdmissionStore(tmp_path)
    store.reserve(ingress(payload=b"private full payload"))
    with pytest.raises(A2aAdmissionDeniedError):
        store.hydrate("task-a", "other-principal", "workspace-a")
    with pytest.raises(A2aAdmissionDeniedError):
        store.hydrate("task-a", "verified-host-A", "other-workspace")
    assert store.hydrate("task-a", "verified-host-A", "workspace-a") == b"private full payload"


def test_ingress_repr_does_not_log_private_human_payload():
    request = ingress(payload=b"private-opaque-message-not-for-log")
    assert b"private-opaque-message-not-for-log".decode() not in repr(request)


def test_conflicting_payload_detected_without_replacing_root(tmp_path: Path):
    store = A2aTaskAdmissionStore(tmp_path)
    store.reserve(ingress())
    before = store._paths("task-a")[0].read_bytes()
    with pytest.raises(A2aAdmissionConflictError):
        store.reserve(ingress(payload=b"different"))
    assert store._paths("task-a")[0].read_bytes() == before


def test_corrupt_root_denies_mutation_and_cannot_reset_after_restart(tmp_path: Path):
    store = A2aTaskAdmissionStore(tmp_path)
    store.reserve(ingress())
    root, _ = store._paths("task-a")
    root.write_bytes(b'{"corrupted":"not a valid admission"}')
    with pytest.raises(A2aAdmissionUnavailableError):
        A2aTaskAdmissionStore(tmp_path).reserve(ingress())
    with pytest.raises(A2aAdmissionUnavailableError):
        store.hydrate("task-a", "verified-host-A", "workspace-a")


def test_tampered_hash_and_untrusted_symlink_deny_without_read(tmp_path: Path):
    store = A2aTaskAdmissionStore(tmp_path)
    store.reserve(ingress())
    root, _ = store._paths("task-a")
    content = json.loads(root.read_text())
    content["request_sha256"] = "0" * 64
    root.write_text(json.dumps(content))
    with pytest.raises(A2aAdmissionUnavailableError):
        store.reserve(ingress())

    root.unlink()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"should never be opened or overwritten")
    root.symlink_to(outside)
    with pytest.raises(A2aAdmissionUnavailableError):
        store.reserve(ingress())
    assert outside.read_bytes() == b"should never be opened or overwritten"


def test_noncanonical_record_and_hardlinked_file_fail_closed(tmp_path: Path):
    store = A2aTaskAdmissionStore(tmp_path)
    store.reserve(ingress())
    root, _ = store._paths("task-a")
    # A valid semantic JSON row is not evidence that it is the exact receipt
    # bytes previously durably committed.
    row = json.loads(root.read_text())
    root.write_text(json.dumps(row, indent=2))
    with pytest.raises(A2aAdmissionUnavailableError):
        store.reserve(ingress())

    root.unlink()
    outside = tmp_path / "hidden-link"
    outside.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    outside.chmod(0o600)
    os.link(outside, root)
    with pytest.raises(A2aAdmissionUnavailableError):
        store.reserve(ingress())


def test_post_link_directory_fsync_failure_is_uncertain_and_never_grants_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    store = A2aTaskAdmissionStore(tmp_path)
    original_fsync = admission._fsync_directory

    def fail(directory):
        if directory == store.directory:
            raise OSError("injected authoritative record durability failure")
        return original_fsync(directory)

    with monkeypatch.context() as scope:
        scope.setattr(admission, "_fsync_directory", fail)
        with pytest.raises(A2aAdmissionCommitUncertainError) as error:
            store.reserve(ingress())
    assert error.value.retry_safe is False
    assert A2aTaskAdmissionStore(tmp_path).reserve(ingress()).newly_reserved is False
    assert store.hydrate("task-a", "verified-host-A", "workspace-a") == ingress().payload


def test_existing_root_must_pass_directory_durability_fence(tmp_path: Path, monkeypatch):
    store = A2aTaskAdmissionStore(tmp_path)
    store.reserve(ingress())
    original = admission._fsync_directory

    def reject_root(directory):
        if directory == store.directory:
            raise OSError("injected existing root fence failure")
        return original(directory)

    with monkeypatch.context() as scope:
        scope.setattr(admission, "_fsync_directory", reject_root)
        with pytest.raises(A2aAdmissionCommitUncertainError):
            store.reserve(ingress())
    assert store.reserve(ingress()).newly_reserved is False


def test_invalid_or_oversize_ingress_fails_without_creating_records(tmp_path: Path):
    store = A2aTaskAdmissionStore(tmp_path)
    cases = [
        ingress(payload=b""),
        ingress(payload=b"x" * (admission.MAX_INGRESS_BYTES + 1)),
        ingress(task="../path-traversal"),
        ingress(principal=""),
    ]
    for value in cases[:2] + cases[3:]:
        with pytest.raises(A2aAdmissionDeniedError):
            store.reserve(value)
    # A taskId containing slashes is valid opaque data, but can never alter
    # the hashed filename/location or escape the store.
    escaped = store.reserve(cases[2])
    assert escaped.newly_reserved
    assert set(store.directory.glob("task-*.json")) == {store._paths("../path-traversal")[0]}


def test_concurrent_thread_reserve_has_exactly_one_winner(tmp_path: Path):
    store = A2aTaskAdmissionStore(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outputs = list(pool.map(lambda _: store.reserve(ingress()), range(16)))
    assert sum(row.newly_reserved for row in outputs) == 1
    assert len({row.receipt_id for row in outputs}) == 1


def test_process_restart_and_multiprocess_reservation_one_winner(tmp_path: Path):
    script = (
        "import json,sys;"
        "from llm_loop.web.a2a_task_admission import A2aTaskAdmissionStore,A2aTaskIngress;"
        "r=A2aTaskAdmissionStore(sys.argv[1]).reserve("
        "A2aTaskIngress('task-multi','host-A','ctx','client','agent','workspace',b'payload'));"
        "print(json.dumps({'new':r.newly_reserved,'receipt':r.receipt_id}))"
    )
    # Shell-free subprocess, project interpreter, no provider or network.
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[2] / "src")},
        )
        for _ in range(5)
    ]
    rows = []
    for proc in procs:
        stdout, stderr = proc.communicate(timeout=20)
        assert proc.returncode == 0, stderr
        rows.append(json.loads(stdout))
    assert sum(row["new"] for row in rows) == 1
    assert len({row["receipt"] for row in rows}) == 1
    assert A2aTaskAdmissionStore(tmp_path).hydrate(
        "task-multi", "host-A", "workspace"
    ) == b"payload"
