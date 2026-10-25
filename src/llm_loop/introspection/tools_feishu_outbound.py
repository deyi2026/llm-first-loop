"""AI 主动出站飞书工具（EVO-20260813-432813b2，涉安全边界演进）。

设计原则（用户授权实施，2026-08-13）：
- 默认禁用：FEISHU_OUTBOUND_ENABLED 默认 false，需人工开启
- 二次确认：confirm=True 才执行，否则仅打印"待发送"预览
- 接收方白名单：仅允许向已交互过的飞书用户发送（FEISHU_OUTBOUND_ALLOWED_USERS 配置）；
  未设置时回退 {FEISHU_OWNER_OPEN_ID}，两者皆空 = 默认全部拒绝（P0-4/S1-3：空集合
  不再放行所有人），显式逃生阀 FEISHU_OUTBOUND_ALLOW_ALL=1（每次放行记审计+warning）
- 附件根约束：file_path realpath 后必须位于 workspace_root / <repo>/data / /tmp 之内，
  且命中 security_guard.sensitive_path_reason() 的敏感文件判定直接拒绝
- 内容泄密拦截：security_guard.scan_text() 检出高置信密钥 → 拒绝且不回显命中片段
  （逃生阀 LFL_FEISHU_ALLOW_SECRETS=1，放行记 warning）
- folder_token 约束：FEISHU_DOC_FOLDER_ALLOWLIST 未设置时仅允许空 folder_token（根目录）
- 速率限制：每接收方 ≤5 条/分钟（防风暴）
- 审计落盘：data/audit/feishu_outbound.jsonl（每次主动出站记录）
- 复用 FeishuRestClient：与入站消息回复共享底层 SDK 客户端
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from llm_loop import security_guard
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.runtime.resolver import business_config_snapshot

logger = logging.getLogger(__name__)

# ── 安全防护：模块级状态（单进程内有效） ──
_OUTBOUND_CONFIG = business_config_snapshot("feishu_outbound")
_audit_dir_env = _OUTBOUND_CONFIG.get("FEISHU_AUDIT_DIR", "data/audit")
_outbound_audit_path = Path(_audit_dir_env) / "feishu_outbound.jsonl"

# 速率状态：{ receive_id: [timestamp1, timestamp2, ...] }
_rate_state: dict[str, list[float]] = {}


def _is_outbound_enabled() -> bool:
    """读取环境变量 FEISHU_OUTBOUND_ENABLED（默认 false）."""
    return os.environ.get("FEISHU_OUTBOUND_ENABLED", "false").lower() in ("true", "1", "yes")


def _get_allowed_users() -> set[str]:
    """读取允许接收方集合（P0-4/S1-3：默认拒绝，空集合不再放行所有人）.

    优先级：
    1. FEISHU_OUTBOUND_ALLOWED_USERS（逗号分隔 open_id/chat_id/user_id）
    2. 未设置时回退 {FEISHU_OWNER_OPEN_ID}（保底 owner 通知通道不中断）
    3. 两者皆空 → 空集合 = 拒绝所有接收方，除非显式逃生阀
       FEISHU_OUTBOUND_ALLOW_ALL=1（该模式每次放行都写审计 + warning）
    """
    raw = os.environ.get("FEISHU_OUTBOUND_ALLOWED_USERS", "").strip()
    if raw:
        return {u.strip() for u in raw.split(",") if u.strip()}
    owner = os.environ.get("FEISHU_OWNER_OPEN_ID", "").strip()
    if owner:
        return {owner}
    return set()


def _allow_all_override() -> bool:
    """显式逃生阀 FEISHU_OUTBOUND_ALLOW_ALL=1：允许空白名单放行所有接收方."""
    return os.environ.get("FEISHU_OUTBOUND_ALLOW_ALL", "").strip().lower() in ("1", "true", "yes")


def _allow_secrets_override() -> bool:
    """显式逃生阀 LFL_FEISHU_ALLOW_SECRETS=1：放行含高置信密钥特征的内容."""
    return os.environ.get("LFL_FEISHU_ALLOW_SECRETS", "").strip().lower() in ("1", "true", "yes")


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


# ── P0-4 / S1-3 出站约束辅助（判定原语单一事实源：llm_loop.security_guard）──

def _attachment_roots() -> list[Path]:
    """附件允许根（resolve 后比较）：workspace_root、<workspace>/data、/tmp."""
    try:
        from llm_loop.core.run_context import workspace_base

        ws = Path(workspace_base()).resolve()
    except Exception:  # noqa: BLE001 — 兜底：workspace 上下文不可用时退 cwd（与 fs 工具同策略）
        ws = Path.cwd().resolve()
    return [ws, ws / "data", Path("/tmp").resolve()]


def _check_attachment_path(file_path: str) -> tuple[str, str] | None:
    """附件路径约束（S1-3）：越出允许根 / 命中敏感文件判定 → 返回 (错误码, 说明)；通过返回 None.

    敏感判定走 security_guard.sensitive_path_reason()（单一事实源，不在此重写正则）；
    错误信息只附判定原因（dir:<name> / name:<file>），不读不附文件内容。
    """
    try:
        resolved = Path(file_path).expanduser().resolve(strict=False)
    except OSError as exc:
        return "attachment_path_outside_workspace", f"路径解析失败: {exc}"
    roots = _attachment_roots()
    if not any(resolved == r or resolved.is_relative_to(r) for r in roots):
        return (
            "attachment_path_outside_workspace",
            "附件真实路径（realpath）越出允许根 workspace_root / <repo>/data / /tmp，已拒绝；"
            "如需发送工作区外文件，请先将其复制到工作区或 /tmp 下",
        )
    reason = security_guard.sensitive_path_reason(resolved)
    if reason is not None:
        return (
            "attachment_sensitive_file",
            f"命中敏感文件判定（{reason}），疑似凭据/密钥文件，已拒绝外发",
        )
    return None


def _text_to_scan(content: str, *, msg_type: str | None = None) -> str:
    """待扫描文本：card(interactive) 内容是 JSON 文本，额外做一次解码-重编码（覆盖 \\uXXXX 转义密钥）."""
    texts = [content]
    if msg_type == "interactive" or content.lstrip()[:1] in ("{", "["):
        with contextlib.suppress(ValueError, TypeError):
            texts.append(json.dumps(json.loads(content), ensure_ascii=False))
    return "\n".join(t for t in texts if t)


def _check_outbound_text(
    text: str, *, action: str, receive_id: str = "", title: str = ""
) -> tuple[bool, str]:
    """发送前内容泄密拦截（P0-4）：高置信密钥特征 → 拒绝；错误信息只给 kind 列表，不回显命中片段."""
    kinds = sorted({h.kind for h in security_guard.scan_text(text) if h.severity == "strong"})
    if not kinds:
        return True, ""
    record: dict[str, Any] = {
        "ts": time.time(),
        "action": action,
        "result": "blocked_secret",
        "secret_kinds": kinds,
        "content_len": len(text),
    }
    if receive_id:
        record["receive_id"] = _mask_id(receive_id)
    if title:
        record["title"] = title
    if _allow_secrets_override():
        logger.warning(
            "[feishu_outbound] LFL_FEISHU_ALLOW_SECRETS=1 生效：内容含高置信密钥特征 kinds=%s 仍被放行（action=%s）",
            kinds,
            action,
        )
        record["result"] = "allowed_secret_override"
        _write_audit(record)
        return True, ""
    _write_audit(record)
    return False, (
        "[outbound_content_secret_detected] 内容检测到高置信密钥特征 kinds="
        + ",".join(kinds)
        + "（为防泄露不回显命中片段）；确需发送请人工确认后设置 LFL_FEISHU_ALLOW_SECRETS=1"
    )


def _folder_token_allowed(folder_token: str | None) -> bool:
    """folder_token 约束（P0-4）：FEISHU_DOC_FOLDER_ALLOWLIST 设置时非空 token 必须在其中；未设置时只允许空 token."""
    token = (folder_token or "").strip()
    raw = os.environ.get("FEISHU_DOC_FOLDER_ALLOWLIST", "").strip()
    if not raw:
        return not token
    allowlist = {t.strip() for t in raw.split(",") if t.strip()}
    if not token:
        return True
    return token in allowlist


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
    if not allowed:
        # P0-4/S1-3：docstring 曾承诺"默认空=全部拒绝"，实现却是空集合放行所有人（fail-open）。
        # 现在反转默认：空集合 = 拒绝，除非显式逃生阀（每次放行写审计 + warning）。
        if not _allow_all_override():
            return False, (
                "[outbound_denied_no_allowlist] 接收方白名单为空，默认全部拒绝："
                "请设置 FEISHU_OUTBOUND_ALLOWED_USERS（逗号分隔 open_id/chat_id/user_id），"
                "或设置 FEISHU_OWNER_OPEN_ID 作为回退接收方；"
                "如确认放行所有接收方，显式设置 FEISHU_OUTBOUND_ALLOW_ALL=1（每次放行都会记审计与告警）"
            )
        logger.warning(
            "[feishu_outbound] FEISHU_OUTBOUND_ALLOW_ALL=1 生效：白名单为空仍放行接收方 %s（审计留痕）",
            _mask_id(receive_id),
        )
        _write_audit({
            "ts": time.time(),
            "action": "preflight_allow_all_override",
            "receive_id": _mask_id(receive_id),
            "result": "allowed_by_override",
        })
    elif receive_id not in allowed:
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

    # P0-4 内容泄密拦截：text 原文 / interactive 卡片 JSON 解码重编码后扫描
    ok, msg = _check_outbound_text(
        _text_to_scan(content, msg_type=msg_type), action="send_message", receive_id=receive_id
    )
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

    # P0-4 folder_token 约束：allowlist 未设置时只允许空 token（默认根目录）
    if not _folder_token_allowed(folder_token):
        _write_audit({
            "ts": time.time(),
            "action": "create_doc",
            "title": title,
            "result": "blocked_folder",
            "folder_token": ((folder_token or "").strip()[:8] + "***") if (folder_token or "").strip() else "",
        })
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                "[folder_not_allowed] folder_token 不在 FEISHU_DOC_FOLDER_ALLOWLIST 允许范围内"
                "（该变量未设置时仅允许空 folder_token=默认根目录）"
            ),
            tool_call_id="",
            tool_name="create_feishu_doc",
        )

    # P0-4 内容泄密拦截：title + content 一并扫描
    ok, msg = _check_outbound_text(f"{title}\n{content}", action="create_doc", title=title)
    if not ok:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=msg,
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
        # S1-3 附件根约束 + 敏感文件拦截（realpath 后判定，防 symlink 逃逸）
        verdict = _check_attachment_path(file_path)
        if verdict is not None:
            code, detail = verdict
            _write_audit({
                "ts": time.time(),
                "action": "send_attachment",
                "receive_id": _mask_id(receive_id),
                "file_path": file_path,
                "result": "blocked",
                "reason": code,
            })
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[{code}] {detail}",
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
