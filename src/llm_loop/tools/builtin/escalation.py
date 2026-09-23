"""提权闭环工具（escalation_request / escalation_wait）.

配合 tools/escalation.py EscalationStore 与 registry 灾难层令牌校验:
被灾难性硬阻断（FR-SAFE-01）拦下、但确属必要的操作，可提交人工提权申请，
web 面板弹窗审批后凭一次性令牌重发同一命令。闭环全程无需用户向 AI 手动
转述审批结果（escalation_wait 轮询接收决定）。
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.tools.escalation import EscalationStore
from llm_loop.tools.safety import CatastrophicGuard

_MAX_WAIT_S = 300
_DEFAULT_WAIT_S = 120


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
                f"状态: pending（web 面板将弹窗提示人工审批）\n"
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
        "同一命令；denied → 拒绝理由；超时未决 → 返回 pending（可再等或改期）。"
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

        status = rec.get("status", "")
        if status == "pending":
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=(
                    f"[等待超时] request_id={rid} 仍为 pending（人工未处理）。"
                    f"可再次 escalation_wait 继续等待，或向用户说明后改期；"
                    f"不要在无令牌状态下重试被阻断命令。"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        if status == "approved":
            token = str(rec.get("token", "") or "")
            exp = str(rec.get("token_expires_at", "") or "")
            note = str(rec.get("decision_note", "") or "")
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
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"[状态] request_id={rid} → {status}"
                f"（consumed=令牌已用；expired=已过期。过期/耗尽如仍必要请重新申请。）"
            ),
            tool_call_id="",
            tool_name=self.name,
        )
