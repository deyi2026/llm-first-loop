"""Dedicated shared Web/Feishu lifecycle control surface."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.runtime.service_control import (
    DeploymentGenerationConflictError,
    ManagedServiceDeploymentStore,
    spawn_service_control_worker,
)


class ServiceControlTool:
    name = "service_control"
    description = (
        "共享 Web/Feishu 生命周期控制面。status 只读返回 operator-published desired deployment/action；"
        "restart 必须携带刚观察到的 expected_generation，程序先 durable accepted 再由 detached worker "
        "按 desired-state exact code_root/runtime_root 调 official restart_mirror。"
        "模型决定是否需要重启；PID/cwd/历史 manifest 都不能自行获得控制权。P0-A 仅支持 status/restart。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "restart"],
                "description": "status=只读；restart=受控异步重启",
            },
            "target": {
                "type": "string",
                "enum": ["web", "feishu", "all"],
                "description": "restart 目标；status 时可省略",
            },
            "expected_generation": {
                "type": "integer",
                "minimum": 1,
                "description": "restart 必填：来自最近 status 的 exact deployment generation",
            },
            "action_id": {
                "type": "string",
                "description": "status 可选：查询已返回的 service-control action receipt",
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        *,
        store: ManagedServiceDeploymentStore,
        worker_spawner: Callable[[str], None] | None = None,
        session_id_getter: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self._worker_spawner = worker_spawner or (
            lambda action_id: spawn_service_control_worker(self.store, action_id)
        )
        self._session_id_getter = session_id_getter or (lambda: current_session_id.get() or "")

    def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get("action", "") or "").strip().lower()
        if action == "status":
            action_id = str(kwargs.get("action_id", "") or "").strip()
            if action_id:
                try:
                    receipt = self.store.read_action(action_id)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    return self._failure(f"[service_control status failed] {type(exc).__name__}: {exc}")
                if receipt is None:
                    return self._failure(f"[service_control] action_id not found: {action_id}")
                body = {"action": receipt.to_dict()}
            else:
                try:
                    deployment = self.store.read()
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    return self._failure(f"[service_control status failed] {type(exc).__name__}: {exc}")
                body = {"deployment": deployment.to_dict() if deployment else None}
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=json.dumps(body, ensure_ascii=False, sort_keys=True),
                tool_call_id="",
                tool_name=self.name,
            )

        if action != "restart":
            return self._failure("[参数错误] action 仅支持 status/restart")
        target = str(kwargs.get("target", "") or "").strip().lower()
        if target not in {"web", "feishu", "all"}:
            return self._failure("[参数错误] restart target 必须是 web/feishu/all")
        raw_expected_generation = kwargs.get("expected_generation")
        if raw_expected_generation is None:
            return self._failure("[参数错误] restart 必须提供 expected_generation")
        try:
            expected_generation = int(str(raw_expected_generation))
        except ValueError:
            return self._failure("[参数错误] restart 必须提供 expected_generation")
        try:
            receipt = self.store.accept_restart(
                target=target,
                expected_generation=expected_generation,
                requester_session_id=self._session_id_getter(),
            )
        except (DeploymentGenerationConflictError, OSError, ValueError, json.JSONDecodeError) as exc:
            return self._failure(f"[service_control restart rejected] generation/desired-state: {exc}")

        # Durable accepted receipt exists before the detached worker can affect Web/Feishu.
        try:
            self._worker_spawner(receipt.action_id)
        except Exception as exc:  # noqa: BLE001 - failed spawn must become durable failure
            with contextlib.suppress(Exception):
                self.store.update_action(
                    receipt.action_id,
                    status="failed",
                    detail=f"worker spawn failed: {type(exc).__name__}: {exc}",
                )
            return self._failure(f"[service_control worker spawn failed] {type(exc).__name__}: {exc}")
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                "[service_control accepted] "
                f"action_id={receipt.action_id} target={target} "
                f"generation={receipt.deployment_generation}; "
                "用 service_control(action=status, action_id=...) 查询 detached worker 终态"
            ),
            tool_call_id="",
            tool_name=self.name,
        )

    def _failure(self, content: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=content,
            tool_call_id="",
            tool_name=self.name,
        )
