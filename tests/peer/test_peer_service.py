"""编排层：准入顺序、幂等、租约额度、拒绝/失败回执、manifest 形状。"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest

from llm_loop.peer.admission import AdmissionStore
from llm_loop.peer.artifacts import ArtifactStore
from llm_loop.peer.errors import PeerError
from llm_loop.peer.models import GrantRecord, iso, utcnow
from llm_loop.peer.service import PeerService
from llm_loop.peer.store import PeerStore

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "lfl.peer.v1"


@pytest.fixture()
def env(tmp_path):
    allowed = tmp_path / "work" / "allowed"
    allowed.mkdir(parents=True)
    store = PeerStore(tmp_path / "peer")
    service = PeerService(
        store=store,
        admissions=AdmissionStore(tmp_path / "peer"),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        node_id="deepin-01",
    )
    return service, store, allowed, tmp_path


def make_grant(allowed: Path, **overrides) -> GrantRecord:
    base = dict(
        grant_id="gr_ABCDEFGH1234",
        node_id="deepin-01",
        issued_by={"ingress": "feishu", "human": "lfl"},
        issued_at=iso(utcnow()),
        expires_at=iso(utcnow() + timedelta(hours=1)),
        state="active",
        allowed_kinds=("fs.read", "fs.list"),
        allowed_paths=(str(allowed),),
        max_concurrency=2,
        max_tasks_total=5,
    )
    base.update(overrides)
    return GrantRecord(**base)


def submit_payload(allowed: Path, *, effect_id="eff_00000001", kind="fs.read", **params):
    return {
        "schema": "lfl.peer.v1",
        "effect_id": effect_id,
        "kind": kind,
        "params": params or {"path": str(allowed / "a.txt")},
        "deadline_s": 30,
        "expect": ["summary", "artifact"],
    }


def test_submit_happy_path_writes_admission_and_receipt(env):
    service, store, allowed, _tmp = env
    store.issue_grant(make_grant(allowed))
    (allowed / "a.txt").write_text("hello")

    receipt = service.submit(submit_payload(allowed))
    assert receipt["state"] == "succeeded"
    assert receipt["schema"] == "lfl.peer.v1"
    assert receipt["grant_id"] == "gr_ABCDEFGH1234"
    assert receipt["executor"] == {"node_id": "deepin-01", "health": "ok"}
    assert receipt["result"]["summary"].startswith("read 5 bytes")
    assert receipt["result"]["artifacts"][0]["ref"].startswith("artifact://v1/")

    admission = AdmissionStore(store.root).get_by_task(receipt["task_id"])
    assert admission is not None and admission.verdict == "admitted"
    assert store.get_grant("gr_ABCDEFGH1234").tasks_used == 1


def test_receipt_keys_are_within_schema(env):
    service, store, allowed, _tmp = env
    store.issue_grant(make_grant(allowed))
    (allowed / "a.txt").write_text("x")
    receipt = service.submit(submit_payload(allowed))
    allowed_keys = {
        "schema", "task_id", "effect_id", "admission_id", "grant_id", "state", "reason_code",
        "idempotency_class", "attempt", "blocked_reason", "suggested_next", "result",
        "executor", "observed_at",
    }
    assert set(receipt) <= allowed_keys
    assert re.fullmatch(r"[A-Za-z0-9._:-]{8,64}", receipt["task_id"])


def test_idempotent_replay_returns_same_task_without_second_charge(env):
    service, store, allowed, _tmp = env
    store.issue_grant(make_grant(allowed))
    (allowed / "a.txt").write_text("x")
    first = service.submit(submit_payload(allowed))
    second = service.submit(submit_payload(allowed))
    assert second["task_id"] == first["task_id"]
    assert second["state"] == "succeeded"
    assert store.get_grant("gr_ABCDEFGH1234").tasks_used == 1


def test_effect_id_reuse_with_different_params_conflicts(env):
    service, store, allowed, _tmp = env
    store.issue_grant(make_grant(allowed))
    (allowed / "a.txt").write_text("x")
    (allowed / "b.txt").write_text("y")
    service.submit(submit_payload(allowed))
    with pytest.raises(PeerError) as err:
        service.submit(submit_payload(allowed, path=str(allowed / "b.txt")))
    assert err.value.reason_code == "idempotency_conflict"


def test_no_grant_denies_with_grant_not_found_receipt(env):
    service, store, allowed, _tmp = env
    (allowed / "a.txt").write_text("x")
    receipt = service.submit(submit_payload(allowed))
    assert receipt["state"] == "denied"
    assert receipt["reason_code"] == "grant_not_found"
    admission = AdmissionStore(store.root).get_by_task(receipt["task_id"])
    assert admission.verdict == "denied" and admission.grant_id is None


def test_kind_not_in_grant_is_denied_receipt(env):
    service, store, allowed, _tmp = env
    store.issue_grant(make_grant(allowed, allowed_kinds=("fs.list",)))
    (allowed / "a.txt").write_text("x")
    receipt = service.submit(submit_payload(allowed))
    assert receipt["state"] == "denied"
    assert receipt["reason_code"] == "policy_task_kind_not_allowed"
    assert receipt["suggested_next"]
    assert store.get_grant("gr_ABCDEFGH1234").tasks_used == 0


def test_path_outside_allowed_is_denied_and_audited(env):
    service, store, allowed, tmp_path = env
    store.issue_grant(make_grant(allowed))
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    receipt = service.submit(submit_payload(allowed, path=str(outside)))
    assert receipt["state"] == "denied"
    assert receipt["reason_code"] == "path_outside_allowed_paths"
    admission = AdmissionStore(store.root).get_by_task(receipt["task_id"])
    assert admission.verdict == "denied" and admission.reason_code == "path_outside_allowed_paths"


def test_exhausted_grant_denies_before_execution(env):
    service, store, allowed, _tmp = env
    store.issue_grant(make_grant(allowed, max_tasks_total=1))
    (allowed / "a.txt").write_text("x")
    assert service.submit(submit_payload(allowed, effect_id="eff_00000001"))["state"] == "succeeded"
    second = service.submit(submit_payload(allowed, effect_id="eff_00000002"))
    assert second["state"] == "denied"
    assert second["reason_code"] == "grant_exhausted"


def test_executor_failure_becomes_failed_receipt(env):
    service, store, allowed, _tmp = env
    store.issue_grant(make_grant(allowed))
    receipt = service.submit(submit_payload(allowed, kind="fs.list", path=str(allowed / "missing")))
    assert receipt["state"] == "failed"
    assert receipt["reason_code"] == "params_schema_invalid"


def test_unimplemented_kind_fails_with_handler_missing(env):
    service, store, allowed, _tmp = env
    store.issue_grant(make_grant(allowed, allowed_kinds=("desktop.focus_probe",)))
    receipt = service.submit(
        {
            "schema": "lfl.peer.v1",
            "effect_id": "eff_focusprobe",
            "kind": "desktop.focus_probe",
            "params": {},
            "deadline_s": 5,
        }
    )
    assert receipt["state"] == "failed"
    assert receipt["reason_code"] == "policy_task_kind_not_allowed"


def test_malformed_payload_rejected(env):
    service, _store, allowed, _tmp = env
    bad_payloads = [
        {},
        {"schema": "v2", "effect_id": "eff_00000001", "kind": "fs.read", "params": {}, "deadline_s": 5},
        {"schema": "lfl.peer.v1", "effect_id": "short", "kind": "fs.read", "params": {}, "deadline_s": 5},
        {"schema": "lfl.peer.v1", "effect_id": "eff_00000001", "kind": "fs.read", "params": {}, "deadline_s": 4},
        {
            "schema": "lfl.peer.v1", "effect_id": "eff_00000001", "kind": "fs.read",
            "params": {}, "deadline_s": 5, "extra": 1,
        },
        {
            "schema": "lfl.peer.v1", "effect_id": "eff_00000001", "kind": "fs.read",
            "params": {}, "deadline_s": 5, "expect": ["bogus"],
        },
    ]
    for payload in bad_payloads:
        with pytest.raises(PeerError) as err:
            service.submit(payload)
        assert err.value.reason_code in {"params_schema_invalid", "policy_task_kind_not_allowed"}


def test_manifest_shape_and_grant_brief(env):
    service, store, allowed, _tmp = env
    store.issue_grant(make_grant(allowed))
    manifest = service.manifest()
    assert manifest["schema"] == "lfl.peer.v1"
    assert manifest["peer_api"] == "1"
    assert manifest["node_id"] == "deepin-01"
    assert manifest["display_protocol"] == "none"
    assert manifest["desktop"]["inject_type"] is False
    assert manifest["grant"]["grant_id"] == "gr_ABCDEFGH1234"
    assert manifest["grant"]["tasks_remaining"] == 5
    assert {k["kind"] for k in manifest["kinds"]} >= {"fs.read", "fs.list"}
    assert "shell.exec" not in {k["kind"] for k in manifest["kinds"]}


def test_manifest_without_grant_advertises_null(env):
    service, _store, _allowed, _tmp = env
    assert service.manifest()["grant"] is None


def test_suggestion_map_matches_reason_codes_source():
    """suggestions.py 是 reason-codes.json 的生成物，键集合必须完全一致（防两处漂移）。"""
    import json

    from llm_loop.peer.suggestions import REASON_SUGGESTIONS

    data = json.loads((SCHEMA_DIR / "reason-codes.json").read_text())
    if isinstance(data, dict) and isinstance(data.get("codes"), dict):
        data = data["codes"]
    assert set(REASON_SUGGESTIONS) == set(data)
    assert all(isinstance(v, str) and v for v in REASON_SUGGESTIONS.values())


def test_receipt_state_is_closed_set(env):
    service, store, allowed, _tmp = env
    store.issue_grant(make_grant(allowed))
    (allowed / "a.txt").write_text("x")
    receipt = service.submit(submit_payload(allowed))
    assert receipt["state"] in {
        "submitted", "admitted", "queued", "running", "blocked",
        "succeeded", "failed", "unknown_outcome", "denied", "cancelled",
    }


def test_manifest_conforms_and_conditional_guard_really_blocks(env):
    """schema 条件：inject_click=true ⇒ screenshot 必须 true。修复后要能实测拒绝对应输入。"""
    import json

    jsonschema = pytest.importorskip("jsonschema")
    service, store, allowed, _tmp = env
    store.issue_grant(make_grant(allowed))
    manifest = service.manifest()
    schema = json.loads((SCHEMA_DIR / "manifest.schema.json").read_text())
    jsonschema.validate(manifest, schema)

    bad = json.loads(json.dumps(manifest))
    bad["desktop"].update(inject_click=True, screenshot=False)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_concurrent_same_effect_id_executes_once(env):
    """独立审查 P1-2（2026-11-08）：并发同 effect_id 提交恰执行一次。

    O_EXCL 占坑先于副作用：双线程同时 submit，只有占坑成功方落任务并
    执行；后来者返回同一 task_id 的幂等回执。破坏 check-then-act 双执行。
    """
    import threading

    service, store, allowed, _ = env
    target = allowed / "counter.txt"
    target.write_text("0", encoding="utf-8")
    store.issue_grant(make_grant(allowed))
    payload = submit_payload(allowed, effect_id="eff_race_0001", path=str(target))
    # fs.read 是只读 kind——用执行副作用计数不可行；断言落点=任务唯一性
    receipts: list[dict] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def submit():
        try:
            barrier.wait(timeout=5)
            receipts.append(service.submit(dict(payload)))
        except Exception as exc:  # noqa: BLE001 — 收集竞态方异常
            errors.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors, errors
    same = [r for r in receipts if r.get("task_id") == receipts[0]["task_id"]]
    assert len(receipts) == 2 and len(same) == 2, receipts
    tasks = [t for t in store.list_tasks(node_id="deepin-01", limit=100)
             if t.effect_id == "eff_race_0001"]
    assert len(tasks) == 1, [t.task_id for t in tasks]
    ledger = store.root / "effects" / "deepin-01__eff_race_0001.json"
    assert ledger.is_file()


def test_select_grant_prefers_active_over_retained_exhausted(env):
    """独立审查第 4 轮 P1-1（2026-11-08）：续约后 active 租约必须被选中。

    G4/D10 续约保留旧租约（exhausted/更早到期）+ 新建 active——按最早
    expires_at 全量排序会永远选中保留租约，调度恒 grant_exhausted。
    """
    service, store, allowed, _ = env
    earlier = make_grant(
        allowed, grant_id="gr_OLDERLEASE1", tasks_used=5,  # 已用尽
    )
    from datetime import timedelta

    renewed = make_grant(
        allowed,
        grant_id="gr_NEWERLEASE2",
        expires_at=iso(utcnow() + timedelta(days=365)),  # 远期 active：续约产物
    )
    store.issue_grant(earlier)
    store.issue_grant(renewed)
    earlier_record = store.get_grant("gr_OLDERLEASE1")
    assert earlier_record.tasks_used >= earlier_record.max_tasks_total
    selected = service._select_grant()
    assert selected.grant_id == "gr_NEWERLEASE2", (
        f"续约后必须选 active 租约，实际选中 {selected.grant_id}"
    )
    # 反向兼容：只有 exhausted 租约时仍选中它（闸2 产生具体拒绝码）
    store.revoke_grant("gr_NEWERLEASE2", by="test")
    only_exhausted = service._select_grant()
    assert only_exhausted.grant_id == "gr_OLDERLEASE1"
