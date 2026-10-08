"""service_control_state DRC T2 durability 故障注入测试.

对齐 tests/unit/test_schedule_durability.py 的两阶段语义验证（复用
ScheduleStore durability contract，DESIGN-20261007-durable-run-contract）：
  replace 前=definitely_not_committed（旧状态全文保留，无 tmp 残留）；
  replace 后目录 fsync 耗尽=commit_outcome_uncertain（磁盘已是新内容，
  expected_sha256/visible_state 逐字 readback，禁止第二次 rewrite/rename）。
"""

import hashlib
import json
from pathlib import Path

import pytest

import llm_loop.runtime.service_control as sc
from llm_loop.runtime.service_control import (
    DeploymentGenerationConflictError,
    ManagedServiceDeployment,
    ManagedServiceDeploymentStore,
)


def _deployment(tmp_path: Path, *, generation: int = 1) -> ManagedServiceDeployment:
    code_root = (tmp_path / "code").resolve()
    runtime_root = (tmp_path / "runtime-root").resolve()
    code_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    return ManagedServiceDeployment(
        schema="managed-service-deployment/v1",
        deployment_id=f"deploy-{generation}",
        generation=generation,
        git_head="a" * 40,
        code_root=str(code_root),
        runtime_root=str(runtime_root),
        webui_artifact_sha256="b" * 64,
    )


