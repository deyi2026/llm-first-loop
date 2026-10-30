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
    DeploymentBindingError,
    DeploymentGenerationConflictError,
    ManagedServiceDeployment,
    ManagedServiceDeploymentStore,
    acknowledge_verify,
    adopt_admission_barrier,
    binding_next_steps,
    build_deployment,
    compose_convergence_view,
    compose_service_identity_view,
    record_model_override,
    release_admission_barrier,
    spawn_service_control_worker,
)
from llm_loop.runtime.service_control_derivation import (
    RestartTargetDerivation,
    derive_restart_target,
)
from llm_loop.tools.review_gate import GATE_NOTE_PREFIX


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


_ACTION_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "status": (),
    "publish": ("code_root",),
    "update": ("code_root", "reason"),
    "restart": ("target",),
    "release": ("service", "reason"),
    "adopt": ("service", "expected_owner", "evidence", "reason"),
    "override": ("action_id", "gate", "evidence", "evidence_level", "reason"),
    "verify_acknowledge": ("action_id", "verdict", "evidence", "reason"),
}

_SERVICE_TARGETS = ("web", "feishu", "wecom", "learning", "all")
_MANAGED_SERVICES = ("web", "feishu", "wecom", "learning")
_VERIFY_VERDICTS = ("accept", "reobserve", "override")
_EVIDENCE_LEVELS = ("E1", "E2", "E3")


def _service_control_contract_error(action: str, kwargs: dict) -> str:
    """Return one aggregated mechanical argument error before any side effect."""

    if action not in _ACTION_REQUIRED_FIELDS:
        return ""
    missing = [
        field
        for field in _ACTION_REQUIRED_FIELDS[action]
        if not str(kwargs.get(field, "") or "").strip()
    ]
    invalid: list[str] = []
    if action == "restart":
        target = str(kwargs.get("target", "") or "").strip().lower()
        if target and target not in _SERVICE_TARGETS:
            invalid.append(f"target={target!r} (allowed={list(_SERVICE_TARGETS)})")
    elif action == "update":
        target = str(
            kwargs.get("restart_target", "") or kwargs.get("target", "") or ""
        ).strip().lower()
        if target and target not in _SERVICE_TARGETS:
            invalid.append(
                f"restart_target={target!r} (allowed={list(_SERVICE_TARGETS)})"
            )
    elif action in {"release", "adopt"}:
        service = str(kwargs.get("service", "") or "").strip().lower()
        if service and service not in _MANAGED_SERVICES:
            invalid.append(f"service={service!r} (allowed={list(_MANAGED_SERVICES)})")
    elif action == "override":
        level = str(kwargs.get("evidence_level", "") or "").strip().upper()
        if level and level not in _EVIDENCE_LEVELS:
            invalid.append(
                f"evidence_level={level!r} (allowed={list(_EVIDENCE_LEVELS)})"
            )
    elif action == "verify_acknowledge":
        verdict = str(kwargs.get("verdict", "") or "").strip().lower()
        if verdict and verdict not in _VERIFY_VERDICTS:
            invalid.append(f"verdict={verdict!r} (allowed={list(_VERIFY_VERDICTS)})")
    if not missing and not invalid:
        return ""
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if invalid:
        details.append("invalid=" + "; ".join(invalid))
    return (
        f"[参数错误] service_control action={action} 参数契约不满足: "
        + "; ".join(details)
        + "；请按本回执一次性修正全部字段；若需字段类型/enum，先读取 "
        "get_tool_schema(service_control)"
    )


