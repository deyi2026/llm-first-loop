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
    ServiceControlAction,
    acknowledge_verify,
    adopt_admission_barrier,
    binding_next_steps,
    build_deployment,
    compose_convergence_view,
    compose_service_identity_view,
    compose_service_identity_with_guard_freshness,
    next_check_for_action,
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
    elif action == "status":
        view = str(kwargs.get("view", "") or "").strip().lower()
        if view and view not in _STATUS_VIEWS:
            invalid.append(f"view={view!r} (allowed={list(_STATUS_VIEWS)})")
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


_STATUS_VIEWS = ("targets", "full")


def _drift_status(value: object) -> object:
    """guard_code_drift 可能是 dict（含 status）或标量，取可读状态不猜结构."""
    if isinstance(value, dict):
        return value.get("status")
    return value


def _compose_status_body(
    store: ManagedServiceDeploymentStore, target: str = "", view: str = ""
) -> dict[str, object]:
    """status 载荷组装：默认 targets（每服务一行），view=full 取完整证据面.

    2026-11-01 实测：完整视图 45570 字符，工具回执被截断时正好丢掉各服务实况
    （generation_lag 521 条占 32710）。默认改成"每服务现在什么样"，完整证据面
    显式 view=full（该信号已在 runtime 层按 target 去重封顶，不再无限膨胀）。
    """
    resolved = (view or "targets").strip().lower() or "targets"
    if resolved not in _STATUS_VIEWS:
        raise ValueError(f"view={resolved!r} (allowed={list(_STATUS_VIEWS)})")
    identity = compose_service_identity_with_guard_freshness(store)
    body = _full_status_body(identity) if resolved == "full" else _targets_status_body(identity)
    scope = (target or "").strip().lower()
    return _narrow_status_body(body, scope) if scope and scope != "all" else body


def _full_status_body(identity: dict) -> dict[str, object]:
    """完整证据面：与历史 status 载荷同键（只多一个 view 标记）."""
    return {
        "view": "full",
        "deployment": identity["deployment"],
        "services": identity["services"],
        "admission_barriers": identity.get("admission_barriers", []),
        "available_exits": identity.get("available_exits", []),
        "gate_classification": identity.get("gate_classification", []),
        "compat_retirement": identity.get("compat_retirement", []),
        "idle_state": identity.get("idle_state", {}),
        "stage_facts": identity.get("stage_facts", {}),
        "evidence_refs": identity.get("evidence_refs", {}),
        "audit_signals": identity.get("audit_signals", {}),
    }


def _targets_status_body(identity: dict) -> dict[str, object]:
    """紧凑视图：每服务一行关键事实 + 障碍/待裁决 + 滞后摘要."""
    services: dict[str, object] = {}
    for name, entry in (identity.get("services") or {}).items():
        live = entry.get("live") or {}
        services[name] = {
            "pid": live.get("pid"),
            "alive": live.get("pid_alive"),
            "started_at": live.get("started_at"),
            "git_head": str(live.get("git_head") or "")[:12],
            "manifest_present": live.get("manifest_present"),
            "matches_desired_generation": live.get("matches_desired_generation"),
            "restart_required": entry.get("restart_required"),
            "admission_barrier": entry.get("admission_barrier"),
            "terminal_action_barrier": entry.get("terminal_action_barrier"),
            "reasons": entry.get("reasons"),
            "guard_code_drift": _drift_status(live.get("guard_code_drift")),
        }
    audit = identity.get("audit_signals") or {}
    return {
        "view": "targets",
        "hint": "view=full 取完整证据面（gate_classification/compat_retirement/evidence_refs）",
        "deployment": identity["deployment"],
        "services": services,
        "admission_barriers": identity.get("admission_barriers", []),
        "stage_facts": identity.get("stage_facts", {}),
        "audit_summary": {
            "generation_lag": audit.get("generation_lag", []),
            "orphan_barrier": audit.get("orphan_barrier"),
            "waiting_timeout": audit.get("waiting_timeout"),
            # 非终态动作（一行一动作）：这是"改了为什么还没生效"的直接答案。
            # 此前的 targets 视图只表达"该不该重启"（restart_required），不表达
            # "正在等什么"，读的人分不清"等我这轮结束"和"卡死"。
            "in_flight": audit.get("in_flight", []),
        },
    }


