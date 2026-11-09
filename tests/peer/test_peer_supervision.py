"""T9-b 监督通道：宣告条件、等待态无副作用、票据一次性/绑定/时效、确认与拒绝。

口径（DESIGN-20261108 §2）：
- 宣告三条件（开关 + 写域 + 通道可用）未同时成立时，fs.write 不出现在 manifest；
- 提交只落 waiting，不执行、不消耗额度；
- 每次执行都需要一张绑定参数摘要的一次性票据，执行前重判租户/额度/路径；
- 拒绝/过期/重放都必须给出可判定的 reason_code。
"""

from __future__ import annotations

import base64
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from llm_loop.peer.admission import AdmissionStore
from llm_loop.peer.artifacts import ArtifactStore
from llm_loop.peer.errors import PeerError
from llm_loop.peer.models import GrantRecord, TaskRecord, iso, now_local
from llm_loop.peer.service import PeerService
from llm_loop.peer.store import PeerStore

REPO = Path(__file__).resolve().parents[2]
NODE = "deepin-01"
GRANT_ID = "gr_SUP00000001"


def _env(tmp_path: Path, *, write_root: str | None = "", ttl: int = 60, clock=now_local):
    root = tmp_path / "wr"
    root.mkdir(exist_ok=True)
    store = PeerStore(tmp_path / "peer")
    service = PeerService(
        store=store,
        admissions=AdmissionStore(tmp_path / "peer"),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        node_id=NODE,
        write_root=str(root) if write_root == "" else write_root,
        supervision_enabled=True,
        supervision_ttl_s=ttl,
        clock=clock,
    )
    return service, store, root


def _grant(root: Path, **overrides) -> GrantRecord:
    base = dict(
        grant_id=GRANT_ID,
        node_id=NODE,
        issued_by={"ingress": "feishu", "human": "lfl"},
        issued_at=iso(now_local()),
        expires_at=iso(now_local() + timedelta(hours=1)),
        state="active",
        allowed_kinds=("fs.read", "fs.list", "fs.write"),
        allowed_paths=(str(root),),
        max_concurrency=2,
        max_tasks_total=5,
    )
    base.update(overrides)
    return GrantRecord(**base)


def _write_payload(root: Path, *, effect_id: str = "eff_w0000001", content: bytes = b"hello"):
    return {
        "schema": "lfl.peer.v1",
        "effect_id": effect_id,
        "kind": "fs.write",
        "params": {
            "path": str(root / "out.txt"),
            "content_b64": base64.b64encode(content).decode(),
        },
        "deadline_s": 30,
    }


def _held(env):
    service, store, root = env
    store.issue_grant(_grant(root))
    receipt = service.submit(_write_payload(root))
    assert receipt["state"] == "awaiting_supervision"
    return service, store, root, receipt["task_id"]


# ---- 宣告条件 --------------------------------------------------------------
def test_write_is_not_advertised_without_supervision(tmp_path):
    service, store, root = _env(tmp_path)
    service._supervision_enabled = False
    assert "fs.write" not in {k["kind"] for k in service.manifest()["kinds"]}


def test_write_is_not_advertised_without_write_root(tmp_path):
    service, _store, _root = _env(tmp_path, write_root=None)
    assert "fs.write" not in {k["kind"] for k in service.manifest()["kinds"]}


def test_write_advertised_when_three_conditions_hold(tmp_path):
    service, _store, _root = _env(tmp_path)
    assert "fs.write" in {k["kind"] for k in service.manifest()["kinds"]}


# ---- 准入与等待态 ----------------------------------------------------------
def test_write_without_supervision_is_denied(tmp_path):
    service, store, root = _env(tmp_path)
    service._supervision_enabled = False
    store.issue_grant(_grant(root))
    receipt = service.submit(_write_payload(root))
    assert receipt["state"] == "denied"
    assert receipt["reason_code"] == "requires_supervised_execution"
    assert not (root / "out.txt").exists()


