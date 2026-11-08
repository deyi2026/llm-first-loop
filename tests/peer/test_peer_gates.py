"""T6 应拦闸的单元级证明：能力播报、健康水位、审计失败、中断恢复、明文绑定。

这些用例与 ``scripts/peer_acceptance.py``（真进程 + 真端口 + 真 HMAC）互补：
这里固定语义边界与 fail-closed 分支，验收脚本负责"真实输入确实被拒"。
"""
from __future__ import annotations

import importlib.util
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from llm_loop.peer.admission import AdmissionStore
from llm_loop.peer.artifacts import ArtifactStore
from llm_loop.peer.kinds import EXECUTABLE_KINDS, manifest_kinds
from llm_loop.peer.models import GrantRecord, TaskRecord, iso, now_local
from llm_loop.peer.service import PeerService
from llm_loop.peer.store import PeerStore

REPO = Path(__file__).resolve().parents[2]


def _grant(allowed: Path, **overrides) -> GrantRecord:
    base = dict(
        grant_id="gr_GATES000001",
        node_id="deepin-01",
        issued_by={"ingress": "feishu", "human": "lfl"},
        issued_at=iso(now_local()),
        expires_at=iso(now_local() + timedelta(hours=1)),
        state="active",
        allowed_kinds=("fs.read", "fs.list"),
        allowed_paths=(str(allowed),),
        max_concurrency=2,
        max_tasks_total=5,
    )
    base.update(overrides)
    return GrantRecord(**base)


@pytest.fixture()
def env(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "a.txt").write_text("hello")
    store = PeerStore(tmp_path / "peer")
    service = PeerService(
        store=store,
        admissions=AdmissionStore(tmp_path / "peer"),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        node_id="deepin-01",
    )
    store.issue_grant(_grant(allowed))
    return service, store, allowed, tmp_path


def _payload(allowed: Path, effect_id: str = "eff_gates0001", **params) -> dict:
    return {
        "schema": "lfl.peer.v1",
        "effect_id": effect_id,
        "kind": "fs.read",
        "params": params or {"path": str(allowed / "a.txt")},
        "deadline_s": 30,
        "expect": ["summary", "artifact"],
    }


def _task(state: str, *, kind="fs.read", idem="idempotent", supervised=False) -> TaskRecord:
    now = iso(now_local())
    return TaskRecord(
        task_id=f"task_{state}_{kind.replace('.', '_')}",
        effect_id=f"eff_{state}_{kind.replace('.', '_')}",
        node_id="deepin-01",
        kind=kind,
        params={"path": "/nonexistent/never-read"},
        expect=("summary",),
        deadline_s=30,
        state=state,
        idempotency_class=idem,
        supervised_only=supervised,
        created_at=now,
        updated_at=now,
    )


_CHAIN = {
    "submitted": (),
    "admitted": ("admitted",),
    "queued": ("admitted", "queued"),
    "running": ("admitted", "queued", "running"),
}


def _seed(store: PeerStore, task: TaskRecord) -> TaskRecord:
    """按合法转移链落盘历史记录：put_task 要求首状态 submitted 且逐跳合法。"""
    current = store.put_task(replace(task, state="submitted"))
    for state in _CHAIN.get(task.state, (task.state,)):
        current = store.put_task(replace(task, state=state), expected_state=current.state)
    return current


# ---- 能力播报：不播报没有 handler 的 kind ----------------------------------
def test_manifest_advertised_kinds_are_all_executable():
    # D5：宣告面 ⊆ 真能执行；且"需要人逐次确认"的 kind 只在监督就绪时才宣告。
    advertised = {row["kind"] for row in manifest_kinds()}
    assert advertised == set(EXECUTABLE_KINDS) - {"fs.write"}
    assert "fs.write" not in advertised
    assert {row["kind"] for row in manifest_kinds(supervised_ready=True)} == set(EXECUTABLE_KINDS)
    assert not any(kind.startswith("desktop.") for kind in advertised)


def test_manifest_never_advertises_kind_without_handler(env):
    service, _store, _allowed, _tmp = env
    assert {k["kind"] for k in service.manifest()["kinds"]} <= set(EXECUTABLE_KINDS)