def _narrow_status_body(body: dict[str, object], scope: str) -> dict[str, object]:
    """按服务收窄：只留该服务的条目（对 targets/full 两种视图都生效）."""
    services = body.get("services")
    if isinstance(services, dict) and scope not in services:
        raise ValueError(
            f"target={scope!r} 不在 services ({sorted(services)}); allowed=all"
        )
    narrowed = dict(body)
    if isinstance(services, dict):
        narrowed["services"] = {scope: services[scope]}
    for key in ("stage_facts", "evidence_refs", "idle_state"):
        section = body.get(key)
        if isinstance(section, dict) and scope in section:
            narrowed[key] = {scope: section[scope]}
    barriers = body.get("admission_barriers")
    if isinstance(barriers, list):
        narrowed["admission_barriers"] = [
            item
            for item in barriers
            if isinstance(item, dict) and scope in {item.get("service"), item.get("target")}
        ]
    exits = body.get("available_exits")
    if isinstance(exits, list):
        narrowed["available_exits"] = [
            item
            for item in exits
            if isinstance(item, dict) and scope in {item.get("service"), item.get("target")}
        ]
    audit = narrowed.get("audit_summary") or narrowed.get("audit_signals")
    if isinstance(audit, dict):
        lag = audit.get("generation_lag")
        if isinstance(lag, list):
            audit = dict(audit)
            audit["generation_lag"] = [
                item
                for item in lag
                if isinstance(item, dict) and item.get("target") == scope
            ]
            narrowed["audit_summary" if "audit_summary" in narrowed else "audit_signals"] = audit
        # in_flight 按覆盖面收窄：target=all 的动作仍留下（它对每个服务都在等），
        # 只把 services 收窄到 scope——否则 target=web 会连带全量四服务。
        flight = audit.get("in_flight")
        if isinstance(flight, list):
            audit = dict(audit)
            kept: list[dict[str, object]] = []
            for item in flight:
                if not isinstance(item, dict):
                    continue
                covered = item.get("services")
                services = covered if isinstance(covered, list) else []
                if scope not in services and item.get("target") != scope:
                    continue
                kept.append({**item, "services": [scope]})
            audit["in_flight"] = kept
            narrowed["audit_summary" if "audit_summary" in narrowed else "audit_signals"] = audit
    narrowed["target"] = scope
    return narrowed


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
                "description": "restart 目标；status 时用于按服务收窄回执；publish 时可省略",
            },
            "view": {
                "type": "string",
                "enum": ["targets", "full"],
                "description": (
                    "status 可选：targets（默认，每服务一行关键事实+障碍+滞后摘要，"
                    "约 2KB）；full=完整证据面（含 gate_classification/compat_retirement/"
                    "evidence_refs/audit_signals，约 13KB）"
                ),
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
            return self._status(kwargs)

        if action == "publish":
            return self._publish_action(kwargs)

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
                + self._deferred_restart_note(target)
                + self._next_check_note(receipt)
            ),
            tool_call_id="",
            tool_name=self.name,
        )

    def _status(self, kwargs: dict[str, object]) -> ToolResult:
        """status 两形态：单动作回执（附 next_check 契约）或聚合视图。"""
        action_id = str(kwargs.get("action_id", "") or "").strip()
        if action_id:
            return self._status_by_action_id(action_id)
        try:
            body = _compose_status_body(
                self.store,
                str(kwargs.get("target", "") or ""),
                str(kwargs.get("view", "") or ""),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return self._failure(f"[service_control status failed] {type(exc).__name__}: {exc}")
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(body, ensure_ascii=False, sort_keys=True),
            tool_call_id="",
            tool_name=self.name,
        )

    def _status_by_action_id(self, action_id: str) -> ToolResult:
        """单动作回执：原字段 + 非终态动作的 ``next_check``（只读派生，不新增门禁）。"""
        try:
            receipt = self.store.read_action(action_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return self._failure(f"[service_control status failed] {type(exc).__name__}: {exc}")
        if receipt is None:
            return self._failure(f"[service_control] action_id not found: {action_id}")
        body: dict[str, object] = {"action": receipt.to_dict()}
        next_check = next_check_for_action(
            receipt, extra_gates=self._deferred_gates(receipt)
        )
        if next_check is not None:
            body["next_check"] = next_check
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(body, ensure_ascii=False, sort_keys=True),
            tool_call_id="",
            tool_name=self.name,
        )

    def _publish_action(self, kwargs: dict[str, object]) -> ToolResult:
        """模型侧 publish：与 CLI publish 同一套机械边界（干净树 + dist hash + CAS）。

        shell 围栏不动（CLI 仍 operator-only），模型走本工具；runtime_root 按
        data_dir 契约推导，不接受调用点自选。EVO-20261014-7ba73d88: 成功/失败
        回执均携带 review 闸提示。
        """
        gate_note = self._review_gate_line()
        deployment, error = self._publish(
            str(kwargs.get("code_root", "") or "").strip(),
            kwargs.get("expected_generation"),
        )
        if error is not None:
            return self._failure(f"{gate_note}\n{error}")
        assert deployment is not None
        return self._publish_result(deployment, gate_note)

    def _publish_result(self, deployment: ManagedServiceDeployment, gate_note: str) -> ToolResult:
        """publish 成功回执：desired 快照 + 收敛快照 + 可直接执行的 restart 清单。

        ``restart_required`` 复用 ``compose_convergence_view`` 的 ``lagging``
        （同一判据：stable_generation != desired_generation），不另立第二套判定；
        收敛快照读取失败时缺省该键，可见性增强不反噬成功回执。
        """
        convergence, restart_required = self._convergence_blocks()
        body: dict[str, object] = {
            "published": deployment.to_dict(),
            "review_gate": gate_note,
            "next": (
                "desired 已推进；restart_required 列出的服务（= convergence.lagging，"
                "判据 stable_generation != desired_generation）逐个 "
                "service_control(action=restart, target=..., "
                f"expected_generation={deployment.generation}) 完成重启；"
                "restart_required 缺失表示收敛快照读取失败，改用 status 复核"
            ),
        }
        if restart_required is not None:
            body["restart_required"] = restart_required
        if convergence is not None:
            body["convergence"] = convergence
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(body, ensure_ascii=False, sort_keys=True),
            tool_call_id="",
            tool_name=self.name,
        )

    @staticmethod
    def _deferred_gates(receipt: ServiceControlAction) -> tuple[str, ...]:
        """web 类两阶段门（``action.target in {web, all}``）：accepted 态还没落到
        status 上，但回执得自证"还差哪道门"——否则 target=all 会被读成已重启。"""
        if receipt.target in {"web", "all"} and receipt.status in {
            "accepted",
            "waiting_for_requester_exit",
        }:
            return ("waiting_for_requester_exit",)
        return ()

    @staticmethod
    def _next_check_note(receipt: ServiceControlAction) -> str:
        """非终态重启回执的「下一轮怎么验」契约（严格 JSON，可 json.loads）。

        两阶段门只有两个真实出口：本轮 run 自然结束、或 override + 证据。把
        "为什么还没生效"和"下一轮查什么"写成键，才不用靠人读段落自己记。
        """
        payload = next_check_for_action(
            receipt, extra_gates=ServiceControlTool._deferred_gates(receipt)
        )
        if payload is None:
            return ""
        return "; next_check=" + json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _deferred_restart_note(target: str) -> str:
        """web 类重启必然等待 requester run 结束：把「尚未生效」写成机器可读待办。

        第一阶段闸门挂在**动作**上（`action.target in {"web","all"}`，见
        runtime 两阶段等待），所以 target=all 时整条动作（四个服务）都在等待，
        不只是 web——回执若只写 web，读回执的人会以为其余三个已重启完成。

        payload 必须是可 json.loads 的严格 JSON：回执里写了"机器可读"就得真能解析。
        """
        if target not in {"web", "all"}:
            return ""
        deferred = ["web"] if target == "web" else ["web", "feishu", "wecom", "learning"]
        payload = json.dumps(
            {
                "pending": True,
                "condition": "requester_run_end",
                "services": deferred,
                "effective_after_session_end": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        names = "/".join(deferred)
        return (
            f"; deferred_effect={payload} —— 对 {names} **尚未生效**："
            "进程要等本轮 run 结束后才重启，在此之前 status/state 仍读旧 generation。"
            "会话结束后必须用 service_control(action=status, target=...) 复核 effective "
            "generation 才能声称已运行新代码"
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
        convergence, restart_required = self._convergence_blocks()
        if restart_required is not None:
            body["restart_required"] = restart_required
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

    def _convergence_blocks(
        self,
    ) -> tuple[dict[str, object] | None, list[str] | None]:
        """收敛快照 + 由其次级键 ``lagging`` 派生的 restart 清单。

        publish 回执里的 ``restart_required`` 直接就是 ``lagging``——同一判据
        （stable_generation != desired_generation），不在这里做第二套判断。
        """
        convergence = self._convergence_block()
        if convergence is None:
            return None, None
        lagging = convergence.get("lagging")
        if not isinstance(lagging, list):
            return convergence, None
        return convergence, [str(service) for service in lagging]

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
