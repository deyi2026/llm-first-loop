"""ToolRegistry：注册/发现/执行（design.md §2.2.2.2 / §2.1.3.3 机制二）.

核心循环只依赖本类接口（FR-TOOL-03）；execute 统一执行包裹:
参数校验 → 灾难性安全校验 → 真实执行（带超时）→ 五态如实构造。
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

from llm_loop.core.message import Message, MessageSource, ToolCall, ToolResult, ToolResultStatus
from llm_loop.tools.safety import CatastrophicGuard

# execute 包裹的扩展钩子（由外部装配: 如架构自省 record_action）
PreExecuteHook = Callable[[ToolCall], None]


class ToolRegistry:
    """工具注册表：注册/发现/执行（统一执行包裹）."""

    def __init__(
        self,
        *,
        safety_guard: CatastrophicGuard | None = None,
        tool_timeout_s: float = 60.0,
        max_output_chars: int = 100000,
        archive_store: Any | None = None,
        failure_guidance_enabled: bool = True,
    ) -> None:
        self._tools: dict[str, Any] = {}
        self._lock = threading.Lock()
        self.safety = safety_guard or CatastrophicGuard()
        self.tool_timeout_s = tool_timeout_s
        self.max_output_chars = max_output_chars
        self.failure_guidance_enabled = failure_guidance_enabled
        self._pre_execute_hooks: list[PreExecuteHook] = []
        self._archive_store = archive_store  # ArchiveStore（T22 超长结果另存）
        self._session_id = ""

    def set_session_id(self, session_id: str) -> None:
        """由循环注入当前会话（压缩档案关联）."""
        self._session_id = session_id

    def _archive_oversize_output(self, call: ToolCall, full_content: str) -> None:
        """T22: 超长工具结果另存到压缩档案（信息零丢失，可检索找回）."""
        if self._archive_store is None or not self._session_id:
            return
        try:
            self._archive_store.archive(
                self._session_id,
                role="tool",
                source="tool",
                content=full_content,
                tool_name=call.name,
                tool_call_id=call.id,
                status="oversize",
            )
        except Exception:
            import logging

            logging.getLogger(__name__).warning("超长结果另存失败（fail-open）", exc_info=True)

    # ── 注册 / 发现 ──
    def register(self, tool: Any) -> None:
        """注册工具（启动时装配；重名覆盖并告警日志）."""
        with self._lock:
            if tool.name in self._tools:
                import logging

                logging.getLogger(__name__).warning("工具重名覆盖: %s", tool.name)
            self._tools[tool.name] = tool

    def get(self, name: str) -> Any:
        with self._lock:
            tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"工具不存在: {name}")
        return tool

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._tools)

    def schemas(self) -> list[dict]:
        """生成 LLM tools 参数（JSON Schema，约束 C4）."""
        with self._lock:
            defs = [
                {"name": t.name, "description": t.description, "parameters": t.parameters}
                for t in self._tools.values()
            ]
        return defs

    def add_pre_execute_hook(self, hook: PreExecuteHook) -> None:
        """注册执行前钩子（如架构自省动作轨迹采集，零侵入）."""
        self._pre_execute_hooks.append(hook)

    # ── 执行包裹 ──
    def execute(self, call: ToolCall) -> ToolResult:
        """统一执行包裹: 校验 → 安全 → 执行 → 五态如实构造.

        设计: design.md §2.1.3.3 机制二 —— 工具自身只写业务逻辑，
        参数/安全/超时/状态构造统一在此完成。
        """
        start = time.perf_counter()

        # 0. tool_call_id 有效性（约束 C1，由循环保证；此处兜底）
        if not call.id:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 工具调用缺少 tool_call_id，无法绑定执行。请重新声明（程序不会伪造执行）。",
                tool_call_id="",
                tool_name=call.name,
                duration_ms=0.0,
            )

        try:
            tool = self.get(call.name)
        except KeyError:
            return self._result(
                ToolResultStatus.FAILURE,
                call,
                f"[工具不存在] 未注册的工具 '{call.name}'。可用工具: {', '.join(self.names())}",
                duration_ms=0.0,
            )

        # 1. 参数最小防御（T38: 仅非 dict 报错；类型偏差交 AI 自主更正 + 工具容错执行）
        if not isinstance(call.arguments, dict):
            return self._result(
                ToolResultStatus.FAILURE,
                call,
                f"[参数错误] 参数必须为 JSON 对象，收到 {type(call.arguments).__name__}。正确用法示例: {json.dumps(tool.parameters, ensure_ascii=False)[:400]}",
                duration_ms=0.0,
            )

        # 2. 灾难性安全校验（FR-SAFE-01；仅可破坏工具）
        if self._is_destructive_tool(call.name):
            blocked = self.safety.guard(call.name, call.arguments)
            if blocked:
                return ToolResult(
                    status=ToolResultStatus.BLOCKED,
                    content=f"[安全硬阻断] 已阻止可能造成不可逆破坏的行动。{blocked.reason}",
                    tool_call_id=call.id,
                    tool_name=call.name,
                    error_detail=f"判定依据: {blocked.evidence}",
                    duration_ms=0.0,
                )

        # 3. 执行前钩子（架构自省动作轨迹）
        for hook in self._pre_execute_hooks:
            try:
                hook(call)
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "pre_execute hook 异常（fail-open）", exc_info=True
                )

        # 4. 真实执行（带超时控制）
        try:
            result = self._run_with_timeout(tool, call)
            duration_ms = (time.perf_counter() - start) * 1000
            result.duration_ms = duration_ms
            return result
        except Exception as exc:  # noqa: BLE001 — 如实构造异常结果
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[执行异常] {type(exc).__name__}: {exc}",
                tool_call_id=call.id,
                tool_name=call.name,
                error_type=type(exc).__name__,
                error_detail=traceback.format_exc(limit=5),
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    def _result(
        self, status: ToolResultStatus, call: ToolCall, content: str, *, duration_ms: float
    ) -> ToolResult:
        return ToolResult(
            status=status,
            content=content,
            tool_call_id=call.id,
            tool_name=call.name,
            duration_ms=duration_ms,
        )

    def _is_destructive_tool(self, name: str) -> bool:
        """是否具备破坏能力的工具（需过灾难性安全校验）."""
        return name in {"execute_command", "delete_file", "write_file", "edit_file", "append_file"}

    def _run_with_timeout(self, tool: Any, call: ToolCall) -> ToolResult:
        """真实执行 + 超时控制 + 输出截断标注."""
        # execute_command 可传 shell=True 场景由工具自身处理；
        # 此处统一超时控制（工具 execute 同步阻塞，用线程 + join 兜底）
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(tool.execute, **call.arguments)
            try:
                result = future.result(timeout=self.tool_timeout_s)
            except concurrent.futures.TimeoutError:
                pool.shutdown(wait=False, cancel_futures=True)
                return ToolResult(
                    status=ToolResultStatus.TIMEOUT,
                    content=f"[执行超时] 工具 '{call.name}' 超过 {self.tool_timeout_s:.0f}s 未完成",
                    tool_call_id=call.id,
                    tool_name=call.name,
                    partial_output=None,
                )
        if not isinstance(result, ToolResult):
            # 工具直接返回文本/原始值时包装为 success（如实）
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=str(result),
                tool_call_id=call.id,
                tool_name=call.name,
            )
        # 输出超长截断 + 如实标注（T22: 完整结果先另存，信息不丢失）
        if len(result.content) > self.max_output_chars:
            full = result.content
            # 另存完整结果到压缩档案（关联 tool_call_id，可检索找回）
            self._archive_oversize_output(call, full)
            result.content = (
                full[: self.max_output_chars]
                + f"\n…[结果超长，已截断，共 {len(full)} 字符]；完整结果已另存至压缩档案，可用 search_archive 检索找回…"
            )
        # 工具自身可能返回空 tool_call_id → 用声明 id 填充（约束 C1 绑定）
        if not result.tool_call_id:
            result.tool_call_id = call.id
        if not result.tool_name:
            result.tool_name = call.name
        return result


_FAILURE_GUIDANCE = {
    "failure": "建议: 检查参数/路径/网络后重试，或改用其他更合适的工具（规则 RULE-AI-02/07）。",
    "error": "建议: 工具执行异常，检查输入后重试，或换用等价工具完成任务。",
    "timeout": "建议: 工具执行超时，可重试（增大超时或换更轻量方案），或改用其他工具。",
}


def tool_result_to_message(result: ToolResult, *, failure_guidance_enabled: bool = True) -> Message:
    """ToolResult → tool 消息（如实承载状态，T21: content 前置状态标注）.

    M41: 失败回执追加引导段（错误类型 + 建议换用工具/重试，衔接 RULE-AI-02/07），
    BLOCKED 不加引导（灾难性拦截语义，不做任何诱导）。五态语义零改动。
    约束 C2: content 非空；AI 视角: AI 无需推断执行状态。
    """
    status_label = result.status.value if result.status else "unknown"
    content = (
        f"[状态: {status_label}] {result.content}"
        if result.content.strip()
        else f"[{result.tool_name} 执行{status_label}]（无输出）"
    )
    if failure_guidance_enabled and result.status and result.status.value in _FAILURE_GUIDANCE:
        content += "\n" + _FAILURE_GUIDANCE[result.status.value]
    return Message(
        role="tool",
        content=content,
        source=MessageSource.TOOL,
        tool_call_id=result.tool_call_id,
        status=result.status,
        tool_name=result.tool_name,
        error_detail=result.error_detail,
    )
