"""lifecycle_agency 分组2/6: 模型侧门禁出口对称性.

每个门禁的模型出口（release/adopt/override/verify_acknowledge）都必须：
- 一致性类可被模型依证据推进/裁决；
- 物理/身份类返回明确拒绝（不静默穿透）；
- 冲突时返回事实（当前 owner / 当前值），不静默。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.runtime import service_control as sc


def _deployment(tmp_path: Path, generation: int = 1) -> sc.ManagedServiceDeployment:
    return sc.ManagedServiceDeployment(
        schema=sc._DEPLOYMENT_SCHEMA,
        deployment_id=f"dep-{generation}",
        generation=generation,
        git_head="a" * 40,
        code_root=str(tmp_path),
        runtime_root=str(tmp_path),
        webui_artifact_sha256="b" * 64,
    )


def _store(tmp_path: Path) -> sc.ManagedServiceDeploymentStore:
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_deployment(tmp_path), expected_generation=0)
    return store


def _accepted_action(store, *, target: str = "web"):
    return store.accept_restart(
        target=target, expected_generation=1, requester_session_id="s-exit"
    )


# ── release 出口 ──────────────────────────────────────────────────────────


def test_release_by_owner_clears_barrier(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    result = sc.release_admission_barrier(
        store, service="web", reason="服务已恢复", expected_operation_id=action.action_id
    )
    assert result["released"] is True
    assert store.barriers.blocked("web") is None


def test_release_without_owner_conflict_reports_current(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    result = sc.release_admission_barrier(
        store, service="web", reason="误判 owner", expected_operation_id="svc-other"
    )
    assert result["released"] is False
    assert result["conflict"]["current_owner"] == action.action_id
    assert store.barriers.blocked("web") is not None


def test_release_is_idempotent_when_absent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = sc.release_admission_barrier(store, service="feishu", reason="本无屏障")
    assert result["released"] is False
    assert result["already_absent"] is True


def test_release_requires_reason(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _accepted_action(store)
    with pytest.raises(ValueError, match="reason"):
        sc.release_admission_barrier(store, service="web", reason="")


# ── adopt 出口（L21 恢复性接管）───────────────────────────────────────────


def test_adopt_takes_over_owner(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    result = sc.adopt_admission_barrier(
        store,
        service="web",
        expected_owner=action.action_id,
        reason="owner 动作已 failed",
        evidence="stage_fact=web_stopped, 服务未起",
    )
    assert result["adopted"] is True
    blocked = store.barriers.blocked("web")
    assert blocked is not None and blocked.operation_id == result["operation_id"]


def test_adopt_owner_mismatch_reports_conflict(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    result = sc.adopt_admission_barrier(
        store,
        service="web",
        expected_owner="svc-other",
        reason="误判",
        evidence="x",
    )
    assert result["adopted"] is False
    assert result["conflict"]["current_owner"] == action.action_id


def test_failed_action_barrier_can_be_adopted(tmp_path: Path) -> None:
    """L21: running→failed 一律 keep，但模型可对失败动作的屏障发起接管."""
    store = _store(tmp_path)
    action = _accepted_action(store)
    store.update_action(action.action_id, status="running", detail="")
    store.update_action(action.action_id, status="failed", detail="restart rc=1")
    assert store.barriers.blocked("web") is not None  # running→failed fail-closed keep
    result = sc.adopt_admission_barrier(
        store,
        service="web",
        expected_owner=action.action_id,
        reason="已确认物理未生效，接管恢复",
        evidence="stage_fact=web_stopped",
    )
    assert result["adopted"] is True


# ── override 出口 ────────────────────────────────────────────────────────


def test_override_consistency_gate_is_accepted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    result = sc.record_model_override(
        store,
        action_id=action.action_id,
        gate="precheck:active_run",
        evidence="active run 检查为无法确认，实际无会话在跑",
        evidence_level="E2",
        reason="等待窗口不应锁死",
    )
    assert result["accepted"] is True


def test_override_physical_gate_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    result = sc.record_model_override(
        store,
        action_id=action.action_id,
        gate="port_in_use",
        evidence="我认为端口没占用",
        evidence_level="E3",
        reason="尝试穿透",
    )
    assert result["accepted"] is False
    assert result["rejected"]["class"] == sc.GATE_CLASS_PHYSICAL_IMPOSSIBLE


def test_override_identity_gate_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    result = sc.record_model_override(
        store,
        action_id=action.action_id,
        gate="precheck:service_binding",
        evidence="我认为绑定没问题",
        evidence_level="E3",
        reason="尝试穿透",
    )
    assert result["accepted"] is False
    assert result["rejected"]["class"] == sc.GATE_CLASS_IDENTITY_CONFLICT


def test_override_unknown_gate_not_silently_allowed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    result = sc.record_model_override(
        store,
        action_id=action.action_id,
        gate="no_such_gate",
        evidence="x",
        evidence_level="E1",
        reason="x",
    )
    assert result["accepted"] is False


def test_override_requires_valid_evidence_level(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    with pytest.raises(ValueError, match="E1/E2/E3"):
        sc.record_model_override(
            store,
            action_id=action.action_id,
            gate="precheck:active_run",
            evidence="x",
            evidence_level="E9",
            reason="x",
        )


# ── verify_acknowledge 出口 ──────────────────────────────────────────────


def test_verify_acknowledge_accept_settles_succeeded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    store.update_action(action.action_id, status="running", detail="")
    result = sc.acknowledge_verify(
        store,
        action_id=action.action_id,
        verdict="accept",
        evidence="manifest pid/head 与 desired 一致",
        reason="证据充分",
    )
    assert result["status"] == "succeeded"
    assert store.read_action(action.action_id).status == "succeeded"


def test_verify_acknowledge_override_settles_failed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    store.update_action(action.action_id, status="running", detail="")
    result = sc.acknowledge_verify(
        store,
        action_id=action.action_id,
        verdict="override",
        evidence="进程实际未换新版本",
        reason="不认可程序证据",
    )
    assert result["status"] == "failed"


def test_verify_acknowledge_reobserve_returns_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sc, "_VERIFY_TIMEOUT_S", 0.05)
    monkeypatch.setattr(sc, "_VERIFY_MANIFEST_WAIT_S", 0.01)
    monkeypatch.setattr(sc, "_VERIFY_POLL_S", 0.01)
    store = _store(tmp_path)
    action = _accepted_action(store)
    store.update_action(action.action_id, status="running", detail="")
    result = sc.acknowledge_verify(
        store,
        action_id=action.action_id,
        verdict="reobserve",
        evidence="再观测一次",
        reason="证据不足",
    )
    assert result["accepted"] is True
    assert result["evidence_verdict"] in {"confirmed_ok", "confirmed_fail", "criterion_absent"}
    assert store.read_action(action.action_id).status == "verify_evidence_ready"


def test_verify_acknowledge_requires_evidence_and_reason(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    store.update_action(action.action_id, status="running", detail="")
    with pytest.raises(ValueError, match="evidence"):
        sc.acknowledge_verify(
            store, action_id=action.action_id, verdict="accept", evidence="", reason="x"
        )
    with pytest.raises(ValueError, match="reason"):
        sc.acknowledge_verify(
            store, action_id=action.action_id, verdict="accept", evidence="x", reason=""
        )


# ── 出口写入 append-only 审计 ────────────────────────────────────────────


def test_exit_actions_write_append_only_audit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = _accepted_action(store)
    sc.record_model_override(
        store,
        action_id=action.action_id,
        gate="precheck:active_run",
        evidence="e",
        evidence_level="E2",
        reason="r",
    )
    sc.release_admission_barrier(
        store, service="web", reason="释放", expected_operation_id=action.action_id
    )
    audit = store.data_dir / "audit" / "service_control_exits.jsonl"
    assert audit.is_file()
    events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert {"override_accepted", "release"} <= {event["event"] for event in events}

# ── L6/N-4（adjudication-20260922 裁定 b）：succeeded 可申诉 ──────────────


def test_verify_acknowledge_accept_on_succeeded_is_idempotent(tmp_path: Path) -> None:
    """N-4 对称性修复：confirmed_ok 程序判定的 succeeded 对模型可申诉。

    accept 起点为 succeeded → 幂等成功（补记模型裁决与审计，不改变终态）。
    """
    store = _store(tmp_path)
    action = _accepted_action(store)
    store.update_action(action.action_id, status="succeeded", detail="restart_mirror rc=0")
    result = sc.acknowledge_verify(
        store,
        action_id=action.action_id,
        verdict="accept",
        evidence="复核 manifest 三服务 head/pid 一致",
        reason="认可程序成功判定，补记模型裁决",
    )
    assert result["status"] == "succeeded"
    final = store.read_action(action.action_id)
    assert final.status == "succeeded"
    assert "model verify verdict=accept" in final.detail


def test_verify_acknowledge_override_on_succeeded_reopens_failed(tmp_path: Path) -> None:
    """模型不认可程序成功判定 → succeeded 可翻转为 failed（append-only 审计留痕）."""
    store = _store(tmp_path)
    action = _accepted_action(store)
    store.update_action(action.action_id, status="succeeded", detail="restart_mirror rc=0")
    result = sc.acknowledge_verify(
        store,
        action_id=action.action_id,
        verdict="override",
        evidence="manifest pid 已变但 head 仍为旧提交，版本未切换",
        reason="程序判据通过但结论与事实不符",
    )
    assert result["status"] == "failed"
    assert store.read_action(action.action_id).status == "failed"


def test_verify_acknowledge_still_rejects_accepted_state(tmp_path: Path) -> None:
    """可申诉集只扩到 succeeded；accepted（未执行）仍拒绝——出口不前移."""
    store = _store(tmp_path)
    action = _accepted_action(store)
    result = sc.acknowledge_verify(
        store,
        action_id=action.action_id,
        verdict="accept",
        evidence="x",
        reason="y",
    )
    assert result["accepted"] is False
    assert "not awaiting verify" in result["reason"]
