"""L3 协助收件箱工具（DESIGN-20261105 §4.7 / L3，跨会话协作）.

3 个工具:
- help_request: 投递一条协助请求到 pending/（跨会话持久化，可标记 block 阻塞）
- help_inbox: 列未决请求 + counts/corrupted（供 coordination_status 与 S1-08 机检消费）
- help_resolve: 应答（resolved/declined），pending/<id> → done/<id>

失败口径: 参数缺失 missing_param / need 或 decision 非法 bad_param /
目录不可用 inbox_unavailable / id 不存在 not_found / 写失败 io_error /
损坏文件 store_corruption —— 一律 FAILURE 带 reason_code，不抛到宿主。
边界: 收到协助请求 ≠ 获得写权（设计 §4.7）；本工具组只做投递/应答记账。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.help_inbox import (
    HELP_DECISIONS,
    HELP_NEEDS,
    HelpInbox,
    HelpInboxCorruptionError,
    HelpInboxError,
    HelpInboxNotFoundError,
)

_MAX_ITEMS = 50  # help_inbox 回执条数上限（超出截断并如实标注，counts 恒为全量）

HELP_REQUEST_TOOL_DEF: dict = {
    "name": "help_request",
    "description": (
        "向其他会话投递一条协助请求（L3 文件式收件箱，跨会话持久化）。"
        "何时用: 需要另一个会话/人提供信息、评审，或本 lane 被卡住需要标记阻塞时。"
        "need 口径: info=要信息; block=被阻塞; review=请评审。"
        "block 的作用域（2026-11-09 起）: 填了 lane_id/to_session 只挡该 lane/会话的合并；"
        "两者都不填才是全局停工信号（会让所有 lane 合并被 S1-08 拦）——提醒某人收口用 info，别用 block。"
        "何时不用: 只是自查可读状态（用 help_inbox）。"
        "边界: 收到请求 ≠ 获得写权; 投递即止，不自动派发（被请求方自行认领）。"
        "失败对策: need 非法换合法值重试; inbox_unavailable 表示 data 目录不可写。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "主题（必填，一句话可辨识）"},
            "body": {"type": "string", "description": "详细说明（必填：要什么/为什么/给谁）"},
            "need": {
                "type": "string",
                "enum": list(HELP_NEEDS),
                "description": "协助类型（缺省 info; 显式空串按非法处理）",
            },
            "to_session": {"type": "string", "description": "目标会话 id（空=广播）"},
            "lane_id": {"type": "string", "description": "关联 lane（如有）"},
            "goal_id": {"type": "string", "description": "关联 goal（如有）"},
            "deadline": {"type": "string", "description": "期限（不透明字符串，建议 ISO）"},
        },
        "required": ["topic", "body"],
    },
}

HELP_INBOX_TOOL_DEF: dict = {
    "name": "help_inbox",
    "description": (
        "列出未决协助请求（L3 收件箱 pending/，按 ts 升序）。"
        "何时用: 开工前查有没有人向你/向所有人请求协助、有没有 need=block 的阻塞项"
        "（counts.blocking 就是 S1-08 机检的判定输入）。"
        "回执: {items:[...], counts:{pending,blocking}, corrupted:int}——"
        "corrupted 是被跳过的损坏文件数（如实报告，不静默）; items 超 50 条截断并标注。"
        "何时不用: 要应答用 help_resolve; 要看历史看 done/ 目录。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "need": {
                "type": "string",
                "enum": list(HELP_NEEDS),
                "description": "按 need 过滤（空=不过滤）",
            },
            "to_session": {
                "type": "string",
                "description": "按目标会话过滤（命中精确目标或广播; 空=不过滤）",
            },
        },
    },
}

HELP_RESOLVE_TOOL_DEF: dict = {
    "name": "help_resolve",
    "description": (
        "应答一条协助请求: pending/<id> → done/<id>，保留原字段并追加 "
        "response/by_session/resolved_at。decision=resolved（已解决）或 declined（婉拒）。"
        "何时用: 你提供了对方要的信息/评审，或明确不接受该请求时。"
        "幂等: 对已应答 id 重复调用返回既有终态记录，不覆写历史。"
        "失败对策: not_found 检查 id; bad_param 检查 decision 取值。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "help_request 回执的消息 id"},
            "response": {"type": "string", "description": "应答内容（必填）"},
            "decision": {
                "type": "string",
                "enum": list(HELP_DECISIONS),
                "description": "应答结论（缺省 resolved）",
            },
        },
        "required": ["id", "response"],
    },
}

HELP_TOOL_DEFS = [
    HELP_REQUEST_TOOL_DEF,
    HELP_INBOX_TOOL_DEF,
    HELP_RESOLVE_TOOL_DEF,
]


def _data_dir(host: Any) -> str:
    """宿主 data_dir 推导（与 tools_lane._store 同源取 host.audit_dir）。

    settings.audit_dir ≡ <data_dir>/audit（config.py 同一 property 链），
    故 audit_dir.parent 即 data_dir；宿主未装配或末段不是 audit → './data'
    （与既有口径一致: 拿不到时退 ./data，不伪造）。
    """
    audit_dir = getattr(host, "audit_dir", None)
    if audit_dir:
        path = Path(str(audit_dir))
        if path.name == "audit":
            return str(path.parent)
    return "./data"


def _inbox(host: Any) -> HelpInbox | None:
    try:
        return HelpInbox(_data_dir(host))
    except OSError:
        return None


def _session_id(host: Any) -> str:
    """当前会话 id（from_session/by_session 记账用，仅显示，不作鉴权）。"""
    try:
        sid = host.current_session_id()
        if sid:
            return str(sid)
    except Exception:  # noqa: BLE001 — 会话绑定仅用于显示
        pass
    try:
        from llm_loop.introspection.tools_status import bound_session_id

        return bound_session_id() or ""
    except Exception:  # noqa: BLE001
        return ""


def _fail(message: str, tool: str, reason_code: str) -> ToolResult:
    return ToolResult(
        ToolResultStatus.FAILURE, f"[{reason_code}] {message}", "", tool
    )


def _ok(payload: Any, tool: str, summary: str) -> ToolResult:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return ToolResult(ToolResultStatus.SUCCESS, f"{summary}\n{text}", "", tool)


def run_help_request(ctx: Any, host: Any, args: dict) -> ToolResult:
    inbox = _inbox(host)
    if inbox is None:
        return _fail("data 目录不可用，协助收件箱未装配", "help_request", "inbox_unavailable")
    topic = str(args.get("topic", "") or "").strip()
    body = str(args.get("body", "") or "").strip()
    missing = [n for n, v in (("topic", topic), ("body", body)) if not v]
    if missing:
        return _fail(f"缺少必填参数 {missing}", "help_request", "missing_param")
    need = str(args.get("need", "info") or "")
    if need not in HELP_NEEDS:
        return _fail(f"need 仅允许 {HELP_NEEDS}: {need!r}", "help_request", "bad_param")

    try:
        msg = inbox.post(
            topic=topic,
            body=body,
            need=need,
            from_session=_session_id(host),
            to_session=str(args.get("to_session", "") or ""),
            lane_id=str(args.get("lane_id", "") or ""),
            goal_id=str(args.get("goal_id", "") or ""),
            deadline=str(args.get("deadline", "") or ""),
        )
    except HelpInboxError as exc:
        return _fail(str(exc), "help_request", "bad_param")
    except OSError as exc:
        return _fail(f"收件箱写入失败: {exc}", "help_request", "io_error")

    note = (
        "\n注意: need=block 已计入阻塞——S1 第 8 条机检会因此不放行该 lane 合并。"
        if need == "block"
        else ""
    )
    return _ok(
        {"id": msg["id"], "path": str(inbox.pending_path(msg["id"]))},
        "help_request",
        f"[help 已投递] id={msg['id']} need={need} to={msg['to_session'] or 'any'}"
        f" topic={msg['topic']}{note}",
    )


def run_help_inbox(ctx: Any, host: Any, args: dict) -> ToolResult:
    inbox = _inbox(host)
    if inbox is None:
        return _fail("data 目录不可用，协助收件箱未装配", "help_inbox", "inbox_unavailable")
    need = str(args.get("need", "") or "")
    if need and need not in HELP_NEEDS:
        return _fail(f"need 仅允许 {HELP_NEEDS}: {need!r}", "help_inbox", "bad_param")
    to_session = str(args.get("to_session", "") or "")

    try:
        items = inbox.list_pending(need=need or None, to_session=to_session or None)
        counts = inbox.counts()
        corrupted = inbox.corrupted_count()
    except OSError as exc:
        return _fail(f"收件箱读取失败: {exc}", "help_inbox", "io_error")

    truncated = len(items) > _MAX_ITEMS
    payload = {
        "items": items[:_MAX_ITEMS],
        "counts": counts,
        "corrupted": corrupted,
    }
    if truncated:
        payload["truncated_items"] = True  # items 截断如实标注; counts/corrupted 恒全量
    summary = (
        f"[help 收件箱] pending={counts['pending']} blocking={counts['blocking']} "
        f"corrupted={corrupted}"
        + ("（items 已截断至 50 条，counts 为全量）" if truncated else "")
    )
    return _ok(payload, "help_inbox", summary)


def run_help_resolve(ctx: Any, host: Any, args: dict) -> ToolResult:
    inbox = _inbox(host)
    if inbox is None:
        return _fail("data 目录不可用，协助收件箱未装配", "help_resolve", "inbox_unavailable")
    msg_id = str(args.get("id", "") or "").strip()
    response = str(args.get("response", "") or "").strip()
    missing = [n for n, v in (("id", msg_id), ("response", response)) if not v]
    if missing:
        return _fail(f"缺少必填参数 {missing}", "help_resolve", "missing_param")
    decision = str(args.get("decision", "resolved") or "")
    if decision not in HELP_DECISIONS:
        return _fail(
            f"decision 仅允许 {HELP_DECISIONS}: {decision!r}", "help_resolve", "bad_param"
        )

    try:
        entry = inbox.resolve(
            msg_id, response, by_session=_session_id(host), decision=decision
        )
    except HelpInboxNotFoundError as exc:
        return _fail(str(exc), "help_resolve", "not_found")
    except HelpInboxCorruptionError as exc:
        return _fail(str(exc), "help_resolve", "store_corruption")
    except HelpInboxError as exc:
        return _fail(str(exc), "help_resolve", "bad_param")
    except OSError as exc:
        return _fail(f"收件箱写入失败: {exc}", "help_resolve", "io_error")

    return _ok(
        {"id": entry["id"], "state": entry["state"]},
        "help_resolve",
        f"[help 已应答] id={entry['id']} state={entry['state']} "
        f"by={entry.get('by_session') or '-'}",
    )
