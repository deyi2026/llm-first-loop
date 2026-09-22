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
    NEXT_STEP_KIND_GENERATION_CONFLICT,
    BindingProblemKind,
    DeploymentGenerationConflictError,
    ManagedServiceDeployment,
    ManagedServiceDeploymentStore,
    acknowledge_verify,
    adopt_admission_barrier,
    binding_next_steps,
    build_deployment,
    compose_service_identity_view,
    record_model_override,
    release_admission_barrier,
    spawn_service_control_worker,
)


def _derive_restart_target(code_root: str) -> str:
    """update 缺省目标：按 code_root 路径名推导，推导不出则 all.

    Web/Feishu/Learning 通常同源单 worktree（路径不含服务名）→ all；若部署按
    服务拆分 worktree（路径含服务名）则只重启该服务。缺省值可被显式
    ``restart_target`` 覆盖。
    """
    name = Path(code_root).expanduser().name.lower()
    for service in ("web", "feishu", "learning"):
        if service in name:
            return service
    return "all"


def _missing_artifacts(code_root: str) -> list[str]:
    """L15/AC-13: 列出会让 build_deployment 绑定失败的缺失产物路径（可机械观测）."""
    dist = Path(code_root).expanduser() / "webui" / "dist"
    if not dist.is_dir():
        return [str(dist)]
    return []


def _next_step_text(kinds: list[str]) -> str:
    """svc_deploy I7: 工具面失败文案同源追加一步（复用 I2 映射，禁止另写文案）."""
    steps = binding_next_steps(kinds)
    if not steps:
        return ""
    rendered = []
    for step in steps:
        if step.exit_action:
            rendered.append(
                f"{step.problem_kind}: 下一步 service_control(action={step.exit_action})；{step.note}"
            )
        else:
            rendered.append(f"{step.problem_kind}: {step.note}")
    return "next_step: " + "; ".join(rendered)