def test_held_task_has_no_side_effect_and_no_quota_charge(tmp_path):
    service, store, root, task_id = _held(_env(tmp_path))
    assert not (root / "out.txt").exists()
    assert store.get_grant(GRANT_ID).tasks_used == 0
    rows = service.list_supervised()
    assert [r["task_id"] for r in rows] == [task_id]
    assert rows[0]["remaining_s"] > 0


# ---- 票据：缺失 / 重放 / 篡改 / 时效 ---------------------------------------
def test_resume_without_ticket_fails_closed(tmp_path):
    service, _store, root, task_id = _held(_env(tmp_path))
    receipt = service.resume_supervised(task_id, decided_by="tester")
    assert receipt["state"] == "failed"
    assert receipt["reason_code"] == "supervision_ticket_missing"
    assert not (root / "out.txt").exists()


def test_ticket_is_single_use(tmp_path):
    service, store, root, task_id = _held(_env(tmp_path))
    service.issue_supervision_ticket(task_id, issued_by="tester")
    receipt = service.resume_supervised(task_id, decided_by="tester")
    assert receipt["state"] == "succeeded"
    assert (root / "out.txt").read_bytes() == b"hello"
    assert store.get_grant(GRANT_ID).tasks_used == 1

    digest = store.get_task(task_id).params_digest
    with pytest.raises(PeerError) as err:
        service._operator.consume(task_id, params_digest=digest)
    assert err.value.reason_code == "supervision_ticket_consumed"


def test_ticket_bound_to_params_digest(tmp_path, monkeypatch):
    service, store, _root, task_id = _held(_env(tmp_path))
    service.issue_supervision_ticket(task_id, issued_by="tester")
    original = store.get_task(task_id)
    monkeypatch.setattr(
        service, "_get_waiting", lambda _tid: replace(original, params_digest="0" * 64)
    )
    receipt = service.resume_supervised(task_id, decided_by="tester")
    assert receipt["state"] == "failed"
    assert receipt["reason_code"] == "supervision_ticket_mismatch"


def test_expired_ticket_is_rejected(tmp_path):
    now = [now_local()]
    env = _env(tmp_path, ttl=60, clock=lambda: now[0])
    service, store, _root, task_id = _held(env)
    service.issue_supervision_ticket(task_id, issued_by="tester")
    now[0] += timedelta(seconds=120)
    with pytest.raises(PeerError) as err:
        service._operator.consume(task_id, params_digest=store.get_task(task_id).params_digest)
    assert err.value.reason_code == "supervision_ticket_expired"


def test_task_waiting_past_ttl_converges_to_timeout(tmp_path):
    now = [now_local()]
    env = _env(tmp_path, ttl=1, clock=lambda: now[0])
    service, _store, _root, task_id = _held(env)
    now[0] += timedelta(seconds=2)
    receipt = service.resume_supervised(task_id, decided_by="tester")
    assert receipt["state"] == "failed"
    assert receipt["reason_code"] == "supervision_timeout"


# ---- 拒绝 / 中断恢复 ------------------------------------------------------
def test_reject_converges_to_denied_without_execution(tmp_path):
    service, store, root, task_id = _held(_env(tmp_path))
    receipt = service.reject_supervised(task_id, decided_by="tester")
    assert receipt["state"] == "denied"
    assert receipt["reason_code"] == "execution_not_authorized"
    assert not (root / "out.txt").exists()
    assert store.get_grant(GRANT_ID).tasks_used == 0


def test_recover_keeps_waiting_across_restart(tmp_path):
    """DESIGN D2：等待态在副作用之前，重启保留等待，不判成结果不明/失败。

    保留等待才让人回来点确认仍然有效；收敛责任在 TTL（下一个用例）。
    """
    service, store, root, task_id = _held(_env(tmp_path))
    recovered = service.recover_interrupted()
    assert recovered == []
    assert store.get_task(task_id).state == "awaiting_supervision"
    assert not (root / "out.txt").exists()