# ---- 健康水位 --------------------------------------------------------------
def test_degraded_health_denies_before_execution(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "a.txt").write_text("hello")
    store = PeerStore(tmp_path / "peer")
    service = PeerService(
        store=store,
        admissions=AdmissionStore(tmp_path / "peer"),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        node_id="deepin-01",
        health="degraded",  # 运维显式覆盖（演练/维护期导流）
    )
    store.issue_grant(_grant(allowed))

    assert service.manifest()["health"] == "degraded"
    receipt = service.submit(_payload(allowed))
    assert receipt["state"] == "denied"
    assert receipt["reason_code"] == "executor_unhealthy"
    assert store.get_grant("gr_GATES000001").tasks_used == 0
    assert not (tmp_path / "artifacts").exists() or not list((tmp_path / "artifacts").rglob("*"))


def test_watermark_rule_degrades_above_threshold(env, monkeypatch):
    """水位判定本身：usage% >= watermark → degraded；manifest 播报与判定同源。"""
    import shutil

    service, _store, _allowed, _tmp = env
    assert service._audit_watermark_pct == 90
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(1000, 950, 50)
    )
    assert service.health() == "degraded"
    assert service.manifest()["limits"]["audit_watermark_pct"] == 90
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(1000, 899, 101)
    )
    assert service.health() == "ok"


def test_watermark_is_clamped_and_manifest_matches_gate(tmp_path):
    """越界水位被夹到 50..99，且播报值就是判定值（不允许两处真值）。"""
    service = PeerService(
        store=PeerStore(tmp_path / "p"),
        admissions=AdmissionStore(tmp_path / "p"),
        artifacts=ArtifactStore(tmp_path / "a"),
        node_id="deepin-01",
        audit_watermark_pct=1,
    )
    assert service._audit_watermark_pct == 50
    assert service.manifest()["limits"]["audit_watermark_pct"] == 50
    import shutil as _sh

    orig = _sh.disk_usage
    _sh.disk_usage = lambda _p: type(orig("/"))(1000, 600, 400)
    try:
        assert service.health() == "degraded"
    finally:
        _sh.disk_usage = orig


def test_health_is_fail_closed_when_disk_unreadable(env, monkeypatch):
    service, _store, _allowed, _tmp = env
    import shutil

    def boom(_path):
        raise OSError("statvfs failed")

    monkeypatch.setattr(shutil, "disk_usage", boom)
    assert service.health() == "degraded"


# ---- 审计不可用：拒绝执行，不消耗额度 --------------------------------------
def test_audit_unavailable_denies_without_execution(env):
    service, store, allowed, tmp_path = env
    service._admissions.dir.chmod(0o500)
    try:
        receipt = service.submit(_payload(allowed))
    finally:
        service._admissions.dir.chmod(0o700)

    assert receipt["state"] == "denied"
    assert receipt["reason_code"] == "audit_unavailable"
    assert store.get_grant("gr_GATES000001").tasks_used == 0
    artifacts = tmp_path / "artifacts"
    assert not artifacts.exists() or not [p for p in artifacts.rglob("*") if p.is_file()]


def test_audit_unavailable_overrides_original_deny_reason(env):
    """审计写失败时，拒绝原因必须是 audit_unavailable（否则"为什么拒"无从追溯）。"""
    service, _store, allowed, _tmp = env
    service._admissions.dir.chmod(0o500)
    try:
        receipt = service.submit(_payload(allowed, path="/etc/passwd"))
    finally:
        service._admissions.dir.chmod(0o700)
    assert receipt["state"] == "denied"
    assert receipt["reason_code"] == "audit_unavailable"


# ---- 中断恢复：状态收敛，绝不自动重跑 --------------------------------------
def test_recover_running_idempotent_becomes_failed_crashed(env):
    service, store, _allowed, _tmp = env
    _seed(store, _task("running"))
    recovered = service.recover_interrupted()
    assert [t.state for t in recovered] == ["failed"]
    assert recovered[0].reason_code == "crashed"


def test_recover_running_non_idempotent_becomes_unknown_outcome(env):
    service, store, _allowed, _tmp = env
    _seed(store, _task("running", kind="fs.write", idem="non_idempotent", supervised=True))
    recovered = service.recover_interrupted()
    assert [t.state for t in recovered] == ["unknown_outcome"]
    assert recovered[0].reason_code == "crashed"


def test_recover_admitted_and_queued_become_failed_and_never_execute(env):
    service, store, _allowed, tmp_path = env
    _seed(store, _task("admitted"))
    _seed(store, _task("queued"))
    recovered = service.recover_interrupted()
    assert {t.state for t in recovered} == {"failed"}
    assert len(recovered) == 2
    artifacts = tmp_path / "artifacts"
    assert not artifacts.exists() or not [p for p in artifacts.rglob("*") if p.is_file()]
    # 第二次调用无事可做：恢复是幂等的
    assert service.recover_interrupted() == []


