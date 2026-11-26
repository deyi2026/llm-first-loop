"""提权闭环工具（escalation_request / escalation_wait）.

配合 tools/escalation.py EscalationStore 与 registry 灾难层令牌校验:
被灾难性硬阻断（FR-SAFE-01）拦下、但确属必要的操作，可提交人工提权申请，
web 面板弹窗审批后凭一次性令牌重发同一命令。闭环全程无需用户向 AI 手动
转述审批结果（escalation_wait 轮询接收决定）。
"""

from __future__ import annotations

from datetime import datetime

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.timekeeping import system_local_now
from llm_loop.tools.escalation import (
    ISSUE_FAIL_REASON_DEFAULT_HINT,
    ISSUE_FAIL_REASON_HINTS,
    ISSUE_FAILED_REASON_PREFIX,
    EscalationStore,
)
from llm_loop.tools.safety import CatastrophicGuard

_MAX_WAIT_S = 300
_DEFAULT_WAIT_S = 120
_RETRY_HINT = (
    "请在原会话核对任务与当前状态，若仍需要且尚未执行，使用原申请类型重新提交："
    "普通命令 escalation_request，宿主路径 host_access_request，验证凭证走原 Host 签发申请入口。"
    "必须取得新 request_id 并重新人工审批；不得复活旧凭证或重做已完成操作。"
)
# EVO-20261127-dd37be50: 人工批准验证凭证时 Host 判定签发材料不可成立（HostVerifyError
# 的原因码）。记录已落为终态 failed，这里把它翻成 AI 能据以行动的说明；原因码→说明的
# 映射与审批路由共用同一份（tools.escalation.ISSUE_FAIL_REASON_HINTS）。
_ISSUE_RETRY_HINT = (
    "该申请已终态、不可复用：不要再 escalation_wait，也不要请人工重批同一申请。"
    "若合并仍有必要：先核对 lane 状态与 main 是否前进并据此更新 lane，"
    "重做 merge_review_start（取得新的 child_id），再重新 verify_receipt_request 并重新人工批准。"
)
# 审查剩余有效期低于此分钟数即提示（展示阈值，不参与任何签发判定）。
_REVIEW_EXPIRY_WARN_MIN = 10


def _review_expiry_note(rec: dict) -> str:
    """验证凭证类申请：按记录里的审查截止时刻给出提示（仅提示；能否签发只由 Host 判定）."""
    if rec.get("request_kind") != "verify_receipt":
        return ""
    host_request = rec.get("host_request")
    raw = str(host_request.get("host_review_expires_at") or "") if isinstance(host_request, dict) else ""
    try:
        expires = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return ""  # 旧记录无截止时刻 / 格式不可解析：不提示，不猜测
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=system_local_now().tzinfo)
    remaining_min = (expires - system_local_now()).total_seconds() / 60
    if remaining_min <= 0:
        return (
            f"注意：该申请绑定的独立审查已过截止时刻（{raw}），人工现在批准也会签发失败。"
            "请勿继续空等：向用户说明，必要时重做 merge_review_start 后重新 verify_receipt_request。"
        )
    if remaining_min <= _REVIEW_EXPIRY_WARN_MIN:
        return (
            f"注意：该申请绑定的独立审查将于 {raw} 截止（剩余约 {int(remaining_min)} 分钟），"
            "请提醒人工在此前完成批准；过期后签发会失败。"
        )
    return ""


def _fail(tool: str, content: str) -> ToolResult:
    return ToolResult(
        status=ToolResultStatus.FAILURE,
        content=content,
        tool_call_id="",
        tool_name=tool,
    )