def test_expire_supervision_converges_waiting_even_when_disabled(tmp_path):
    """TTL 收尾不依赖开关：关掉 --supervision 也要把旧等待态收干净（P2-4）。"""
    now = [now_local()]
    env = _env(tmp_path, ttl=1, clock=lambda: now[0])
    service, store, _root, task_id = _held(env)
    service._supervision_enabled = False  # 模拟重启后没带 --supervision
    now[0] += timedelta(seconds=2)
    expired = service.expire_supervision()
    assert expired == [task_id]
    assert store.get_task(task_id).state == "failed"


def test_expire_skips_task_concurrently_admitted(tmp_path, monkeypatch):
    """确认与 TTL 收尾竞争：确认先赢时 expire 不覆盖、不抛错（P2-4 并发面）。"""
    now = [now_local()]
    env = _env(tmp_path, ttl=1, clock=lambda: now[0])
    service, store, _root, task_id = _held(env)
    stale = store.get_task(task_id)  # expire 先取到的旧快照
    store.put_task(
        stale.with_updates(state="admitted"),
        expected_state="awaiting_supervision",
    )
    monkeypatch.setattr(store, "list_tasks", lambda **_kw: [stale])
    now[0] += timedelta(seconds=2)
    assert service.expire_supervision() == []
    assert store.get_task(task_id).state == "admitted"


# ---- CLI：非 TTY 不得确认 --------------------------------------------------
def test_cli_confirm_refuses_without_tty(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "peer_operator.py"),
            "--data-dir",
            str(tmp_path),
            "--node-id",
            NODE,
            "--write-root",
            str(tmp_path),
            "confirm",
            "task_x",
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert proc.returncode == 2
    assert "TTY" in proc.stderr


def test_precheck_failure_keeps_ticket_and_waiting_state(tmp_path, monkeypatch):
    """重判失败不销毁授权：票据与等待态都还在，人工修好前提后可直接重试。"""
    service, store, _root, task_id = _held(_env(tmp_path))
    service.issue_supervision_ticket(task_id, issued_by="tester")

    def boom(**_kwargs):
        raise PeerError("executor_unhealthy", "injected precheck failure")

    monkeypatch.setattr("llm_loop.peer.service.precheck", boom)
    with pytest.raises(PeerError) as err:
        service.resume_supervised(task_id, decided_by="tester")
    assert err.value.reason_code == "executor_unhealthy"

    task = store.get_task(task_id)
    assert task is not None and task.state == "awaiting_supervision"
    ticket = service._operator.load(task_id, params_digest=task.params_digest or "")
    assert ticket.task_id == task_id


def test_update_to_running_respects_concurrency_in_store_lock(tmp_path):
    """P1-4：并发裁决必须在 store 同一临界区；更新分支也不能绕开 max_running。"""
    _service, store, root = _env(tmp_path)

    def task(tid: str) -> TaskRecord:
        return TaskRecord(
            tid,
            f"eff-{tid}",
            NODE,
            "fs.read",
            {"path": str(root / "x")},
            (),
            30,
            "submitted",
            "idempotent",
            False,
            iso(now_local()),
            iso(now_local()),
        )

    store.put_task(task("tsk_a"))
    a = store.put_task(task("tsk_a").with_updates(state="admitted"), expected_state="submitted")
    a = store.put_task(a.with_updates(state="queued"), expected_state="admitted")
    store.put_task(a.with_updates(state="running"), expected_state="queued")
    awaiting = store.put_task(task("tsk_b"), max_running=5)
    awaiting = store.put_task(
        awaiting.with_updates(state="awaiting_supervision"), expected_state="submitted"
    )
    with pytest.raises(PeerError) as err:
        store.put_task(
            awaiting.with_updates(state="admitted"),
            expected_state="awaiting_supervision",
            max_running=1,
        )
    assert err.value.reason_code == "quota_concurrency_exceeded"


def test_peer_serve_cli_wires_supervision_and_write_root():
    """serve 装配必须真的接上 write_root：F821/签名缺失会让 --supervision 起不来。"""
    import importlib.util
    import inspect
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "peer_serve_under_test", root / "scripts" / "peer_serve.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    params = set(inspect.signature(module.build_app).parameters)
    assert {"write_root", "supervision_enabled", "supervision_ttl_s"} <= params