def test_recover_does_not_touch_terminal_tasks(env):
    service, store, _allowed, _tmp = env
    _seed(store, _task("denied"))
    assert service.recover_interrupted() == []
    assert store.get_task(_task("denied").task_id).state == "denied"


# ---- 明文绑定：非回环一律拒启 ----------------------------------------------
def _serve_module():
    spec = importlib.util.spec_from_file_location(
        "peer_serve_under_test", REPO / "scripts" / "peer_serve.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_loopback_detection():
    mod = _serve_module()
    assert mod._is_loopback("127.0.0.1")
    assert mod._is_loopback("::1")
    assert mod._is_loopback("localhost")
    assert not mod._is_loopback("0.0.0.0")
    assert not mod._is_loopback("203.0.113.10")  # TEST-NET-3：非回环，且不指向任何内网
    assert not mod._is_loopback("example.com")


def test_non_loopback_bind_is_refused_before_uvicorn(tmp_path):
    mod = _serve_module()
    code = mod.main(
        ["--data-dir", str(tmp_path), "--node-id", "deepin-01", "--host", "0.0.0.0"]
    )
    assert code == 2


# ---- 撤销 vs 从无租约：两种可解释原因 --------------------------------------
def test_revoked_grant_reports_grant_revoked_not_not_found(env):
    service, store, allowed, _tmp = env
    store.revoke_grant("gr_GATES000001", by="test")
    receipt = service.submit(_payload(allowed))
    assert receipt["state"] == "denied"
    assert receipt["reason_code"] == "grant_revoked"


def test_missing_grant_still_reports_not_found(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "a.txt").write_text("hello")
    service = PeerService(
        store=PeerStore(tmp_path / "peer"),
        admissions=AdmissionStore(tmp_path / "peer"),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        node_id="deepin-01",
    )
    receipt = service.submit(_payload(allowed))
    assert receipt["reason_code"] == "grant_not_found"


# ---- 产物篡改隔离：唯一允许改写终局的边 ------------------------------------
def _succeeded_task(ref: str) -> TaskRecord:
    now = iso(now_local())
    return TaskRecord(
        task_id="task_quarantine_1",
        effect_id="eff_quarantine_1",
        node_id="deepin-01",
        kind="fs.read",
        params={"path": "/tmp/x"},
        expect=("summary", "artifact"),
        deadline_s=30,
        state="submitted",
        idempotency_class="idempotent",
        supervised_only=False,
        created_at=now,
        updated_at=now,
        result={"summary": "ok", "artifacts": [{"ref": ref, "sha256": "x", "bytes": 1}]},
    )


def test_quarantine_moves_succeeded_task_to_failed(env):
    service, store, _allowed, _tmp = env
    base = _succeeded_task("artifact://v1/deadbeef")
    from dataclasses import replace as _replace

    current = store.put_task(base)
    for state in ("admitted", "queued", "running", "succeeded"):
        current = store.put_task(_replace(base, state=state), expected_state=current.state)

    moved = service.quarantine_artifact("artifact://v1/deadbeef")
    assert [t.state for t in moved] == ["failed"]
    assert moved[0].reason_code == "artifact_digest_mismatch"
    assert store.get_task("task_quarantine_1").state == "failed"


def test_terminal_rewrite_is_narrow(env):
    """除了 succeeded→failed 的隔离边，其它终局改写仍然一律拒绝。"""
    service, store, _allowed, _tmp = env
    from dataclasses import replace as _replace

    from llm_loop.peer.errors import PeerError

    base = _succeeded_task("artifact://v1/deadbeef")
    current = store.put_task(base)
    for state in ("admitted", "queued", "running", "succeeded"):
        current = store.put_task(_replace(base, state=state), expected_state=current.state)

    with pytest.raises(PeerError) as err:
        store.put_task(_replace(base, state="succeeded"), expected_state="succeeded")
    assert err.value.reason_code == "idempotency_conflict"

    # 即使显式打开隔离开关，succeeded → unknown_outcome 也不在允许边上
    with pytest.raises(PeerError) as err2:
        store.put_task(
            _replace(base, state="unknown_outcome"),
            expected_state="succeeded",
            allow_terminal_rewrite=True,
        )
    assert err2.value.reason_code == "idempotency_conflict"
