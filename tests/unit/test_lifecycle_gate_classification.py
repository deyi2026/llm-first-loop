"""lifecycle_agency 任务 1.2: GateClassification 静态分级表回归.

规格依据 design 2.1.3.2 / spec AC-9。分级表是静态声明：把"硬拒还是降级、
有没有模型出口"收敛为可审计常量。physical_impossible / identity_conflict
保留硬拒且不得被 override 穿透；consistency 可经结构化出口推进。
"""

from __future__ import annotations

import re
from pathlib import Path

from llm_loop.runtime import service_control as sc

_VALID_CLASSES = {
    sc.GATE_CLASS_PHYSICAL_IMPOSSIBLE,
    sc.GATE_CLASS_IDENTITY_CONFLICT,
    sc.GATE_CLASS_CONSISTENCY,
}

# design 2.1.3.2 要求声明的门禁全集（含 override gate 名）。
_EXPECTED_GATES = {
    "waiting_for_requester_exit",
    "waiting_for_idle",
    "precheck:artifact",
    "precheck:service_binding",
    "precheck:active_run",
    "precheck:dual_root",
    "precheck:dual_root_identity",
    "precheck:root_source",
    "precheck:knowledge_binding",
    "precheck:knowledge_store",
    "verify",
    "barrier",
    "port_in_use",
    "process_mutex",
    "stop_failure",
    "mirror_isolation",
}

# 必须保留硬拒（不可 override 穿透）的物理/身份门禁。
_NON_PENETRABLE = {
    "precheck:service_binding",
    "precheck:dual_root_identity",
    "port_in_use",
    "process_mutex",
    "stop_failure",
    "mirror_isolation",
}


def test_classification_covers_every_declared_gate() -> None:
    assert set(sc.GATE_CLASSIFICATION) == _EXPECTED_GATES
    assert {entry.gate for entry in sc._GATE_CLASSIFICATION_ENTRIES} == _EXPECTED_GATES


def test_every_category_is_legal() -> None:
    for entry in sc._GATE_CLASSIFICATION_ENTRIES:
        assert entry.category in _VALID_CLASSES, entry.gate
        assert entry.reason.strip(), entry.gate


def test_physical_and_identity_gates_reject_override() -> None:
    for gate in _NON_PENETRABLE:
        assert not sc.gate_override_allowed(gate), gate
        entry = sc.classify_gate(gate)
        assert entry is not None
        assert entry.category in {
            sc.GATE_CLASS_PHYSICAL_IMPOSSIBLE,
            sc.GATE_CLASS_IDENTITY_CONFLICT,
        }
        assert entry.exit_action == ""


def test_consistency_gates_allow_override() -> None:
    for gate in _EXPECTED_GATES - _NON_PENETRABLE:
        entry = sc.classify_gate(gate)
        assert entry is not None
        assert entry.category == sc.GATE_CLASS_CONSISTENCY, gate
        assert sc.gate_override_allowed(gate), gate
        assert entry.exit_action, gate


def test_unknown_gate_is_not_silently_allowed() -> None:
    assert sc.classify_gate("no_such_gate") is None
    assert not sc.gate_override_allowed("no_such_gate")


def test_status_view_is_serializable_and_readonly() -> None:
    view = sc.gate_classification_view()
    assert len(view) == len(_EXPECTED_GATES)
    for row in view:
        assert set(row) == {"gate", "category", "exit_action", "script_gate", "reason"}
        assert all(isinstance(value, str) for value in row.values())

def _script_text() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "scripts" / "restart_mirror.sh").read_text(encoding="utf-8")


def test_script_override_gates_are_declared_consistency() -> None:
    """L9/L10/L11/L23: 脚本侧 _override_enabled 的门必须已声明且可穿透.

    防止脚本与分级表漂移：脚本多写一个未声明 gate（模型无从举证）或把
    identity/physical 门错误接入 override（越过红线）都会在此暴露。
    """
    gates = set(re.findall(r"_override_enabled\s+([A-Za-z0-9_:.-]+)", _script_text()))
    assert gates, "restart_mirror.sh 未接线任何 consistency override 分支"
    for gate in gates:
        entry = sc.classify_gate(gate)
        assert entry is not None, f"脚本使用了未在分级表声明的 gate: {gate}"
        assert entry.override_allowed, f"脚本把不可穿透门接入 override: {gate}"