def test_supervision_deadline_is_persisted_and_shared_across_cli_instances(tmp_path):
    now = [now_local()]
    env = _env(tmp_path, ttl=8, clock=lambda: now[0])
    service, store, root, task_id = _held(env)
    task = store.get_task(task_id)
    assert task is not None
    assert task.supervision_expires_at == iso(now[0] + timedelta(seconds=8))

    # The operator CLI constructs a fresh service whose default TTL is 300s.
    # It must use the task's persisted absolute deadline, not its own config.
    operator_service = PeerService(
        store=store,
        admissions=AdmissionStore(tmp_path / "peer"),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        node_id=NODE,
        write_root=str(root),
        supervision_enabled=True,
        supervision_ttl_s=300,
        clock=lambda: now[0],
    )
    row = operator_service.list_supervised()[0]
    assert row["expires_at"] == task.supervision_expires_at
    ticket = operator_service.issue_supervision_ticket(task_id, issued_by="tester")
    assert ticket.expires_at == task.supervision_expires_at

    now[0] += timedelta(seconds=9)
    receipt = operator_service.resume_supervised(task_id, decided_by="tester")
    assert receipt["state"] == "failed"
    assert receipt["reason_code"] == "supervision_timeout"
    assert not (root / "out.txt").exists()
    assert store.get_grant(GRANT_ID).tasks_used == 0


def test_supervision_deadline_is_capped_by_task_deadline(tmp_path):
    now = [now_local()]
    env = _env(tmp_path, ttl=60, clock=lambda: now[0])
    _service, store, _root, task_id = _held(env)
    task = store.get_task(task_id)
    assert task is not None
    assert task.supervision_expires_at == iso(now[0] + timedelta(seconds=30))


def test_legacy_waiting_task_without_persisted_deadline_fails_closed(tmp_path):
    service, store, root, task_id = _held(_env(tmp_path, ttl=60))
    task = store.get_task(task_id)
    assert task is not None
    # Simulate a JSON record written by a pre-upgrade wheel: the normal store
    # correctly rejects awaiting->awaiting as an illegal state transition.
    payload = store._read("tasks")  # noqa: SLF001 -- fixture for legacy persisted data
    for item in payload["items"]:
        if item.get("task_id") == task_id:
            item.pop("supervision_expires_at", None)
    store._write("tasks", payload)  # noqa: SLF001 -- test-only legacy fixture

    assert service.list_supervised() == []
    failed = store.get_task(task_id)
    assert failed is not None
    assert failed.state == "failed"
    assert failed.reason_code == "supervision_timeout"
    assert not (root / "out.txt").exists()
    assert store.get_grant(GRANT_ID).tasks_used == 0


def test_resume_rejects_ticket_expiry_different_from_task_deadline(tmp_path):
    import json

    service, store, root, task_id = _held(_env(tmp_path, ttl=60))
    service.issue_supervision_ticket(task_id, issued_by="tester")
    ticket_path = service._operator._path(task_id)  # noqa: SLF001
    raw = json.loads(ticket_path.read_text(encoding="utf-8"))
    raw["expires_at"] = iso(now_local() + timedelta(hours=1))
    ticket_path.write_text(json.dumps(raw), encoding="utf-8")

    receipt = service.resume_supervised(task_id, decided_by="tester")
    assert receipt["state"] == "failed"
    assert receipt["reason_code"] == "supervision_ticket_mismatch"
    assert not (root / "out.txt").exists()
    assert store.get_grant(GRANT_ID).tasks_used == 0