def _expected_payload(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _no_tmp_leftover(directory: Path) -> bool:
    return not list(directory.glob(".*.tmp"))


def test_atomic_json_normal_path_and_no_tmp_leftover(tmp_path):
    path = tmp_path / "state.json"
    sc._atomic_json(path, {"a": 1})
    assert path.read_text(encoding="utf-8") == _expected_payload({"a": 1})
    assert _no_tmp_leftover(tmp_path)


def test_fault_before_replace_is_definitely_not_committed(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    old_payload = _expected_payload({"a": "old"})
    path.write_text(old_payload, encoding="utf-8")

    calls = {"n": 0}
    real_replace = sc.os.replace

    def boom(src, dst, *args, **kwargs):
        if Path(dst) == path:
            calls["n"] += 1
            raise OSError("replace boom")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(sc.os, "replace", boom)

    with pytest.raises(sc.ServiceControlPersistError) as caught:
        sc._atomic_json(path, {"a": "new"})

    assert caught.value.outcome == "definitely_not_committed"
    # 旧状态全文保留；有界重试后放弃；无 tmp 残留。
    assert path.read_text(encoding="utf-8") == old_payload
    assert calls["n"] == sc._STATE_PERSIST_ATTEMPTS
    assert _no_tmp_leftover(tmp_path)


def test_dir_fsync_exhaustion_is_uncertain_and_does_not_rewrite(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text(_expected_payload({"a": "old"}), encoding="utf-8")

    real_write = sc._write_temp_exclusive
    real_replace = sc.os.replace
    writes = {"n": 0}
    replaces = {"n": 0}

    def counted_write(temp: Path, text: str) -> None:
        writes["n"] += 1
        real_write(temp, text)

    def counted_replace(src, dst, *args, **kwargs):
        if Path(dst) == path:
            replaces["n"] += 1
        return real_replace(src, dst, *args, **kwargs)

    def fail_dir_fsync(directory: Path) -> None:
        raise OSError("dir fsync boom")

    monkeypatch.setattr(sc, "_write_temp_exclusive", counted_write)
    monkeypatch.setattr(sc.os, "replace", counted_replace)
    monkeypatch.setattr(sc, "_fsync_directory", fail_dir_fsync)

    with pytest.raises(sc.ServiceControlCommitUncertainError) as caught:
        sc._atomic_json(path, {"a": "new"})

    payload = _expected_payload({"a": "new"})
    assert caught.value.outcome == "commit_outcome_uncertain"
    assert caught.value.visible_state == "matches"
    assert caught.value.expected_sha256 == hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()
    # replace 已生效：磁盘是新内容；replace 后绝不第二次 rewrite/rename。
    assert path.read_text(encoding="utf-8") == payload
    assert writes["n"] == 1
    assert replaces["n"] == 1
    assert _no_tmp_leftover(tmp_path)


def test_transient_pre_replace_failure_recovers_within_retry_budget(
    tmp_path, monkeypatch
):
    path = tmp_path / "state.json"
    real_write = sc._write_temp_exclusive
    flaky_state = {"n": 0}

    def flaky_write(temp: Path, text: str) -> None:
        flaky_state["n"] += 1
        if flaky_state["n"] <= 2:
            raise OSError("transient write boom")
        real_write(temp, text)

    monkeypatch.setattr(sc, "_write_temp_exclusive", flaky_write)

    sc._atomic_json(path, {"a": "recovered"})

    assert path.read_text(encoding="utf-8") == _expected_payload({"a": "recovered"})
    assert flaky_state["n"] == 3
    assert _no_tmp_leftover(tmp_path)


def test_uncertain_readback_unreadable_is_reported(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text(_expected_payload({"a": "old"}), encoding="utf-8")

    def fail_dir_fsync(directory: Path) -> None:
        raise OSError("dir fsync boom")

    real_read_text = Path.read_text

    def boom_read_text(self, *args, **kwargs):
        if self == path:
            raise OSError("read boom")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(sc, "_fsync_directory", fail_dir_fsync)
    monkeypatch.setattr(Path, "read_text", boom_read_text)

    with pytest.raises(sc.ServiceControlCommitUncertainError) as caught:
        sc._atomic_json(path, {"a": "new"})

    assert caught.value.visible_state == "unreadable"
    assert caught.value.outcome == "commit_outcome_uncertain"


def test_cas_pre_replace_failure_keeps_old_generation(tmp_path, monkeypatch):
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    first = _deployment(tmp_path, generation=1)
    store.compare_and_swap(first, expected_generation=0)
    real_replace = sc.os.replace

    def boom(src, dst, *args, **kwargs):
        if Path(dst) == store.path:
            raise OSError("replace boom")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(sc.os, "replace", boom)

    second = _deployment(tmp_path, generation=2)
    with pytest.raises(sc.ServiceControlPersistError) as caught:
        store.compare_and_swap(second, expected_generation=1)

    assert caught.value.outcome == "definitely_not_committed"
    assert store.read().generation == 1
    assert store.read().deployment_id == first.deployment_id


def test_cas_uncertain_advances_file_and_blocks_blind_replay(tmp_path, monkeypatch):
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_deployment(tmp_path, generation=1), expected_generation=0)

    def fail_dir_fsync(directory: Path) -> None:
        raise OSError("dir fsync boom")

    monkeypatch.setattr(sc, "_fsync_directory", fail_dir_fsync)

    second = _deployment(tmp_path, generation=2)
    with pytest.raises(sc.ServiceControlCommitUncertainError) as caught:
        store.compare_and_swap(second, expected_generation=1)

    assert caught.value.visible_state == "matches"
    # replace 已生效：磁盘已推进到 gen2；按旧代盲重放被 CAS 机械拒绝。
    assert store.read().generation == 2
    with pytest.raises(DeploymentGenerationConflictError):
        store.compare_and_swap(second, expected_generation=1)


def _store_with_accepted_web_action(
    tmp_path: Path,
) -> tuple[ManagedServiceDeploymentStore, sc.ServiceControlAction]:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_deployment(tmp_path, generation=1), expected_generation=0)
    action = store.accept_restart(
        target="web",
        expected_generation=1,
        requester_session_id="durability-probe",
    )
    assert store.barriers.blocked("web") is not None
    return store, action


def _fail_action_dir_fsync(
    store: ManagedServiceDeploymentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_fsync = sc._fsync_directory

    def fail(directory: Path) -> None:
        if Path(directory) == store.actions_dir:
            raise OSError("action directory fsync boom")
        real_fsync(directory)

    monkeypatch.setattr(sc, "_fsync_directory", fail)


def test_action_succeeded_uncertain_matches_reconciles_and_releases_barrier(
    tmp_path, monkeypatch
):
    """Action visible_state=matches 时必须继续 terminal barrier release."""
    store, action = _store_with_accepted_web_action(tmp_path)
    _fail_action_dir_fsync(store, monkeypatch)
    emitted: list[str] = []
    monkeypatch.setattr(
        sc,
        "_emit_terminal_event",
        lambda _store, terminal: emitted.append(terminal.action_id),
    )

    updated = store.update_action(action.action_id, status="succeeded")

    assert updated.status == "succeeded"
    assert store.read_action(action.action_id).status == "succeeded"
    assert store.barriers.blocked("web") is None
    assert emitted == [action.action_id]


def test_action_failed_uncertain_matches_reconciles_and_releases_pre_run_barrier(
    tmp_path, monkeypatch
):
    """accepted→failed 尚无物理副作用，uncertain exact-match 后仍须释放 barrier."""
    store, action = _store_with_accepted_web_action(tmp_path)
    _fail_action_dir_fsync(store, monkeypatch)

    updated = store.update_action(action.action_id, status="failed", detail="pre-run reject")

    assert updated.status == "failed"
    assert store.read_action(action.action_id).status == "failed"
    assert store.barriers.blocked("web") is None


def test_action_running_to_failed_uncertain_matches_keeps_barrier_fail_closed(
    tmp_path, monkeypatch
):
    """running→failed 可能已有物理副作用；reconcile 后仍须保持 barrier."""
    store, action = _store_with_accepted_web_action(tmp_path)
    running = store.update_action(action.action_id, status="running")
    assert running.status == "running"
    _fail_action_dir_fsync(store, monkeypatch)

    updated = store.update_action(
        action.action_id,
        status="failed",
        detail="restart may have stopped a service",
    )

    assert updated.status == "failed"
    assert store.read_action(action.action_id).status == "failed"
    barrier = store.barriers.blocked("web")
    assert barrier is not None
    assert barrier.operation_id == action.action_id


def test_accept_restart_uncertain_matches_continues_to_establish_barrier(
    tmp_path, monkeypatch
):
    """accepted 文件已 exact-visible 时不得留下“action 有、barrier 无”的裂缝."""
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_deployment(tmp_path, generation=1), expected_generation=0)
    _fail_action_dir_fsync(store, monkeypatch)
    real_replace = sc.os.replace
    action_replaces: list[Path] = []

    def counted_replace(src, dst, *args, **kwargs):
        if Path(dst).parent == store.actions_dir:
            action_replaces.append(Path(dst))
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(sc.os, "replace", counted_replace)

    action = store.accept_restart(
        target="web",
        expected_generation=1,
        requester_session_id="durability-probe",
    )

    assert store.read_action(action.action_id) == action
    barrier = store.barriers.blocked("web")
    assert barrier is not None
    assert barrier.operation_id == action.action_id
    assert action_replaces == [store.action_path(action.action_id)]


def test_accept_restart_uncertain_nonmatching_state_stays_fail_closed(
    tmp_path, monkeypatch
):
    """readback 非 matches 时不得建立 barrier 或继续 action 生命周期."""
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_deployment(tmp_path, generation=1), expected_generation=0)
    _fail_action_dir_fsync(store, monkeypatch)
    monkeypatch.setattr(sc, "_payload_visible_state", lambda path, payload: "mismatch")

    with pytest.raises(sc.ServiceControlCommitUncertainError) as caught:
        store.accept_restart(
            target="web",
            expected_generation=1,
            requester_session_id="durability-probe",
        )

    assert caught.value.visible_state == "mismatch"
    assert store.barriers.blocked("web") is None