class ServiceControlTool:
    name = "service_control"
    description = (
        "共享 Web/Feishu/Learning 生命周期控制面。status 只读返回 desired deployment/action 回执；"
        "publish 把干净 git 代码根发布为新 desired deployment（程序校验 tracked 树干净 + webui dist "
        "产物 hash 绑定，并自动以当前 generation 做 CAS）；"
        "update 单语义完成'固化期望部署 + 物理生效'，内部编排 publish+restart，模型无需自己分两步；"
        "restart 由 detached worker 两阶段执行（等待 requester 会话结束/目标空闲时不占 lifecycle "
        "lease，物理重启阶段复核 generation），按 desired-state exact code_root/runtime_root 调 "
        "official restart_mirror。expected_generation 可省略，缺省自动取当前 desired 代。"
        "release/adopt/override/verify_acknowledge 是每个门禁的模型侧出口：等待超时/屏障归属/"
        "核验证据都可被模型依证据推进或裁决，程序只保事实与物理边界。"
        "模型决定是否需要发布/重启；PID/cwd/历史 manifest 都不能自行获得控制权。"
        "终态 failed 动作留下的屏障可被新 restart 接管（自恢复）；非终态 owner 冲突仍拒绝。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "publish",
                    "update",
                    "restart",
                    "release",
                    "adopt",
                    "override",
                    "verify_acknowledge",
                ],
                "description": (
                    "status=只读；publish=发布新 desired deployment；update=发布+重启单语义；"
                    "restart=受控异步重启；release/adopt=屏障释放/接管；"
                    "override=对非物理门禁举证推进；verify_acknowledge=对核验证据裁决"
                ),
            },
            "target": {
                "type": "string",
                "enum": ["web", "feishu", "learning", "all"],
                "description": "restart 目标；status/publish 时可省略",
            },
            "restart_target": {
                "type": "string",
                "enum": ["web", "feishu", "learning", "all"],
                "description": "update 可选：物理生效目标，缺省按 code_root 推导（推导不出则 all）",
            },
            "expected_generation": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "可选：期望操作的 desired deployment generation（CAS）。缺省自动取当前"
                    "desired 代，无需先调 status 记录"
                ),
            },
            "code_root": {
                "type": "string",
                "description": (
                    "publish/update 必填：待发布/上线的代码根（git worktree）。必须 tracked "
                    "干净、HEAD 即待发布提交、webui/dist 为该次构建产物；runtime_root 由 data_dir 契约推导"
                ),
            },
            "reason": {
                "type": "string",
                "description": "update/release/adopt/override/verify_acknowledge 必填：本次意图（进审计）",
            },
            "action_id": {
                "type": "string",
                "description": "status/override/verify_acknowledge：目标 service-control action",
            },
            "service": {
                "type": "string",
                "enum": ["web", "feishu", "learning"],
                "description": "release/adopt 必填：屏障所属服务",
            },
            "gate": {
                "type": "string",
                "description": "override 必填：待推进的门禁名（如 waiting_for_idle）",
            },
            "evidence": {
                "type": "string",
                "description": "override/adopt/verify_acknowledge：支撑判断的观测事实",
            },
            "evidence_level": {
                "type": "string",
                "enum": ["E1", "E2", "E3"],
                "description": "override：E1 机械空闲事实 / E2 模型观测推论 / E3 纯声明",
            },
            "expected_operation_id": {
                "type": "string",
                "description": "release 可选：期望的当前屏障 owner（不符则返回冲突事实）",
            },
            "expected_owner": {
                "type": "string",
                "description": "adopt 必填：被接管屏障的当前 owner",
            },
            "new_owner": {
                "type": "string",
                "description": "adopt 可选：接管后的 owner id（缺省自动生成）",
            },
            "force": {
                "type": "boolean",
                "description": "release：仅用于清除损坏/未知 owner 屏障",
            },
            "verdict": {
                "type": "string",
                "enum": ["accept", "reobserve", "override"],
                "description": "verify_acknowledge：accept=接受证据置成功；reobserve=再观测一次；override=不认可证据",
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
                    "admission_barriers": view.get("admission_barriers", []),
                    "available_exits": view.get("available_exits", []),
                    "gate_classification": view.get("gate_classification", []),
                    "compat_retirement": view.get("compat_retirement", []),
                    "idle_state": view.get("idle_state", {}),
                    "stage_facts": view.get("stage_facts", {}),
                    "evidence_refs": view.get("evidence_refs", {}),
                    "audit_signals": view.get("audit_signals", {}),
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
            deployment, error = self._publish(
                str(kwargs.get("code_root", "") or "").strip(),
                kwargs.get("expected_generation"),
            )
            if error is not None:
                return self._failure(error)
            assert deployment is not None
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

        if action == "update":
            return self._update(kwargs)

        if action in {"release", "adopt", "override", "verify_acknowledge"}:
            return self._exit_action(action, kwargs)

        if action != "restart":
            return self._failure(
                "[参数错误] action 仅支持 status/publish/update/restart/"
                "release/adopt/override/verify_acknowledge"
            )
        target = str(kwargs.get("target", "") or "").strip().lower()
        if target not in {"web", "feishu", "learning", "all"}:
            return self._failure("[参数错误] restart target 必须是 web/feishu/learning/all")
        raw_expected_generation = kwargs.get("expected_generation")
        if raw_expected_generation is None:
            current = self.store.read()
            expected_generation = current.generation if current is not None else 0
        else:
            try:
                expected_generation = int(str(raw_expected_generation))
            except ValueError:
                return self._failure("[参数错误] restart 必须提供整数 expected_generation")
        try:
            receipt = self.store.accept_restart(
                target=target,
                expected_generation=expected_generation,
                requester_session_id=self._session_id_getter(),
                origin="restart",
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
                "可用 service_control(action=status, action_id=...) 查询终态，无需同步阻塞"
            ),
            tool_call_id="",
            tool_name=self.name,
        )

    def _publish(
        self, code_root: str, raw_expected_generation: object
    ) -> tuple[ManagedServiceDeployment | None, str | None]:
        """发布新 desired deployment；返回 ``(deployment, error_content)``。

        这是 publish 与 update 共用的同一套机械边界（干净 git 树 + webui dist
        产物 hash + generation CAS），避免单语义 update 另起一套判据。
        """
        if not code_root:
            return None, "[参数错误] 必须提供 code_root（待发布的 git 代码根）"
        if raw_expected_generation is None:
            current = self.store.read()
            expected_generation = current.generation if current is not None else 0
        else:
            try:
                expected_generation = int(str(raw_expected_generation))
            except ValueError:
                return None, "[参数错误] expected_generation 必须是整数"
        runtime_root = Path(self.store.data_dir).parent
        try:
            deployment = build_deployment(
                code_root=code_root,
                runtime_root=runtime_root,
                generation=expected_generation + 1,
            )
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            # L15/AC-13: 产物缺失是模型可修复的状态 → 回报缺哪一项，而非笼统拒绝。
            missing = _missing_artifacts(code_root)
            if missing:
                return None, (
                    "[service_control publish rejected] artifact_missing("
                    + ", ".join(missing)
                    + f"): {exc}; "
                    + _next_step_text([BindingProblemKind.WEBUI_ARTIFACT_UNAVAILABLE])
                )
            # svc_deploy I7：同源追加可执行下一步（复用 I2 映射，禁止另写文案）。
            if isinstance(exc, ValueError) and "clean" in str(exc):
                binding_kind = BindingProblemKind.TRACKED_WORKTREE_DIRTY
            elif isinstance(exc, ValueError):
                binding_kind = BindingProblemKind.GIT_STATUS_UNAVAILABLE
            else:
                binding_kind = "publish_error"
            return None, (
                f"[service_control publish rejected] binding: {type(exc).__name__}: {exc}; "
                + _next_step_text([binding_kind])
            )
        try:
            self.store.compare_and_swap(
                deployment, expected_generation=expected_generation
            )
        except DeploymentGenerationConflictError as exc:
            current = self.store.read()
            current_generation = current.generation if current is not None else 0
            return None, (
                f"[service_control publish rejected] generation_conflict(current={current_generation}): "
                f"{exc}; 可直接以 current 值重试; "
                + _next_step_text([NEXT_STEP_KIND_GENERATION_CONFLICT])
            )
        except ValueError as exc:
            return None, f"[service_control publish rejected] generation/desired-state: {exc}"
        return deployment, None

    def _update(self, kwargs: dict) -> ToolResult:
        """L12/L13/L15: 单语义更新——内部编排 publish 的绑定+CAS 与 restart 两阶段."""
        code_root = str(kwargs.get("code_root", "") or "").strip()
        reason = str(kwargs.get("reason", "") or "").strip()
        if not code_root:
            return self._failure("[参数错误] update 必须提供 code_root（待上线的 git 代码根）")
        if not reason:
            return self._failure("[参数错误] update 必须提供非空 reason（本次更新意图）")
        restart_target = str(
            kwargs.get("restart_target", "") or kwargs.get("target", "") or ""
        ).strip().lower()
        if not restart_target:
            restart_target = _derive_restart_target(code_root)
        if restart_target not in {"web", "feishu", "learning", "all"}:
            return self._failure(
                "[参数错误] update restart_target 必须是 web/feishu/learning/all"
            )

        deployment, error = self._publish(code_root, kwargs.get("expected_generation"))
        if error is not None:
            return self._failure(error)
        if deployment is None:
            return self._failure("[service_control update failed] publish 未返回 deployment")

        try:
            receipt = self.store.accept_restart(
                target=restart_target,
                expected_generation=deployment.generation,
                requester_session_id=self._session_id_getter(),
                origin="update",
            )
        except (
            DeploymentGenerationConflictError,
            BarrierConflictError,
            OSError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            # desired 已推进但物理未受理：如实回报已生效的一半，附继续路径。
            return self._failure(
                "[service_control update partial] desired 已发布到 "
                f"generation={deployment.generation}（git_head={deployment.git_head}），"
                f"但 restart 受理失败：{exc}; 可用 service_control(action=restart, "
                f"target={restart_target}, expected_generation={deployment.generation}) 继续; "
                + _next_step_text([NEXT_STEP_KIND_GENERATION_CONFLICT])
            )
        try:
            self._worker_spawner(receipt.action_id)
        except Exception as exc:  # noqa: BLE001 - failed spawn must become durable failure
            with contextlib.suppress(Exception):
                self.store.update_action(
                    receipt.action_id,
                    status="failed",
                    detail=f"worker spawn failed: {type(exc).__name__}: {exc}",
                )
            return self._failure(
                f"[service_control worker spawn failed] {type(exc).__name__}: {exc}"
            )

        live_hint = self._live_identity_hint(deployment, restart_target)
        body: dict[str, object] = {
            "updated": {
                "action_id": receipt.action_id,
                "target": restart_target,
                "generation": deployment.generation,
                "git_head": deployment.git_head,
                "webui_artifact_sha256": deployment.webui_artifact_sha256,
                "reason": reason,
            },
            "next": (
                "desired 已固化并已受理物理重启（异步）；用 "
                f"service_control(action=status, action_id={receipt.action_id}) 查询实际生效身份与证据"
            ),
        }
        if live_hint:
            body["live_identity_hint"] = live_hint
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(body, ensure_ascii=False, sort_keys=True),
            tool_call_id="",
            tool_name=self.name,
        )

    def _live_identity_hint(
        self, deployment: ManagedServiceDeployment, restart_target: str
    ) -> str:
        """AC-12: 目标 live 身份已是本次 desired 时，明确提示"本次不改变运行版本"."""
        try:
            services = compose_service_identity_view(self.store).get("services") or {}
        except (OSError, ValueError, json.JSONDecodeError):
            return ""
        targets = list(services) if restart_target == "all" else [restart_target]
        same = [
            service
            for service in targets
            if ((services.get(service) or {}).get("live") or {}).get("git_head")
            == deployment.git_head
        ]
        if not same:
            return ""
        return (
            "以下目标 live git_head 已等于本次 desired（"
            + ",".join(sorted(same))
            + "），本次不会改变其运行版本"
        )

    def _exit_action(self, action: str, kwargs: dict) -> ToolResult:
        """模型侧门禁出口：release/adopt/override/verify_acknowledge（design 2.2.2.2-2.2.2.5）."""
        try:
            if action == "release":
                result = release_admission_barrier(
                    self.store,
                    service=str(kwargs.get("service", "") or ""),
                    reason=str(kwargs.get("reason", "") or ""),
                    expected_operation_id=str(
                        kwargs.get("expected_operation_id", "") or ""
                    ),
                    evidence=str(kwargs.get("evidence", "") or ""),
                    force=bool(kwargs.get("force", False)),
                )
            elif action == "adopt":
                result = adopt_admission_barrier(
                    self.store,
                    service=str(kwargs.get("service", "") or ""),
                    expected_owner=str(kwargs.get("expected_owner", "") or ""),
                    reason=str(kwargs.get("reason", "") or ""),
                    evidence=str(kwargs.get("evidence", "") or ""),
                    new_owner=str(kwargs.get("new_owner", "") or ""),
                )
            elif action == "override":
                result = record_model_override(
                    self.store,
                    action_id=str(kwargs.get("action_id", "") or ""),
                    gate=str(kwargs.get("gate", "") or ""),
                    evidence=str(kwargs.get("evidence", "") or ""),
                    evidence_level=str(kwargs.get("evidence_level", "") or ""),
                    reason=str(kwargs.get("reason", "") or ""),
                )
            else:  # verify_acknowledge
                result = acknowledge_verify(
                    self.store,
                    action_id=str(kwargs.get("action_id", "") or ""),
                    verdict=str(kwargs.get("verdict", "") or ""),
                    evidence=str(kwargs.get("evidence", "") or ""),
                    reason=str(kwargs.get("reason", "") or ""),
                )
        except (ValueError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            return self._failure(
                f"[service_control {action} rejected] {type(exc).__name__}: {exc}"
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(
                {"action": action, **result}, ensure_ascii=False, sort_keys=True
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
