"""Dedicated shared Web/Feishu lifecycle control surface."""

from __future__ import annotations

import contextlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.runtime.admission_barrier import BarrierConflictError
from llm_loop.runtime.service_control import (
    DeploymentGenerationConflictError,
    ManagedServiceDeploymentStore,
    build_deployment,
    compose_service_identity_view,
    spawn_service_control_worker,
)


class ServiceControlTool:
    name = "service_control"
    description = (
        "共享 Web/Feishu/Learning 生命周期控制面。status 只读返回 desired deployment/action 回执；"
        "publish 把干净 git 代码根发布为新 desired deployment（需刚观察到的 expected_generation 做 CAS，"
        "程序校验 tracked 树干净 + webui dist 产物 hash 绑定）；"
        "restart 必须携带刚观察到的 expected_generation，程序先 durable accepted 再由 detached worker "
        "两阶段执行（等待 requester 会话结束/目标空闲时不占 lifecycle lease，物理重启阶段复核 generation）， "
        "按 desired-state exact code_root/runtime_root 调 official restart_mirror。"
        "模型决定是否需要发布/重启；PID/cwd/历史 manifest 都不能自行获得控制权。"
        "终态 failed 动作留下的屏障可被新 restart 接管（自恢复）；非终态 owner 冲突仍拒绝。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "publish", "restart"],
                "description": "status=只读；publish=发布新 desired deployment；restart=受控异步重启",
            },
            "target": {
                "type": "string",
                "enum": ["web", "feishu", "learning", "all"],
                "description": "restart 目标；status/publish 时可省略",
            },
            "expected_generation": {
                "type": "integer",
                "minimum": 0,
                "description": "publish/restart 必填：来自最近 status 的 exact deployment generation（CAS）",
            },
            "code_root": {
                "type": "string",
                "description": (
                    "publish 必填：待发布的代码根（git worktree）。必须 tracked 干净、"
                    "HEAD 即待发布提交、webui/dist 为该次构建产物；runtime_root 由 data_dir 契约推导"
                ),
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
                    view = compose_service_identity_view(self.store)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    return self._failure(f"[service_control status failed] {type(exc).__name__}: {exc}")
                body = {
                    "deployment": view["deployment"],
                    "services": view["services"],
                }
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=json.dumps(body, ensure_ascii=False, sort_keys=True),
                tool_call_id="",
                tool_name=self.name,
            )

        if action == "publish":
            # S4c：模型侧 publish——与 CLI publish 同一套机械边界（干净 git 树
            # + webui dist 产物 hash + generation CAS）；shell 围栏不动（CLI
            # 仍 operator-only），模型走本工具。runtime_root 按 data_dir
            # 契约推导（runtime_root/data = data_dir），不接受调用点自选。
            code_root = str(kwargs.get("code_root", "") or "").strip()
            if not code_root:
                return self._failure("[参数错误] publish 必须提供 code_root（待发布的 git 代码根）")
            raw_expected_generation = kwargs.get("expected_generation")
            if raw_expected_generation is None:
                return self._failure("[参数错误] publish 必须提供 expected_generation（最近 status 的当前代）")
            try:
                expected_generation = int(str(raw_expected_generation))
            except ValueError:
                return self._failure("[参数错误] publish 必须提供整数 expected_generation")
            runtime_root = Path(self.store.data_dir).parent
            try:
                deployment = build_deployment(
                    code_root=code_root,
                    runtime_root=runtime_root,
                    generation=expected_generation + 1,
                )
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                return self._failure(
                    f"[service_control publish rejected] binding: {type(exc).__name__}: {exc}"
                )
            try:
                self.store.compare_and_swap(
                    deployment, expected_generation=expected_generation
                )
            except (DeploymentGenerationConflictError, ValueError) as exc:
                return self._failure(
                    f"[service_control publish rejected] generation/desired-state: {exc}"
                )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=json.dumps(
                    {
                        "published": deployment.to_dict(),
                        "next": (
                            "desired 已推进；接着 service_control(action=restart, target=..., "
                            f"expected_generation={deployment.generation}) 完成重启"
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                tool_call_id="",
                tool_name=self.name,
            )

        if action != "restart":
            return self._failure("[参数错误] action 仅支持 status/publish/restart")
        target = str(kwargs.get("target", "") or "").strip().lower()
        if target not in {"web", "feishu", "learning", "all"}:
            return self._failure("[参数错误] restart target 必须是 web/feishu/learning/all")
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
        except (
            DeploymentGenerationConflictError,
            BarrierConflictError,
            OSError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
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
                "两阶段等待（web/all 先等 requester 会话结束，再等目标空闲）期间不占 publish 锁；"
                "发起方应立即结束本轮、勿轮询本 action，下一轮用 service_control(action=status, action_id=...) 查终态"
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