class EscalationRequestTool:
    name = "escalation_request"
    description = (
        "灾难性安全硬阻断的人工提权申请（闭环第一步）。前置条件: execute_command "
        "返回 [安全硬阻断] 且该操作确属必要。会先复验该命令确实会被硬阻断"
        "（未被阻断的命令直接执行即可，本工具会拒绝，防止通道滥用）。"
        "提交后 web 面板弹窗展示命令原文与理由供人工批准/拒绝；"
        "随后用 escalation_wait(request_id) 等待决定，批准后凭一次性"
        "escalation_token 以 execute_command 重发**同一命令**（令牌绑定精确"
        "命令文本，改动一字即废；单次有效；默认 10 分钟过期）。"
        "注意: 提权只绕过灾难硬阻断层，EXEC_MODE 等独立边界不受影响。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "被阻断的命令原文（须与将重发的命令逐字一致）",
            },
            "justification": {
                "type": "string",
                "maxLength": 2000,
                "description": (
                    "必要性说明：为什么必须执行、目标是什么、为何无更安全的等价做法。"
                    "人工审批据此裁决，请如实具体。"
                ),
            },
            "tool_name": {
                "type": "string",
                "description": "目标工具名（默认 execute_command）",
            },
        },
        "required": ["command", "justification"],
    }

    def __init__(self, store: EscalationStore) -> None:
        self._store = store

    def execute(self, **kwargs) -> ToolResult:
        command = str(kwargs.get("command", "") or "").strip()
        justification = str(kwargs.get("justification", "") or "").strip()
        tool_name = str(kwargs.get("tool_name", "execute_command") or "execute_command").strip()
        if not command:
            return _fail(self.name, "[参数错误] command 不能为空")
        if len(justification) < 10:
            return _fail(self.name, "[参数错误] justification 过短（≥10 字符）：人工审批需要具体理由")

        # 复验：该命令确实会被灾难性硬阻断（防通道滥用/预授权）
        blocked = CatastrophicGuard().guard(tool_name, {"command": command, "run_in_background": False})
        if blocked is None:
            return _fail(
                self.name,
                "[拒绝] 该命令未被灾难性硬阻断（FR-SAFE-01），无需提权——直接执行即可。"
                "若被 EXEC_MODE 或共享服务边界拦下，请走各自通道（审批回调/白名单），不是本工具。",
            )

        rec = self._store.create(
            tool_name=tool_name,
            command=command,
            justification=justification,
            session_id=current_session_id.get(),
            requested_by="ai",
        )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"[提权申请已提交] request_id={rec.get('id', '')}\n"
                f"阻断原因: {blocked.reason}（{blocked.evidence}）\n"
                f"状态: pending（web 面板将弹窗提示人工审批；等待超时不会取消申请）\n"
                f"下一步: escalation_wait(request_id=...) 等待决定；批准后返回一次性令牌，"
                f"用 execute_command(command=同一命令, escalation_token=令牌) 重发。"
            ),
            tool_call_id="",
            tool_name=self.name,
        )


