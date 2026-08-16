"""路径 I：修复循环编排（design.md §2.1 / spec §5.5 + P0-D1 定案）.

封装"跑检查→失败→定位→子代理修复→重跑"为原子工作流，LLM 一次调用启动循环。

P0-D1 定案（DECISIONS.md D1）: FixLoopTool 内部经 SubAgentRunner 起子代理
完成修复（同步工具语义下主 LLM 无法等待修复），主 LLM 只发起与验收终态。

- 循环上限 max_rounds（缺省 5）；熔断 fuse_count（缺省 3，连续同指纹）
- 每轮迭代事件落盘（task.fix_loop.round）+ 终态落盘（task.fix_loop.terminated）
- 循环内工具调用经 ToolRegistry 包裹（CatastrophicGuard 安全检查不绕过）
- 程序不自动改代码：修复由子代理 LLM 经 edit_file 完成
- 编排异常 → ToolResult[ERROR] 不抛穿主循环
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.task_quality.models import FixLoopFinalStatus, FixLoopRecord, RoundRecord

logger = logging.getLogger(__name__)


class FixLoopTool:
    """修复循环工具（路径 I，P0-D1 子代理内修复）."""

    name = "fix_loop"
    description = (
        "修复循环编排：封装'跑检查→失败→定位→子代理修复→重跑'为原子工作流。"
        "何时用: 测试/检查失败需自动迭代修复（LLM 一次调用启动循环，子代理完成修复）。"
        "何时不用: 简单单次修复直接 edit_file；需要主 LLM 全程掌控时手动迭代。"
        "失败对策: 达上限/熔断如实回执未修复项；编排异常回执 error 不抛穿。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "check_command": {
                "type": "string",
                "description": "检查命令（如 'pytest tests/test_x.py -x' 或 'ruff check src/x.py'）",
            },
            "max_rounds": {"type": "integer", "description": "循环上限（默认 5）"},
            "fuse_count": {"type": "integer", "description": "熔断阈值（默认 3，连续修复同一错误）"},
            "fix_hint": {"type": "string", "description": "修复提示（给子代理的上下文指引）"},
        },
        "required": ["check_command"],
    }

    def __init__(
        self,
        *,
        registry: Any,
        subagent_runner: Any | None = None,
        error_locator: Any | None = None,
        default_max_rounds: int = 5,
        default_fuse_count: int = 3,
        event_store: Any | None = None,
        audit_dir: Path | None = None,
        session_id: str = "",
        enabled_fn: Any | None = None,  # D3: 动态开关回调（None=恒开；False=回执未启用）
    ) -> None:
        self._registry = registry
        self._subagent_runner = subagent_runner
        self._error_locator = error_locator
        self._default_max_rounds = default_max_rounds
        self._default_fuse_count = default_fuse_count
        self._event_store = event_store
        self._audit_dir = audit_dir
        self._session_id = session_id
        self._enabled_fn = enabled_fn

    def execute(self, **kwargs) -> ToolResult:
        """执行修复循环（同步；内部经子代理完成修复）."""
        # D3: 动态开关关闭 → 如实回执未启用（不静默放行）
        if self._enabled_fn is not None:
            try:
                if not self._enabled_fn():
                    return ToolResult(
                        status=ToolResultStatus.FAILURE,
                        content=(
                            "[状态: failure] fix_loop 未启用（task_quality 动态开关关闭）。"
                            "可经 adjust_strategy 设置 fix_loop_enabled=1 开启。"
                        ),
                        tool_call_id="", tool_name=self.name,
                    )
            except Exception:  # noqa: BLE001 — 开关读取异常按关闭处理（fail-safe）
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[状态: failure] fix_loop 开关读取异常，按关闭处理",
                    tool_call_id="", tool_name=self.name,
                )
        check_command = str(kwargs.get("check_command", "") or "").strip()
        if not check_command:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'check_command'",
                tool_call_id="", tool_name=self.name,
            )
        max_rounds = int(kwargs.get("max_rounds", self._default_max_rounds) or self._default_max_rounds)
        fuse_count = int(kwargs.get("fuse_count", self._default_fuse_count) or self._default_fuse_count)
        fix_hint = str(kwargs.get("fix_hint", "") or "")

        loop_id = f"fix_{uuid.uuid4().hex[:8]}"
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        fingerprint_count: dict[str, int] = {}
        rounds: list[RoundRecord] = []
        unfixed: list[str] = []

        try:
            for rn in range(1, max_rounds + 1):
                # 1. 跑检查（经 ToolRegistry 包裹，含安全检查）
                check_result = self._registry.execute(
                    ToolCall(id=f"{loop_id}_c{rn}", name="execute_command",
                             arguments={"command": check_command})
                )
                check_passed = check_result.status == ToolResultStatus.SUCCESS and "failed" not in check_result.content.lower()

                if check_passed:
                    record = RoundRecord(rn, check_result="passed", rerun_result="passed")
                    rounds.append(record)
                    self._append_event("task.fix_loop.terminated", {
                        "loop_id": loop_id, "trace_id": trace_id,
                        "final_status": FixLoopFinalStatus.PASSED.value,
                        "rounds": rn, "max_rounds": max_rounds,
                    })
                    self._persist_audit(loop_id, trace_id, rn, "passed", "")
                    return ToolResult(
                        status=ToolResultStatus.SUCCESS,
                        content=(
                            f"[状态: success] 修复循环通过（{loop_id}，trace={trace_id}，"
                            f"执行 {rn} 轮）\n检查命令: {check_command}\n"
                            f"{FixLoopRecord(loop_id, trace_id, max_rounds, tuple(rounds), FixLoopFinalStatus.PASSED).to_feedback_section()}"
                        ),
                        tool_call_id="", tool_name=self.name,
                    )

                # 2. 失败 → 定位（路径 H，可选）
                location_text = ""
                if self._error_locator is not None:
                    try:
                        loc = self._error_locator.locate(check_result.content, check_command)
                        if not loc.fallback:
                            location_text = loc.to_injection_text()
                    except Exception:  # noqa: BLE001 — 定位失败跳过（fail-open）
                        pass

                # 3. 错误指纹 + 熔断判断
                fingerprint = self._fingerprint(location_text or check_result.content)
                if fingerprint:
                    fingerprint_count[fingerprint] = fingerprint_count.get(fingerprint, 0) + 1
                    if fingerprint_count[fingerprint] >= fuse_count:
                        rounds.append(RoundRecord(rn, check_result="failed", location_info=fingerprint,
                                                  fix_action="", rerun_result="fuse"))
                        self._append_event("task.fix_loop.terminated", {
                            "loop_id": loop_id, "trace_id": trace_id,
                            "final_status": FixLoopFinalStatus.FUSE_TRIGGERED.value,
                            "rounds": rn, "fuse_count": fuse_count,
                        })
                        self._persist_audit(loop_id, trace_id, rn, "fuse", fingerprint)
                        return ToolResult(
                            status=ToolResultStatus.FAILURE,
                            content=(
                                f"[状态: failure] 熔断：连续 {fuse_count} 次修复同一错误未通过"
                                f"（{loop_id}，trace={trace_id}）\n未修复项: {fingerprint[:200]}\n"
                                f"{FixLoopRecord(loop_id, trace_id, max_rounds, tuple(rounds), FixLoopFinalStatus.FUSE_TRIGGERED, (fingerprint,), fuse_count).to_feedback_section()}"
                            ),
                            tool_call_id="", tool_name=self.name,
                        )

                # 4. 子代理修复（P0-D1：子代理 LLM 经 edit_file 自主修复）
                fix_result = self._subagent_fix(check_command, location_text, fix_hint, loop_id, rn)
                rounds.append(RoundRecord(
                    rn, check_result="failed", location_info=fingerprint,
                    fix_action=fix_result[:100], rerun_result="pending",
                ))
                self._append_event("task.fix_loop.round", {
                    "loop_id": loop_id, "trace_id": trace_id,
                    "round": rn, "fingerprint": fingerprint,
                    "fix_result": fix_result[:200],
                })
                unfixed.append(fingerprint or "unknown error")

            # 达上限
            self._append_event("task.fix_loop.terminated", {
                "loop_id": loop_id, "trace_id": trace_id,
                "final_status": FixLoopFinalStatus.LIMIT_REACHED.value,
                "rounds": max_rounds,
            })
            self._persist_audit(loop_id, trace_id, max_rounds, "limit", "; ".join(unfixed[:5]))
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    f"[状态: failure] 修复循环达上限未修复（{loop_id}，trace={trace_id}，"
                    f"{max_rounds} 轮）\n未修复项: {', '.join(u[:80] for u in unfixed[:5])}\n"
                    f"{FixLoopRecord(loop_id, trace_id, max_rounds, tuple(rounds), FixLoopFinalStatus.LIMIT_REACHED, tuple(unfixed)).to_feedback_section()}"
                ),
                tool_call_id="", tool_name=self.name,
            )
        except Exception as exc:  # noqa: BLE001 — 编排异常不抛穿主循环
            logger.exception("修复循环编排异常（回执 error）")
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[状态: error] 修复循环异常: {type(exc).__name__}: {exc}，已终止（已完成 {len(rounds)} 轮）",
                tool_call_id="", tool_name=self.name,
            )

    def _subagent_fix(self, check_command: str, location: str, hint: str, loop_id: str, rn: int) -> str:
        """经 SubAgentRunner 起子代理修复（P0-D1）.

        Returns:
            子代理最终回答摘要（失败返回错误描述，不抛穿）。
        """
        if self._subagent_runner is None:
            return "(无子代理执行器，跳过修复)"
        task = (
            f"修复代码使以下检查通过。检查命令: {check_command}\n"
            f"当前失败信息:\n{location[:1500]}\n"
            f"修复提示: {hint}\n"
            "要求: 用 edit_file 修改相关代码修复问题；修复后用 execute_command 跑检查验证；"
            "若无法修复请如实说明原因。"
        )
        try:
            result = self._subagent_runner.run(task, context=f"修复循环 {loop_id} 第 {rn} 轮", depth=1)
            if result is not None and getattr(result, "refused", False):
                return f"(子代理拒绝: {getattr(result, 'final_answer', '')[:100]})"
            return str(getattr(result, "final_answer", "") or "")[:200] or "(子代理无输出)"
        except Exception as exc:  # noqa: BLE001 — 子代理异常不阻断循环
            logger.warning("子代理修复异常（继续下一轮）: %s", exc)
            return f"(子代理异常: {type(exc).__name__})"

    @staticmethod
    def _fingerprint(text: str) -> str:
        """错误指纹（file+line+reason 哈希）."""
        if not text:
            return ""
        return hashlib.sha256(text[:500].encode()).hexdigest()[:16]

    def _append_event(self, etype: str, payload: dict) -> None:
        """事件落盘（fail-open）."""
        if self._event_store is None:
            return
        try:
            self._event_store.append(self._session_id, etype, payload)
        except Exception:  # noqa: BLE001
            logger.warning("修复循环事件落盘失败（fail-open）", exc_info=True)

    def _persist_audit(self, loop_id: str, trace_id: str, rounds: int, status: str, detail: str) -> None:
        """审计落盘 data/audit/task_quality.jsonl（fail-open）."""
        if self._audit_dir is None:
            return
        try:
            import json
            import time

            self._audit_dir.mkdir(parents=True, exist_ok=True)
            with (self._audit_dir / "task_quality.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": time.time(), "loop_id": loop_id, "trace_id": trace_id,
                    "rounds": rounds, "status": status, "detail": detail[:200],
                }, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("修复循环审计落盘失败（fail-open）: %s", exc)


# 协议别名（tasks.md §7.1）
FixLoopToolProtocol = FixLoopTool