def test_script_declares_structured_stage_fact() -> None:
    """L4: 脚本产出结构化 stage_fact（替代 detail 文本白名单猜副作用）."""
    text = _script_text()
    assert "LFL_RESTART_STAGE_FACT" in text
    assert "not_started" in text


def test_script_identity_gates_are_not_overridable() -> None:
    """L10: 根身份/服务绑定门属 identity_conflict，脚本不得提供 override 放行."""
    text = _script_text()
    for gate in ("precheck:dual_root_identity", "precheck:service_binding"):
        assert not re.search(rf"_override_enabled\s+{re.escape(gate)}", text), gate

def test_script_marks_direct_invocation_non_authoritative() -> None:
    """L16/tasks 8.1: 直连脚本回执显式标注非权威并指向 service_control."""
    text = _script_text()
    assert "direct-non-authoritative" in text
    assert "LFL_RESTART_AUTHORITY" in text
    assert '"authoritative"' in text
    assert "service_control(action=restart|update)" in text


def test_script_authority_derives_from_worker_action_id() -> None:
    """权威=worker 注入 action_id；直连无 action_id → 非权威（只标注不拦）."""
    text = _script_text()
    assert 'LFL_RESTART_ACTION_ID="${LFL_RESTART_ACTION_ID:-}"' in text
    assert 'RESTART_AUTHORITY="service_control"' in text


def test_compat_retirement_criteria_are_mechanically_observable() -> None:
    """L18/tasks 8.3: 每条兼容层都有可机械观测的退役判据（AC-17）."""
    expected_layers = {
        "direct_restart_script",
        "control_subprocess_env_version_discipline",
        "mixed_run_contract_f9",
        "root_source_four_state_branch",
    }
    assert {entry.layer for entry in sc.COMPAT_RETIREMENT_CRITERIA} == expected_layers
    for entry in sc.COMPAT_RETIREMENT_CRITERIA:
        assert entry.retire_criterion.strip(), entry.layer
        assert entry.observable_signal.strip(), entry.layer
    view = sc.compat_retirement_view()
    assert len(view) == len(sc.COMPAT_RETIREMENT_CRITERIA)
    for row in view:
        assert set(row) == {
            "layer",
            "location",
            "purpose",
            "retire_criterion",
            "observable_signal",
        }


def test_model_action_plan_exposes_no_compat_precondition() -> None:
    """L17/tasks 8.2: 模型操作路径不含版本/兼容前置条件（AC-16）."""
    from llm_loop.runtime.service_control import (
        ManagedServiceDeployment,
        ServiceControlAction,
        build_restart_plan,
    )

    action = ServiceControlAction(
        schema="service-control-action/v1",
        action_id="a" * 8,
        action="restart",
        target="web",
        deployment_id="deploy-1",
        deployment_generation=1,
        requester_session_id="s",
        status="accepted",
        created_at="2026-09-22T00:00:00+00:00",
        updated_at="2026-09-22T00:00:00+00:00",
    )
    deployment = ManagedServiceDeployment(
        schema="managed-service-deployment/v1",
        deployment_id="deploy-1",
        generation=1,
        git_head="b" * 40,
        code_root="/tmp/code",
        runtime_root="/tmp/rt",
        webui_artifact_sha256="c" * 64,
    )
    plan = build_restart_plan(action, deployment)
    for key in plan.env:
        lowered = key.lower()
        assert "compat" not in lowered
        assert "legacy" not in lowered
        assert "version" not in lowered


def test_no_gate_without_a_model_or_physical_justification() -> None:
    """AC-19 治理自洽: 无出口的门禁只能是物理/身份边界，否则即新增硬门禁."""
    for entry in sc._GATE_CLASSIFICATION_ENTRIES:
        if entry.exit_action:
            assert entry.category == sc.GATE_CLASS_CONSISTENCY, entry.gate
            continue
        assert entry.category in {
            sc.GATE_CLASS_PHYSICAL_IMPOSSIBLE,
            sc.GATE_CLASS_IDENTITY_CONFLICT,
        }, f"consistency 门 {entry.gate} 缺模型出口 = 新增硬门禁"

