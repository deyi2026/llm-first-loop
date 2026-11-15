"""Host capability grant 工具（DESIGN-20261114 Deepin P0 最小闭环）.

沙盒（bwrap/sandbox-exec）外单文件 read/write 的人工授权申请入口：
申请字段由服务端冻结（会话/工具/cwd/realpath/文件 sha256/精确命令文本），
Web 审批面板仅接受**已登录浏览器会话**批准（loopback 未登录不能自批），
批准后签发持久 HostCapabilityGrant，凭 grant_id 以 execute_command 在
沙盒内精确单文件 bind 执行一次。

首批范围（设计 §4 决议）：
- 仅既存**常规单文件**；创建/删除/目录/递归一律拒绝；
- 仅 read（--ro-bind）与 write（--bind）两种操作；
- 命令文本/cwd/会话/路径/文件版本逐项绑定，任何一项不同即拒绝；
- 不可绕过父 write-scope（deny 命中仍拒）、灾难命令守卫、OS ACL。
"""

from __future__ import annotations

import hashlib
import os

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id, workspace_base
from llm_loop.tools.escalation import EscalationStore

_MAX_TTL_S = 600
_MAX_WAIT_S = 120
_MAX_COMMAND_CHARS = 2000


def _fail(content: str) -> ToolResult:
    return ToolResult(
        status=ToolResultStatus.FAILURE,
        content=content,
        tool_call_id="",
        tool_name="host_access_request",
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_request(path: str, operation: str, command: str, justification: str, ttl_s: int) -> str | None:
    """返回拒绝原因（None=通过）。全部 fail-closed，不做静默纠偏。"""
    if not os.path.isabs(path):
        return f"[拒绝] path 必须是绝对路径（收到 {path!r}）"
    if any(ch in path for ch in "*?["):
        return "[拒绝] path 含 glob 通配符（host-grant 仅支持精确单文件）"
    if "/../" in path or path.endswith("/.."):
        return "[拒绝] path 含 .. 段"
    if os.path.islink(path):
        return f"[拒绝] path 本身是符号链接（host-grant 拒绝 symlink，请提交真实路径）: {path}"
    real = os.path.realpath(path)
    if real != path:
        return f"[拒绝] path 非真实路径（realpath={real}）。请以真实绝对路径申请"
    if not os.path.isfile(real):
        return f"[拒绝] 仅支持**既存常规单文件**（不存在/目录/设备/已删除均拒绝）: {path}"
    if operation not in ("read", "write"):
        return f"[拒绝] operation 仅支持 read|write（收到 {operation!r}）；创建/删除/目录操作 P0 不支持"
    if not command or not command.strip():
        return "[拒绝] command 不能为空：授权绑定你计划以 execute_command 执行的精确命令文本"
    if len(command) > _MAX_COMMAND_CHARS:
        return f"[拒绝] command 过长（>{_MAX_COMMAND_CHARS} 字符）"
    if not justification or len(justification.strip()) < 10:
        return "[拒绝] justification 至少 10 个字符，说明为什么需要沙盒外访问该文件"
    if not (1 <= ttl_s <= _MAX_TTL_S):
        return f"[拒绝] ttl_seconds 取值 1..{_MAX_TTL_S} 秒（默认 600）"
    return None


class HostAccessRequestTool:
    name = "host_access_request"
    description = (
        "沙盒外单个既存文件 read/write 的人工授权申请（DESIGN-20261114 Deepin P0）。"
        "申请内容服务端冻结：会话/工具/cwd/真实路径/文件 sha256/精确命令文本，"
        "web 审批面板人工批准后签发一次性持久 grant（默认 600s 过期），"
        "凭 execute_command(host_grant_id=...) 在沙盒内以精确单文件授权执行一次"
        "（后端：Linux bwrap=FD 固定挂载；macOS sandbox-exec=可写根追加，EVO-20261115-488367d4）。"
        "仅支持既存常规单文件（symlink/目录/不存在/通配符拒绝）；operation 仅 read|write；"
        "command 必须与随后 execute_command 的 command 参数逐字一致；"
        "批准通道仅限已登录浏览器会话（未登录 loopback/Bearer 不能自批）。"
        "提交后用 escalation_wait(request_id) 等待审批结果。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "目标文件绝对路径（必须真实路径：非 symlink、realpath 一致、既存常规文件）",
            },
            "operation": {
                "type": "string",
                "enum": ["read", "write"],
                "description": "read=沙盒内只读可见（bwrap --ro-bind；sandbox-exec 读本就放开，授权仍冻结文件版本与单次语义）；write=沙盒内可写（bwrap --bind / sandbox-exec 可写根，文件级）",
            },
            "command": {
                "type": "string",
                "description": (
                    "计划以 execute_command 执行的精确命令文本（授权与它逐字绑定，"
                    "执行时任何差异都会被拒绝）"
                ),
            },
            "justification": {
                "type": "string",
                "maxLength": 2000,
                "description": "必要性说明（≥10 字符）：为什么需要沙盒外访问、影响与替代方案。人工审批据此裁决。",
            },
            "ttl_seconds": {
                "type": "integer",
                "description": "grant 有效期秒数（默认 600，上限 600；从批准时刻起算）",
            },
            "wait_seconds": {
                "type": "number",
                "description": "提交后原地等待审批的秒数（0-120，默认 0=立即返回由 escalation_wait 等待）",
            },
        },
        "required": ["path", "operation", "command", "justification"],
    }

    def __init__(self, store: EscalationStore) -> None:
        self._store = store

    def execute(self, **kwargs) -> ToolResult:
        path = str(kwargs.get("path", "") or "").strip()
        operation = str(kwargs.get("operation", "") or "").strip().lower()
        command = str(kwargs.get("command", "") or "")
        justification = str(kwargs.get("justification", "") or "").strip()
        try:
            ttl_s = int(kwargs.get("ttl_seconds", _MAX_TTL_S) or _MAX_TTL_S)
        except (TypeError, ValueError):
            return _fail("[拒绝] ttl_seconds 非法")
        try:
            wait_s = float(kwargs.get("wait_seconds", 0) or 0)
        except (TypeError, ValueError):
            wait_s = 0.0
        wait_s = max(0.0, min(wait_s, _MAX_WAIT_S))

        reason = _validate_request(path, operation, command, justification, ttl_s)
        if reason:
            return _fail(reason)

        canonical = os.path.realpath(path)
        try:
            file_sha = _sha256_file(canonical)
        except OSError as exc:
            return _fail(f"[拒绝] 无法读取目标文件计算版本哈希（fail-closed）: {exc}")
        cwd = os.path.realpath(workspace_base())
        session = current_session_id.get() or ""
        if not session:
            return _fail("[拒绝] 当前无会话上下文（host-grant 必须绑定会话）")

        display = (
            f"[host-grant:{operation}] {canonical}\n"
            f"file_sha256={file_sha}\n"
            f"cwd={cwd}\n"
            f"command={command}"
        )
        extra = {
            "host_operation": operation,
            "host_canonical_path": canonical,
            "host_file_sha256": file_sha,
            "host_command_sha256": _sha256_text(command),
            "host_cwd": cwd,
            "host_session_id": session,
            "host_ttl_s": ttl_s,
            "host_command_text": command,
        }
        rec = self._store.create(
            tool_name="execute_command",
            command=display,
            justification=justification,
            session_id=session,
            kind="host_grant",
            extra=extra,
        )
        rid = rec.get("id", "")

        if wait_s <= 0:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=(
                    f"[已提交] host-grant 申请 request_id={rid}\n"
                    f"授权请求: {operation} {canonical}\n"
                    f"（绑定: 会话 {session} | cwd {cwd} | 文件 sha256 {file_sha[:16]}… | "
                    f"命令文本 {extra['host_command_sha256'][:16]}…；有效期 {ttl_s}s）\n"
                    f"web 审批面板（需**已登录**浏览器会话）批准后，"
                    f"用 escalation_wait(request_id='{rid}') 获取 grant_id。"
                ),
                tool_call_id="",
                tool_name=self.name,
            )

        decided = self._store.wait_for_decision(rid, wait_s)
        if decided is None:
            return _fail(f"[未找到] 提权申请不存在: {rid}")
        status = decided.get("status", "")
        if status == "pending":
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=(
                    f"[等待超时] request_id={rid} 仍为 pending（人工未处理）。"
                    f"可用 escalation_wait(request_id='{rid}') 继续等待。"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        if status == "approved":
            gid = str(decided.get("host_grant_id", "") or "")
            if not gid:
                return _fail(
                    f"[状态异常] 已批准但持久授权签发中断（无 grant_id），"
                    f"请重新提交 host_access_request: {rid}"
                )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=(
                    f"[已批准] host-grant request_id={rid}\n"
                    f"grant_id={gid}\n"
                    f"用法: execute_command(host_grant_id='{gid}', "
                    f"command=<与申请逐字一致的命令>) —— 单次有效。"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        if status == "denied":
            return _fail(
                f"[已拒绝] request_id={rid}\n拒绝理由: "
                f"{decided.get('decision_note', '') or '(未填写)'}\n"
                f"请遵守人工裁决：不得换路径/命令重试同类目标。"
            )
        return _fail(f"[状态] request_id={rid} → {status}（如仍必要请重新申请）")
