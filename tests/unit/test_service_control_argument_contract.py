from __future__ import annotations

import json
import re

from llm_loop.core.message import ToolResultStatus
from llm_loop.runtime import service_control as sc
from llm_loop.runtime.service_control import ManagedServiceDeploymentStore
from llm_loop.tools.builtin.service_control import ServiceControlTool
from llm_loop.tools.registry import ToolRegistry


def _tool(tmp_path):
    spawned: list[str] = []
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    tool = ServiceControlTool(store=store, worker_spawner=spawned.append)
    return tool, store, spawned


def test_existing_lazy_schema_keeps_restart_target_enum_without_extra_override() -> None:
    lazy = ToolRegistry._lazy_schema_skeleton(ServiceControlTool.parameters)

    assert not hasattr(ServiceControlTool, "lazy_parameters")
    assert lazy["properties"]["target"]["enum"] == [
        "web",
        "feishu",
        "wecom",
        "learning",
        "all",
    ]


def test_verify_acknowledge_reports_all_missing_fields_in_one_preflight(tmp_path) -> None:
    tool, store, spawned = _tool(tmp_path)

    result = tool.execute(
        action="verify_acknowledge",
        action_id="svc-x",
        verdict="accept",
    )

    assert result.status == ToolResultStatus.FAILURE
    assert "missing=evidence,reason" in result.content
    assert "get_tool_schema(service_control)" in result.content
    assert spawned == []
    assert store.read_action("svc-x") is None


def test_restart_missing_target_hint_lists_allowed_values_in_one_shot(tmp_path) -> None:
    """缺参回执一次给全：restart 的可选值不该靠"再撞一次"才看到（2026-11-02 复盘）."""
    tool, store, spawned = _tool(tmp_path)

    result = tool.execute(action="restart")

    assert result.status == ToolResultStatus.FAILURE
    assert "missing=target" in result.content
    assert "required=target" in result.content
    assert "target allowed=web/feishu/wecom/learning/all" in result.content
    assert spawned == []


def test_publish_missing_code_root_names_next_restart_field(tmp_path) -> None:
    """publish→restart 是相邻两步：publish 缺参时就把下一步必填一起给出."""
    tool, store, spawned = _tool(tmp_path)

    result = tool.execute(action="publish")

    assert result.status == ToolResultStatus.FAILURE
    assert "missing=code_root" in result.content
    assert "required=code_root" in result.content
    assert "next=restart 需要 target（allowed=web/feishu/wecom/learning/all）" in result.content
    assert spawned == []


def test_restart_invalid_target_fails_before_accept_or_spawn(tmp_path) -> None:
    tool, store, spawned = _tool(tmp_path)

    result = tool.execute(action="restart", target="web+feishu")

    assert result.status == ToolResultStatus.FAILURE
    assert "target='web+feishu'" in result.content
    assert "web" in result.content and "feishu" in result.content
    assert spawned == []
    assert list(store.actions_dir.glob("*.json")) == []


def test_verify_contract_rejects_invalid_verdict_and_missing_evidence_together(tmp_path) -> None:
    tool, _store, spawned = _tool(tmp_path)

    result = tool.execute(
        action="verify_acknowledge",
        action_id="svc-x",
        verdict="done",
        reason="operator reviewed evidence",
    )

    assert result.status == ToolResultStatus.FAILURE
    assert "missing=evidence" in result.content
    assert "verdict='done'" in result.content
    assert spawned == []


def test_update_needs_target_rejects_before_any_store_write(tmp_path) -> None:
    """T2（2026-10-27）: basename 无服务名 token → NEEDS_TARGET 校验阶段拒绝，
    store 零写入（无 publish/CAS、无 action 落盘、无 worker spawn）。"""
    tool, store, spawned = _tool(tmp_path)
    code = tmp_path / "shared-root"
    code.mkdir()

    result = tool.execute(action="update", code_root=str(code), reason="上线")

    assert result.status == ToolResultStatus.FAILURE
    assert "NEEDS_TARGET" in result.content
    assert "web/feishu/wecom/learning/all" in result.content
    assert "service_control(action=update" in result.content  # 一条示例命令
    assert spawned == []
    assert store.read() is None
    assert list(store.actions_dir.glob("*.json")) == []


def _publish_deployment(tmp_path) -> None:
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(
        sc.ManagedServiceDeployment(
            schema=sc._DEPLOYMENT_SCHEMA,
            deployment_id="dep-1",
            generation=1,
            git_head="a" * 40,
            code_root=str(tmp_path),
            runtime_root=str(tmp_path),
            webui_artifact_sha256="b" * 64,
        ),
        expected_generation=0,
    )


def _deferred_payload(content: str) -> dict:
    m = re.search(r"deferred_effect=(\{.*?\}) ——", content)
    assert m, f"回执缺少 deferred_effect JSON：{content}"
    return json.loads(m.group(1))


