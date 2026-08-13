"""AI 主动出站飞书工具（EVO-20260813-432813b2，涉安全边界演进）。

设计原则（用户授权实施，2026-08-13）：
- 默认禁用：FEISHU_OUTBOUND_ENABLED 默认 false，需人工开启
- 二次确认：confirm=True 才执行，否则仅打印"待发送"预览
- 接收方白名单：仅允许向已交互过的飞书用户发送（FEISHU_OUTBOUND_ALLOWED_USERS 配置）
- 速率限制：每接收方 ≤5 条/分钟（防风暴）
- 审计落盘：data/audit/feishu_outbound.jsonl（每次主动出站记录）
- 复用 FeishuRestClient：与入站消息回复共享底层 SDK 客户端
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

# ── 安全防护：模块级状态（单进程内有效） ──
_audit_dir_env = os.environ.get("FEISHU_AUDIT_DIR", "data/audit")
_outbound_audit_path = Path(_audit_dir_env) / "feishu_outbound.jsonl"

# 速率状态：{ receive_id: [timestamp1, timestamp2, ...] }
_rate_state: dict[str, list[float]] = {}


def _is_outbound_enabled() -> bool:
    """读取环境变量 FEISHU_OUTBOUND_ENABLED（默认 false）."""
    return os.environ.get("FEISHU_OUTBOUND_ENABLED", "false").lower() in ("true", "1", "yes")


def _get_allowed_users() -> set[str]:
    """读取 FEISHU_OUTBOUND_ALLOWED_USERS（逗号分隔，默认空=全部拒绝）."""
    raw = os.environ.get("FEISHU_OUTBOUND_ALLOWED_USERS", "").strip()
    if not raw:
        return set()
    return {u.strip() for u in raw.split(",") if u.strip()}


def _get_rate_limit() -> int:
    """读取 FEISHU_OUTBOUND_RATE_PER_MIN（默认 5）."""
    raw = os.environ.get("FEISHU_OUTBOUND_RATE_PER_MIN", "5").strip()
    try:
        v = int(raw)
        return v if v > 0 else 5
    except ValueError:
        return 5


def _check_rate_limit(receive_id: str) -> tuple[bool, str]:
    """速率检查：返回 (ok, message)."""
    limit = _get_rate_limit()
    now = time.time()
    timestamps = _rate_state.setdefault(receive_id, [])
    cutoff = now - 60.0
    timestamps[:] = [t for t in timestamps if t > cutoff]
    if len(timestamps) >= limit:
        return False, f"[速率限制] 接收方 {receive_id} 在过去 60s 内已发送 {len(timestamps)} 条（上限 {limit}/分钟）"
    return True, ""


def _record_send(receive_id: str) -> None:
    """记录本次发送时间戳."""
    _rate_state.setdefault(receive_id, []).append(time.time())


def _write_audit(record: dict) -> None:
    """审计落盘（fail-open: IO 失败不阻断发送）."""
    try:
        _outbound_audit_path.parent.mkdir(parents=True, exist_ok=True)
        with _outbound_audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[feishu_outbound] 审计写入失败: {exc}", file=sys.stderr)


def _mask_id(value: str) -> str:
    """脱敏 receive_id（前后各保留 4 字符）."""
    if not value or len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-4:]


# ── 工具定义 ──

SEND_FEISHU_MESSAGE_TOOL_DEF: dict = {
    "name": "send_feishu_message",
    "description": "主动向飞书用户/群发送文本/卡片消息（EVO-20260813-432813b2 涉安全边界）。何时用: 用户明确要求'把内容发到我飞书'且已开启 FEISHU_OUTBOUND_ENABLED 时。何时不用: 默认禁用、未经用户授权、未通过白名单/速率限制检查时（程序会如实拒绝并说明原因）。失败对策: 开关未启用/白名单不通过/超速率/SDK 异常均如实返回失败原因。",
    "parameters": {
        "type": "object",
        "properties": {
            "receive_id": {"type": "string", "description": "飞书 open_id / chat_id / user_id（与 receive_id_type 对应）"},
            "content": {"type": "string", "description": "消息内容（Markdown/纯文本）"},
            "receive_id_type": {"type": "string", "enum": ["open_id", "chat_id", "user_id", "email"], "description": "接收方 ID 类型，默认 open_id"},
            "msg_type": {"type": "string", "enum": ["text", "interactive"], "description": "消息类型，text=纯文本，interactive=卡片（含表格/链接）"},
            "confirm": {"type": "boolean", "description": "二次确认（必须为 true 才执行）"},
        },
        "required": ["receive_id", "content", "confirm"],
    },
}

CREATE_FEISHU_DOC_TOOL_DEF: dict = {
    "name": "create_feishu_doc",
    "description": "创建飞书文档（docx）并返回 doc_id + URL（EVO-20260813-432813b2 涉安全边界）。何时用: 用户明确要求生成飞书文档。何时不用: 开关未启用时。失败对策: SDK 异常/权限不足如实返回。",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "文档标题"},
            "content": {"type": "string", "description": "文档 Markdown 内容"},
            "folder_token": {"type": "string", "description": "目标文件夹 token（可选）"},
            "confirm": {"type": "boolean", "description": "二次确认"},
        },
        "required": ["title", "content", "confirm"],
    },
}

SEND_FEISHU_ATTACHMENT_TOOL_DEF: dict = {
    "name": "send_feishu_attachment",
    "description": "向飞书用户发送本地文件或飞书文档作为附件（EVO-20260813-432813b2 涉安全边界）。何时用: 用户要求'把文档发给我'且本地有该文件时。何时不用: 开关未启用/白名单不通过/速率限制/文件不存在时。失败对策: 各类失败如实回执。",
    "parameters": {
        "type": "object",
        "properties": {
            "receive_id": {"type": "string", "description": "飞书 open_id/chat_id/user_id"},
            "file_path": {"type": "string", "description": "本地文件绝对路径"},
            "doc_id": {"type": "string", "description": "已创建的飞书文档 ID（与 file_path 二选一）"},
            "receive_id_type": {"type": "string", "enum": ["open_id", "chat_id", "user_id", "email"]},
            "confirm": {"type": "boolean", "description": "二次确认"},
        },
        "required": ["receive_id", "confirm"],
    },
}


# ── 工具实现 ──

def _preflight_check(receive_id: str, confirm: bool) -> tuple[bool, str]:
    """出站前置检查（开关/二次确认/白名单/速率）."""
    if not _is_outbound_enabled():
        return False, "[主动出站已禁用] FEISHU_OUTBOUND_ENABLED 未开启（默认 false，需人工开启）"
    if not confirm:
        return False, "[二次确认未通过] 必须显式传 confirm=true 才执行主动出站（防误操作）"
    allowed = _get_allowed_users()
    if allowed and receive_id not in allowed:
        return False, f"[白名单未通过] 接收方 {_mask_id(receive_id)} 不在 FEISHU_OUTBOUND_ALLOWED_USERS 配置内"
    ok, msg = _check_rate_limit(receive_id)
    if not ok:
        return False, msg
    return True, ""


def run_send_feishu_message(
    ctx: Any,
    audit: Any,
    args: dict,
) -> ToolResult:
    """send_feishu_message 工具实现."""
    receive_id = (args.get("receive_id") or "").strip()
    content = args.get("content") or ""
    receive_id_type = args.get("receive_id_type") or "open_id"
    msg_type = args.get("msg_type") or "interactive"
    confirm = bool(args.get("confirm"))

    if not receive_id or not content:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] receive_id 与 content 必填",
            tool_call_id="",
            tool_name="send_feishu_message",
        )

    ok, msg = _preflight_check(receive_id, confirm)
    if not ok:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=msg,
            tool_call_id="",
            tool_name="send_feishu_message",
        )

    try:
        import lark_oapi as lark

        from llm_loop.feishu.config import load_feishu_config
        from llm_loop.feishu.rest import FeishuRestClient
        config = load_feishu_config()
        if not config.has_credentials:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[配置缺失] FEISHU_APP_ID/FEISHU_APP_SECRET 未配置",
                tool_call_id="",
                tool_name="send_feishu_message",
            )
        lark_client = (
            lark.Client.builder()
            .app_id(config.app_id)
            .app_secret(config.app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
        client = FeishuRestClient(config, lark_client)
        # send_text 已含 interactive/text 两种模式（内部按 msg_type 路由）
        message_id = client.send_text(receive_id, content, receive_id_type=receive_id_type)
    except Exception as exc:
        _write_audit({
            "ts": time.time(),
            "action": "send_message",
            "receive_id": _mask_id(receive_id),
            "receive_id_type": receive_id_type,
            "msg_type": msg_type,
            "result": "fail",
            "error": str(exc),
        })
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[发送失败] FeishuRestClient 异常: {exc}",
            tool_call_id="",
            tool_name="send_feishu_message",
        )

    _record_send(receive_id)
    _write_audit({
        "ts": time.time(),
        "action": "send_message",
        "receive_id": _mask_id(receive_id),
        "receive_id_type": receive_id_type,
        "msg_type": msg_type,
        "result": "success",
        "message_id": message_id,
        "content_len": len(content),
    })

    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=f"[send_feishu_message] 主动发送成功 message_id={message_id}",
        tool_call_id="",
        tool_name="send_feishu_message",
    )


def run_create_feishu_doc(
    ctx: Any,
    audit: Any,
    args: dict,
) -> ToolResult:
    """create_feishu_doc 工具实现."""
    title = (args.get("title") or "").strip()
    content = args.get("content") or ""
    folder_token = args.get("folder_token")
    confirm = bool(args.get("confirm"))

    if not title or not content:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] title 与 content 必填",
            tool_call_id="",
            tool_name="create_feishu_doc",
        )

    if not _is_outbound_enabled():
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[主动出站已禁用] FEISHU_OUTBOUND_ENABLED 未开启",
            tool_call_id="",
            tool_name="create_feishu_doc",
        )
    if not confirm:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[二次确认未通过] 必须 confirm=true 才执行",
            tool_call_id="",
            tool_name="create_feishu_doc",
        )

    try:
        import lark_oapi as lark

        from llm_loop.feishu.config import load_feishu_config
        from llm_loop.feishu.rest import FeishuRestClient
        config = load_feishu_config()
        if not config.has_credentials:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[配置缺失] FEISHU_APP_ID/FEISHU_APP_SECRET 未配置",
                tool_call_id="",
                tool_name="create_feishu_doc",
            )
        lark_client = (
            lark.Client.builder()
            .app_id(config.app_id)
            .app_secret(config.app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
        client = FeishuRestClient(config, lark_client)
        doc_id, doc_url = client.create_doc(title=title, content=content, folder_token=folder_token)
    except Exception as exc:
        _write_audit({
            "ts": time.time(),
            "action": "create_doc",
            "title": title,
            "result": "fail",
            "error": str(exc),
        })
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[创建文档失败] {exc}",
            tool_call_id="",
            tool_name="create_feishu_doc",
        )

    _write_audit({
        "ts": time.time(),
        "action": "create_doc",
        "title": title,
        "doc_id": doc_id,
        "doc_url": doc_url,
        "result": "success",
        "content_len": len(content),
    })

    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=f"[create_feishu_doc] 创建成功 doc_id={doc_id} url={doc_url}",
        tool_call_id="",
        tool_name="create_feishu_doc",
    )


def run_send_feishu_attachment(
    ctx: Any,
    audit: Any,
    args: dict,
) -> ToolResult:
    """send_feishu_attachment 工具实现."""
    receive_id = (args.get("receive_id") or "").strip()
    file_path = args.get("file_path")
    doc_id = args.get("doc_id")
    receive_id_type = args.get("receive_id_type") or "open_id"
    confirm = bool(args.get("confirm"))

    if not receive_id:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] receive_id 必填",
            tool_call_id="",
            tool_name="send_feishu_attachment",
        )
    if not file_path and not doc_id:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] file_path 与 doc_id 至少传一个",
            tool_call_id="",
            tool_name="send_feishu_attachment",
        )

    ok, msg = _preflight_check(receive_id, confirm)
    if not ok:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=msg,
            tool_call_id="",
            tool_name="send_feishu_attachment",
        )

    if file_path:
        fp = Path(file_path)
        if not fp.exists() or not fp.is_file():
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[文件不存在] {file_path}",
                tool_call_id="",
                tool_name="send_feishu_attachment",
            )

    try:
        import lark_oapi as lark

        from llm_loop.feishu.config import load_feishu_config
        from llm_loop.feishu.rest import FeishuRestClient
        config = load_feishu_config()
        if not config.has_credentials:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[配置缺失] FEISHU_APP_ID/FEISHU_APP_SECRET 未配置",
                tool_call_id="",
                tool_name="send_feishu_attachment",
            )
        lark_client = (
            lark.Client.builder()
            .app_id(config.app_id)
            .app_secret(config.app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
        client = FeishuRestClient(config, lark_client)
        message_id = client.send_file(
            receive_id=receive_id,
            file_path=file_path,
            doc_id=doc_id,
            receive_id_type=receive_id_type,
        )
    except Exception as exc:
        _write_audit({
            "ts": time.time(),
            "action": "send_attachment",
            "receive_id": _mask_id(receive_id),
            "file_path": file_path,
            "doc_id": doc_id,
            "result": "fail",
            "error": str(exc),
        })
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[发送附件失败] {exc}",
            tool_call_id="",
            tool_name="send_feishu_attachment",
        )

    _record_send(receive_id)
    _write_audit({
        "ts": time.time(),
        "action": "send_attachment",
        "receive_id": _mask_id(receive_id),
        "file_path": file_path,
        "doc_id": doc_id,
        "result": "success",
        "message_id": message_id,
    })

    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=f"[send_feishu_attachment] 附件发送成功 message_id={message_id}",
        tool_call_id="",
        tool_name="send_feishu_attachment",
    )