class ServiceControlTool:
    name = "service_control"
    description = (
        "共享 Web/Feishu/Learning 生命周期控制面。status 只读返回 desired deployment/action 回执；"
        "publish 把干净 git 代码根发布为新 desired deployment（程序校验 tracked 树干净 + webui dist "
        "产物 hash 绑定，并自动以当前 generation 做 CAS）；"
        "update 单语义完成'固化期望部署 + 物理生效'，内部编排 publish+restart，模型无需自己分两步；"
        "restart 由 detached worker 两阶段执行（等待 requester 会话结束/目标空闲时不占 lifecycle "
        "lease，物理重启阶段复核 generation），按 desired-state exact code_root/runtime_root 调 "
        "official restart_mirror。建议显式带 expected_generation=最新 status 观察值（可省略，"
        "缺省自动取当前 desired 代）；generation 冲突回执即当前事实：直接以回执 current 重试"
        "（存活 owner ≤一 poll 可过；死 worker 由 reaper 按 30s/120s/2100s 分档回收），"
        "不等待、不询问。"
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
                "enum": ["web", "feishu", "wecom", "learning", "all"],
                "description": "restart 目标；status/publish 时可省略",
            },
            "restart_target": {
                "type": "string",
                "enum": ["web", "feishu", "wecom", "learning", "all"],
                "description": (
                    "update 可选：物理生效目标；缺省按 code_root basename 的 token 精确推导"
                    "（如 feishu-code→feishu），推导不出则 NEEDS_TARGET 拒绝，需显式指定"
                ),
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
                "enum": ["web", "feishu", "wecom", "learning"],
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
        review_gate_recorder: Callable[[dict], str] | None = None,
    ) -> None:
        self.store = store
        self._worker_spawner = worker_spawner or (
            lambda action_id: spawn_service_control_worker(self.store, action_id)
        )
        self._session_id_getter = session_id_getter or (lambda: current_session_id.get() or "")
        # EVO-20261014-7ba73d88: publish 闸提示记录器（factory 注入）。
        self._review_gate_recorder = review_gate_recorder

    def _review_gate_line(self) -> str:
        """Deployment observation only; service publish is not article publication."""
        fact = ""
        recorder = getattr(self, "_review_gate_recorder", None)
        if recorder is not None:
            try:
                fact = str(
                    recorder(
                        {
                            "action_kind": "deployment_publish",
                            "tool": "service_control",
                            "action": "publish",
                        }
                    )
                    or ""
                )
            except Exception:  # noqa: BLE001 - 观测失败不构成审查资格或免审
                fact = ""
        if not fact:
            fact = "unknown（未注入探测器）"
        return (
            f"{GATE_NOTE_PREFIX} service_control publish 是代码部署，非文稿发表｜"
            f"观测线索（审查资格未核验）: {fact}｜"
            "本行不授予文稿发表资格或扩大原授权"
        )

    def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get("action", "") or "").strip().lower()
        contract_error = _service_control_contract_error(action, kwargs)
        if contract_error:
            return self._failure(contract_error)
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
            # EVO-20261014-7ba73d88: publish 闸提示（动作前探测，成功/失败回执均携带）。
            gate_note = self._review_gate_line()
            deployment, error = self._publish(
                str(kwargs.get("code_root", "") or "").strip(),
                kwargs.get("expected_generation"),
            )
            if error is not None:
                return self._failure(f"{gate_note}\n{error}")
            assert deployment is not None
            # EVO-20260924-dc3c7c78：成功回执附只读收敛快照（同眼可见
            # lagging）；读取失败缺省该键，可见性增强不反噬成功回执。
            publish_body: dict[str, object] = {
                "published": deployment.to_dict(),
                "review_gate": gate_note,
                "next": (
                    "desired 已推进；对 convergence.lagging 中仍落后的服务逐个 "
                    "service_control(action=restart, target=..., "
                    f"expected_generation={deployment.generation}) 完成重启"
                ),
            }
            convergence = self._convergence_block()
            if convergence is not None:
                publish_body["convergence"] = convergence
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=json.dumps(publish_body, ensure_ascii=False, sort_keys=True),
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
        if target not in {"web", "feishu", "wecom", "learning", "all"}:
            return self._failure("[参数错误] restart target 必须是 web/feishu/wecom/learning/all")
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
                "两阶段等待（web/all 先等 requester 会话结束，再等目标空闲）期间不占 publish 锁。"
                "受理≠完成：后台动作的终态是异步事实——未查询到 status=succeeded/failed"
                " 不得当作已完成/已失败宣布；终态核对入口："
                "service_control(action=status, action_id=...)（或 status 含 action 摘要），"
                "event_stream(query=service_action_terminal) 亦可检索（EVO-20260924-8266b693 A）；"
                "failed 终态会保留待确认（verify_acknowledge）直到显式闭合"
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
            # 三层决策（CT-2/3，消除文本猜测与裸串）：结构化 kind 直读 →
            # ValueError 类型兜底 → 环境类映射（git 二进制缺失/子进程失败 →
            # GIT_HEAD_UNAVAILABLE，既有 note"git 不可用或非 worktree，非
            # service_control 可修复"精准命中）。
            if isinstance(exc, DeploymentBindingError):
                binding_kind = exc.kind
            elif isinstance(exc, ValueError):
                binding_kind = BindingProblemKind.GIT_STATUS_UNAVAILABLE
            else:
                binding_kind = BindingProblemKind.GIT_HEAD_UNAVAILABLE
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
        """L12/L13/L15: 单语义更新——内部编排 publish 的绑定+CAS 与 restart 两阶段.

        T2（2026-10-27）：缺省目标按 basename token 精确推导（单实现源
        ``service_control_derivation``），推导不出不得静默兜底 all——校验阶段
        NEEDS_TARGET 拒绝（先于 publish/CAS，零副作用）；显式传参优先，回执
        仅在推导生效时标注 derived_from。
        """
        code_root = str(kwargs.get("code_root", "") or "").strip()
        reason = str(kwargs.get("reason", "") or "").strip()
        if not code_root:
            return self._failure("[参数错误] update 必须提供 code_root（待上线的 git 代码根）")
        if not reason:
            return self._failure("[参数错误] update 必须提供非空 reason（本次更新意图）")
        explicit_target = str(
            kwargs.get("restart_target", "") or kwargs.get("target", "") or ""
        ).strip().lower()
        derivation: RestartTargetDerivation | None = None
        if explicit_target:
            restart_target = explicit_target
        else:
            derivation = derive_restart_target(code_root)
            if derivation.target is None:
                return self._failure(
                    "[service_control update rejected] NEEDS_TARGET: code_root basename "
                    f"{derivation.basename!r} 无法唯一推导 restart_target（token 精确匹配"
                    "要求恰好一个服务名 token；无服务名或多服务歧义均不推导）；可选 "
                    "target=web/feishu/wecom/learning/all；示例: service_control(action=update, "
                    "code_root={code_root}, restart_target=web, reason=<意图>)；"
                    "本次未产生任何 publish/CAS 写入，请显式指定后重试"
                )
            restart_target = derivation.target
        if restart_target not in {"web", "feishu", "wecom", "learning", "all"}:
            return self._failure(
                "[参数错误] update restart_target 必须是 web/feishu/wecom/learning/all"
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
        # 先组装局部 updated（dict[str, object]），最后整体赋给 body["updated"]；
        # 直接对 body["updated"] 下标赋值会触发 pyright reportIndexIssue（值为
        # object），且键集、层级、出现条件必须保持不变。
        updated: dict[str, object] = {
            "action_id": receipt.action_id,
            "target": restart_target,
            "generation": deployment.generation,
            "git_head": deployment.git_head,
            "webui_artifact_sha256": deployment.webui_artifact_sha256,
            "reason": reason,
        }
        if derivation is not None:
            # T2：目标由推导得来 → 显式标注推导依据（basename 与命中 token）；
            # 显式传参时不标注。
            updated["derived_from"] = {
                "basename": derivation.basename,
                "matched_token": derivation.matched_token,
            }
        body: dict[str, object] = {
            "updated": updated,
            "next": (
                "desired 已固化并已受理物理重启（异步）；用 "
                f"service_control(action=status, action_id={receipt.action_id}) 查询实际生效身份与证据"
            ),
        }
        if live_hint:
            body["live_identity_hint"] = live_hint
        # EVO-20260924-dc3c7c78：成功回执附只读收敛快照——受理≠完成，剩余
        # lagging 服务在回执里直接可见；读取失败缺省该键。
        convergence = self._convergence_block()
        if convergence is not None:
            body["convergence"] = convergence
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(body, ensure_ascii=False, sort_keys=True),
            tool_call_id="",
            tool_name=self.name,
        )

    def _convergence_block(self) -> dict[str, object] | None:
        """EVO-20260924-dc3c7c78：publish/update 成功回执的只读收敛快照。

        复用 compose_convergence_view（identity view 派生，无新判据）；读取
        失败时返回 None（调用方缺省该键），可见性增强不反噬成功回执本身。
        """
        try:
            return compose_convergence_view(self.store)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

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
