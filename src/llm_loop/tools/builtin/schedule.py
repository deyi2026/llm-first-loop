"""基础工具: 定时提醒（DSH-PLUGINS-20260816 ②）——at/after/rate 注册提醒.

何时用: 需要定时提醒（如 N 秒后检查结果、周期汇报、绝对时间点提醒）；
提醒经 interop notify 注入会话（LFL 下轮 run 回显，web/飞书可见）。
何时不用: 即时通知直接说；跨系统协作消息走 interop 协调通道（topic=coordinate）。
失败对策: 参数非法如实返回；存储 fail-open。
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.scheduler import ScheduleStore


class ScheduleTool:
    name = "schedule"
    description = (
        "注册定时提醒：after（N 秒后一次）/ at（绝对时间）/ rate（每 N 秒重复，可限次数）。"
        "到点提醒经协调通道注入会话（下轮 run 回显，web/飞书可见）。"
        "何时用: 需要延迟/周期性提醒（如 60 秒后检查后台任务、每 5 分钟汇报状态）。"
        "何时不用: 即时动作直接执行；一次性协调消息走 interop。"
        "失败对策: 参数校验失败如实返回；存储异常 fail-open。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "提醒内容（必填，将注入会话可见）",
            },
            "after": {
                "type": "number",
                "description": "N 秒后触发一次（默认 0=立即？不——必须 >0 或给 at）",
            },
            "at": {
                "type": "string",
                "description": "绝对触发时间 ISO（如 '2026-08-17T10:00:00'，本地时区）；与 after 二选一",
            },
            "repeat_interval": {
                "type": "number",
                "description": "重复间隔秒（>0 表示周期提醒）",
            },
            "max_count": {
                "type": "integer",
                "description": "最多触发次数（重复时有效，默认 1）",
            },
        },
        "required": ["message"],
    }

    def __init__(self, store: ScheduleStore | None = None) -> None:
        self._store = store

    def _get_store(self) -> ScheduleStore:
        if self._store is None:
            self._store = ScheduleStore()
        return self._store

    def execute(self, **kwargs) -> ToolResult:
        message = str(kwargs.get("message", "") or "").strip()
        after = float(kwargs.get("after", 0) or 0)
        at = str(kwargs.get("at", "") or "").strip()
        repeat_interval = float(kwargs.get("repeat_interval", 0) or 0)
        max_count = int(kwargs.get("max_count", 1) or 1)

        if not message:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'message'",
                tool_call_id="",
                tool_name=self.name,
            )
        if after < 0 or repeat_interval < 0:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] after/repeat_interval 必须 ≥ 0",
                tool_call_id="",
                tool_name=self.name,
            )

        # 绝对时间解析（ISO，本地时区；带 Z 视为 UTC）
        at_ts: float | None = None
        if at:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(at)
                if dt.tzinfo is None:
                    dt = dt.astimezone()  # 无时区按本地
                at_ts = dt.timestamp()
            except ValueError:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[参数错误] at 时间格式非法（期望 ISO 如 '2026-08-17T10:00:00'）: {at}",
                    tool_call_id="",
                    tool_name=self.name,
                )

        sid = self._get_store().add(
            message, after=after, at=at_ts, repeat_interval=repeat_interval, max_count=max_count
        )
        when = f"after {after}s" if after > 0 else (f"at {at}" if at else "immediate")
        if repeat_interval > 0:
            when += f"（每 {repeat_interval}s，最多 {max_count} 次）"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[schedule] 已注册提醒 {sid}: '{message}'（{when}）。到点经协调通道注入会话。",
            tool_call_id="",
            tool_name=self.name,
        )
