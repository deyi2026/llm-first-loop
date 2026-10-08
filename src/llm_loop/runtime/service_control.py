"""Mechanical shared-service lifecycle authority for LFL Web/Feishu.

This module deliberately separates three things:

* ``ManagedServiceDeployment`` is operator-published desired deployment identity.
  PID/process observations never create or change that authority.
* ``ManagedServiceMutationGuard`` is a narrow accident fence for generic shell
  execution.  It blocks known LFL shared-service lifecycle mutations and points
  callers at the dedicated ``service_control`` tool; it is not an OS sandbox.
* service-control actions are durable before a detached worker may execute the
  official restart script.  The worker derives code/runtime roots only from the
  desired deployment record, never from caller cwd or inherited business env.
  Restarts execute two-phase: waiting (requester exit, target idle) holds no
  lifecycle lease so publication is never blocked by a waiting action; the
  physical restart runs under the lifecycle lease with a fresh generation
  check.

The model still decides whether a restart is useful.  Program code owns only the
physical authority boundary and exact generation/root binding.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import logging
import os
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from llm_loop.resources.foreground import active_run_locks
from llm_loop.runtime.admission_barrier import (
    AdmissionBarrierRegistry,
    BarrierConflictError,
)
from llm_loop.runtime.learning_idle import learning_busy_reason
from llm_loop.timekeeping import system_local_now

_DEPLOYMENT_SCHEMA = "managed-service-deployment/v1"

logger = logging.getLogger(__name__)
_ACTION_SCHEMA = "service-control-action/v1"
_DEPLOYMENT_FIELDS = frozenset(
    {
        "schema",
        "deployment_id",
        "generation",
        "git_head",
        "code_root",
        "runtime_root",
        "webui_artifact_sha256",
    }
)
_ACTION_FIELDS = frozenset(
    {
        "schema",
        "action_id",
        "action",
        "target",
        "deployment_id",
        "deployment_generation",
        "requester_session_id",
        "status",
        "created_at",
        "updated_at",
        "detail",
    }
)
# v1 只读兼容：以下字段是 SPEC lifecycle_agency 新增的可选证据/出口字段，
# 旧记录缺失时按空值解析；存在时严格解析。新增必填字段才递增 schema 版本，
# 这里全部可选，故仍为 v1 且双向可读（design 2.2.1）。
_ACTION_OPTIONAL_FIELDS = frozenset(
    {
        "stage_fact",
        "reason_ref",
        "model_override",
        "verify_evidence",
        "verify_verdict",
        "origin",
        # svc_deploy N2: 被拒动作的可执行下一步（JSON 数组文本），与既有 6 项
        # 同族同层；旧记录缺失即空值，不递增 schema 版本。
        "next_step",
        # EVO-20260924-8266b693 B: failed 动作"待确认"闭合戳；旧记录缺失即未确认。
        "acknowledged_at",
        # 生命周期加固（GOAL-20261008-f143e051）：执行 worker pid；旧记录缺失即 0
        # （未知，reaper 回退旧 2100s 时窗）。
        "worker_pid",
    }
)
_MANAGED_SERVICES = ("web", "feishu", "learning")
_ACTION_TARGETS = ("web", "feishu", "learning", "all")
_ACTION_STATUSES = frozenset(
    {
        "accepted",
        "waiting_for_requester_exit",
        "waiting_for_idle",
        "running",
        # design 2.1.3.4: 两个**非终态**中间态承载"证据 ≠ 裁决"——
        # restarted=物理完成、verify_evidence_ready=证据就绪待模型裁决。
        "restarted",
        "verify_evidence_ready",
        "succeeded",
        "failed",
    }
)

# Two-phase restart waiting budgets (seconds). Waiting phases deliberately run
# WITHOUT the global lifecycle lease: publishing a desired deployment must
# never be blocked by a restart action that is merely waiting for its
# requester session to finish or for the target to become idle. Both waits
# fail closed; there is no model-side force-through path.
_REQUESTER_EXIT_POLL_S = 2.0
_REQUESTER_EXIT_TIMEOUT_S = 900.0
_IDLE_POLL_S = 5.0
_IDLE_TIMEOUT_S = 900.0
_STALE_WAITING_MARGIN_S = 300.0
# 生命周期加固（GOAL-20261008-f143e051）：waiting action 带 worker_pid 时，
# reaper 可按进程存活判定提前回收——dead-pid 宽限覆盖 poll 间隔与 stamp 延迟，
# 把 caller 超时杀 worker 的锁死窗口从最长 2100s 收缩到秒级。
_STALE_PID_GRACE_S = 30.0
# lifecycle_agency L6/L7（已删除）: 旧 `_VERIFY_MAX_ATTEMPTS=2` 让程序据核验
# 结论自动重跑脚本并自动判终态——这是程序替模型做策略判断（违反 Q5），也是
# "判据缺失被当失败"的来源。现 `_verify_restart_targets` 只产三态证据
# （confirmed_ok/confirmed_fail/criterion_absent），重跑由模型经
# verify_acknowledge 显式发起；判据缺失不否决。
_VERIFY_POLL_S = 2.0
_VERIFY_TIMEOUT_S = 180.0
_VERIFY_MANIFEST_WAIT_S = 2.0

# §8.2: 准入屏障覆盖目标服务的全部入口——target=all 覆盖三个受管服务。
_MANAGED_SERVICE_NAMES = ("web", "feishu", "learning")

# lifecycle_agency L4（已删除）: 旧 `_RESTART_PRECHECK_FAILED_MARKERS` 白名单用
# detail 文本猜测"本次失败是否零物理副作用"——程序在做语义判断（违反 Q5）。
# 现改由脚本产出结构化 `stage_fact`（not_started/…/started），worker 只读该
# 字段：stage_fact == not_started 即零副作用，可释放屏障；其余按事实 keep。
# 新增失败形态不再需要扩白名单（消除 2026-09-22 13:20 的"白名单死窗"）。
# §6 路径契约：回执相对路径单源常量，经 build_restart_plan 的
# LFL_RESTART_RECEIPT_REL 注入脚本；脚本侧回退默认值必须与此字节一致，
# 禁止任何一侧另行猜路径发现。
_RESTART_RECEIPT_REL = "data/restart-receipt.json"

# --------------------------------------------------------------------------
# 门禁分级静态声明（design 2.1.3.2 / SPEC lifecycle_agency 任务 1.2）
#
# 这是**静态声明**而非运行时裁决：把"硬拒还是降级、有没有模型出口"收敛为
# 可审计常量，取代散落在 case 分支里的隐式顺序。分级依据只有两条：
#   ① 该事实是否可被模型通过现有工具改变？
#   ② 该事实是否是不可协商的物理/授权边界？
#
# physical_impossible / identity_conflict 保留硬拒，且 **不得** 被 override
# 穿透（命中时返回明确拒绝理由，不静默）。其余为 consistency：门禁降级为
# 证据呈现，模型可经结构化出口举证推进。
# --------------------------------------------------------------------------
GATE_CLASS_PHYSICAL_IMPOSSIBLE = "physical_impossible"
GATE_CLASS_IDENTITY_CONFLICT = "identity_conflict"
GATE_CLASS_CONSISTENCY = "consistency"

_NO_OVERRIDE_CLASSES = frozenset(
    {GATE_CLASS_PHYSICAL_IMPOSSIBLE, GATE_CLASS_IDENTITY_CONFLICT}
)


@dataclass(frozen=True)
class GateClassification:
    """One gate's static class + the model-callable exit that satisfies it."""

    gate: str
    category: str
    exit_action: str
    script_gate: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "gate": self.gate,
            "category": self.category,
            "exit_action": self.exit_action,
            "script_gate": self.script_gate,
            "reason": self.reason,
        }

    @property
    def override_allowed(self) -> bool:
        return self.category not in _NO_OVERRIDE_CLASSES


_GATE_CLASSIFICATION_ENTRIES: tuple[GateClassification, ...] = (
    GateClassification(
        gate="waiting_for_requester_exit",
        category=GATE_CLASS_CONSISTENCY,
        exit_action="override",
        script_gate="",
        reason="requester 会话是否仍在跑是可被模型举证的状态，不应是唯一出路",
    ),
    GateClassification(
        gate="waiting_for_idle",
        category=GATE_CLASS_CONSISTENCY,
        exit_action="override",
        script_gate="",
        reason="目标忙碌是可被机械复验/模型举证的运行时状态",
    ),
    GateClassification(
        gate="precheck:artifact",
        category=GATE_CLASS_CONSISTENCY,
        exit_action="update",
        script_gate="webui_artifact_preflight",
        reason="产物缺失是模型可通过构建修复的状态；应给缺失清单而非硬拒",
    ),
    GateClassification(
        gate="precheck:service_binding",
        category=GATE_CLASS_IDENTITY_CONFLICT,
        exit_action="",
        script_gate="service_control_binding",
        reason="desired 绑定是身份事实，漂移后果不可逆；模型须重新 publish",
    ),
    GateClassification(
        gate="precheck:active_run",
        category=GATE_CLASS_CONSISTENCY,
        exit_action="override",
        script_gate="active_run_precheck",
        reason='"无法确认"≠"忙碌"；模型可举证推进',
    ),
    GateClassification(
        gate="precheck:dual_root",
        category=GATE_CLASS_CONSISTENCY,
        exit_action="override",
        script_gate="dual_root",
        reason="树脏/嵌套是模型可解释的状态，可举证",
    ),
    GateClassification(
        gate="precheck:dual_root_identity",
        category=GATE_CLASS_IDENTITY_CONFLICT,
        exit_action="",
        script_gate="dual_root",
        reason="根身份不可解析时无法安全执行物理重启；程序无可替代",
    ),
    GateClassification(
        gate="precheck:root_source",
        category=GATE_CLASS_CONSISTENCY,
        exit_action="override",
        script_gate="root_source",
        reason="显式根已确认时，环境残留只应是告警证据而非硬拒",
    ),
    GateClassification(
        gate="precheck:knowledge_binding",
        category=GATE_CLASS_CONSISTENCY,
        exit_action="override",
        script_gate="knowledge_binding_preflight",
        reason="保留'分叉拒绝静默选赢家'内核，新增模型显式声明出口",
    ),
    GateClassification(
        gate="precheck:knowledge_store",
        category=GATE_CLASS_CONSISTENCY,
        exit_action="override",
        script_gate="knowledge_preflight",
        reason="store 健康是可恢复状态，模型可举证",
    ),
    GateClassification(
        gate="verify",
        category=GATE_CLASS_CONSISTENCY,
        exit_action="verify_acknowledge",
        script_gate="",
        reason="核验是证据采集，完成判断归模型",
    ),
    GateClassification(
        gate="barrier",
        category=GATE_CLASS_CONSISTENCY,
        exit_action="release|adopt|override",
        script_gate="",
        reason="屏障归属可由模型接管/释放/举证，非物理不可能",
    ),
    GateClassification(
        gate="port_in_use",
        category=GATE_CLASS_PHYSICAL_IMPOSSIBLE,
        exit_action="",
        script_gate="port_in_use",
        reason="端口独占是物理事实，程序无可替代",
    ),
    GateClassification(
        gate="process_mutex",
        category=GATE_CLASS_PHYSICAL_IMPOSSIBLE,
        exit_action="",
        script_gate="process_mutex",
        reason="同服务进程互斥是物理事实",
    ),
    GateClassification(
        gate="stop_failure",
        category=GATE_CLASS_PHYSICAL_IMPOSSIBLE,
        exit_action="",
        script_gate="stop_failure",
        reason="停止失败后启动会撞端口，物理不可能",
    ),
    GateClassification(
        gate="mirror_isolation",
        category=GATE_CLASS_PHYSICAL_IMPOSSIBLE,
        exit_action="",
        script_gate="mirror_isolation",
        reason="旧主区/镜像端口隔离是红线",
    ),
)

GATE_CLASSIFICATION: dict[str, GateClassification] = {
    entry.gate: entry for entry in _GATE_CLASSIFICATION_ENTRIES
}


def classify_gate(gate: str) -> GateClassification | None:
    """Static class lookup; None for an unregistered gate (caller decides)."""
    return GATE_CLASSIFICATION.get(gate)


def gate_override_allowed(gate: str) -> bool:
    """True only when the gate is consistency-class (non-physical/inherent)."""
    entry = GATE_CLASSIFICATION.get(gate)
    return bool(entry is not None and entry.override_allowed)


def gate_classification_view() -> list[dict[str, str]]:
    """Read-only view for ``status`` (evidence, never a gate)."""
    return [entry.to_dict() for entry in _GATE_CLASSIFICATION_ENTRIES]


@dataclass(frozen=True)
class CompatRetirement:
    """一条兼容层的**可机械观测**退役判据（tasks 8.3 / L18 / AC-17）.

    退役判据必须是可机械计数的事实（审计/log 中可数），不得是主观判断；
    本表只作证据呈现，不新增任何阻断行为（Admission asymmetry）。
    """

    layer: str
    location: str
    purpose: str
    retire_criterion: str
    observable_signal: str

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


COMPAT_RETIREMENT_CRITERIA: tuple[CompatRetirement, ...] = (
    CompatRetirement(
        layer="direct_restart_script",
        location="scripts/restart_mirror.sh",
        purpose="操作员应急通道（非权威，回执标注 authority=direct-non-authoritative）",
        retire_criterion="连续 N 次生命周期变更全部经 service_control 权威入口完成，且无一次直连",
        observable_signal="data/restart-receipt.log 中 authority!=service_control 的条数连续为 0",
    ),
    CompatRetirement(
        layer="control_subprocess_env_version_discipline",
        location="service_control.py:_control_subprocess_env/_control_code_root",
        purpose="防旧控制器执行新 worker（rolling rollback 安全）",
        retire_criterion="worker 与控制器同源（_control_code_root() == desired code_root）成为常态",
        observable_signal="审计中 worker_code_root==desired_code_root 的比例为 100%",
    ),
    CompatRetirement(
        layer="mixed_run_contract_f9",
        location="部署流程",
        purpose="脚本/worker 升级顺序等价",
        retire_criterion="部署工具链全程原子切根（无'脚本先升/worker 先升'窗口）",
        observable_signal="部署审计中不存在 script/worker 版本错配窗口记录",
    ),
    CompatRetirement(
        layer="root_source_four_state_branch",
        location="scripts/restart_mirror.sh:104-150（现 _root_source_check）",
        purpose="环境残留防污染",
        retire_criterion="所有调用点显式注入 LFL_RESTART_*_CONFIRMED=1",
        observable_signal="data/audit/restart_preflight.log 中 code_root_source=same-repo-defer 条数为 0",
    ),
)


def compat_retirement_view() -> list[dict[str, str]]:
    """Read-only view of compat-layer retirement criteria (evidence, never a gate)."""
    return [entry.to_dict() for entry in COMPAT_RETIREMENT_CRITERIA]


def _barrier_services_for_target(target: str) -> tuple[str, ...]:
    """Services whose NEW-run admission a restart target must gate (§8.2)."""
    if target == "all":
        return _MANAGED_SERVICE_NAMES
    return (target,)


class DeploymentGenerationConflictError(RuntimeError):
    """Desired deployment changed since the caller observed it."""


@dataclass(frozen=True)
class ManagedServiceDeployment:
    schema: str
    deployment_id: str
    generation: int
    git_head: str
    code_root: str
    runtime_root: str
    webui_artifact_sha256: str

    def __post_init__(self) -> None:
        if self.schema != _DEPLOYMENT_SCHEMA:
            raise ValueError(f"unsupported deployment schema: {self.schema!r}")
        if not self.deployment_id.strip():
            raise ValueError("deployment_id must be non-empty")
        if not isinstance(self.generation, int) or self.generation < 1:
            raise ValueError("generation must be a positive integer")
        if not re.fullmatch(r"[0-9a-f]{40}", self.git_head):
            raise ValueError("git_head must be an exact 40-char lowercase SHA")
        for label, raw in (("code_root", self.code_root), ("runtime_root", self.runtime_root)):
            path = Path(raw).expanduser()
            if not path.is_absolute():
                raise ValueError(f"{label} must be absolute")
        if not re.fullmatch(r"[0-9a-f]{64}", self.webui_artifact_sha256):
            raise ValueError("webui_artifact_sha256 must be sha256 hex")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ManagedServiceDeployment:
        keys = frozenset(raw)
        unknown = sorted(keys - _DEPLOYMENT_FIELDS)
        missing = sorted(_DEPLOYMENT_FIELDS - keys)
        if unknown:
            raise ValueError(f"deployment unknown fields: {unknown}")
        if missing:
            raise ValueError(f"deployment missing fields: {missing}")
        return cls(
            schema=str(raw["schema"]),
            deployment_id=str(raw["deployment_id"]),
            generation=int(raw["generation"]),
            git_head=str(raw["git_head"]),
            code_root=str(raw["code_root"]),
            runtime_root=str(raw["runtime_root"]),
            webui_artifact_sha256=str(raw["webui_artifact_sha256"]),
        )


