"""基础工具: subagent_report 子代理中途报告（DSH 借鉴 022-B，2026-08-17）.

子代理执行中主动回报进展/发现（可多次，报告≠结束）——父侧执行可见性提升：
- 报告经 contextvar sink 收集（runner 注入），随 SubAgentResult.reports 回传父级
- 同时写 interop inbox（from=subagent-report）——父会话后续轮注入可见（web/飞书）
- 仅子代理会话内可用（无 contextvar → 拒绝）；inbox 写失败 fail-open 不影响收集
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus

logger = logging.getLogger(__name__)

# 子代理上下文契约: (报告收集器 list, 子代理 sid)；runner.run 注入，无则非子代理上下文
_SUBAGENT_REPORT_CTX: contextvars.ContextVar[tuple[list[str], str] | None] = (
    contextvars.ContextVar("subagent_report_ctx", default=None)
)

# 单次子代理最多报告条数（防御: 防 sink 无限增长 + inbox 刷屏）
_MAX_REPORTS = 20


class SubagentReportTool:
    name = "subagent_report"
    description = (
        "子代理中途报告：向父代理回报当前进展/发现（可多次调用，报告≠结束，"
        "结束后仍需给出最终回答）。仅子代理会话内可用。"
        "何时用: 子代理任务执行中发现关键信息/阶段性结论/需要父侧知晓的异常时。"
        "何时不用: 最终结论（请放入最终回答）；非子代理上下文（会拒绝）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "报告内容（进展/发现/异常，简洁明确）",
            },
        },
        "required": ["content"],
    }

    def execute(self, **kwargs) -> ToolResult:
        content = str(kwargs.get("content", "") or "").strip()
        if not content:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'content'（报告内容）",
                tool_call_id="",
                tool_name=self.name,
            )
        ctx = _SUBAGENT_REPORT_CTX.get()
        if ctx is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[状态: failure] subagent_report 仅子代理会话内可用（当前不在子代理上下文）",
                tool_call_id="",
                tool_name=self.name,
            )
        sink, sid = ctx
        if len(sink) >= _MAX_REPORTS:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[状态: failure] 已达报告上限（{_MAX_REPORTS} 条），后续结论请并入最终回答",
                tool_call_id="",
                tool_name=self.name,
            )
        sink.append(content)
        # interop inbox 通知（父会话后续轮可见）——fail-open
        try:
            base = Path(os.environ.get("LFL_DATA_DIR", "data")) / "interop" / "lfl_to_dsh" / "pending"
            base.mkdir(parents=True, exist_ok=True)
            now = datetime.now(UTC)
            ts = now.strftime("%Y%m%d-%H%M%S")
            # 序号保证同秒多条不碰撞（sid 仅 12 位 hex，ts 秒级，同秒连续报告会同名覆盖）
            fname = f"{now.strftime('%Y%m%d')}-sub-{ts}-{sid[-6:]}-{len(sink)}.json"
            payload = {
                "id": f"{now.strftime('%Y%m%d')}-sub-{sid}",
                "from": "subagent-report",
                "to": "lfl",
                "ts": now.isoformat(),
                "topic": "notify",
                "ref": sid,
                "body": f"[子代理进展] {content}",
                "status": "pending",
            }
            (base / fname).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001 — fail-open
            logger.warning("subagent_report inbox 通知失败（fail-open）: %s", sid, exc_info=True)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[已记录进展 {len(sink)} 条] {content[:200]}",
            tool_call_id="",
            tool_name=self.name,
        )