def test_restart_web_receipt_marks_effect_deferred_until_requester_exit(tmp_path) -> None:
    """[web restart 受理即当作已生效] → [FAIL]：回执必须写成"会话结束后生效"的待办。

    web 进程只能在 requester run 收尾后重启，长期会话里这最后一跳最容易被误读成
    "本轮已完成"，所以把未生效事实写进回执而不靠人记。
    """
    _publish_deployment(tmp_path)
    tool, store, spawned = _tool(tmp_path)

    result = tool.execute(action="restart", target="web", expected_generation=1)

    assert result.status == ToolResultStatus.SUCCESS
    assert len(spawned) == 1
    # 回执自称"机器可读"，就必须真能 json.loads（P2 审查意见）。
    assert _deferred_payload(result.content) == {
        "condition": "requester_run_end",
        "effective_after_session_end": True,
        "pending": True,
        "services": ["web"],
    }
    assert "尚未生效" in result.content


def test_restart_all_receipt_defers_every_target_not_just_web(tmp_path) -> None:
    """[target=all 回执只写 web 未生效] → [FAIL]：闸门挂在动作上，四个服务都在等。"""
    _publish_deployment(tmp_path)
    tool, _store, spawned = _tool(tmp_path)

    result = tool.execute(action="restart", target="all", expected_generation=1)

    assert result.status == ToolResultStatus.SUCCESS
    assert len(spawned) == 1
    assert _deferred_payload(result.content)["services"] == [
        "web",
        "feishu",
        "wecom",
        "learning",
    ]
    assert "web/feishu/wecom/learning" in result.content


def test_restart_non_web_receipt_has_no_deferred_marker(tmp_path) -> None:
    """[非 web 目标回执也挂"待会话结束"标记] → [FAIL]：learning/feishu/wecom 不该被误读。"""
    _publish_deployment(tmp_path)
    tool, _store, spawned = _tool(tmp_path)

    result = tool.execute(action="restart", target="learning", expected_generation=1)

    assert result.status == ToolResultStatus.SUCCESS
    assert len(spawned) == 1
    assert "deferred_effect" not in result.content
    assert "effective_after_session_end" not in result.content


def _next_check_payload(content: str) -> dict[str, object]:
    match = re.search(r"next_check=(\{[^\n]*\})\s*$", content)
    assert match is not None, f"回执缺少 next_check JSON：{content}"
    return json.loads(match.group(1))


def test_restart_receipt_carries_next_check_contract(tmp_path) -> None:
    """[回执只说"会话结束后复核"] → [FAIL]：查哪个 action、断言什么、门有哪些出口，要机器可读。"""
    _publish_deployment(tmp_path)
    tool, _store, spawned = _tool(tmp_path)

    result = tool.execute(action="restart", target="web", expected_generation=1)

    assert result.status == ToolResultStatus.SUCCESS
    assert len(spawned) == 1
    payload = _next_check_payload(result.content)
    assert payload["action"] == "status"
    assert payload["target"] == "web"
    assert payload["expected_generation"] == 1
    assert str(payload["action_id"]).startswith("svc-")
    assert "succeeded" in str(payload["assert"])
    assert "waiting_for_requester_exit" in payload["gates"]
    assert {exit_["kind"] for exit_ in payload["exits"]} == {"natural", "override"}
    assert "结束时" in str(payload["when"])


def test_status_action_id_exposes_next_check_for_non_terminal_action(tmp_path) -> None:
    """[status 只回原始字段] → [FAIL]：非终态动作的复核契约要一并回。"""
    _publish_deployment(tmp_path)
    tool, _store, _spawned = _tool(tmp_path)
    accepted = tool.execute(action="restart", target="web", expected_generation=1)
    action_id = _next_check_payload(accepted.content)["action_id"]

    body = json.loads(tool.execute(action="status", action_id=action_id).content)

    assert body["action"]["action_id"] == action_id
    assert body["next_check"]["action_id"] == action_id
    assert body["next_check"]["action"] == "status"


def test_status_action_id_omits_next_check_for_terminal_action(tmp_path) -> None:
    """[终态动作也挂 next_check] → [FAIL]：已终态就没有"下一轮该查什么"。"""
    _publish_deployment(tmp_path)
    tool, store, _spawned = _tool(tmp_path)
    accepted = tool.execute(action="restart", target="web", expected_generation=1)
    action_id = str(_next_check_payload(accepted.content)["action_id"])
    store.update_action(action_id, status="failed", detail="boom")

    body = json.loads(tool.execute(action="status", action_id=action_id).content)

    assert body["action"]["status"] == "failed"
    assert "next_check" not in body


def test_restart_all_next_check_declares_whole_action_deferred(tmp_path) -> None:
    """[target=all 只写 web 在等] → [FAIL]：整条动作都在等，四个服务都要写进去。"""
    _publish_deployment(tmp_path)
    tool, _store, _spawned = _tool(tmp_path)

    result = tool.execute(action="restart", target="all", expected_generation=1)

    assert result.status == ToolResultStatus.SUCCESS
    payload = _next_check_payload(result.content)
    assert payload["target"] == "all"
    assert "waiting_for_requester_exit" in payload["gates"]
    assert "deferred_effect" in result.content
    # 两个机器可读块必须能各自独立解析（re 只截到第一个 JSON 的边界）
    assert '"pending": true' in result.content