@dataclass(frozen=True)
class ServiceControlAction:
    schema: str
    action_id: str
    action: Literal["restart"]
    target: Literal["web", "feishu", "learning", "all"]
    deployment_id: str
    deployment_generation: int
    requester_session_id: str
    status: Literal[
        "accepted",
        "waiting_for_requester_exit",
        "waiting_for_idle",
        "running",
        "restarted",
        "verify_evidence_ready",
        "succeeded",
        "failed",
    ]
    created_at: str
    updated_at: str
    detail: str = ""
    # --- SPEC lifecycle_agency 可选证据/出口字段（v1 兼容，缺失即空） ---
    # 结构化阶段事实（L4）：not_started/web_stopped/feishu_stopped/learning_stopped/started
    stage_fact: str = ""
    # 完整原因稳定引用（L19）：展示层截断，durable 源经 ref 可回读
    reason_ref: str = ""
    # 模型举证推进记录（JSON 文本；worker 于等待循环读取）
    model_override: str = ""
    # 核验证据与模型裁决（L6/L7：证据 ≠ 裁决）
    verify_evidence: str = ""
    verify_verdict: str = ""
    # 触发来源：restart / update（update 是 publish+restart 的单语义封装）
    origin: str = ""
    # svc_deploy N2：被拒动作的可执行下一步（JSON 数组文本；空 = 未产生）。
    # 结构化、有界、不参与 detail 的 2000/400 截断；模型经 status 自动透出。
    next_step: str = ""
    # EVO-20260924-8266b693 B：failed 动作的"待确认"闭合戳（ISO 时间；空 = 未确认）。
    # v1 兼容：旧 action 文件无此键 → 默认空（未确认）。确认入口
    # verify_acknowledge(verdict=accept) on failed；确认前 failed 动作持续占用
    # pending_actions 投影与开场状态提醒（即使 desired 代已前进/被新动作接管）。
    acknowledged_at: str = ""
    # 生命周期加固（GOAL-20261008-f143e051）：执行 worker pid（0 = 未知/旧记录）。
    # reaper 据此按进程存活判定 waiting 回收，替代纯时间窗。
    worker_pid: int = 0

    def __post_init__(self) -> None:
        if self.schema != _ACTION_SCHEMA:
            raise ValueError(f"unsupported action schema: {self.schema!r}")
        if not self.action_id.strip():
            raise ValueError("action_id must be non-empty")
        if self.action != "restart":
            raise ValueError("P0-A only supports restart")
        if self.target not in _ACTION_TARGETS:
            raise ValueError(f"unsupported target: {self.target}")
        if self.deployment_generation < 1:
            raise ValueError("deployment_generation must be positive")
        if self.status not in _ACTION_STATUSES:
            raise ValueError(f"invalid action status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ServiceControlAction:
        keys = frozenset(raw)
        unknown = sorted(keys - (_ACTION_FIELDS | _ACTION_OPTIONAL_FIELDS))
        missing = sorted(_ACTION_FIELDS - keys)
        if unknown:
            raise ValueError(f"action unknown fields: {unknown}")
        if missing:
            raise ValueError(f"action missing fields: {missing}")
        return cls(
            schema=str(raw["schema"]),
            action_id=str(raw["action_id"]),
            action=str(raw["action"]),  # type: ignore[arg-type]
            target=str(raw["target"]),  # type: ignore[arg-type]
            deployment_id=str(raw["deployment_id"]),
            deployment_generation=int(raw["deployment_generation"]),
            requester_session_id=str(raw["requester_session_id"]),
            status=str(raw["status"]),  # type: ignore[arg-type]
            created_at=str(raw["created_at"]),
            updated_at=str(raw["updated_at"]),
            detail=str(raw["detail"]),
            stage_fact=str(raw.get("stage_fact") or ""),
            reason_ref=str(raw.get("reason_ref") or ""),
            model_override=str(raw.get("model_override") or ""),
            verify_evidence=str(raw.get("verify_evidence") or ""),
            verify_verdict=str(raw.get("verify_verdict") or ""),
            origin=str(raw.get("origin") or ""),
            next_step=str(raw.get("next_step") or ""),
            acknowledged_at=str(raw.get("acknowledged_at") or ""),
            worker_pid=int(raw.get("worker_pid") or 0),
        )


@dataclass(frozen=True)
class ManagedServiceGuardDecision:
    blocked: bool
    reason: str
    services: tuple[str, ...] = ()


@dataclass(frozen=True)
class RestartPlan:
    argv: tuple[str, ...]
    cwd: str
    env: dict[str, str]


def _local_now() -> str:
    return system_local_now().isoformat()


# ---- DRC T2 写路径（service_control_state partial → conform，2026-10-08）----
# 复用 ScheduleStore durability contract（scheduler._commit_state 两阶段语义；
# DESIGN-20261007-durable-run-contract §4 契约红线 1：T2 覆写禁止裸 write_text、
# 禁止 fail-open 吞写失败）：
#   replace 前（确定性区）：tmp O_EXCL → write → flush → file fsync → os.replace，
#     整 payload 可有界重试；任何失败清理 tmp，主状态保持旧全文；
#   replace 后（durability fence 区）：只重试 directory fsync，绝不再次
#     rewrite/rename 同一 semantic mutation。
# 耗尽分型：
#   replace 前失败 → ServiceControlPersistError（outcome=definitely_not_committed）；
#   replace 后目录 fsync 耗尽 → ServiceControlCommitUncertainError
#     （outcome=commit_outcome_uncertain，expected_sha256 + 持锁逐字 readback 的
#     visible_state）；调用方禁止把 uncertain 解释成"肯定没写"后盲重放。
# 调用约定：两个调用点（compare_and_swap / _write_action_unlocked）均持
# ManagedServiceDeploymentStore.lease，readback 因此是单写者视野下的核对。
_STATE_PERSIST_ATTEMPTS = 3
_STATE_PERSIST_RETRY_DELAY_S = 0.05


class ServiceControlPersistError(OSError):
    """service-control 状态确定未提交（replace 前失败/目录不可用）。"""

    outcome = "definitely_not_committed"


class ServiceControlCommitUncertainError(ServiceControlPersistError):
    """replace 已生效但 directory fsync 耗尽；禁止盲重放语义 mutation。"""

    outcome = "commit_outcome_uncertain"

    def __init__(
        self,
        *,
        path: Path,
        expected_sha256: str,
        visible_state: str,
        cause: OSError,
    ) -> None:
        super().__init__(f"service-control 状态 replace 已生效但 durability 未确认: {cause}")
        self.path = str(path)
        self.expected_sha256 = str(expected_sha256)
        self.visible_state = str(visible_state)
        self.cause = cause

    def __str__(self) -> str:
        base = super().__str__()
        return (
            f"{base}; outcome={self.outcome}; visible_state={self.visible_state}; "
            f"expected_sha256={self.expected_sha256}"
        )


def _write_temp_exclusive(temp: Path, text: str) -> None:
    """独占创建 tmp 并完整写入 + file fsync（半写只污染 tmp，不碰主状态）。"""
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(directory: Path) -> None:
    """目录 fsync：让 rename 本身在掉电后可见（对齐 scheduler._fsync_directory）。"""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _payload_visible_state(path: Path, payload: str) -> str:
    """持 state lease 时核当前文件是否逐字等于 intended payload."""
    try:
        current = path.read_text(encoding="utf-8")
    except OSError:
        return "unreadable"
    return "matches" if current == payload else "mismatch"


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    """T2 原子覆写：tmp+file fsync+replace+目录 fsync；失败分型显式抛出。

    调用方必须已持 ``ManagedServiceDeploymentStore.lease``（单写者）。
    """
    payload = json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n"
    payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ServiceControlPersistError(f"service-control 状态目录不可用: {exc}") from exc

    last: OSError = OSError("service-control state persist: no attempt recorded")
    for attempt in range(1, _STATE_PERSIST_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(_STATE_PERSIST_RETRY_DELAY_S * (attempt - 1))
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            _write_temp_exclusive(tmp, payload)
            os.replace(tmp, path)
            break
        except OSError as exc:
            last = exc
            logger.warning(
                "service-control 状态 replace 前写失败（attempt %s/%s）: %s",
                attempt,
                _STATE_PERSIST_ATTEMPTS,
                exc,
            )
        finally:
            tmp.unlink(missing_ok=True)
    else:
        logger.error(
            "service-control 状态确定未提交（replace 前重试 %s 次耗尽）: %s",
            _STATE_PERSIST_ATTEMPTS,
            last,
        )
        raise ServiceControlPersistError(
            f"service-control 状态确定未提交（replace 前重试 {_STATE_PERSIST_ATTEMPTS} 次后放弃）: {last}"
        ) from last

    last_dir: OSError = OSError("service-control directory fsync: no attempt recorded")
    for attempt in range(1, _STATE_PERSIST_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(_STATE_PERSIST_RETRY_DELAY_S * (attempt - 1))
        try:
            _fsync_directory(path.parent)
            return
        except OSError as exc:
            last_dir = exc
            logger.warning(
                "service-control 状态 replace 后目录 fsync 失败（attempt %s/%s）: %s",
                attempt,
                _STATE_PERSIST_ATTEMPTS,
                exc,
            )
    visible_state = _payload_visible_state(path, payload)
    logger.error(
        "service-control 状态 commit outcome uncertain：replace 已发生但目录 fsync 重试耗尽；"
        "visible_state=%s expected_sha256=%s",
        visible_state,
        payload_sha256,
    )
    raise ServiceControlCommitUncertainError(
        path=path,
        expected_sha256=payload_sha256,
        visible_state=visible_state,
        cause=last_dir,
    ) from last_dir


class EvidenceRef:
    """L19: durable exact-source store for long reasons.

    先落完整源，再给展示层一个稳定引用（内容寻址 `reason:<sha256>`）；展示
    层的 `[:N]` 截断只影响回执片段，模型可经 ref 回读完整内容（对齐
    DEVELOPMENT_REPAIR_SAFETY Q1/Q2）。禁止把凭证/绝对私有路径的*引用*写入
    公开产物——引用本身只是内容哈希。
    """

    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self._root = Path(data_dir).expanduser() / "audit" / "reasons"

    def write_full(self, reason: str) -> str:
        blob = str(reason or "")
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        target = self._root / f"{digest}.txt"
        if not target.is_file():
            self._root.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{digest}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            tmp.write_text(blob, encoding="utf-8")
            tmp.replace(target)
        return f"reason:{digest}"

    def resolve(self, ref: str) -> str | None:
        token = str(ref or "")
        if not token.startswith("reason:"):
            return None
        digest = token[len("reason:") :]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return None
        try:
            return (self._root / f"{digest}.txt").read_text(encoding="utf-8")
        except OSError:
            return None


def _durable_detail(store: ManagedServiceDeploymentStore, detail: str) -> tuple[str, str]:
    """L19: 先写完整源并返回稳定 ref，再返回展示片段。

    "仅存截断片段而声称原因已记录"被显式禁止（spec 4.4-2）：只要 detail 非空，
    完整内容必落 durable 源，片段与完整源可经 ``reason_ref`` 区分。
    """
    full = str(detail or "")
    if not full:
        return "", ""
    return full[:2000], store.evidence.write_full(full)


# --------------------------------------------------------------------------
# svc_deploy N2：问题类 → 可执行下一步（单点映射，纯函数零 IO）
#
# 目的：把"被拒之后怎么走"写进模型/操作者实际拿到的回执。映射输入是**结构化
# 类别**（BindingProblemKind），**禁止**解析 detail 文本/正则/相似度猜测（对齐
# DEVELOPMENT_REPAIR_SAFETY Q5）。新增问题类 = 枚举加一项 + 本表加一行，不必
# 扩启发式白名单。
# --------------------------------------------------------------------------


class BindingProblemKind:
    """封闭枚举：binding 核验的 8 类问题（字面值即持久化/断言口径）。"""

    CODE_ROOT_MISMATCH = "code_root_mismatch"
    RUNTIME_ROOT_MISMATCH = "runtime_root_mismatch"
    GIT_HEAD_UNAVAILABLE = "git_head_unavailable"
    GIT_HEAD_MISMATCH = "git_head_mismatch"
    TRACKED_WORKTREE_DIRTY = "tracked_worktree_dirty"
    GIT_STATUS_UNAVAILABLE = "git_status_unavailable"
    WEBUI_ARTIFACT_UNAVAILABLE = "webui_artifact_unavailable"
    WEBUI_ARTIFACT_MISMATCH = "webui_artifact_mismatch"

    ALL = frozenset(
        {
            CODE_ROOT_MISMATCH,
            RUNTIME_ROOT_MISMATCH,
            GIT_HEAD_UNAVAILABLE,
            GIT_HEAD_MISMATCH,
            TRACKED_WORKTREE_DIRTY,
            GIT_STATUS_UNAVAILABLE,
            WEBUI_ARTIFACT_UNAVAILABLE,
            WEBUI_ARTIFACT_MISMATCH,
        }
    )


class DeploymentBindingError(ValueError):
    """binding 核验失败的结构化异常（svc_deploy CT-2/3：消除消费方文本猜测）。

    消息文本与既有 ``ValueError`` 逐字一致；``kind`` 由产出方在抛出点一次性
    声明（取值 ∈ ``BindingProblemKind.ALL`` 字面值），消费方直读。
    """

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


# CAS 类冲突（非 binding 核验）复用同一映射表。
NEXT_STEP_KIND_GENERATION_CONFLICT = "generation_conflict"


@dataclass(frozen=True)
class BindingProblem:
    """一条 binding 问题：结构化类别 + 既有原文（逐字）+ 取值。

    ``text`` 与既有 ``verify_deployment_binding`` 的 problem 原文逐字一致，
    因此改由结构化事实源派生后，``verify_deployment_binding`` 的返回值不变。
    """

    kind: str
    text: str
    desired: str = ""
    actual: str = ""


@dataclass(frozen=True)
class NextStep:
    """一条指向既有可调用入口的下一步（事实型，不含完成裁决）。"""

    problem_kind: str
    exit_action: str
    argv_hint: str
    note: str


# argv_hint 只含参数名与占位符，不落真实绝对路径（INV-7）。
_NEXT_STEP_PUBLISH_ARGV_HINT = (
    "--code-root <code_root> --runtime-root <runtime_root> --data-dir <data_dir>"
)
_NEXT_STEP_KEYS = ("problem_kind", "exit_action", "argv_hint", "note")

# 单点映射表（顺序 = 输出顺序的声明优先级；deterministic、零 IO）。
_NEXT_STEP_BY_KIND: Mapping[str, NextStep] = {
    BindingProblemKind.GIT_HEAD_MISMATCH: NextStep(
        problem_kind=BindingProblemKind.GIT_HEAD_MISMATCH,
        exit_action="publish",
        argv_hint=_NEXT_STEP_PUBLISH_ARGV_HINT,
        note="desired 记录需推进到 code_root 当前 HEAD 后再 restart（走 publish/update）",
    ),
    BindingProblemKind.CODE_ROOT_MISMATCH: NextStep(
        problem_kind=BindingProblemKind.CODE_ROOT_MISMATCH,
        exit_action="publish",
        argv_hint=_NEXT_STEP_PUBLISH_ARGV_HINT,
        note="以 desired 记录的 code_root 规范路径重新 publish，再 restart",
    ),
    BindingProblemKind.RUNTIME_ROOT_MISMATCH: NextStep(
        problem_kind=BindingProblemKind.RUNTIME_ROOT_MISMATCH,
        exit_action="publish",
        argv_hint=_NEXT_STEP_PUBLISH_ARGV_HINT,
        note="以 desired 记录的 runtime_root 规范路径重新 publish，再 restart",
    ),
    BindingProblemKind.WEBUI_ARTIFACT_MISMATCH: NextStep(
        problem_kind=BindingProblemKind.WEBUI_ARTIFACT_MISMATCH,
        exit_action="publish",
        argv_hint=_NEXT_STEP_PUBLISH_ARGV_HINT,
        note="需先重建 webui/dist 产物后再 publish（程序不自动构建）",
    ),
    BindingProblemKind.WEBUI_ARTIFACT_UNAVAILABLE: NextStep(
        problem_kind=BindingProblemKind.WEBUI_ARTIFACT_UNAVAILABLE,
        exit_action="publish",
        argv_hint=_NEXT_STEP_PUBLISH_ARGV_HINT,
        note="webui/dist 缺失，需先构建产物后再 publish（程序不自动构建）",
    ),
    BindingProblemKind.TRACKED_WORKTREE_DIRTY: NextStep(
        problem_kind=BindingProblemKind.TRACKED_WORKTREE_DIRTY,
        exit_action="",
        argv_hint="",
        note="需先由操作者提交或还原 tracked 改动；程序不 stash/commit/checkout",
    ),
    BindingProblemKind.GIT_HEAD_UNAVAILABLE: NextStep(
        problem_kind=BindingProblemKind.GIT_HEAD_UNAVAILABLE,
        exit_action="",
        argv_hint="",
        note="git 不可用或非 worktree，非 service_control 可修复，无预设下一步",
    ),
    BindingProblemKind.GIT_STATUS_UNAVAILABLE: NextStep(
        problem_kind=BindingProblemKind.GIT_STATUS_UNAVAILABLE,
        exit_action="",
        argv_hint="",
        note="git status 不可用，非 service_control 可修复，无预设下一步",
    ),
    NEXT_STEP_KIND_GENERATION_CONFLICT: NextStep(
        problem_kind=NEXT_STEP_KIND_GENERATION_CONFLICT,
        exit_action="publish",
        argv_hint=_NEXT_STEP_PUBLISH_ARGV_HINT,
        note="以回执给出的 current 代重试（不自动重试）",
    ),
}

_NEXT_STEP_UNREGISTERED_NOTE = "no_preset_next_step"


def binding_next_steps(
    problems: Sequence[BindingProblem] | Sequence[str],
) -> tuple[NextStep, ...]:
    """问题类集合 → 下一步元组（按声明顺序去重，同输入同输出）。

    ``problems`` 既可传 ``BindingProblem`` 序列，也可传类别字面值序列。
    未登记类别输出显式 ``no_preset_next_step``（不猜、不丢原文）。
    """
    kinds: list[str] = []
    for problem in problems:
        kind = problem.kind if isinstance(problem, BindingProblem) else str(problem)
        if kind and kind not in kinds:
            kinds.append(kind)
    steps = [_NEXT_STEP_BY_KIND[kind] for kind in _NEXT_STEP_BY_KIND if kind in kinds]
    for kind in kinds:
        if kind not in _NEXT_STEP_BY_KIND:
            steps.append(
                NextStep(
                    problem_kind=kind,
                    exit_action="",
                    argv_hint="",
                    note=_NEXT_STEP_UNREGISTERED_NOTE,
                )
            )
    return tuple(steps)


def encode_next_steps(steps: Sequence[NextStep]) -> str:
    """NextStep 序列 → JSON 数组文本（空输入 → ``""``，确定性排序）。"""
    items = [dataclasses.asdict(step) for step in steps]
    if not items:
        return ""
    return json.dumps(items, ensure_ascii=False, sort_keys=True)


def decode_next_steps(raw: str) -> list[dict[str, str]]:
    """JSON 数组文本 → 展示数组；损坏/非数组/元素非 dict → ``[]``（诚实降级）。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            return []
        out.append({key: str(item.get(key) or "") for key in _NEXT_STEP_KEYS})
    return out


def _next_steps_view(kinds: Sequence[str]) -> list[dict[str, str]]:
    """类别集合 → 展示用 next_step 数组（单点映射 + 编解码，纯函数零 IO）。"""
    return decode_next_steps(encode_next_steps(binding_next_steps(kinds)))


class ManagedServiceDeploymentStore:
    """Closed-schema desired deployment + durable action receipts.

    ``service-control.lock`` is a cross-process mechanical lease.  It serializes
    desired-state CAS and action acceptance; observing a PID never grants this lease.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.runtime_dir = self.data_dir / "runtime"
        self.path = self.runtime_dir / "managed_service_deployment.json"
        self.lock_path = self.runtime_dir / "service-control-state.lock"
        self.lifecycle_lock_path = self.runtime_dir / "service-control.lock"
        self.actions_dir = self.runtime_dir / "service-control-actions"
        # §8.2 准入屏障：受理即建立、终态按服务粒度释放；同 data_dir 下
        # 与 actions 目录并列，所有进程（web/feishu/调度/CLI）读同一路径。
        self.barriers = AdmissionBarrierRegistry(self.data_dir)
        # L19: 完整原因稳定引用（展示层截断，durable 源可回读）。
        self.evidence = EvidenceRef(self.data_dir)

    @contextmanager
    def lease(self) -> Iterator[None]:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            try:
                import fcntl
            except ImportError as exc:  # pragma: no cover - production/CI are POSIX
                raise RuntimeError("service control requires POSIX fcntl locking") from exc
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def lifecycle_lease(self) -> Iterator[None]:
        """Serialize physical lifecycle execution against desired deployment publish."""
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        with self.lifecycle_lock_path.open("a+", encoding="utf-8") as handle:
            try:
                import fcntl
            except ImportError as exc:  # pragma: no cover - production/CI are POSIX
                raise RuntimeError("service control requires POSIX fcntl locking") from exc
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> ManagedServiceDeployment | None:
        if not self.path.is_file():
            return None
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("managed service deployment must be a JSON object")
        return ManagedServiceDeployment.from_dict(raw)

    def read(self) -> ManagedServiceDeployment | None:
        # Readers never take the state lease: every write is an atomic
        # same-directory tmp+file fsync+rename (_atomic_json, DRC T2), so a
        # reader observes the previous snapshot, the new snapshot, or no file
        # at all.
        # Observing missing state must stay physically read-only: no
        # directory/lock-file creation and no exclusive flock on the
        # read path (status/show/verify observations included).
        return self._read_unlocked()

    def compare_and_swap(
        self,
        deployment: ManagedServiceDeployment,
        *,
        expected_generation: int,
    ) -> None:
        if expected_generation < 0:
            raise ValueError("expected_generation must be >= 0")
        # Publishing a new desired deployment must not race a physical restart.
        # Lock order is always lifecycle -> state.
        with self.lifecycle_lease(), self.lease():
            current = self._read_unlocked()
            current_generation = current.generation if current is not None else 0
            if current_generation != expected_generation:
                raise DeploymentGenerationConflictError(
                    f"deployment generation changed: expected={expected_generation} current={current_generation}"
                )
            if deployment.generation != expected_generation + 1:
                raise ValueError(
                    "next deployment generation must equal expected_generation + 1 "
                    f"(next={deployment.generation}, expected={expected_generation})"
                )
            _atomic_json(self.path, deployment.to_dict())

    def action_path(self, action_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", action_id):
            raise ValueError("invalid action_id")
        return self.actions_dir / f"{action_id}.json"

    def read_action(self, action_id: str) -> ServiceControlAction | None:
        path = self.action_path(action_id)
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("service control action must be a JSON object")
        return ServiceControlAction.from_dict(raw)

    def _write_action_unlocked(self, action: ServiceControlAction) -> None:
        """Persist one action transition and reconcile post-replace uncertainty.

        `_atomic_json` deliberately surfaces directory-fsync exhaustion as
        `ServiceControlCommitUncertainError` even when the intended bytes are
        already visible. Action transitions have ordered post-write effects
        (barrier establish/release, terminal-event emission), so propagating a
        `visible_state=matches` uncertainty here would split the control
        state: the action file advances but its post-write effect is skipped.

        While holding the state lease, exact readback of the same action is a
        sufficient mechanical reconcile signal to continue those effects
        without rewriting/replaying the semantic transition. Any mismatch or
        unreadable state remains fail-closed.
        """
        path = self.action_path(action.action_id)
        try:
            _atomic_json(path, action.to_dict())
            return
        except ServiceControlCommitUncertainError as exc:
            if exc.visible_state != "matches":
                raise
            try:
                current = self.read_action(action.action_id)
            except (OSError, ValueError) as readback_exc:
                raise exc from readback_exc
            if current != action:
                raise exc
            logger.warning(
                "service-control action durability 未确认但 exact readback matches；"
                "按当前 action 状态继续后置 transition effects: action_id=%s status=%s",
                action.action_id,
                action.status,
            )

    def record_worker_pid(self, action_id: str, pid: int) -> None:
        """生命周期加固（GOAL-20261008-f143e051）：盖章执行 worker pid。

        幂等：pid 未变则不写（避免无谓 bump updated_at 重置 reaper 时窗）。
        仅写 pid 与 updated_at，不改 status/detail——与 update_action 的
        状态迁移/屏障释放/终态事件语义完全隔离。
        """
        with self.lease():
            action = self.read_action(action_id)
            if action is None or action.worker_pid == pid:
                return
            self._write_action_unlocked(
                dataclasses.replace(action, worker_pid=pid, updated_at=_local_now())
            )

    def _reap_stale_waiting_actions_unlocked(self) -> None:
        """Fail waiting actions whose detached worker died; defense in depth.

        生命周期加固（GOAL-20261008-f143e051）：优先按 worker_pid 存活判定——
        pid 已死且超过宽限即回收（秒级解锁屏障）；无 pid 的旧 action 或 pid
        复用等无法确认的场景回退原 2100s 时间窗。
        """
        now_ts = system_local_now().timestamp()
        stale_before = now_ts - (
            _REQUESTER_EXIT_TIMEOUT_S + _IDLE_TIMEOUT_S + _STALE_WAITING_MARGIN_S
        )
        pid_grace_before = now_ts - _STALE_PID_GRACE_S
        for path in sorted(self.actions_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                action = ServiceControlAction.from_dict(raw)
            except (OSError, ValueError):
                continue
            if action.status not in {"waiting_for_requester_exit", "waiting_for_idle"}:
                continue
            try:
                updated_ts = datetime.fromisoformat(action.updated_at).timestamp()
            except ValueError:
                updated_ts = 0.0
            reap_detail = ""
            if (
                action.worker_pid > 0
                and updated_ts < pid_grace_before
                and _pid_dead(action.worker_pid)
            ):
                reap_detail = (
                    f"stale waiting state reaped: worker pid {action.worker_pid} dead"
                )
            elif updated_ts < stale_before:
                reap_detail = "stale waiting state reaped: detached worker presumed dead"
            if not reap_detail:
                continue
            self._write_action_unlocked(
                dataclasses.replace(
                    action,
                    status="failed",
                    updated_at=_local_now(),
                    detail=reap_detail,
                )
            )
            # waiting 态未开始任何副作用：屏障随终态释放（§8.3）。
            for service in _barrier_services_for_target(action.target):
                self.barriers.release(service, operation_id=action.action_id)

    def update_action(
        self,
        action_id: str,
        *,
        status: Literal[
            "accepted",
            "waiting_for_requester_exit",
            "waiting_for_idle",
            "running",
            "restarted",
            "verify_evidence_ready",
            "succeeded",
            "failed",
        ],
        detail: str = "",
        stage_fact: str | None = None,
        verify_evidence: str | None = None,
        verify_verdict: str | None = None,
        model_override: str | None = None,
        origin: str | None = None,
        next_step: str | None = None,
        acknowledged_at: str | None = None,
    ) -> ServiceControlAction:
        with self.lease():
            action = self.read_action(action_id)
            if action is None:
                raise FileNotFoundError(action_id)
            detail_text, reason_ref = _durable_detail(self, detail)
            updated = dataclasses.replace(
                action,
                status=status,
                updated_at=_local_now(),
                detail=detail_text,
                reason_ref=reason_ref or action.reason_ref,
                stage_fact=action.stage_fact if stage_fact is None else stage_fact,
                verify_evidence=(
                    action.verify_evidence if verify_evidence is None else verify_evidence
                ),
                verify_verdict=(
                    action.verify_verdict if verify_verdict is None else verify_verdict
                ),
                model_override=(
                    action.model_override if model_override is None else model_override
                ),
                origin=action.origin if origin is None else origin,
                next_step=action.next_step if next_step is None else next_step,
                acknowledged_at=(
                    action.acknowledged_at if acknowledged_at is None else acknowledged_at
                ),
            )
            self._write_action_unlocked(updated)
            _release_barriers_for_transition(
                self,
                previous=action,
                updated=updated,
            )
            _emit_terminal_event(self, updated)
            return updated

    def accept_restart(
        self,
        *,
        target: str,
        expected_generation: int,
        requester_session_id: str,
        origin: str = "",
    ) -> ServiceControlAction:
        if target not in _ACTION_TARGETS:
            raise ValueError(f"unsupported restart target: {target}")
        with self.lease():
            deployment = self._read_unlocked()
            if deployment is None:
                raise DeploymentGenerationConflictError("managed service deployment is not published")
            if deployment.generation != expected_generation:
                raise DeploymentGenerationConflictError(
                    f"deployment generation changed: expected={expected_generation} "
                    f"current={deployment.generation}"
                )
            self._reap_stale_waiting_actions_unlocked()
            now = _local_now()
            action = ServiceControlAction(
                schema=_ACTION_SCHEMA,
                action_id=f"svc-{uuid.uuid4().hex}",
                action="restart",
                target=target,  # type: ignore[arg-type]
                deployment_id=deployment.deployment_id,
                deployment_generation=deployment.generation,
                requester_session_id=str(requester_session_id or ""),
                status="accepted",
                created_at=now,
                updated_at=now,
                detail="",
                # svc_deploy 5.3：审计可区分动作来源（update = publish+restart 单语义）。
                origin=origin,
            )
            self._write_action_unlocked(action)
            # §8.2-4：受理与屏障建立原子化——屏障建立失败时受理一并失败，
            # 把受理记录改写为 failed（可审计），不留"已受理但无屏障"的操作。
            established: list[str] = []
            adopted: list[str] = []
            conflict: BarrierConflictError | None = None

            def _rollback_claimed() -> None:
                for service in established + adopted:
                    self.barriers.release(service, operation_id=action.action_id)

            try:
                for service in _barrier_services_for_target(target):
                    try:
                        self.barriers.establish(
                            service,
                            operation_id=action.action_id,
                            reason="restart",
                        )
                        established.append(service)
                        continue
                    except BarrierConflictError as exc:
                        # S4b（§8.3 承诺的"后续操作接管"机制化）：owner 动作
                        # 已终态（failed/succeeded）→ 新动作接管屏障（无准入
                        # 窗口、留审计）；owner 非终态/未知/corrupt → 维持
                        # fail-closed，恢复路径仍是操作员覆盖 CLI。
                        current = self.barriers.blocked(service)
                        owner_id = (
                            current.operation_id
                            if current is not None and not current.corrupt
                            else ""
                        )
                        owner_action: ServiceControlAction | None = None
                        if owner_id:
                            try:
                                owner_action = self.read_action(owner_id)
                            except (OSError, ValueError):
                                owner_action = None
                        if (
                            owner_action is not None
                            and owner_action.status in {"failed", "succeeded"}
                            and self.barriers.adopt(
                                service,
                                operation_id=action.action_id,
                                previous_owner=owner_id,
                            )
                        ):
                            adopted.append(service)
                            continue
                        conflict = exc
                        break
            except OSError as exc:
                _rollback_claimed()
                self._write_action_unlocked(
                    dataclasses.replace(
                        action,
                        status="failed",
                        updated_at=_local_now(),
                        detail=f"admission barrier establishment failed, acceptance rejected: {exc}",
                    )
                )
                raise RuntimeError(
                    f"admission barrier establishment failed, acceptance rejected: {exc}"
                ) from exc
            if conflict is not None:
                _rollback_claimed()
                self._write_action_unlocked(
                    dataclasses.replace(
                        action,
                        status="failed",
                        updated_at=_local_now(),
                        detail=f"admission barrier conflict, acceptance rejected: {conflict}",
                    )
                )
                raise DeploymentGenerationConflictError(
                    f"admission barrier conflict, acceptance rejected: {conflict}"
                ) from conflict
            return action


def _read_process_command(pid: int) -> str:
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _service_command_matches(service: str, command: str) -> bool:
    if not command:
        return False
    return (
        f"llm_loop.runtime.launch {service}" in command
        or f"-m llm_loop.{service}" in command
    )


def _shell_segments(command: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"&&|\|\||;|\|", command) if segment.strip()]


def _kill_signal_is_probe(tokens: list[str]) -> bool:
    # ``kill -0 PID`` / ``kill -s 0 PID`` are liveness observations, not mutation.
    if "-0" in tokens:
        return True
    for idx, token in enumerate(tokens[:-1]):
        if token in {"-s", "--signal"} and tokens[idx + 1] == "0":
            return True
    return False


def _pid_alive(pid: int) -> bool:
    """Signal-0 liveness probe (observation only; never mutates the process)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        # EPERM = 进程存在但属主不同（macOS 上 pid 1/系统服务即此情形）。
        return True
    except OSError:
        return False
    return True


def latest_succeeded_actions(
    store: ManagedServiceDeploymentStore,
) -> dict[str, ServiceControlAction]:
    """Most recent succeeded restart receipt per target (read-only observation)."""
    latest: dict[str, ServiceControlAction] = {}
    if not store.actions_dir.is_dir():
        return latest
    for path in sorted(store.actions_dir.glob("*.json")):
        try:
            action = ServiceControlAction.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if action.action != "restart" or action.status != "succeeded":
            continue
        current = latest.get(action.target)
        try:
            action_updated_ts = datetime.fromisoformat(action.updated_at).timestamp()
        except ValueError:
            action_updated_ts = 0.0
        try:
            current_updated_ts = (
                datetime.fromisoformat(current.updated_at).timestamp()
                if current is not None
                else 0.0
            )
        except ValueError:
            current_updated_ts = 0.0
        if current is None or action_updated_ts > current_updated_ts:
            latest[action.target] = action
    return latest


def _barrier_view(store: ManagedServiceDeploymentStore, service: str) -> dict[str, Any] | None:
    """单服务屏障视图（None=无屏障）；供 identity 视图按服务暴露.

    design 2.2.2.6 / L20：并列 owner 身份、owner 动作状态、``corrupt`` 与
    当前状态**对应的可用出口列表**，交模型判断。
    """
    barrier = store.barriers.blocked(service)
    if barrier is None:
        return None
    view: dict[str, Any] = barrier.to_view()
    view["available_exits"] = ["release", "adopt", "override"]
    view["owner_action_status"] = None
    if barrier.operation_id:
        try:
            owner_action = store.read_action(barrier.operation_id)
        except Exception:  # noqa: BLE001 — 只读探测；视图不因单点坏数据失败
            owner_action = None
        view["owner_action_status"] = owner_action.status if owner_action else None
    return view


_TERMINAL_ACTION_STATUSES = frozenset({"succeeded", "failed"})


def _terminal_action_barrier_reason(
    store: ManagedServiceDeploymentStore, service: str
) -> str | None:
    """R3②: 终态 action 仍持屏障的孤儿信号（只读探测）.

    R1 落地后 worker 在消费 receipt 时释放屏障，因此该窗口只出现在
    worker 死亡/中断间隙；非 None 即"需要操作员介入"（覆盖 CLI）。
    """
    barrier = store.barriers.blocked(service)
    if barrier is None or barrier.corrupt or not barrier.operation_id:
        return None
    try:
        action = store.read_action(barrier.operation_id)
    except Exception:  # noqa: BLE001 — 只读探测；视图不因单点坏数据失败
        return "barrier_owner_action_unreadable"
    if action is None:
        return "barrier_owner_action_missing"
    if action.status in _TERMINAL_ACTION_STATUSES:
        return f"terminal_action_holds_barrier status={action.status}"
    return None


def read_all_actions(store: ManagedServiceDeploymentStore) -> list[ServiceControlAction]:
    """Read every action receipt (read-only; unreadable rows are skipped)."""
    actions: list[ServiceControlAction] = []
    try:
        paths = sorted(store.actions_dir.glob("*.json"))
    except OSError:
        return actions
    for path in paths:
        try:
            actions.append(
                ServiceControlAction.from_dict(json.loads(path.read_text(encoding="utf-8")))
            )
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return actions


def compose_lifecycle_evidence_view(store: ManagedServiceDeploymentStore) -> dict[str, Any]:
    """只读证据面（design 2.2.2.6 / tasks 9.1）：只**增**字段，不新增门禁.

    覆盖 L19（evidence_refs）、L20（屏障可用出口）、L22（idle_state 三态）、
    L24（audit_signals）与门禁分级表。读取路径零副作用：不建目录、不加锁。
    """
    actions = read_all_actions(store)
    latest_by_service: dict[str, ServiceControlAction] = {}
    for action in actions:
        for service in _MANAGED_SERVICES:
            if action.target not in {service, "all"}:
                continue
            current = latest_by_service.get(service)
            if current is None or action.updated_at > current.updated_at:
                latest_by_service[service] = action

    available_exits: list[dict[str, Any]] = []
    orphan_barrier: list[str] = []
    barrier_dir_changed: list[str] = []
    for service in _MANAGED_SERVICES:
        barrier = store.barriers.blocked(service)
        if barrier is None:
            continue
        available_exits.append(
            {
                "gate": "barrier",
                "service": service,
                "exits": ["release", "adopt", "override"],
            }
        )
        reason = _terminal_action_barrier_reason(store, service)
        if reason:
            if reason.startswith("terminal_action"):
                orphan_barrier.append(service)
            else:
                barrier_dir_changed.append(f"{service}: {reason}")

    for action in actions:
        gates = pending_gates_for_action(action)
        if not gates:
            continue
        exits = sorted(
            {
                entry.exit_action
                for gate in gates
                if (entry := classify_gate(gate)) is not None and entry.exit_action
            }
        )
        for gate in gates:
            available_exits.append(
                {
                    "gate": gate,
                    "action_id": action.action_id,
                    "target": action.target,
                    "exits": exits,
                }
            )

    deployment = store.read()
    generation_lag: list[dict[str, Any]] = []
    if deployment is not None:
        for action in actions:
            if (
                action.status == "succeeded"
                and action.deployment_generation < deployment.generation
            ):
                generation_lag.append(
                    {
                        "target": action.target,
                        "generation": action.deployment_generation,
                        "lag_generations": deployment.generation
                        - action.deployment_generation,
                    }
                )

    waiting_timeout: list[dict[str, Any]] = []
    now = system_local_now()
    timeout_s = _REQUESTER_EXIT_TIMEOUT_S + _IDLE_TIMEOUT_S + _STALE_WAITING_MARGIN_S
    for action in actions:
        if not action.status.startswith("waiting"):
            continue
        ts = _parse_iso(action.updated_at)
        if ts is None:
            continue
        age = (now - ts).total_seconds()
        if age > timeout_s:
            waiting_timeout.append(
                {
                    "action_id": action.action_id,
                    "status": action.status,
                    "age_s": round(age),
                }
            )

    runtime_root = str(store.data_dir.parent)
    idle_state: dict[str, dict[str, str]] = {}
    for target in ("web", "feishu", "learning", "all"):
        state, detail = _target_idle_state(target=target, runtime_root=runtime_root)
        idle_state[target] = {"state": state, "detail": detail}

    stage_facts = {
        service: {
            "action_id": action.action_id,
            "status": action.status,
            "stage_fact": action.stage_fact,
        }
        for service, action in latest_by_service.items()
    }
    evidence_refs = {
        service: {"action_id": action.action_id, "reason_ref": action.reason_ref}
        for service, action in latest_by_service.items()
        if action.reason_ref
    }
    return {
        "available_exits": available_exits,
        "gate_classification": gate_classification_view(),
        "compat_retirement": compat_retirement_view(),
        "idle_state": idle_state,
        "stage_facts": stage_facts,
        "evidence_refs": evidence_refs,
        "audit_signals": {
            "generation_lag": generation_lag,
            "orphan_barrier": orphan_barrier,
            "barrier_dir_changed": barrier_dir_changed,
            "waiting_timeout": waiting_timeout,
        },
    }


# 2026-09-24 修正: 8903 起（镜像权威端口）——8902 属旧主区残留口径，
# 判活扫描含 8902 时会把旧主区/无关监听误当 web（与 plist 错指同类）。
_WEB_PORT_FALLBACK_RANGE = ("8903", "8905")


def _web_port_listener_pid() -> int | None:
    """web 端口监听者 pid（单一权威探针=端口，fail-open）.

    2026-09-24 13:08 实证：guard 与权威通道并发重启（端口空窗 detect_fail），
    双 web 抢端口一活一死，死的（29502）写的 manifest 留下死 pid → 面板
    live_pid_not_running 误报而真实服务（29418）正监听。manifest 是
    last-writer 观察面，可被短命写者污染；端口不会被污染——有监听者即有服务。
    """
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-tiTCP:{_WEB_PORT_FALLBACK_RANGE[0]}-{_WEB_PORT_FALLBACK_RANGE[1]}",
             "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — 探测不可得 → None（不兜底）
        return None
    for token in out.split():
        try:
            pid = int(token)
        except ValueError:
            continue
        try:
            cmd = subprocess.run(
                ["ps", "-o", "command=", "-p", str(pid)],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            return None
        if cmd and "llm_loop" in cmd:
            return pid
    return None


def compose_service_identity_view(store: ManagedServiceDeploymentStore) -> dict[str, Any]:
    """Desired/live/stable identity view per managed service (read-only).

    - desired: operator-published deployment (generation + git_head + roots).
    - live: each service's own startup runtime manifest (pid/started_at/git_head).
    - stable: the latest succeeded controlled-restart receipt covering the
      service.  ``git_head`` is asserted only when that receipt still matches
      the current desired generation; older receipts keep generation-only
      facts (no invented identity).
    """
    deployment = store.read()
    succeeded = latest_succeeded_actions(store)
    services: dict[str, Any] = {}
    for service in _MANAGED_SERVICES:
        manifest_path = store.runtime_dir / f"runtime_manifest.{service}.json"
        live: dict[str, Any] = {"manifest_present": manifest_path.is_file()}
        if live["manifest_present"]:
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                pid = int(raw.get("pid") or 0)
                live.update(
                    {
                        "pid": pid or None,
                        "pid_alive": _pid_alive(pid),
                        "started_at": raw.get("started_at"),
                        "git_head": raw.get("git_head"),
                        "build": raw.get("build_identity") or {},
                        "model_ref": raw.get("model_ref"),
                        "provider_id": raw.get("provider_id"),
                        "config_hash": raw.get("config_hash"),
                        "semantic_scopes": raw.get("semantic_scopes") or {},
                        "semantic_scope_sources": raw.get("semantic_scope_sources") or {},
                    }
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                live["manifest_error"] = True
        # 2026-09-24 13:08 端口兜底：manifest pid 死但端口有 llm_loop 监听者 →
        # 以端口监听者为准（pid_source=port_listener），manifest 原值降级为
        # manifest_pid 保留展示。只修 web（feishu/learning 无统一端口口径），
        # 只在"manifest 声称的 pid 已死"时触发——活 pid 仍以 manifest 为准，
        # 不引入常态双探针抖动。
        if (
            service == "web"
            and live.get("pid")
            and not live.get("pid_alive")
            and not live.get("manifest_error")
        ):
            port_pid = _web_port_listener_pid()
            if port_pid is not None:
                live["manifest_pid"] = live.get("pid")
                live["manifest_pid_alive"] = False
                live["pid"] = port_pid
                live["pid_alive"] = True
                live["pid_source"] = "port_listener"
        if deployment is not None and not live.get("manifest_error"):
            # L8: live 代探测——runtime manifest 不携带 generation，只能用
            # git_head 与 desired 的相等性**推断**"live 是否已达到期望代"。
            # 这是推断而非身份事实：显式标注 inferred 并并列原始证据（pid/
            # manifest/head/started_at），由模型自行判断，不以推断冒充身份。
            live["matches_desired_generation"] = bool(live.get("pid_alive")) and (
                str(live.get("git_head") or "") == deployment.git_head
            )
            # design 2.2.2.6: live 代次只是推断事实，显式标注 inferred。
            live["inferred"] = True
            live["matches_desired_generation_inferred"] = True
            live["matches_desired_generation_evidence"] = {
                "pid": live.get("pid"),
                "pid_alive": live.get("pid_alive"),
                "git_head": live.get("git_head"),
                "started_at": live.get("started_at"),
                # 只暴露文件名，不落绝对私有路径到模型可读产物（spec 4.3-3）。
                "manifest": manifest_path.name,
                "manifest_present": bool(live.get("manifest_present")),
                "desired_git_head": deployment.git_head,
            }
        candidates = [
            action
            for target, action in succeeded.items()
            if target == service or target == "all"
        ]
        receipt = max(candidates, key=lambda a: a.updated_at) if candidates else None
        stable: dict[str, Any] | None = None
        if receipt is not None:
            matches = (
                deployment is not None
                and receipt.deployment_generation == deployment.generation
            )
            stable = {
                "action_id": receipt.action_id,
                "target": receipt.target,
                "generation": receipt.deployment_generation,
                "succeeded_at": receipt.updated_at,
                "git_head": deployment.git_head if matches and deployment else None,
                "matches_desired_generation": matches,
            }
            if deployment is not None and receipt.deployment_generation < deployment.generation:
                # R3①降级/R6: live 健康而回执落后只作完整性事实展示（直连
                # 重启是合法无回执路径），不进 restart_required。
                stable["lag_generations"] = (
                    deployment.generation - receipt.deployment_generation
                )
                stable["stale"] = bool(live.get("matches_desired_generation"))
                if stable["stale"]:
                    stable["note"] = (
                        "live 进程已新于回执（直连重启未写 durable 回执）；以 live 为准"
                    )
            else:
                # design 2.2.2.6: lag_generations 恒定存在（0=无代差，只读证据）。
                stable["lag_generations"] = 0
        reasons: list[str] = []
        if deployment is None:
            reasons.append("desired_deployment_missing")
        elif not live["manifest_present"]:
            reasons.append("live_manifest_missing")
        elif live.get("manifest_error"):
            reasons.append("live_manifest_unreadable")
        else:
            if live.get("pid") and not live.get("pid_alive"):
                reasons.append("live_pid_not_running")
            live_head = str(live.get("git_head") or "")
            if not live_head:
                reasons.append("live_git_head_missing")
            elif live_head != deployment.git_head:
                reasons.append(
                    f"live_git_head_mismatch live={live_head} desired={deployment.git_head}"
                )
        services[service] = {
            "live": live,
            "stable": stable,
            "restart_required": bool(reasons),
            "reasons": reasons,
            # §8.3: 准入屏障按服务可见——屏障仍活跃 = "受影响未恢复"，
            # 恢复路径是操作员覆盖 CLI 或后续操作接管，不得静默消失。
            "admission_barrier": _barrier_view(store, service),
            # R3②: 终态 action 仍持屏障（孤儿屏障）→ 需要操作员介入的
            # 唯一硬信号；正常 receipt 消费路径会先把它清掉。
            "terminal_action_barrier": _terminal_action_barrier_reason(store, service),
        }
    return {
        "deployment": deployment.to_dict() if deployment else None,
        "services": services,
        "admission_barriers": [b.to_view() for b in store.barriers.snapshot()],
        # design 2.2.2.6 / tasks 9.1：只读证据面（可用出口/分级表/空闲三态/
        # 阶段事实/证据引用/审计信号）。只增字段，不新增任何阻断行为。
        **compose_lifecycle_evidence_view(store),
        # 显示事实：服务器本地时区 UTC 偏移（分钟，含夏令时实时值）。前端据此
        # 把 ISO 时间渲染为"服务器挂钟"，与访问设备的浏览器时区无关。
        "server_tz_offset_minutes": round(
            system_local_now().utcoffset().total_seconds() // 60
        ),
    }


def compose_convergence_view(store: ManagedServiceDeploymentStore) -> dict[str, Any]:
    """Read-only per-service convergence snapshot (EVO-20260924-dc3c7c78).

    纯派生自 :func:`compose_service_identity_view`：``lagging`` = 最新
    succeeded 受控重启回执尚未覆盖当前 desired generation 的服务（含从未有
    succeeded 回执的服务）。只读证据面——不新增门禁/锁/restart action；
    用途是让 publish/update 成功回执在"同一眼"暴露代差，替代事后告警发现。
    """
    view = compose_service_identity_view(store)
    deployment = view.get("deployment") or {}
    desired_generation = deployment.get("generation")
    services: dict[str, Any] = {}
    lagging: list[str] = []
    for service, svc in sorted((view.get("services") or {}).items()):
        stable = (svc or {}).get("stable") or {}
        stable_generation = stable.get("generation")
        converged = (
            desired_generation is not None
            and stable_generation is not None
            and stable_generation == desired_generation
        )
        services[service] = {
            "stable_generation": stable_generation,
            "lag_generations": stable.get("lag_generations"),
            "converged": converged,
        }
        if not converged:
            lagging.append(service)
    return {
        "desired_generation": desired_generation,
        "services": services,
        "lagging": lagging,
        "read_only": True,
        "note": (
            "lagging=尚无覆盖当前 desired generation 的 succeeded restart "
            "receipt（含从未有 succeeded 回执的服务）；收敛是异步事实，"
            "本块只读、不派发 restart"
        ),
    }


def _append_exit_audit(store: ManagedServiceDeploymentStore, record: Mapping[str, Any]) -> None:
    """append-only 出口审计（L2/任务 7.4）：否决/接管/释放/拒绝各留一行。

    每行必含非空 reason 与操作者身份；重复行使否决产生多行而非覆盖。
    审计失败只告警，绝不阻断调用者（fail-open）。
    """
    audit_dir = store.data_dir / "audit"
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        payload = {"ts": _local_now(), **dict(record)}
        with (audit_dir / "service_control_exits.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        logger.warning("service-control exit audit append failed: %s", exc)


def _emit_terminal_event(store: ManagedServiceDeploymentStore, action: ServiceControlAction) -> None:
    """EVO-20260924-8266b693 A：终态（succeeded/failed）写统一事件流。

    失败只落私有 service-control 台账时无主动反馈通道——受理回执之外，
    succeeded/failed 终态事件进 requester 会话的事件流（event_stream 可检索，
    scope=workspace 亦可见）。fail-open：事件写入失败不阻断状态转移
    （audit 台账仍由调用方负责）。
    """
    if action.status not in {"succeeded", "failed"}:
        return
    sid = str(action.requester_session_id or "").strip()
    if not sid:
        return
    try:
        from llm_loop.event_log.store import EventStore

        event_store = EventStore(store.data_dir / "event_logs", enabled=True)
        event_store.append(
            sid,
            "service_action_terminal",
            {
                "action_id": action.action_id,
                "action": action.action,
                "target": action.target,
                "status": action.status,
                "generation": action.deployment_generation,
                "updated_at": action.updated_at,
                "detail": str(action.detail or "")[:200],
                "reason_ref": action.reason_ref,
                "acknowledged_at": action.acknowledged_at,
            },
        )
    except Exception as exc:  # noqa: BLE001 — 事件流不可用时 fail-open
        logger.warning("service-control terminal event append failed: %s", exc)


def _load_overrides(raw: str) -> list[dict[str, Any]]:
    """解析 action.model_override：JSON list（兼容单条 dict 旧格式）。"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []


def _override_gates_for_action(action: ServiceControlAction) -> str:
    """worker 注入脚本用的 gate 列表（仅 consistency 类，逗号分隔）。"""
    gates = [str(item.get("gate") or "") for item in _load_overrides(action.model_override)]
    return ",".join(gate for gate in gates if gate)


# 该 action 当前状态下可被 override 推进的门禁（只读派生；不新增门禁）。
_MANAGED_SERVICE_SET = frozenset(_MANAGED_SERVICES)
_PRECOMMIT_GATES: tuple[str, ...] = (
    "precheck:active_run",
    "precheck:dual_root",
    "precheck:root_source",
    "precheck:knowledge_binding",
    "precheck:knowledge_store",
)
_VERIFY_GATE = "verify"


def pending_gates_for_action(action: ServiceControlAction) -> tuple[str, ...]:
    """该 action 当前状态下可被 override 推进的 gate 列表（只读）。

    - waiting 态：仅对应 waiting gate；
    - 未进入终态（accepted/waiting/running）：脚本预检门（模型可预声明举证）；
    - restarted/verify_evidence_ready：核验门。
    终态（succeeded/failed）不再有 override 门——恢复路径是新动作 adopt/restart。
    """
    if action.status in {"succeeded", "failed"}:
        return ()
    if action.status == "waiting_for_requester_exit":
        return ("waiting_for_requester_exit",)
    if action.status == "waiting_for_idle":
        return ("waiting_for_idle",)
    if action.status in {"restarted", "verify_evidence_ready"}:
        return (_VERIFY_GATE,)
    if action.status == "running":
        return (*_PRECOMMIT_GATES, _VERIFY_GATE)
    # accepted / 其它非终态
    return _PRECOMMIT_GATES


def release_admission_barrier(
    store: ManagedServiceDeploymentStore,
    *,
    service: str,
    reason: str,
    expected_operation_id: str = "",
    evidence: str = "",
    force: bool = False,
    operator: str = "model",
) -> dict[str, Any]:
    """模型侧屏障释放出口（design 2.2.2.2 / L2）。

    幂等：屏障已不存在返回 already_absent（不报错）。owner 不匹配且非 force
    返回冲突事实与当前 owner（不静默）。force 仅对损坏/未知 owner 屏障生效。
    """
    service = str(service or "").strip()
    if service not in _MANAGED_SERVICE_SET:
        raise ValueError(f"unsupported service: {service!r}")
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("release requires a non-empty reason")

    current = store.barriers.blocked(service)
    if current is None:
        _append_exit_audit(
            store,
            {"event": "release", "service": service, "operator": operator,
             "reason": reason, "already_absent": True},
        )
        return {"released": False, "already_absent": True, "service": service}

    owner = "" if current.corrupt else current.operation_id
    if current.corrupt and not force:
        _append_exit_audit(
            store,
            {"event": "release_rejected", "service": service, "operator": operator,
             "reason": reason, "corrupt_requires_force": True},
        )
        return {
            "released": False,
            "corrupt_requires_force": True,
            "service": service,
            "hint": "损坏屏障需 release(force=true, reason=...) 才可清除",
        }
    expected = str(expected_operation_id or "").strip()
    if not force and expected and expected != owner:
        _append_exit_audit(
            store,
            {"event": "release_rejected", "service": service, "operator": operator,
             "reason": reason, "expected_operation_id": expected, "current_owner": owner},
        )
        return {
            "released": False,
            "conflict": {"current_owner": owner, "expected_operation_id": expected},
            "service": service,
            "hint": "owner 不匹配；不带 expected_operation_id 可释放当前 owner，或核对 status",
        }

    released = (
        store.barriers.force_release(service, reason=reason)
        if force
        else store.barriers.release(service, operation_id=owner)
    )
    _append_exit_audit(
        store,
        {"event": "release", "service": service, "operator": operator, "reason": reason,
         "evidence": str(evidence or ""), "previous_owner": owner, "force": force,
         "released": bool(released)},
    )
    if not released:
        return {"released": False, "already_absent": True, "service": service}
    return {"released": True, "service": service, "previous_owner": owner, "force": force}


def adopt_admission_barrier(
    store: ManagedServiceDeploymentStore,
    *,
    service: str,
    expected_owner: str,
    reason: str,
    evidence: str,
    new_owner: str = "",
    operator: str = "model",
) -> dict[str, Any]:
    """模型侧屏障接管出口（design 2.2.2.3 / L2、§8.3）。

    与 ``accept_restart`` 的自动 adopt 复用同一 registry.adopt；屏障连续
    （原子替换，不产生准入窗口）。owner 不符 → conflict(current_owner)；
    损坏 → corrupt_requires_force。
    """
    service = str(service or "").strip()
    if service not in _MANAGED_SERVICE_SET:
        raise ValueError(f"unsupported service: {service!r}")
    expected_owner = str(expected_owner or "").strip()
    reason = str(reason or "").strip()
    evidence = str(evidence or "").strip()
    if not expected_owner:
        raise ValueError("adopt requires expected_owner")
    if not reason:
        raise ValueError("adopt requires a non-empty reason")
    if not evidence:
        raise ValueError("adopt requires evidence (why the previous owner is no longer valid)")

    current = store.barriers.blocked(service)
    if current is None:
        _append_exit_audit(
            store,
            {"event": "adopt", "service": service, "operator": operator,
             "reason": reason, "evidence": evidence, "already_absent": True},
        )
        return {"adopted": False, "already_absent": True, "service": service}
    if current.corrupt:
        _append_exit_audit(
            store,
            {"event": "adopt_rejected", "service": service, "operator": operator,
             "reason": reason, "corrupt_requires_force": True},
        )
        return {
            "adopted": False,
            "corrupt_requires_force": True,
            "service": service,
            "hint": "损坏屏障无法 adopt；请改用 release(force=true)",
        }
    if current.operation_id != expected_owner:
        _append_exit_audit(
            store,
            {"event": "adopt_rejected", "service": service, "operator": operator,
             "reason": reason, "expected_owner": expected_owner,
             "current_owner": current.operation_id},
        )
        return {
            "adopted": False,
            "conflict": {"current_owner": current.operation_id, "expected_owner": expected_owner},
            "service": service,
        }

    owner_id = str(new_owner or "").strip() or f"svc-adopt-{uuid.uuid4().hex}"
    adopted = store.barriers.adopt(
        service,
        operation_id=owner_id,
        previous_owner=expected_owner,
        reason=reason,
    )
    _append_exit_audit(
        store,
        {"event": "adopt", "service": service, "operator": operator, "reason": reason,
         "evidence": evidence, "previous_owner": expected_owner, "operation_id": owner_id,
         "adopted": bool(adopted)},
    )
    if not adopted:
        return {"adopted": False, "already_absent": True, "service": service}
    return {
        "adopted": True,
        "service": service,
        "previous_owner": expected_owner,
        "operation_id": owner_id,
        "next": "屏障已归本 owner；如需重新发布/重启请继续，或 release 释放",
    }


def record_model_override(
    store: ManagedServiceDeploymentStore,
    *,
    action_id: str,
    gate: str,
    evidence: str,
    evidence_level: str,
    reason: str,
    operator: str = "model",
) -> dict[str, Any]:
    """模型对非物理门禁的举证推进（design 2.2.2.4 / 2.1.3.3 / L3）。

    禁止穿透 physical_impossible / identity_conflict；命中时返回明确拒绝
    理由（不静默）。E3（纯声明）仅可用于非物理 gate。推进后程序**不取消**
    后续证据采集，矛盾事实由 status 并列展示。
    """
    gate = str(gate or "").strip()
    level = str(evidence_level or "").strip().upper()
    evidence = str(evidence or "").strip()
    reason = str(reason or "").strip()
    if level not in {"E1", "E2", "E3"}:
        raise ValueError("evidence_level must be one of E1/E2/E3")
    if not evidence:
        raise ValueError("override requires evidence")
    if not reason:
        raise ValueError("override requires a non-empty reason")

    entry = classify_gate(gate)
    if entry is None:
        return {"accepted": False, "reason": f"unknown gate: {gate!r}"}
    if not entry.override_allowed:
        _append_exit_audit(
            store,
            {"event": "override_rejected", "action_id": action_id, "gate": gate,
             "gate_class": entry.category, "evidence_level": level,
             "operator": operator, "reason": reason},
        )
        return {
            "accepted": False,
            "rejected": {"gate": gate, "class": entry.category, "why": entry.reason},
            "hint": "该门禁属不可穿透的物理/身份边界；请按提示走重新 publish / 物理恢复",
        }

    action = store.read_action(action_id)
    if action is None:
        raise FileNotFoundError(action_id)
    pending = pending_gates_for_action(action)
    if gate not in pending:
        return {
            "accepted": False,
            "reason": f"gate {gate!r} is not currently pending for this action",
            "pending_gates": list(pending),
            "action_status": action.status,
        }

    record = {
        "gate": gate,
        "evidence_level": level,
        "evidence": evidence,
        "reason": reason,
        "operator": operator,
        "ts": _local_now(),
    }
    note = (
        f"model override accepted: gate={gate} level={level}"
        + ("（推论，未机械确证）" if level == "E2" else "")
        + ("（无机械证据）" if level == "E3" else "")
    )
    overrides = [item for item in _load_overrides(action.model_override) if item.get("gate") != gate]
    overrides.append(record)
    updated = _mark_action(
        store,
        action,
        status=action.status,
        detail=note,
        model_override=json.dumps(overrides, ensure_ascii=False, sort_keys=True),
    )
    _append_exit_audit(
        store,
        {"event": "override_accepted", "action_id": action_id, "gate": gate,
         "gate_class": entry.category, "evidence_level": level, "evidence": evidence,
         "operator": operator, "reason": reason, "reason_ref": updated.reason_ref},
    )
    return {
        "accepted": True,
        "action_id": action_id,
        "gate": gate,
        "evidence_level": level,
        "note": "program keeps collecting later evidence; contradictions stay visible in status",
    }


def acknowledge_verify(
    store: ManagedServiceDeploymentStore,
    *,
    action_id: str,
    verdict: str,
    evidence: str,
    reason: str,
    operator: str = "model",
) -> dict[str, Any]:
    """模型对核验证据的裁决（design 2.2.2.5 / L6、L7）。

    - ``accept``: 模型完成判断 → action 置 succeeded；
    - ``reobserve``: 程序重新观测一次并返回新证据（不自动重跑物理脚本）；
    - ``override``: 记录模型不认可程序证据及依据 → failed。
    三种 verdict 均写 append-only 审计。
    """
    verdict = str(verdict or "").strip().lower()
    if verdict not in {"accept", "reobserve", "override"}:
        raise ValueError("verdict must be accept/reobserve/override")
    evidence = str(evidence or "").strip()
    reason = str(reason or "").strip()
    if not evidence:
        raise ValueError("verify_acknowledge requires evidence")
    if not reason:
        raise ValueError("verify_acknowledge requires a non-empty reason")

    action = store.read_action(action_id)
    if action is None:
        raise FileNotFoundError(action_id)
    # L6/N-4（adjudication-20260922 裁定 b）：succeeded 进入可申诉集——
    # confirmed_ok 的程序判终态对模型不再不可翻转；accept 幂等、override 重开
    # 为 failed（屏障按既有转换规则处置，succeeded 起点已释放则保持释放）。
    if action.status not in {"running", "restarted", "verify_evidence_ready", "failed", "succeeded"}:
        return {
            "accepted": False,
            "reason": f"action is not awaiting verify (status={action.status})",
        }

    if verdict == "reobserve":
        deployment = store.read()
        targets = list(_MANAGED_SERVICES) if action.target == "all" else [action.target]
        # 纯证据三态（L6/L7）：reobserve 只重新采集，不替模型判终态。
        observed, summary, healthy = _verify_restart_targets(
            store, deployment, targets, action.updated_at
        )
        updated = _mark_action(
            store,
            action,
            status="verify_evidence_ready",
            detail=f"model reobserve: {summary}",
            verify_evidence=summary,
            verify_verdict=observed,
        )
        _append_exit_audit(
            store,
            {"event": "verify_reobserve", "action_id": action_id, "operator": operator,
             "reason": reason, "evidence": evidence, "summary_ref": updated.reason_ref},
        )
        return {
            "accepted": True,
            "action_id": action_id,
            "verdict": verdict,
            "evidence_verdict": observed,
            "evidence": summary,
            "healthy": list(healthy),
        }

    # EVO-20260924-8266b693 B：failed 动作的 accept 是"确认已知"，不是改判成功——
    # 物理上该动作仍失败过；置 acknowledged_at 闭合"待确认"投影，状态保持 failed。
    if action.status == "failed" and verdict == "accept" and not action.acknowledged_at:
        updated = _mark_action(
            store,
            action,
            status="failed",
            detail=f"failed acknowledged by model: {reason}",
            verify_evidence=evidence,
            verify_verdict=verdict,
            release_barriers=_barrier_services_for_target(action.target),
            acknowledged_at=_local_now(),
        )
        _append_exit_audit(
            store,
            {"event": "verify_acknowledge", "action_id": action_id, "verdict": verdict,
             "operator": operator, "reason": reason, "evidence": evidence,
             "action_status": updated.status, "acknowledged_at": updated.acknowledged_at},
        )
        return {
            "accepted": True,
            "action_id": action_id,
            "verdict": verdict,
            "status": updated.status,
            "acknowledged_at": updated.acknowledged_at,
        }

    status = "succeeded" if verdict == "accept" else "failed"
    updated = _mark_action(
        store,
        action,
        status=status,
        detail=f"model verify verdict={verdict}: {reason}",
        verify_evidence=evidence,
        verify_verdict=verdict,
        release_barriers=(
            _barrier_services_for_target(action.target) if verdict == "accept" else "keep"
        ),
    )
    _append_exit_audit(
        store,
        {"event": "verify_acknowledge", "action_id": action_id, "verdict": verdict,
         "operator": operator, "reason": reason, "evidence": evidence,
         "action_status": updated.status},
    )
    return {"accepted": True, "action_id": action_id, "verdict": verdict, "status": updated.status}


_OPERATOR_CLI_GUIDANCE: dict[str, str] = {
    "barrier-release": (
        "shell 直连 barrier-release 属操作员应急通道；模型自恢复请用结构化出口 "
        "service_control(action=release|adopt|override)"
    ),
    "barriers": (
        "shell 直连 barriers 属操作员通道；模型请用 service_control(action=status) "
        "读取屏障 owner 与可用出口"
    ),
    "publish": (
        "shell 直连 publish 属操作员通道；模型发布/更新请用 "
        "service_control(action=publish|update)"
    ),
    "worker": (
        "shell 直连 worker 属内部通道，不供模型直接调用；请用 "
        "service_control(action=update|restart)"
    ),
}


def _operator_cli_guidance(subcommand: str) -> str:
    """L1: 围栏消息从"禁止"改为"指向结构化出口"（不静默、不阻断工具调用）。"""
    return _OPERATOR_CLI_GUIDANCE.get(
        subcommand,
        "direct service-control CLI is operator-only; model calls use service_control",
    )


class ManagedServiceMutationGuard:
    """Narrow tool-layer fence around LFL shared-service lifecycle mutations."""

    _PID_SOURCE_MARKERS = (
        "runtime_manifest.web.json",
        "runtime_manifest.feishu.json",
        "runtime_manifest.learning.json",
        "feishu_heartbeat.json",
    )

    def __init__(
        self,
        data_dir: str | Path,
        *,
        process_command_reader: Callable[[int], str] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self._process_command_reader = process_command_reader or _read_process_command

    def _live_managed_pids(self) -> dict[int, str]:
        out: dict[int, str] = {}
        runtime = self.data_dir / "runtime"
        for service in _MANAGED_SERVICES:
            path = runtime / f"runtime_manifest.{service}.json"
            if not path.is_file():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or raw.get("service") != service:
                    continue
                pid = int(raw.get("pid") or 0)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if pid <= 0:
                continue
            command = str(self._process_command_reader(pid) or "")
            if _service_command_matches(service, command):
                out[pid] = service
        return out

    @staticmethod
    def _tokens(segment: str) -> list[str]:
        try:
            return shlex.split(segment, posix=True)
        except ValueError:
            return segment.split()

    @staticmethod
    def _core_tokens(tokens: list[str]) -> list[str]:
        """Strip leading env assignments without interpreting shell semantics."""
        if not tokens:
            return []
        idx = 0
        if Path(tokens[0]).name == "env":
            idx = 1
            while idx < len(tokens) and (tokens[idx].startswith("-") or "=" in tokens[idx]):
                idx += 1
        else:
            while idx < len(tokens) and "=" in tokens[idx] and not tokens[idx].startswith("="):
                key, _, _value = tokens[idx].partition("=")
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                    break
                idx += 1
        return tokens[idx:]

    @staticmethod
    def _unwrap_process_prefix(core: list[str]) -> list[str]:
        """Remove non-semantic process wrappers used around an executable."""
        out = list(core)
        while out and Path(out[0]).name in {"nohup", "command"}:
            out = out[1:]
        return out

    @classmethod
    def _direct_launch_service(cls, core: list[str]) -> str:
        tokens = cls._unwrap_process_prefix(core)
        if len(tokens) < 4:
            return ""
        exe = Path(tokens[0]).name
        if not re.fullmatch(r"python(?:3(?:\.\d+)?)?", exe):
            return ""
        if tokens[1:3] != ["-m", "llm_loop.runtime.launch"]:
            return ""
        service = tokens[3]
        return service if service in _MANAGED_SERVICES else ""

    @classmethod
    def _operator_control_cli(cls, core: list[str]) -> str:
        """Return the direct operator CLI subcommand name, or "" if not one.

        L1（lifecycle_agency）：shell 直连仍是 operator 通道并被围栏拦下，
        但分类已从"禁止"改为"经结构化工具放行"——围栏消息必须指向等价
        的模型结构化出口，而不是只说 operator-only。
        """
        tokens = cls._unwrap_process_prefix(core)
        if len(tokens) < 4:
            return ""
        exe = Path(tokens[0]).name
        if not (
            bool(re.fullmatch(r"python(?:3(?:\.\d+)?)?", exe))
            and tokens[1:3] == ["-m", "llm_loop.runtime.service_control"]
        ):
            return ""
        sub = tokens[3]
        return sub if sub in {"publish", "worker", "barriers", "barrier-release"} else ""

    @staticmethod
    def _restart_script_mutation(core: list[str]) -> bool:
        if not core:
            return False
        exe = Path(core[0]).name
        script_idx = 0
        if exe in {"bash", "sh", "zsh"}:
            if len(core) < 2 or core[1] == "-c":
                return False
            script_idx = 1
        script = Path(core[script_idx]).name
        if script not in {"restart_mirror.sh", "restart_system.sh", "restart_feishu.sh"}:
            return False
        action_idx = script_idx + 1
        if action_idx >= len(core):
            # restart_mirror default is a real Web restart, so an omitted action mutates.
            return script == "restart_mirror.sh"
        return core[action_idx] in {"web", "feishu", "learning", "all", "restart", "start", "stop"}

    def _guard_text(
        self,
        text: str,
        managed: Mapping[int, str],
        *,
        depth: int,
    ) -> ManagedServiceGuardDecision | None:
        if depth > 2:
            return None
        segments = _shell_segments(text)
        for segment in segments:
            tokens = self._tokens(segment)
            core = self._core_tokens(tokens)
            if not core:
                continue
            exe = Path(core[0]).name

            if self._restart_script_mutation(core):
                return ManagedServiceGuardDecision(
                    True,
                    "shared Web/Feishu lifecycle must use service_control; generic shell restart is not authoritative",
                    _MANAGED_SERVICES,
                )

            launch_service = self._direct_launch_service(core)
            if launch_service and "--dry-run" not in core:
                return ManagedServiceGuardDecision(
                    True,
                    "direct shared-service launch is not authoritative; use service_control/official deployment",
                    (launch_service,),
                )
            control_cli = self._operator_control_cli(core)
            if control_cli:
                return ManagedServiceGuardDecision(
                    True,
                    _operator_cli_guidance(control_cli),
                    _MANAGED_SERVICES,
                )

            if exe in {"bash", "sh", "zsh"} and "-c" in core and depth < 2:
                idx = core.index("-c")
                if idx + 1 < len(core):
                    nested = self._guard_text(core[idx + 1], managed, depth=depth + 1)
                    if nested is not None:
                        return nested

            if not managed:
                continue
            hit: set[str] = set()
            if exe == "kill" and not _kill_signal_is_probe(core):
                for token in core[1:]:
                    if token.isdigit() and int(token) in managed:
                        hit.add(managed[int(token)])
                low = segment.lower()
                for marker in self._PID_SOURCE_MARKERS:
                    if marker in low:
                        if ".web." in marker:
                            hit.add("web")
                        elif ".feishu." in marker or "feishu_" in marker:
                            hit.add("feishu")
                        elif ".learning." in marker:
                            hit.add("learning")
                if "lsof" in low and "8903" in low:
                    hit.add("web")
                # kill -SIGNAL -1 targets every process the caller may signal.
                if re.search(r"(?:^|\s)-1(?:\s|$)", segment):
                    hit.update(managed.values())
            elif exe in {"pkill", "killall"}:
                if _kill_signal_is_probe(core):
                    continue
                low = " ".join(core[1:]).lower()
                if "llm_loop.runtime.launch" in low and not any(
                    service in low for service in _MANAGED_SERVICES
                ):
                    hit.update(managed.values())
                for service in _MANAGED_SERVICES:
                    if ("llm_loop" in low or "runtime.launch" in low) and service in low:
                        hit.add(service)
                # Broad Python process kills necessarily include live managed Python services.
                if re.search(r"(?:^|\s)(?:python|python3|python3\.\d+)(?:\s|$)", low):
                    hit.update(managed.values())
            elif exe.startswith("python") and "os.kill" in segment:
                for pid, service in managed.items():
                    match = re.search(rf"os\.kill\(\s*{pid}\s*,\s*([^\)]+)\)", segment)
                    if match and match.group(1).strip() not in {"0", "signal.SIG_0"}:
                        hit.add(service)
            if hit:
                return ManagedServiceGuardDecision(
                    True,
                    "managed shared-service PID mutation is fenced; use service_control with observed deployment generation",
                    tuple(sorted(hit)),
                )
        return None

    def guard(self, command: str) -> ManagedServiceGuardDecision | None:
        text = str(command or "").strip()
        if not text:
            return None
        return self._guard_text(text, self._live_managed_pids(), depth=0)


def _control_subprocess_env(
    *,
    code_root: str,
    runtime_root: str,
    extra: Mapping[str, str] | None = None,
    python_src: str | Path | None = None,
) -> dict[str, str]:
    """Build a deterministic minimal environment for lifecycle-control children.

    Do not inherit the caller/Web process environment: provider keys, credentials,
    FORCE flags, stale config anchors, and sandbox HOME/TMPDIR are not lifecycle
    authority. The official restart script reconstructs service HOME/TMPDIR and
    business configuration from canonical roots.

    ``python_src`` binds which ``llm_loop`` tree Python children import from.
    The detached service-control worker must pass the *controller* code root
    (see ``_control_code_root``); the restart-script child keeps the default
    (desired ``code_root``/src) because the script itself belongs to the
    target deployment.
    """
    account_home = pwd.getpwuid(os.getuid()).pw_dir
    resolved_python_src = Path(python_src) if python_src is not None else Path(code_root) / "src"
    env = {
        "HOME": account_home,
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "C.UTF-8",
        "LFL_WORKSPACE_ROOT": code_root,
        "LFL_RUNTIME_ROOT": runtime_root,
        "PYTHONPATH": str(resolved_python_src),
    }
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
    return env


def _control_code_root() -> Path:
    """Code root of the *currently executing* control plane.

    The detached service-control worker must run the control-plane code that
    dispatched it, never the code of the desired deployment target: rolling
    back to a tree that predates this module must not make the worker
    execute the old controller (P0-A.1). A layout that does not look like a
    repository checkout (e.g. a site-packages install) fails closed here
    instead of silently binding to an unrelated root.
    """
    root = Path(__file__).resolve().parents[3]
    if not (root / "src" / "llm_loop").is_dir():
        raise RuntimeError(
            f"control code root sanity check failed: {root}/src/llm_loop not found; "
            "refusing to spawn worker from an unrecognized layout"
        )
    return root


def build_restart_plan(
    action: ServiceControlAction,
    deployment: ManagedServiceDeployment,
) -> RestartPlan:
    if action.action != "restart":
        raise ValueError(f"unsupported action: {action.action}")
    if action.deployment_id != deployment.deployment_id:
        raise DeploymentGenerationConflictError("action deployment_id no longer matches desired deployment")
    if action.deployment_generation != deployment.generation:
        raise DeploymentGenerationConflictError("action deployment generation is stale")
    script = Path(deployment.code_root) / "scripts" / "restart_mirror.sh"
    return RestartPlan(
        argv=("/bin/bash", str(script), action.target),
        cwd=deployment.runtime_root,
        env={
            "LFL_RESTART_CODE_ROOT": deployment.code_root,
            "LFL_RESTART_RUNTIME_ROOT": deployment.runtime_root,
            # lifecycle_agency L5: 回执身份绑定——脚本回执透传本 action_id，
            # worker 只接受同 id 的回执（替代时间窗口启发式）。
            "LFL_RESTART_ACTION_ID": action.action_id,
            # R1 §6: 单源路径契约注入，脚本侧 RECEIPT_JSON 消费同一值
            "LFL_RESTART_RECEIPT_REL": _RESTART_RECEIPT_REL,
            # R4: 受控路径的两个根都来自 deployment（显式值），预检的
            # T0-A3 来源判定据此放行，不依赖 ambient 环境卫生。
            "LFL_RESTART_CODE_ROOT_CONFIRMED": "1",
            "LFL_RESTART_RUNTIME_ROOT_CONFIRMED": "1",
            "RESTART_WAIT_IDLE": "1",
        },
    )


def spawn_service_control_worker(store: ManagedServiceDeploymentStore, action_id: str) -> None:
    action = store.read_action(action_id)
    deployment = store.read()
    if action is None or deployment is None:
        raise RuntimeError("service-control action/deployment missing before worker spawn")
    build_restart_plan(action, deployment)  # stale binding fails before spawn
    log_path = Path(deployment.runtime_root) / "data" / "service-control-worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = _control_subprocess_env(
        code_root=deployment.code_root,
        runtime_root=deployment.runtime_root,
        python_src=_control_code_root() / "src",
    )
    stream = log_path.open("a", encoding="utf-8")
    try:
        subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [
                sys.executable,
                "-m",
                "llm_loop.runtime.service_control",
                "worker",
                "--data-dir",
                str(store.data_dir),
                "--action-id",
                action_id,
            ],
            cwd=deployment.runtime_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        stream.close()


def _interpret_idle_probe(probe: str | bool) -> tuple[str, str]:
    """把 busy_probe 返回值归一为三态（L22）。

    bool: True=confirmed_busy / False=confirmed_idle；字符串按前缀识别；未知
    自由文本仍按 busy（fail-closed，仅延长等待，不构成不可逆门禁）。
    """
    if isinstance(probe, bool):
        return ("confirmed_busy", "") if probe else ("confirmed_idle", "")
    text = str(probe or "")
    if not text:
        return "confirmed_idle", ""
    if text.startswith("confirmed_busy"):
        return "confirmed_busy", text
    if text.startswith("unconfirmable"):
        return "unconfirmable", text
    if text.startswith("confirmed_idle"):
        return "confirmed_idle", text
    return "confirmed_busy", text


def _target_idle_state(*, target: str, runtime_root: str) -> tuple[str, str]:
    """L22: 目标空闲三态 ``confirmed_busy`` / ``confirmed_idle`` / ``unconfirmable``.

    feishu/all 要求飞书桥 heartbeat 空闲；web/all 要求无机械持有的前台 run
    lock；learning/all 要求消费端无在飞 journal job（缺口②：持锁 + admitted/
    started 在飞才 busy，进程死亡的 started 残留不阻塞，由 post-crash
    reconcile 重跑）。

    "无法确认"≠"忙碌"：探测能力不足（heartbeat 缺失、目录不可读）只作如实
    事实披露，不再被程序等同为 busy 而锁死模型行动空间。
    """
    reasons: list[str] = []
    unconfirmable: list[str] = []
    if target in {"feishu", "all"}:
        heartbeat_path = Path(runtime_root) / "data" / "feishu_heartbeat.json"
        try:
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            heartbeat = None
            unconfirmable.append("feishu heartbeat 缺失，无法确认飞书桥空闲")
        except (OSError, ValueError) as exc:
            heartbeat = None
            unconfirmable.append(f"feishu heartbeat 不可解析: {type(exc).__name__}")
        if isinstance(heartbeat, dict):
            processing = str(heartbeat.get("processing_msg_id") or "")
            queue_depth = int(heartbeat.get("queue_depth") or 0)
            if processing or queue_depth > 0:
                reasons.append(
                    f"feishu busy: processing={processing!r} queue_depth={queue_depth}"
                )
    if target in {"web", "all"}:
        sessions_dir = Path(runtime_root) / "data" / "sessions"
        held = active_run_locks(sessions_dir)
        if held:
            reasons.append(f"active run locks: {len(held)}")
    if target in {"learning", "all"}:
        learning_reason = learning_busy_reason(
            Path(runtime_root) / "data" / "sessions"
        )
        if learning_reason:
            reasons.append(learning_reason)
    if reasons:
        return "confirmed_busy", "confirmed_busy: " + "; ".join(reasons)
    if unconfirmable:
        return "unconfirmable", "unconfirmable: " + "; ".join(unconfirmable)
    return "confirmed_idle", "confirmed_idle"


def _target_busy_reason(*, target: str, runtime_root: str) -> str:
    """兼容只读视图：返回**明确**忙碌理由（空串=非明确忙碌）.

    新代码路径应使用 ``_target_idle_state``（保留三态信息）；本函数仅为只读
    证据与既有调用方保留，不参与 worker 门禁判定。
    """
    state, detail = _target_idle_state(target=target, runtime_root=runtime_root)
    return detail if state == "confirmed_busy" else ""


def _target_idle_probe(*, target: str, runtime_root: str) -> str:
    """busy_probe 形态的空闲探针：返回以三态前缀开头的如实事实串."""
    return _target_idle_state(target=target, runtime_root=runtime_root)[1]


def _requester_run_active(sessions_dir: Path, requester_session_id: str) -> bool:
    """True while the requester session's whole-run lease is still held."""
    if not requester_session_id:
        return False
    wanted = f"{requester_session_id}.run.lock"
    return any(path.name == wanted for path in active_run_locks(sessions_dir))


def _mark_action(
    store: ManagedServiceDeploymentStore,
    action: ServiceControlAction,
    *,
    status: str,
    detail: str = "",
    release_barriers: str | tuple[str, ...] | None = None,
    stage_fact: str | None = None,
    verify_evidence: str | None = None,
    verify_verdict: str | None = None,
    model_override: str | None = None,
    next_step: str | None = None,
    acknowledged_at: str | None = None,
) -> ServiceControlAction:
    with store.lease():
        detail_text, reason_ref = _durable_detail(store, detail)
        updated = dataclasses.replace(
            action,
            status=status,  # type: ignore[arg-type]
            updated_at=_local_now(),
            detail=detail_text,
            reason_ref=reason_ref or action.reason_ref,
            stage_fact=action.stage_fact if stage_fact is None else stage_fact,
            verify_evidence=(
                action.verify_evidence if verify_evidence is None else verify_evidence
            ),
            verify_verdict=(
                action.verify_verdict if verify_verdict is None else verify_verdict
            ),
            model_override=(
                action.model_override if model_override is None else model_override
            ),
            next_step=action.next_step if next_step is None else next_step,
            acknowledged_at=(
                action.acknowledged_at if acknowledged_at is None else acknowledged_at
            ),
        )
        store._write_action_unlocked(updated)
        _release_barriers_for_transition(
            store,
            previous=action,
            updated=updated,
            release_barriers=release_barriers,
        )
        _emit_terminal_event(store, updated)
        return updated


def _release_barriers_for_transition(
    store: ManagedServiceDeploymentStore,
    *,
    previous: ServiceControlAction,
    updated: ServiceControlAction,
    release_barriers: str | tuple[str, ...] | None = None,
) -> None:
    """§8.3 barrier lifecycle on state transitions (single policy point).

    release_barriers:
    - None: infer from the transition.  Terminal statuses release when the
      transition proves no physical side effects started (accepted/waiting →
      failed, anything → succeeded).  running → failed keeps barriers
      fail-closed: stops may have happened and the affected services must
      stay "affected and not recovered" until an operator or a follow-up
      operation handles them.
    - "keep": never release (physical restart already ran and failed).
    - tuple[str, ...]: release exactly these services (per-service verify
      verdicts) and keep the rest.
    """
    if updated.status not in {"succeeded", "failed"}:
        return
    if release_barriers == "keep":
        return
    if release_barriers is None:
        if updated.status == "failed" and previous.status == "running":
            return
        services: tuple[str, ...] = _barrier_services_for_target(updated.target)
    else:
        services = tuple(release_barriers)
    for service in services:
        store.barriers.release(service, operation_id=updated.action_id)


def _consume_restart_failure_receipt(
    runtime_root: str | Path,
    *,
    target: str,
    rc: int,
    action_id: str,
    action_created_at: str = "",
    script_output_tail: str = "",
) -> tuple[bool, str]:
    """L4/L5: rc!=0 后按回执的结构化身份 + stage_fact 判定屏障命运。

    归属判定由 ``action_id`` 身份绑定完成（L5，替代时间窗口+rc+scope+marker
    的组合启发式）；零副作用判定由脚本产出的 ``stage_fact`` 完成（L4，替代
    detail 文本白名单）。``stage_fact == not_started`` 即证明本次失败发生在
    任何 ``_stop_*`` 之前，可释放屏障；其余（已进入停止阶段、无回执、解析失败、
    身份不符、旧回执无结构化事实）一律 fail-closed keep。note 进 durable
    action 记录供审计。

    陈旧性判定（2026-09-24 13:4x 实证）：脚本在写回执前崩溃（如 set -u
    unbound 秒退）时磁盘残留的是**上一次动作**的回执——action_id 必然不符，
    但报"身份不符"会把真因（脚本 stderr）吞掉。回执 ts 早于本次 action
    创建时间 → 报 stale_receipt 并附脚本输出尾部；陈旧回执不能证明本次
    零副作用，仍 fail-closed keep。
    """
    path = Path(runtime_root).joinpath(*_RESTART_RECEIPT_REL.split("/"))
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return False, "absent"
    try:
        rec = json.loads(raw)
    except ValueError:
        return False, "unparseable"
    if not isinstance(rec, dict):
        return False, "schema"
    if not isinstance(rec.get("action"), str) or rec["action"] != target:
        return False, f"scope={rec.get('action')!r}"
    if action_created_at:
        try:
            rec_ts = datetime.fromisoformat(str(rec.get("ts") or ""))
            action_ts = datetime.fromisoformat(action_created_at)
        except ValueError:
            rec_ts = action_ts = None  # ts 缺失/不可解析 → 走 action_id 身份判定
        if rec_ts is not None and rec_ts.timestamp() < action_ts.timestamp():
            stripped = script_output_tail.strip()
            tail = stripped.splitlines()[-1][:160] if stripped else ""
            return False, (
                f"stale_receipt ts={rec.get('ts')}（早于本次动作 {action_created_at}；"
                f"非本次所写，脚本可能早崩）{'; 脚本尾部: ' + tail if tail else ''}"
            )
    rec_action_id = str(rec.get("action_id") or "")
    if action_id and rec_action_id != action_id:
        return False, f"action_id_mismatch rec={rec_action_id!r}"
    try:
        rec_rc = int(rec["rc"])
    except (KeyError, TypeError, ValueError):
        return False, "schema(rc)"
    if rec_rc != rc:
        return False, f"rc={rec_rc}!={rc}"
    stage_fact = str(rec.get("stage_fact") or "")
    if stage_fact == "not_started":
        return True, "stage_fact=not_started"
    if not stage_fact:
        detail = str(rec.get("detail") or "")
        return False, f"stage_fact_absent detail={detail[:80]!r}"
    return False, f"stage_fact={stage_fact}"



def _wait_for(
    store: ManagedServiceDeploymentStore,
    action: ServiceControlAction,
    *,
    status: str,
    busy_probe: Callable[[], str | bool],
    poll_s: float,
    timeout_s: float,
    timeout_detail: str,
    gate: str = "",
) -> bool:
    """Poll a busy probe while holding no lifecycle lease.

    等待仍是 fail-closed 超时兜底，但不再是唯一出路（L3）：模型可在等待
    期间经 ``service_control(action=override, gate=...)`` 附证据推进，本循环
    非阻塞读取 action 上的 ``model_override`` 字段后按分级放行。
    """
    _mark_action(store, action, status=status)
    deadline = time.monotonic() + timeout_s
    while True:
        state, probe_detail = _interpret_idle_probe(busy_probe())
        if state != "confirmed_busy":
            if state == "unconfirmable":
                # L22: "无法确认"≠"忙碌"——不阻塞推进，但如实记录事实供模型复核。
                _mark_action(
                    store,
                    action,
                    status=status,
                    detail=(
                        f"{probe_detail}；无法确认空闲，按'非忙碌'推进"
                        "（模型可经 status 复核并反对）"
                    ),
                )
            return True
        try:
            current = store.read_action(action.action_id)
        except (OSError, ValueError):
            current = None
        overrides = _load_overrides(current.model_override) if current is not None else []
        match = next((item for item in overrides if item.get("gate") == gate), None)
        if match is not None:
            remaining = [item for item in overrides if item.get("gate") != gate]
            _mark_action(
                store,
                action,
                status=status,
                model_override=(
                    json.dumps(remaining, ensure_ascii=False, sort_keys=True) if remaining else ""
                ),
                detail=(
                    f"model override accepted for {gate} "
                    f"(level={match.get('evidence_level', '')}); advancing waiting phase"
                ),
            )
            return True
        if time.monotonic() >= deadline:
            _mark_action(
                store,
                action,
                status="failed",
                detail=(
                    f"{timeout_detail} after {timeout_s:.0f}s: {probe_detail}; "
                    f"可用 service_control(action=override, action_id={action.action_id}, "
                    f"gate={gate or '<gate>'}, evidence_level=E1|E2|E3, evidence=..., "
                    "reason=...) 附证据推进"
                ),
            )
            return False
        time.sleep(poll_s)


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO timestamp as aware UTC; None on missing/unparsable input."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


# started_at 宽限：真实服务 manifest 的 started_at 常为秒级精度（向下截断），
# 与 worker 捕获的微秒级重启发起时刻比较需容忍截断误差，否则新进程会被
# 误判 started_before_restart。
_STARTED_AT_GRACE_S = 2.0


def _read_runtime_manifest(
    store: ManagedServiceDeploymentStore, service: str
) -> dict[str, Any] | None:
    """Best-effort read of a service's startup runtime manifest (None if absent)."""
    path = store.runtime_dir / f"runtime_manifest.{service}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _verify_restart_targets(
    store: ManagedServiceDeploymentStore,
    deployment: Any,
    services: list[str],
    restarted_at: str,
) -> tuple[str, str, tuple[str, ...]]:
    """L6/L7: restart 后的**纯证据采集**（三态），不判终态、不自动重跑.

    判据与 compose_service_identity_view 同源：manifest 存在、pid 存活、
    git_head 等于 desired、started_at 不早于本次重启发起时刻（解析失败
    不作判据）。返回 ``(verdict, summary, healthy)``：

    - ``confirmed_ok``: 全部目标机械判据通过；
    - ``confirmed_fail``: 至少一个目标有明确失败证据（pid 死/head 不符/早于重启）；
    - ``criterion_absent``: 无明确失败但判据缺失/未确认（manifest 未现）——
      **判据缺失 ≠ 失败**，不得据此否决（spec 5.4.3-1）。

    healthy 为本次明确判 [ok] 的服务集，供按服务粒度屏障释放使用；
    ``_STARTED_AT_GRACE_S`` / ``_VERIFY_MANIFEST_WAIT_S`` / ``no_manifest_skip``
    均是**如实披露的证据参数**，不单独作为否决依据。
    """
    services = list(services)
    began = _parse_iso(restarted_at)
    deadline = time.monotonic() + _VERIFY_TIMEOUT_S
    manifest_wait_deadline = time.monotonic() + _VERIFY_MANIFEST_WAIT_S
    seen: set[str] = set()
    skipped: set[str] = set()
    while True:
        parts: list[str] = []
        failed = False
        healthy: set[str] = set()
        now = time.monotonic()
        for service in services:
            if service in skipped:
                continue
            raw = _read_runtime_manifest(store, service)
            if raw is not None:
                seen.add(service)
            elif service not in seen and now >= manifest_wait_deadline:
                skipped.add(service)
                continue
            if raw is None:
                # 判据暂缺：未确认，不判失败（区别于明确的 unhealthy 证据）
                parts.append(f"{service}[manifest_missing]")
                continue
            try:
                pid = int(raw.get("pid") or 0)
            except (TypeError, ValueError):
                pid = 0
            head = str(raw.get("git_head") or "")
            problems: list[str] = []
            if not _pid_alive(pid):
                problems.append(f"pid_dead:{pid or 0}")
            if not head:
                problems.append("git_head_missing")
            elif deployment is not None and head != deployment.git_head:
                problems.append("git_head_mismatch")
            started = _parse_iso(raw.get("started_at"))
            if (
                started is not None
                and began is not None
                and started < began - timedelta(seconds=_STARTED_AT_GRACE_S)
            ):
                problems.append("started_before_restart")
            if problems:
                failed = True
                parts.append(f"{service}[" + ",".join(problems) + "]")
            else:
                parts.append(f"{service}[ok pid={pid} head={head[:12]}]")
                healthy.add(service)
        if skipped:
            parts.extend(f"{service}[no_manifest_skip]" for service in sorted(skipped))
        pending = [s for s in services if s not in skipped and s not in healthy]
        if failed:
            verdict = "confirmed_fail"
        elif not pending:
            verdict = "confirmed_ok" if healthy else "criterion_absent"
        else:
            verdict = "criterion_absent"
        summary = f"verify={verdict} " + " ".join(parts)
        if failed or not pending or now >= deadline:
            return verdict, summary, tuple(sorted(healthy))
        time.sleep(_VERIFY_POLL_S)


def _pid_dead(pid: int) -> bool:
    """进程存活探测（signal 0）；pid 复用/他人进程视为存活（保守回退）。"""
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def run_action_worker(store: ManagedServiceDeploymentStore, action_id: str) -> int:
    # 生命周期加固（GOAL-20261008-f143e051）：本进程即执行 worker，进入任何
    # 检查/等待前先盖章 pid——deployment 缺失即时退出的孤儿场景同样受益
    # （reaper 可按死 pid 秒级回收）。盖章失败不阻断执行（旧 store 兼容）。
    try:
        store.record_worker_pid(action_id, os.getpid())
    except (OSError, ValueError):
        pass
    action = store.read_action(action_id)
    deployment = store.read()
    if action is None or deployment is None:
        return 2
    # Fail fast on stale binding before entering any waiting phase.
    try:
        build_restart_plan(action, deployment)
    except (ValueError, DeploymentGenerationConflictError) as exc:
        _mark_action(store, action, status="failed", detail=str(exc))
        return 3

    sessions_dir = Path(deployment.runtime_root) / "data" / "sessions"
    # Phase 1 - requester exit (web/all only): never kill the dispatching
    # session mid-turn, and never hold the lifecycle lease while waiting for
    # it, so desired-state publication stays unblocked.
    if action.target in {"web", "all"} and _requester_run_active(
        sessions_dir, action.requester_session_id
    ) and not _wait_for(
        store,
        action,
        status="waiting_for_requester_exit",
        busy_probe=lambda: _requester_run_active(
            sessions_dir, action.requester_session_id
        ),
        poll_s=_REQUESTER_EXIT_POLL_S,
        timeout_s=_REQUESTER_EXIT_TIMEOUT_S,
        timeout_detail="requester run still active",
        gate="waiting_for_requester_exit",
    ):
        return 1

    # Phase 2 - target idle, same target-scoped semantics as the official
    # restart gates (still without the lifecycle lease).
    if not _wait_for(
        store,
        action,
        status="waiting_for_idle",
        busy_probe=lambda: _target_idle_probe(
            target=action.target, runtime_root=deployment.runtime_root
        ),
        poll_s=_IDLE_POLL_S,
        timeout_s=_IDLE_TIMEOUT_S,
        timeout_detail="target still busy",
        gate="waiting_for_idle",
    ):
        return 1

    # Phase 3 + 4 - 物理重启在 lifecycle lease 内（含发布绑定复检，关闭
    # waiting→execute TOCTOU）；重启后只做纯证据采集，在 lease 外执行（慢启动
    # 不阻塞 desired-state 发布）。程序不据核验自动判终态、不自动重跑：明确
    # 证据（ok/fail）幂等落终态，判据缺失置 verify_evidence_ready 交模型裁决。
    def _run_physical_restart_once() -> tuple[int, Any, str]:
        with store.lifecycle_lease():
            with store.lease():
                latest = store.read_action(action_id)
                desired_now = store._read_unlocked()
            if latest is None or desired_now is None:
                _mark_action(
                    store, action, status="failed", detail="action or desired state missing"
                )
                return 2, None, ""
            try:
                plan = build_restart_plan(latest, desired_now)
            except (ValueError, DeploymentGenerationConflictError) as exc:
                _mark_action(
                    store,
                    latest,
                    status="failed",
                    detail=f"desired deployment advanced while waiting: {exc}",
                )
                return 3, None, ""
            # P0-A.1: byte-level reverify of the desired binding inside the
            # lifecycle lease, immediately before the physical restart. The
            # generation CAS above only proves identity/generation agreement;
            # this proves the target tree still matches the published commit
            # and WebUI artifact hash at execution time. Drift => fail closed
            # without executing the (possibly pre-P0-A) restart script.
            # Feishu-only restarts do not consume WebUI artifacts, so the dist
            # tree hash is not a hard gate for them.
            binding_facts = _binding_problems_structured(
                desired_now,
                code_root=desired_now.code_root,
                runtime_root=desired_now.runtime_root,
                verify_webui=(latest.target != "feishu"),
            )
            if binding_facts:
                binding_problems = [problem.text for problem in binding_facts]
                # svc_deploy N2：拒绝事实（detail）逐字不变；可执行下一步作为
                # 独立结构化字段与 detail 在同一次原子写内落盘（无中间态）。
                _mark_action(
                    store,
                    latest,
                    status="failed",
                    detail="deployment binding failed: " + "; ".join(binding_problems),
                    next_step=encode_next_steps(binding_next_steps(binding_facts)),
                )
                return 4, None, ""
            running = _mark_action(store, latest, status="running")

            # L3/5.x: 把模型经结构化出口举证推进的一致性门禁注入脚本；物理门
            # 永不出现（record_model_override 已拒穿透 identity/physical 类）。
            extra_env = dict(plan.env)
            override_gates = _override_gates_for_action(latest)
            if override_gates:
                extra_env["LFL_RESTART_OVERRIDE_GATES"] = override_gates
            env = _control_subprocess_env(
                code_root=plan.env["LFL_RESTART_CODE_ROOT"],
                runtime_root=plan.env["LFL_RESTART_RUNTIME_ROOT"],
                extra=extra_env,
            )
            restarted_at = _local_now()
            # S4a（2026-09-22 15:12 gen66 事故 svc-8011bb79）：物理重启绝不能
            # 继承调用方 stdio 的生命周期。S3 的 inline CLI 把自身管道交给
            # restart_mirror，读端先死时 bash 在写输出瞬间被 SIGPIPE 杀死
            # （rc=-13），回执未写、web 停后未起。输出改为落 per-action
            # durable 日志，rc 恒为脚本自身退出状态。
            restart_log = (
                Path(plan.env["LFL_RESTART_RUNTIME_ROOT"])
                / "data"
                / "service-control-restart-logs"
                / f"{action_id}.log"
            )
            restart_log.parent.mkdir(parents=True, exist_ok=True)
            with restart_log.open("a", encoding="utf-8") as restart_out:
                restart_out.write(
                    f"\n[{restarted_at}] target={latest.target} argv={shlex.join(plan.argv)}\n"
                )
                restart_out.flush()
                proc = subprocess.run(  # noqa: S603 - desired-state-bound fixed argv, no shell
                    list(plan.argv),
                    cwd=plan.cwd,
                    env=env,
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=restart_out,
                    stderr=subprocess.STDOUT,
                )
            rc = int(proc.returncode or 0)
            if rc != 0:
                # 脚本输出尾部（真因透传：脚本早崩不写回执时，stderr 尾行
                # 是唯一线索——2026-09-24 unbound DATA_DIR 被陈旧回执掩埋实证）
                script_tail = ""
                with contextlib.suppress(OSError):
                    script_tail = restart_log.read_text(encoding="utf-8", errors="replace")[-400:]
                # R1 (SPEC-20260922-service-control-restart-fixpack-v1): 先消费
                # durable 回执再定屏障命运——预检链标记证明零物理副作用（脚本严格
                # 串行，_stop_* 均在其后），释放本目标全部屏障；其余（无回执/解析
                # 失败/mid-run 标记/scope、rc 不匹配/陈旧回执）维持 §8.3
                # fail-closed keep，恢复路径仍是操作员覆盖 CLI 或后续操作接管。
                released, receipt_note = _consume_restart_failure_receipt(
                    plan.env["LFL_RESTART_RUNTIME_ROOT"],
                    target=latest.target,
                    rc=rc,
                    action_id=action_id,
                    action_created_at=running.created_at,
                    script_output_tail=script_tail,
                )
                _mark_action(
                    store,
                    running,
                    status="failed",
                    detail=f"restart_mirror rc={rc}; receipt={receipt_note}; log={restart_log}",
                    release_barriers=(
                        _barrier_services_for_target(latest.target)
                        if released
                        else "keep"
                    ),
                )
                return rc, desired_now, restarted_at
            return rc, desired_now, restarted_at

    # 自核验目标（EVO-20260920-213965a1 案1）：目标全集传入，"是否受
    # manifest 管辖"由 _verify_restart_targets 的首现窗口判定（不受管辖
    # 的目标记 no_manifest_skip，见其 docstring）。
    verify_targets: list[str] = list(_MANAGED_SERVICES) if action.target == "all" else [action.target]

    rc, desired_now, restarted_at = _run_physical_restart_once()
    if rc != 0 or desired_now is None:
        return rc or 1

    # Phase 4 - 纯证据采集，在 lifecycle lease 外执行（慢启动不阻塞 desired-state
    # 发布）。L6/L7：程序只产证据，不据核验自动判终态、不自动重跑；终态由模型
    # 经 verify_acknowledge 裁决（design 2.1.3.4）。
    verdict, summary, healthy = _verify_restart_targets(
        store, desired_now, verify_targets, restarted_at
    )

    identity = (
        f"identity generation={desired_now.generation} git_head={desired_now.git_head}"
    )
    final = store.read_action(action_id)
    if final is None:
        return 2
    if verdict == "confirmed_ok":
        # 机械判据全通过 → 程序幂等处终态（无需模型重复见证）。
        _mark_action(
            store,
            final,
            status="succeeded",
            detail=f"restart_mirror rc=0; {identity}; {summary}",
            verify_evidence=summary,
            verify_verdict=verdict,
        )
        return 0
    if verdict == "confirmed_fail":
        _mark_action(
            store,
            final,
            status="failed",
            detail=(
                f"restart_mirror rc=0 but verify evidence shows failure; "
                f"{identity}; {summary}（程序不自动重跑，待模型/新动作裁决）"
            ),
            verify_evidence=summary,
            verify_verdict=verdict,
            # §8.3: 按服务粒度恢复准入——明确判 [ok] 的服务释放屏障；未确认的
            # 服务保留屏障，交给模型覆盖出口或后续动作接管。
            release_barriers=healthy,
        )
        return 5
    # criterion_absent: 判据缺失/未确认 ≠ 失败，不得据此否决（spec 5.4.3-1）。
    # 置非终态 verify_evidence_ready 并保留屏障，交模型 verify_acknowledge 裁决
    # 或显式重试；不自动重跑、不自动判终态。
    _mark_action(
        store,
        final,
        status="verify_evidence_ready",
        detail=(
            f"restart_mirror rc=0; {identity}; {summary}"
            "（判据缺失/未确认，非失败；待 verify_acknowledge 裁决）"
        ),
        verify_evidence=summary,
        verify_verdict=verdict,
        release_barriers="keep",
    )
    return 6


def _tree_sha256(root: Path) -> str:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"WebUI artifact tree is empty: {root}")
    h = hashlib.sha256()
    for path in files:
        rel = path.relative_to(root).as_posix().encode("utf-8")
        blob = path.read_bytes()
        h.update(len(rel).to_bytes(8, "big"))
        h.update(rel)
        h.update(len(blob).to_bytes(8, "big"))
        h.update(blob)
    return h.hexdigest()


def _binding_problems_structured(
    deployment: ManagedServiceDeployment,
    *,
    code_root: str | Path,
    runtime_root: str | Path,
    verify_webui: bool = True,
) -> list[BindingProblem]:
    """svc_deploy I1: 8 类 binding 判定的结构化事实源。

    判定顺序、条件与 git 子进程调用（次数与超时）与既有
    ``verify_deployment_binding`` **完全一致**，只是把"文本 append"提升为
    "（类别 + 原文 + 取值）append"，使下一步提示由结构化类别派生，而不是读
    文本猜语义（对齐 Q5）。
    """
    code = Path(code_root).expanduser().resolve()
    runtime = Path(runtime_root).expanduser().resolve()
    problems: list[BindingProblem] = []
    if str(code) != deployment.code_root:
        problems.append(
            BindingProblem(
                kind=BindingProblemKind.CODE_ROOT_MISMATCH,
                text=f"code_root mismatch desired={deployment.code_root} actual={code}",
                desired=deployment.code_root,
                actual=str(code),
            )
        )
    if str(runtime) != deployment.runtime_root:
        problems.append(
            BindingProblem(
                kind=BindingProblemKind.RUNTIME_ROOT_MISMATCH,
                text=f"runtime_root mismatch desired={deployment.runtime_root} actual={runtime}",
                desired=deployment.runtime_root,
                actual=str(runtime),
            )
        )
    try:
        head = subprocess.run(
            ["git", "-C", str(code), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append(
            BindingProblem(
                kind=BindingProblemKind.GIT_HEAD_UNAVAILABLE,
                text=f"git_head unavailable: {type(exc).__name__}",
            )
        )
        head = ""
    if head and head != deployment.git_head:
        problems.append(
            BindingProblem(
                kind=BindingProblemKind.GIT_HEAD_MISMATCH,
                text=f"git_head mismatch desired={deployment.git_head} actual={head}",
                desired=deployment.git_head,
                actual=head,
            )
        )
    try:
        dirty = subprocess.run(
            ["git", "-C", str(code), "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if dirty:
            problems.append(
                BindingProblem(
                    kind=BindingProblemKind.TRACKED_WORKTREE_DIRTY,
                    text="code_root tracked worktree is dirty",
                )
            )
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append(
            BindingProblem(
                kind=BindingProblemKind.GIT_STATUS_UNAVAILABLE,
                text=f"git_status unavailable: {type(exc).__name__}",
            )
        )
    if verify_webui:
        try:
            artifact = _tree_sha256(code / "webui" / "dist")
        except (OSError, ValueError) as exc:
            problems.append(
                BindingProblem(
                    kind=BindingProblemKind.WEBUI_ARTIFACT_UNAVAILABLE,
                    text=f"webui artifact unavailable: {exc}",
                )
            )
        else:
            if artifact != deployment.webui_artifact_sha256:
                problems.append(
                    BindingProblem(
                        kind=BindingProblemKind.WEBUI_ARTIFACT_MISMATCH,
                        text=(
                            "webui artifact mismatch "
                            f"desired={deployment.webui_artifact_sha256} actual={artifact}"
                        ),
                        desired=deployment.webui_artifact_sha256,
                        actual=artifact,
                    )
                )
    return problems


def verify_deployment_binding(
    deployment: ManagedServiceDeployment,
    *,
    code_root: str | Path,
    runtime_root: str | Path,
    verify_webui: bool = True,
) -> list[str]:
    """Return exact desired-vs-physical binding mismatches; empty means qualified.

    签名与返回值（problem 原文列表，逐字）保持不变；事实源改为
    ``_binding_problems_structured`` 的文本投影，既有断言零改动。
    """
    return [
        problem.text
        for problem in _binding_problems_structured(
            deployment,
            code_root=code_root,
            runtime_root=runtime_root,
            verify_webui=verify_webui,
        )
    ]


_RELEASE_SIDECAR_KEYS: tuple[str, ...] = ("EXPERIENCES_DIR", "METHODS_DIR")


def _release_sidecar_content(runtime: Path) -> str:
    lines = (
        f"EXPERIENCES_DIR={runtime / 'experiences'}",
        f"METHODS_DIR={runtime / 'data' / 'methods'}",
    )
    return "\n".join(lines) + "\n"


def _materialize_release_sidecar(target: Path, runtime: Path) -> None:
    """release checkout 的最小非敏感 dual-root sidecar `.env` 自动物化。

    gen196/gen197 两次实证的确定性发布链缺口：`.releases/<sha>` 是 linked
    worktree 且 DATA_DIR 在 code_root 之外，restart_mirror.sh 的
    _knowledge_binding_preflight 在 `env -u EXPERIENCES_DIR -u METHODS_DIR`
    下运行 `--check-binding`，两键的唯一来源是模块相对 load_env_file() 读
    release/.env；而 release checkout 只含 tracked 快照，天生缺这两行 ⇒
    preflight 报 dual_root_store_binding_missing，此前靠人工后补。

    契约：sidecar 是与 release checkout 同级的衍生工件——仅白名单两键、
    指向 canonical runtime root、mode 0600、fsync 落盘；内容与期望不一致
    （缺键/路径漂移/白名单外键）即原子重写。绝不复制 canonical `.env` 的
    其它键或 secrets。仅在 build_deployment（publish 生命周期锁内）调用。
    """
    sidecar = target / ".env"
    wanted = _release_sidecar_content(runtime)
    try:
        if (
            sidecar.read_text(encoding="utf-8") == wanted
            and (sidecar.stat().st_mode & 0o777) == 0o600
        ):
            return
    except OSError:
        pass
    tmp = sidecar.with_name(f".{sidecar.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, wanted.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, sidecar)
    os.chmod(sidecar, 0o600)
    dir_fd = os.open(str(sidecar.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _materialize_release_checkout(code: Path, runtime: Path, head: str, artifact: str) -> Path:
    """EVO-20261007-9c6eccf3: 物化固定提交 release checkout，解除 code_root 对开发工作树 HEAD 的绑定。

    2026-10-07 17:25/18:28 实证：publish 后开发树 HEAD 前移导致既有期望代 restart
    precheck git_head mismatch 连续失败。此处把发布代码物化为同仓 linked worktree
    （HEAD 永久钉在 publish 时的 commit），webui/dist 为 gitignored 产物，从开发树
    复制后按 tree-sha 验证。

    语义：release checkout 是纯衍生工件（可再生）。已存在且 HEAD 一致 + tracked
    干净 → 复用（幂等）；HEAD 分歧或 tracked 脏 → 在 publish 时点（lifecycle 锁内）
    重建（remove --force 后重新 add），restart/verify 永不自动 mutation。
    """
    releases = runtime / ".releases"
    releases.mkdir(parents=True, exist_ok=True)
    target = releases / head
    if target.is_dir():
        # 复用前必须确认 target 是本仓注册的 worktree：仓库内的 bogus 目录会让
        # `git -C target rev-parse` 向上爬到父仓库 .git 而误判可复用（已测）。
        listed = subprocess.run(
            ["git", "-C", str(code), "worktree", "list", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
        registered = f"worktree {target}" in listed
        current = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(target), "status", "--porcelain", "--untracked-files=no"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if registered and current == head and not dirty:
            _materialize_release_sidecar(target, runtime)
            return target
        # 衍生工件分歧：重建（bogus 非 worktree 目录走 rmtree 兜底）。
        remove = subprocess.run(
            ["git", "-C", str(code), "worktree", "remove", "--force", str(target)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if remove.returncode != 0 and target.is_dir():
            shutil.rmtree(target)
    subprocess.run(
        ["git", "-C", str(code), "worktree", "prune"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "-C", str(code), "worktree", "add", "--detach", str(target), head],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    dist_src = code / "webui" / "dist"
    dist_dst = target / "webui" / "dist"
    if dist_src.is_dir():
        shutil.copytree(dist_src, dist_dst, dirs_exist_ok=True)
    actual = _tree_sha256(dist_dst)
    if actual != artifact:
        raise DeploymentBindingError(
            f"release checkout webui artifact mismatch: expected={artifact} actual={actual}",
            kind=BindingProblemKind.WEBUI_ARTIFACT_MISMATCH,
        )
    _materialize_release_sidecar(target, runtime)
    return target


def build_deployment(
    *,
    code_root: str | Path,
    runtime_root: str | Path,
    generation: int,
) -> ManagedServiceDeployment:
    code = Path(code_root).expanduser().resolve()
    runtime = Path(runtime_root).expanduser().resolve()
    if not code.is_dir() or not runtime.is_dir():
        raise ValueError("code_root/runtime_root must exist")
    head = subprocess.run(
        ["git", "-C", str(code), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(code), "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    if dirty:
        raise DeploymentBindingError(
            "code_root tracked worktree must be clean before publish",
            kind=BindingProblemKind.TRACKED_WORKTREE_DIRTY,
        )
    artifact = _tree_sha256(code / "webui" / "dist")
    # EVO-20261007-9c6eccf3: code_root 绑定物化后的 release checkout（固定
    # HEAD），与开发工作树解耦；旧期望代（code_root 仍指开发树）语义不变。
    release = _materialize_release_checkout(code, runtime, head, artifact)
    return ManagedServiceDeployment(
        schema=_DEPLOYMENT_SCHEMA,
        deployment_id=f"deploy-{uuid.uuid4().hex}",
        generation=generation,
        git_head=head,
        code_root=str(release),
        runtime_root=str(runtime),
        webui_artifact_sha256=artifact,
    )


def _default_data_dir(runtime_root: Path) -> Path:
    return runtime_root / "data"


def _derive_restart_target_from_code_root(code_root: str) -> str:
    """svc_deploy I5: CLI update 缺省目标——按 code_root 路径名推导，否则 all.

    与工具面 ``_derive_restart_target`` 同规则（单 worktree 多为 all；按服务
    拆分 worktree 时只重启该服务）；缺省可被显式 ``--target`` 覆盖。
    """
    name = Path(code_root).expanduser().name.lower()
    for service in ("web", "feishu", "learning"):
        if service in name:
            return service
    return "all"


def _missing_webui_artifacts(code_root: str | Path) -> list[str]:
    """svc_deploy I5: 列出会让 build_deployment 产物绑定失败的缺失路径."""
    dist = Path(code_root).expanduser() / "webui" / "dist"
    if not dist.is_dir():
        return [str(dist)]
    if not any(path.is_file() for path in dist.rglob("*")):
        return [str(dist)]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llm_loop.runtime.service_control")
    sub = parser.add_subparsers(dest="command", required=True)

    publish = sub.add_parser("publish")
    publish.add_argument(
        "--expected-generation",
        type=int,
        default=None,
        help="期望的当前 desired 代（CAS）；缺省自动取当前代（L14，与工具面一致）",
    )
    publish.add_argument("--code-root", required=True)
    publish.add_argument("--runtime-root", required=True)
    publish.add_argument("--data-dir")

    show = sub.add_parser("show")
    show.add_argument("--data-dir", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--data-dir", required=True)
    verify.add_argument("--code-root", required=True)
    verify.add_argument("--runtime-root", required=True)
    verify.add_argument("--skip-webui", action="store_true")

    worker = sub.add_parser("worker")
    worker.add_argument("--data-dir", required=True)
    worker.add_argument("--action-id", required=True)

    restart_cmd = sub.add_parser("restart")
    restart_cmd.add_argument("--data-dir", required=True)
    restart_cmd.add_argument("--target", choices=_ACTION_TARGETS, default="all")
    restart_cmd.add_argument(
        "--requester",
        default="cli-restart",
        help="requester identity recorded on the durable action (audit)",
    )
    restart_cmd.add_argument(
        "--wait",
        action="store_true",
        help=(
            "inline worker (debug): CLI blocks until terminal state; worst-case "
            f"~{_REQUESTER_EXIT_TIMEOUT_S + _IDLE_TIMEOUT_S}s+ before physical restart. "
            "Default dispatches a detached worker (survives caller timeout/exit)."
        ),
    )

    # svc_deploy I5：CLI 一键部署入口（与工具面 action=update 同名同语义），
    # 附显式别名 deploy。内部只复用既有机械边界，不另起判据。
    update_cmd = sub.add_parser("update", aliases=["deploy"])
    update_cmd.add_argument("--code-root", required=True)
    update_cmd.add_argument("--runtime-root", required=True)
    update_cmd.add_argument("--target", choices=_ACTION_TARGETS, default=None)
    update_cmd.add_argument(
        "--requester",
        default="cli-update",
        help="requester identity recorded on the durable action (audit)",
    )
    update_cmd.add_argument(
        "--reason",
        default="cli-update",
        help="本次更新意图（进审计）；可选、缺省 cli-update（不新增必填门槛）",
    )
    update_cmd.add_argument(
        "--expected-generation",
        type=int,
        default=None,
        help="期望的当前 desired 代（CAS）；缺省自动取当前代",
    )
    update_cmd.add_argument("--data-dir")
    update_cmd.add_argument(
        "--wait",
        action="store_true",
        help=(
            "inline worker (debug): CLI blocks until terminal state; worst-case "
            f"~{_REQUESTER_EXIT_TIMEOUT_S + _IDLE_TIMEOUT_S}s+ before physical restart. "
            "Default dispatches a detached worker (survives caller timeout/exit)."
        ),
    )

    barriers = sub.add_parser("barriers")
    barriers.add_argument("--data-dir", required=True)

    barrier_release = sub.add_parser("barrier-release")
    barrier_release.add_argument("--data-dir", required=True)
    barrier_release.add_argument("--service", required=True)
    barrier_release.add_argument("--operation-id", required=True)
    barrier_release.add_argument(
        "--force",
        action="store_true",
        help="remove a corrupt/unknown-owner barrier (operator cleanup, audited)",
    )
    barrier_release.add_argument("--reason", required=True)

    args = parser.parse_args(argv)
    if args.command == "publish":
        runtime = Path(args.runtime_root).expanduser().resolve()
        data_dir = Path(args.data_dir).expanduser().resolve() if args.data_dir else _default_data_dir(runtime)
        store = ManagedServiceDeploymentStore(data_dir)
        # L14: 模型路径与 CLI 路径语义统一——缺省自动取当前 desired 代，无需先
        # 调 show 记录；并发变化返回当前值供直接重试（AC-11）。
        if args.expected_generation is None:
            current = store.read()
            expected_generation = current.generation if current is not None else 0
        else:
            expected_generation = args.expected_generation
        # svc_deploy I6：publish 失败面自带可执行下一步（脏树/产物缺失结构化，
        # 不再冒泡裸 traceback）；不自动 stash/commit/checkout。
        try:
            deployment = build_deployment(
                code_root=args.code_root,
                runtime_root=runtime,
                generation=expected_generation + 1,
            )
        except ValueError as exc:
            message = str(exc)
            missing = _missing_webui_artifacts(args.code_root)
            if missing or "artifact" in message.lower():
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": "artifact_missing",
                            "missing": missing,
                            "next_step": _next_steps_view(
                                [BindingProblemKind.WEBUI_ARTIFACT_UNAVAILABLE]
                            ),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                )
                return 10
            binding_kind = (
                BindingProblemKind.TRACKED_WORKTREE_DIRTY
                if "clean" in message
                else BindingProblemKind.GIT_STATUS_UNAVAILABLE
            )
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": (
                            "dirty_worktree"
                            if binding_kind == BindingProblemKind.TRACKED_WORKTREE_DIRTY
                            else "publish_rejected"
                        ),
                        "detail": message,
                        "next_step": _next_steps_view([binding_kind]),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 10
        try:
            store.compare_and_swap(deployment, expected_generation=expected_generation)
        except DeploymentGenerationConflictError as exc:
            current = store.read()
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "generation_conflict",
                        "current": current.generation if current is not None else 0,
                        "detail": str(exc),
                        "next_step": _next_steps_view([NEXT_STEP_KIND_GENERATION_CONFLICT]),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 9
        # EVO-20260924-dc3c7c78：成功回执附只读收敛快照——发布成功那一眼
        # 就能看到 lagging 服务，替代事后告警发现；读取失败只缺省该键。
        publish_out = deployment.to_dict()
        try:
            publish_out["convergence"] = compose_convergence_view(store)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        print(json.dumps(publish_out, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "show":
        deployment = ManagedServiceDeploymentStore(args.data_dir).read()
        print(json.dumps(deployment.to_dict() if deployment else {}, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "verify":
        deployment = ManagedServiceDeploymentStore(args.data_dir).read()
        if deployment is None:
            print("managed service deployment is not published", file=sys.stderr)
            return 4
        binding_facts = _binding_problems_structured(
            deployment,
            code_root=args.code_root,
            runtime_root=args.runtime_root,
            verify_webui=not bool(args.skip_webui),
        )
        if binding_facts:
            problems = [problem.text for problem in binding_facts]
            print(
                json.dumps(
                    {
                        "ok": False,
                        "problems": problems,
                        "next_step": _next_steps_view([problem.kind for problem in binding_facts]),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 5
        print(json.dumps({"ok": True, "generation": deployment.generation}, ensure_ascii=False))
        return 0
    if args.command == "worker":
        return run_action_worker(ManagedServiceDeploymentStore(args.data_dir), args.action_id)
    if args.command == "restart":
        # S3（简化包 2026-09-22）：一条命令的受控重启——受理 + worker 内联。
        # 直连脚本与动作链并存是事故放大器（直连不写回执 → stable 落后、操作员
        # 需懂两套语义）；此后操作员/模型只走这一扇门，回执必写、屏障全托管，
        # 直连 restart_mirror.sh 退为应急通道。rc 透传 worker（脚本/核验结论）。
        store = ManagedServiceDeploymentStore(args.data_dir)
        deployment = store.read()
        if deployment is None:
            print(
                json.dumps(
                    {"ok": False, "error": "desired deployment not published"},
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 7
        try:
            action = store.accept_restart(
                target=args.target,
                expected_generation=deployment.generation,
                requester_session_id=args.requester,
                origin="restart",
            )
        except (DeploymentGenerationConflictError, BarrierConflictError) as exc:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": str(exc),
                        "next_step": _next_steps_view([NEXT_STEP_KIND_GENERATION_CONFLICT]),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 8
        print(
            json.dumps(
                {
                    "ok": True,
                    "action_id": action.action_id,
                    "target": args.target,
                    "generation": deployment.generation,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if args.wait:
            # 调试语义：内联 worker 直到终态。启动前显式提示最坏 wall time，
            # 避免调用方（如 execute_command 默认 30s 超时）误杀内联 worker 后
            # action 卡 waiting、屏障持有至 stale reap（最长 2100s）。
            print(
                "[cli-restart] inline worker (--wait): worst-case "
                f"~{_REQUESTER_EXIT_TIMEOUT_S + _IDLE_TIMEOUT_S}s+ before physical "
                "restart; caller timeout below this will orphan the waiting action",
                file=sys.stderr,
                flush=True,
            )
            rc = run_action_worker(store, action.action_id)
        else:
            # 生命周期加固（GOAL-20261008-f143e051）：默认与工具面同款 detached
            # worker——受理后立即返回，worker 独立于调用方存活，杜绝 caller
            # 超时把 waiting action 留成孤儿屏障。
            spawn_service_control_worker(store, action.action_id)
            rc = 0
        final = store.read_action(action.action_id)
        # svc_deploy I6：末行 JSON 只增键（next_step）、不增行；detail 的既有
        # [:400] 行为与 rc 语义不变。
        receipt: dict[str, Any] = {
            "ok": bool(final is not None and final.status == "succeeded"),
            "action_id": action.action_id,
            "status": final.status if final else "missing",
            # L19: 展示片段 + 稳定 ref，完整原因经 reason_ref 可回读。
            "detail": (final.detail if final else "")[:400],
            "reason_ref": final.reason_ref if final else "",
            "next_step": decode_next_steps(final.next_step if final else ""),
        }
        if not args.wait:
            # detached 回执如实反映瞬时态：非 succeeded 但 ok=False 并非失败，
            # 附 detached 标记与收敛视图说明仍在执行。
            receipt["ok"] = True
            receipt["detached"] = True
            receipt["hint"] = "worker detached; poll status/show for terminal state"
            try:
                receipt["convergence"] = compose_convergence_view(store)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        print(
            json.dumps(receipt, ensure_ascii=False),
            flush=True,
        )
        return rc
    if args.command in {"update", "deploy"}:
        # svc_deploy I5：单语义「固化期望部署 + 物理生效」。内部依次复用既有
        # build_deployment → compare_and_swap → accept_restart → run_action_worker，
        # 不新增判据、不绕过 CAS/绑定核验/屏障/两阶段等待；执行形态与既有 CLI
        # restart 一致（同步内联 worker）。
        runtime = Path(args.runtime_root).expanduser().resolve()
        data_dir = (
            Path(args.data_dir).expanduser().resolve()
            if args.data_dir
            else _default_data_dir(runtime)
        )
        store = ManagedServiceDeploymentStore(data_dir)
        restart_target = args.target or _derive_restart_target_from_code_root(args.code_root)
        if args.expected_generation is None:
            current = store.read()
            expected_generation = current.generation if current is not None else 0
        else:
            expected_generation = args.expected_generation
        try:
            deployment = build_deployment(
                code_root=args.code_root,
                runtime_root=runtime,
                generation=expected_generation + 1,
            )
        except ValueError as exc:
            message = str(exc)
            missing = _missing_webui_artifacts(args.code_root)
            if missing or "artifact" in message.lower():
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": "artifact_missing",
                            "missing": missing,
                            "next_step": _next_steps_view(
                                [BindingProblemKind.WEBUI_ARTIFACT_UNAVAILABLE]
                            ),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                )
                return 10
            binding_kind = (
                BindingProblemKind.TRACKED_WORKTREE_DIRTY
                if "clean" in message
                else BindingProblemKind.GIT_STATUS_UNAVAILABLE
            )
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": (
                            "dirty_worktree"
                            if binding_kind == BindingProblemKind.TRACKED_WORKTREE_DIRTY
                            else "publish_rejected"
                        ),
                        "detail": message,
                        "next_step": _next_steps_view([binding_kind]),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 10
        try:
            store.compare_and_swap(deployment, expected_generation=expected_generation)
        except DeploymentGenerationConflictError as exc:
            current = store.read()
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "generation_conflict",
                        "current": current.generation if current is not None else 0,
                        "detail": str(exc),
                        "next_step": _next_steps_view([NEXT_STEP_KIND_GENERATION_CONFLICT]),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 9
        except ValueError as exc:
            print(
                json.dumps(
                    {"ok": False, "error": "publish_rejected", "detail": str(exc)},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 10
        try:
            action = store.accept_restart(
                target=restart_target,
                expected_generation=deployment.generation,
                requester_session_id=args.requester,
                origin="update",
            )
        except (DeploymentGenerationConflictError, BarrierConflictError) as exc:
            # desired 已推进但物理未受理：如实回报已生效的一半（partial）。
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": str(exc),
                        "generation": deployment.generation,
                        "git_head": deployment.git_head,
                        "next_step": _next_steps_view([NEXT_STEP_KIND_GENERATION_CONFLICT]),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 8
        print(
            json.dumps(
                {
                    "ok": True,
                    "action_id": action.action_id,
                    "target": restart_target,
                    "generation": deployment.generation,
                    "git_head": deployment.git_head,
                    "origin": "update",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if args.wait:
            # 调试语义同 restart：内联 worker；显式提示最坏 wall time。
            print(
                "[cli-update] inline worker (--wait): worst-case "
                f"~{_REQUESTER_EXIT_TIMEOUT_S + _IDLE_TIMEOUT_S}s+ before physical "
                "restart; caller timeout below this will orphan the waiting action",
                file=sys.stderr,
                flush=True,
            )
            rc = run_action_worker(store, action.action_id)
        else:
            # 生命周期加固（GOAL-20261008-f143e051）：默认 detached worker，
            # publish/CAS 已生效，物理生效由 detached worker 完成。
            spawn_service_control_worker(store, action.action_id)
            rc = 0
        final = store.read_action(action.action_id)
        # EVO-20260924-dc3c7c78：终局回执附只读收敛快照——重启完成后同一眼
        # 看到仍 lagging 的服务；读取失败只缺省该键。
        update_out: dict[str, Any] = {
            "ok": bool(final is not None and final.status == "succeeded"),
            "action_id": action.action_id,
            "status": final.status if final else "missing",
            "detail": (final.detail if final else "")[:400],
            "reason_ref": final.reason_ref if final else "",
            "next_step": decode_next_steps(final.next_step if final else ""),
        }
        if not args.wait:
            # detached 回执如实反映瞬时态：desired 已固化、worker 正在执行；
            # ok=True 语义 = 受理+发布成功，物理生效看 convergence/status。
            update_out["ok"] = True
            update_out["detached"] = True
            update_out["hint"] = "worker detached; poll status/show for terminal state"
        try:
            update_out["convergence"] = compose_convergence_view(store)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        print(json.dumps(update_out, ensure_ascii=False), flush=True)
        return rc
    if args.command == "barriers":
        registry = ManagedServiceDeploymentStore(args.data_dir).barriers
        print(
            json.dumps(
                {"barriers": [b.to_view() for b in registry.snapshot()]},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "barrier-release":
        registry = ManagedServiceDeploymentStore(args.data_dir).barriers
        released = (
            registry.force_release(args.service, reason=args.reason)
            if args.force
            else registry.release(args.service, operation_id=args.operation_id)
        )
        if not released:
            print(
                json.dumps(
                    {
                        "released": False,
                        "service": args.service,
                        "operation_id": args.operation_id,
                        "hint": "owner mismatch or barrier absent; use `barriers` to list owners",
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 6
        logger.warning(
            "service admission barrier released: service=%s operation=%s reason=%s",
            args.service,
            args.operation_id,
            args.reason,
        )
        print(
            json.dumps(
                {"released": True, "service": args.service, "reason": args.reason},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    return 2


def scan_unacknowledged_failed_actions(data_dir: str | Path) -> list[dict[str, Any]]:
    """EVO-20260924-8266b693 B：扫最近 24h failed 且未确认的 restart 动作（≤10 条）.

    "待确认"语义：failed 且 acknowledged_at 为空。desired 代已前进（被新动作
    接管/supersede）**不再抹除**——痕迹保留（superseded=True 标注）直到
    verify_acknowledge(verdict=accept) 确认，堵"接管即抹痕"。
    供 factory pending_actions 投影与会话开场状态提醒共用；fail-open。
    """
    results: list[dict[str, Any]] = []
    try:
        from datetime import datetime

        store = ManagedServiceDeploymentStore(data_dir)
        desired_generation: int | None = None
        try:
            deployment = store.read()
            desired_generation = deployment.generation if deployment else None
        except Exception:  # noqa: BLE001 — 过滤信息缺失时按未 supersede 处理
            desired_generation = None
        cutoff = system_local_now().timestamp() - 24 * 3600
        for path in sorted(
            (p for p in store.actions_dir.glob("*.json") if p.is_file()),
            key=lambda p: p.name,
            reverse=True,
        )[:40]:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if raw.get("action") != "restart" or raw.get("status") != "failed":
                continue
            if str(raw.get("acknowledged_at") or "").strip():
                continue  # 已确认 → 不占投影/提醒
            raw_generation = raw.get("deployment_generation")
            superseded = bool(
                desired_generation is not None
                and isinstance(raw_generation, int)
                and raw_generation < desired_generation
            )
            try:
                updated_ts = datetime.fromisoformat(str(raw.get("updated_at"))).timestamp()
            except ValueError:
                updated_ts = 0.0
            if updated_ts < cutoff:
                continue
            results.append(
                {
                    "action_id": raw.get("action_id"),
                    "target": raw.get("target"),
                    "generation": raw_generation,
                    "updated_at": raw.get("updated_at"),
                    "detail": str(raw.get("detail") or "")[:160],
                    "superseded": superseded,
                }
            )
            if len(results) >= 10:
                break
    except Exception:  # noqa: BLE001 — 扫描 fail-open
        return []
    return results


if __name__ == "__main__":
    raise SystemExit(main())