def test_legacy_wheel_serve_rejects_missing_supervision_and_write_capabilities(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "peer_serve_wheel_compat_test", REPO / "scripts" / "peer_serve.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class LegacyPeerService:
        def __init__(self, *, store, admissions, artifacts, node_id):
            self.node_id = node_id

    monkeypatch.setattr(module, "PeerService", LegacyPeerService)
    base = dict(store=object(), admissions=object(), artifacts=object(), node_id=NODE)
    assert module._construct_peer_service(**base, supervision_enabled=False) is not None

    for options in (
        {"supervision_enabled": True, "supervision_ttl_s": 8},
        {"write_root": "/tmp/qa-only"},
        {"display_name": "nondefault-label"},
        {"audit_watermark_pct": 80},
    ):
        with pytest.raises(PeerError) as error:
            module._construct_peer_service(**base, **options)
        assert error.value.reason_code == "executor_internal_error"
        assert "peer_runtime_incompatible" in error.value.detail


def test_legacy_kwargs_wheel_cannot_silently_ignore_supervision(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "peer_serve_kwargs_compat_test", REPO / "scripts" / "peer_serve.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class LegacyKwargsPeerService:
        def __init__(self, *, store, admissions, artifacts, node_id, **kwargs):
            self.ignored_kwargs = kwargs

    monkeypatch.setattr(module, "PeerService", LegacyKwargsPeerService)
    base = dict(store=object(), admissions=object(), artifacts=object(), node_id=NODE)
    assert module._construct_peer_service(**base, supervision_enabled=False) is not None
    for options in (
        {"supervision_enabled": True, "supervision_ttl_s": 8},
        {"write_root": "/tmp/qa-only"},
        {"enabled_kinds": {"read_file"}},
        {"max_concurrency": 2},
    ):
        with pytest.raises(PeerError) as error:
            module._construct_peer_service(**base, **options)
        assert error.value.reason_code == "executor_internal_error"
        assert "peer_runtime_incompatible" in error.value.detail


def test_legacy_wheel_operator_refuses_missing_supervision_api(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "peer_operator_wheel_compat_test", REPO / "scripts" / "peer_operator.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class LegacyPeerService:
        def __init__(self, *, store, admissions, artifacts, node_id):
            pass

    monkeypatch.setattr(module, "PeerService", LegacyPeerService)
    with pytest.raises(PeerError) as error:
        module._require_supervision_runtime()
    assert error.value.reason_code == "executor_internal_error"
    assert "peer_runtime_incompatible" in error.value.detail


def test_legacy_kwargs_wheel_operator_must_have_explicit_supervision_parameters(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "peer_operator_kwargs_compat_test", REPO / "scripts" / "peer_operator.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class LegacyKwargsPeerService:
        def __init__(self, *, store, admissions, artifacts, node_id, **kwargs):
            self.ignored_kwargs = kwargs

        def list_supervised(self):
            return []

        def issue_supervision_ticket(self):
            return None

        def resume_supervised(self):
            return None

        def reject_supervised(self):
            return None

    monkeypatch.setattr(module, "PeerService", LegacyKwargsPeerService)
    with pytest.raises(PeerError) as error:
        module._require_supervision_runtime()
    assert error.value.reason_code == "executor_internal_error"
    assert "peer_runtime_incompatible" in error.value.detail


def test_corrupt_persisted_supervision_expiry_fails_closed(tmp_path):
    service, store, root, task_id = _held(_env(tmp_path, ttl=60))
    payload = store._read("tasks")  # noqa: SLF001 -- test-only corrupt on-disk record
    for item in payload["items"]:
        if item.get("task_id") == task_id:
            item["supervision_expires_at"] = "not-a-timestamp"
    store._write("tasks", payload)  # noqa: SLF001 -- test-only corrupt on-disk record
    assert service.list_supervised() == []
    task = store.get_task(task_id)
    assert task is not None and task.state == "failed"
    assert task.reason_code == "supervision_timeout"
    assert not (root / "out.txt").exists()


def test_operator_legacy_ttl_flag_is_accepted_but_not_applied(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "peer_operator.py"),
            "--data-dir",
            str(tmp_path / "peer"),
            "--node-id",
            NODE,
            "--supervision-ttl-s",
            "9999",
            "list",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "没有等待确认" in proc.stdout
