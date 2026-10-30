"""service_control 的 wecom 枚举测试（③）：工具 schema、runtime 白名单、
idle 判定、manifest 身份守卫、restart_system.sh wecom 被判受管操作.
"""

import json
import os

from llm_loop.runtime.manifest import write_manifest
from llm_loop.runtime.resolver import _SERVICE_SCOPED_SECTIONS
from llm_loop.runtime.service_control import (
    _ACTION_TARGETS,
    _MANAGED_SERVICES,
    ManagedServiceMutationGuard,
    _target_idle_state,
)
from llm_loop.runtime.service_control_derivation import (
    DERIVABLE_SERVICE_TARGETS,
    derive_restart_target,
)
from llm_loop.tools.builtin.service_control import (
    _MANAGED_SERVICES as TOOL_MANAGED,
)
from llm_loop.tools.builtin.service_control import (
    _SERVICE_TARGETS as TOOL_TARGETS,
)
from llm_loop.tools.builtin.service_control import (
    ServiceControlTool,
    _service_control_contract_error,
)


def test_tool_schema_enums_contain_wecom():
    """工具 schema：target/restart_target 含 wecom+all；service 含 wecom 不含 all."""
    props = ServiceControlTool.parameters["properties"]
    assert "wecom" in props["target"]["enum"] and "all" in props["target"]["enum"]
    assert "wecom" in props["restart_target"]["enum"]
    assert "wecom" in props["service"]["enum"] and "all" not in props["service"]["enum"]
    assert "wecom" in TOOL_TARGETS and "wecom" in TOOL_MANAGED


def test_status_action_with_wecom_service_not_rejected():
    """service_control(action=status, service=wecom) 不因枚举校验被拒（错误串为空）."""
    assert _service_control_contract_error("status", {"service": "wecom"}) == ""
    # release/adopt 的 service=wecom 也不再是枚举违规
    assert _service_control_contract_error("release", {"service": "wecom", "reason": "r"}) == ""


def test_runtime_enums_contain_wecom():
    """runtime 侧受管服务/动作目标含 wecom."""
    assert "wecom" in _MANAGED_SERVICES
    assert "wecom" in _ACTION_TARGETS


def test_restart_system_sh_wecom_is_managed_mutation():
    """关键行为锁：`restart_system.sh wecom` 必须被判为受管变更（否则会被
    非受管 shell 操作放行，绕过 service_control 的编排/屏障/空闲门禁）."""
    assert (
        ManagedServiceMutationGuard._restart_script_mutation(
            ["/bin/bash", "/repo/scripts/restart_system.sh", "wecom"]
        )
        is True
    )
    # guard 全链路（restart 脚本检查在 managed 名单过滤之前，空名单也拦）
    guard = ManagedServiceMutationGuard(
        "/nonexistent-data-dir-for-test", process_command_reader=lambda pid: ""
    )
    decision = guard.guard("bash /repo/scripts/restart_system.sh wecom")
    assert decision is not None and decision.blocked is True


def test_direct_launch_wecom_is_managed():
    """直接 `python -m llm_loop.runtime.launch wecom` 也被判受管（非权威启动）."""
    guard = ManagedServiceMutationGuard(
        "/nonexistent-data-dir-for-test", process_command_reader=lambda pid: ""
    )
    decision = guard.guard(
        "/repo/.venv/bin/python -m llm_loop.runtime.launch wecom"
    )
    assert decision is not None and decision.blocked is True


def test_target_idle_state_wecom_heartbeat_semantics(tmp_path):
    """wecom 空闲三态：无心跳=unconfirmable 如实披露；processing/queue=busy；空=idle."""
    # 心跳缺失 → unconfirmable（≠busy：不锁死模型行动空间）
    state, detail = _target_idle_state(target="wecom", runtime_root=str(tmp_path))
    assert state == "unconfirmable" and "wecom heartbeat 缺失" in detail
    # 心跳指示处理中 → confirmed_busy
    hb_dir = tmp_path / "data"
    hb_dir.mkdir(parents=True, exist_ok=True)
    (hb_dir / "wecom_heartbeat.json").write_text(
        json.dumps({"processing_msg_id": "req_x", "queue_depth": 0}), encoding="utf-8"
    )
    state, detail = _target_idle_state(target="wecom", runtime_root=str(tmp_path))
    assert state == "confirmed_busy" and "req_x" in detail
    # 空闲 → confirmed_idle
    (hb_dir / "wecom_heartbeat.json").write_text(
        json.dumps({"processing_msg_id": "", "queue_depth": 0}), encoding="utf-8"
    )
    state, _ = _target_idle_state(target="wecom", runtime_root=str(tmp_path))
    assert state == "confirmed_idle"
    # all 目标读双桥心跳：feishu 缺失也如实披露
    state, detail = _target_idle_state(target="all", runtime_root=str(tmp_path))
    assert state == "unconfirmable" and "feishu heartbeat 缺失" in detail


def test_derivation_accepts_wecom_code_root():
    """update 缺省推导：wecom-code 路径可推导 restart_target=wecom."""
    assert "wecom" in DERIVABLE_SERVICE_TARGETS
    derivation = derive_restart_target("/tmp/wecom-code")
    assert derivation.derived and derivation.target == "wecom"


def test_resolver_semantic_scope_accepts_wecom():
    """resolver service-scoped semantic section 接受 wecom（[semantic.wecom] 合法）."""
    assert "wecom" in _SERVICE_SCOPED_SECTIONS["semantic"]


def test_manifest_guard_writes_wecom_identity(tmp_path):
    """manifest 身份守卫：service=wecom 启动写 runtime_manifest.wecom.json."""
    write_manifest({"service": "wecom", "pid": os.getpid()}, tmp_path)
    assert (tmp_path / "runtime" / "runtime_manifest.wecom.json").is_file()
