"""CodeArts 调度集成 数据模型（design.md §2.3.2）.

全部 frozen dataclass（不可变，线程安全）+ StrEnum（与现有 ToolResultStatus 一致）。
无 Any 类型；metrics 限定为 dict[str, int | float | str]；Optional 字段显式 | None。

凭证明文绝不持久化（spec §4.3.1、§5.3.1.3）：Credential 仅内存常驻，
AuditRecord 仅含 credential_ref（类型与 ID 标识，不含明文）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# ── 枚举（StrEnum，与现有 ToolResultStatus 一致）──


class Priority(StrEnum):
    """委派任务优先级."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class RiskLevel(StrEnum):
    """风险等级（normal=常规 / catastrophic=灾难性动作）."""

    NORMAL = "normal"
    CATASTROPHIC = "catastrophic"


class HandleStatus(StrEnum):
    """本地维护的执行句柄状态（含 UNKNOWN 不臆造）."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class RemoteStatus(StrEnum):
    """CodeArts 侧远端执行状态."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ResultStatus(StrEnum):
    """执行结果状态（终态子集，不含 UNKNOWN）."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class AuditAction(StrEnum):
    """审计动作类型."""

    DISPATCH = "dispatch"
    QUERY = "query"
    CANCEL = "cancel"
    COLLECT = "collect"
    RETRY = "retry"
    AUTH_REFRESH = "auth_refresh"
    APPROVAL = "approval"


class AuditResult(StrEnum):
    """审计结果."""

    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKED = "blocked"


class CredentialKind(StrEnum):
    """凭证类型."""

    AK_SK = "ak_sk"
    IAM_TOKEN = "iam_token"


# ── 终态集合（状态同步终止条件）──
TERMINAL_STATUSES: frozenset[HandleStatus] = frozenset(
    {
        HandleStatus.SUCCEEDED,
        HandleStatus.FAILED,
        HandleStatus.TIMEOUT,
        HandleStatus.CANCELLED,
        HandleStatus.UNKNOWN,
    }
)


# ── 值对象 / 领域对象（frozen dataclass）──


@dataclass(frozen=True)
class TimeoutBudget:
    """三级超时预算（连接/调用/执行）."""

    connect_s: int = 10
    call_s: int = 30
    exec_s: int = 1800


@dataclass(frozen=True)
class DispatchTask:
    """委派任务对象（spec §6.1）.

    由 CodeArtsDispatchTool.execute 从工具参数构造（frozen，不可变）。
    """

    task_description: str
    trace_id: str
    context_summary: str = ""
    timeout_budget: TimeoutBudget = field(default_factory=TimeoutBudget)
    expected_output_format: str = ""
    priority: Priority = Priority.NORMAL
    risk_level: RiskLevel = RiskLevel.NORMAL


@dataclass(frozen=True)
class ExecutionHandle:
    """执行句柄（spec §6.2）.

    由 CodeArtsClient.trigger_execution 返回；HandleRegistry.register 登记。
    进程重启经 HandleRegistry.recover 从事件日志重建。
    """

    handle_id: str
    session_id: str
    trace_id: str
    created_at: str
    status: HandleStatus = HandleStatus.PENDING
    last_synced_at: str = ""
    remote_status: RemoteStatus = RemoteStatus.PENDING


@dataclass(frozen=True)
class Artifact:
    """制品产物清单项（按需拉取，不内联大文件）."""

    name: str
    type: str
    access: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    """执行结果对象（spec §6.3）.

    由 ResultCollector.collect 从远端响应构造；经脱敏后转换为 ToolResult。
    """

    final_answer: str
    status: ResultStatus
    execution_log_summary: str = ""
    metrics: dict[str, int | float | str] = field(default_factory=dict)
    artifacts: list[Artifact] = field(default_factory=list)
    failure_reason: str = ""


@dataclass(frozen=True)
class AuditRecord:
    """审计记录对象（spec §6.4）.

    credential_ref 仅含凭证类型与 ID 标识（如 ak_sk:default），不含明文。
    target_api 仅含接口路径不含完整 URL query。
    params_summary 已脱敏（不含 token/密钥/敏感参数值）。
    """

    timestamp: str
    trace_id: str
    action: AuditAction
    target_api: str
    response_status: int
    credential_ref: str
    params_summary: str
    result: AuditResult


@dataclass(frozen=True)
class Credential:
    """凭证对象（内存常驻，绝不落盘）.

    kind=AK_SK 时 ak/sk 有值；kind=IAM_TOKEN 时 token 有值。
    expires_at 为 token 过期时间（ISO8601），AK/SK 模式可空。
    """

    kind: CredentialKind
    region: str
    ak: str = ""
    sk: str = ""
    token: str = ""
    expires_at: str = ""

    def ref(self) -> str:
        """凭证标识（不含明文，用于审计记录）."""
        return f"{self.kind.value}:{self.region}"


@dataclass(frozen=True)
class RiskAssessment:
    """风险判定结果（值对象，随 DispatchTask 判定生成）."""

    level: RiskLevel
    reason: str
    evidence: str
    local_blocked: bool = False
    local_block_reason: str = ""