class EscalationWaitTool:
    name = "escalation_wait"
    description = (
        "等待提权申请的人工决定（闭环接收端）。web 面板批准/拒绝后本工具返回结果: "
        "approved → 一次性 escalation_token（及过期时间），凭它以 execute_command 重发"
        "同一命令；denied → 拒绝理由；超时未决 → 返回 pending（可再等或改期）；"
        "failed → 人工批准时 Host 签发失败（仅验证凭证类）：返回失败码、原因与重试指引，"
        "该申请已终态，不要继续等待或请人工重批。"
        "默认等待 120s、上限 300s。令牌单次有效、绑定批准时的精确命令文本。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "request_id": {
                "type": "string",
                "description": "escalation_request 返回的 request_id（ESC-...）",
            },
            "timeout_s": {
                "type": "number",
                "description": "最长等待秒数（默认 120，上限 300）",
            },
        },
        "required": ["request_id"],
    }

    def __init__(self, store: EscalationStore) -> None:
        self._store = store

    def execute(self, **kwargs) -> ToolResult:
        rid = str(kwargs.get("request_id", "") or "").strip()
        if not rid:
            return _fail(self.name, "[参数错误] request_id 不能为空")
        try:
            timeout_s = float(kwargs.get("timeout_s", _DEFAULT_WAIT_S) or _DEFAULT_WAIT_S)
        except (TypeError, ValueError):
            return _fail(self.name, "[参数错误] timeout_s 非法")
        timeout_s = max(1.0, min(timeout_s, _MAX_WAIT_S))

        rec = self._store.wait_for_decision(rid, timeout_s)
        if rec is None:
            return _fail(self.name, f"[未找到] 提权申请不存在: {rid}")

        if rec.get("_sig_unverified"):
            # ESC-03（FR-03）: 签名失效（跨进程/重启）的申请面板永远无法审批，
            # 立即失败并提示重新申请，不再静默等满超时。
            return _fail(
                self.name,
                f"[已失效] request_id={rid} 由其他进程签名，本会话无法等待其审批结果。"
                + _RETRY_HINT,
            )

        status = rec.get("status", "")
        if status == "pending":
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=(
                    f"[等待超时] request_id={rid} 仍为 pending（人工未处理）。"
                    + _review_expiry_note(rec)
                    + "可再次 escalation_wait 继续等待，或向用户说明后改期；"
                    "不要在无令牌状态下重试被阻断命令。"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        if status == "failed":
            # EVO-20261127-dd37be50: 人工批准时 Host 判定签发材料不可成立（终态）。
            # 明确失败，不再以 pending 让调用方空等；给出可执行的重试路径。
            code = str(rec.get("last_issue_error") or "") or "unknown"
            failed_at = str(rec.get("issue_failed_at") or "")
            lines = [
                f"[签发失败] request_id={rid}",
                f"失败码: {ISSUE_FAILED_REASON_PREFIX}（{code}）",
                f"原因: {ISSUE_FAIL_REASON_HINTS.get(code, ISSUE_FAIL_REASON_DEFAULT_HINT)}",
            ]
            if failed_at:
                lines.append(f"失败时间: {failed_at}")
            lines.append(f"重试指引: {_ISSUE_RETRY_HINT}")
            return _fail(self.name, "\n".join(lines))
        if status == "approved":
            token = str(rec.get("token", "") or "")
            exp = str(rec.get("token_expires_at", "") or "")
            note = str(rec.get("decision_note", "") or "")
            if rec.get("request_kind") == "verify_receipt":
                receipt_id = str(rec.get("verify_receipt_id", "") or "")
                if not receipt_id:
                    return _fail(self.name, f"[状态异常] Host 验证凭证未签发: {rid}")
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    content=(f"[Host 已签发] request_id={rid}\n"
                             f"verify_ref={receipt_id}\n"
                             "专用宿主签发已完成；无需 execute_command 或 host-grant。"),
                    tool_call_id="",
                    tool_name=self.name,
                )
            if rec.get("request_kind") == "host_grant":
                # DESIGN-20261114: host-grant 类批准不铸灾难令牌，凭持久 grant_id 消费
                gid = str(rec.get("host_grant_id", "") or "")
                if not gid:
                    return _fail(
                        self.name,
                        f"[状态异常] host-grant 申请已批准但持久授权签发中断（无 grant_id）。"
                        f"该申请不可复用，请重新提交 host_access_request: {rid}",
                    )
                hr = rec.get("host_request", {}) or {}
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    content=(
                        f"[已批准] host-grant request_id={rid}\n"
                        f"审批备注: {note or '(无)'}\n"
                        f"grant_id={gid}\n"
                        f"授权: {hr.get('host_operation', '?')} {hr.get('host_canonical_path', '?')}"
                        f"（单次，过期时间 {hr.get('host_expires_at', '见 grant 记录')}）\n"
                        f"用法: execute_command(host_grant_id={gid}, "
                        f"command=<与申请逐字一致的命令>, workdir=<与申请一致或省略>) "
                        f"—— grant 绑定精确命令文本/cwd/会话/路径，任何一项不同都会被拒。"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            if not token:
                return _fail(self.name, f"[状态异常] approved 但令牌缺失，请重新申请: {rid}")
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=(
                    f"[已批准] request_id={rid}\n"
                    f"审批备注: {note or '(无)'}\n"
                    f"escalation_token={token}\n"
                    f"有效期至: {exp}\n"
                    f"用法: execute_command(command=<与申请逐字一致的命令>, "
                    f"escalation_token={token}) —— 单次有效，命令文本任何改动都会被拒。"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        if status == "denied":
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=(
                    f"[已拒绝] request_id={rid}\n拒绝理由: "
                    f"{rec.get('decision_note', '') or '(未填写)'}\n"
                    f"请遵守人工裁决：不得重试该命令，也不得换拼写绕行同类目标。"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        if status == "expired":
            return _fail(self.name, f"[已过期] request_id={rid}；原申请记录仍保留。" + _RETRY_HINT)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"[状态] request_id={rid} → {status}"
                f"（consumed=令牌已用；expired=已过期。过期/耗尽如仍必要请重新申请。）"
            ),
            tool_call_id="",
            tool_name=self.name,
        )
