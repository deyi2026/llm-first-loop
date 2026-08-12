"""ToolRegistry：注册/发现/执行（design.md §2.2.2.2 / §2.1.3.3 机制二）.

核心循环只依赖本类接口（FR-TOOL-03）；execute 统一执行包裹:
参数校验 → 灾难性安全校验 → 真实执行（带超时）→ 五态如实构造。
"""

from __future__ import annotations

import json
import re
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
        summary_threshold: int = 5000,
        archive_store: Any | None = None,
        failure_guidance_enabled: bool = True,
        # EVO-d78b270c: 经验库（MemoryStore）注入——失败回执按错误关键词检索
        # procedure 经验条目，命中则注入【已验解法】段（None = 无经验库，零回归）
        memory_store: Any | None = None,
        # EVO-20260810-2549e9b6: EXEC_MODE 命令分级（默认空 = 不启用，生产由 factory 显式装配 blocked）
        exec_mode: str = "",
        exec_allowlist: str = "",
    ) -> None:
        self._tools: dict[str, Any] = {}
        self._lock = threading.Lock()
        self.safety = safety_guard or CatastrophicGuard()
        self.tool_timeout_s = tool_timeout_s
        self.max_output_chars = max_output_chars
        self.summary_threshold = summary_threshold
        self.failure_guidance_enabled = failure_guidance_enabled
        self._memory_store = memory_store  # EVO-d78b270c: 经验库（fail-open 零回归）
        self.exec_mode = exec_mode  # readonly/allowlist/blocked（空 = 不启用分级）
        self.exec_allowlist = [s.strip() for s in (exec_allowlist or "").split(",") if s.strip()]
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

    def schemas(self, lazy: bool = False) -> list[dict]:
        """生成 LLM tools 参数（JSON Schema，约束 C4）.

        EVO-d5db88d9: lazy=True 时返回精简索引（name + description 截断 + 参数骨架），
        模型需要某工具完整参数时调用 get_tool_schema 按需读取（工具规模扩展时上下文占用可控）。
        默认 lazy=False 全量注入（零回归，当前工具规模推荐）。
        """
        with self._lock:
            if lazy:
                defs = [
                    {
                        "name": t.name,
                        "description": (t.description or "")[:200],
                        "parameters": self._lazy_parameters(t),
                    }
                    for t in self._tools.values()
                ]
            else:
                defs = [
                    {"name": t.name, "description": t.description, "parameters": t.parameters}
                    for t in self._tools.values()
                ]
        return defs

    @staticmethod
    def _lazy_parameters(t) -> dict:
        """参数骨架（lazy 索引）：仅保留字段名与类型，体积最小."""
        params = getattr(t, "parameters", {}) or {}
        props = params.get("properties", {})
        return {
            "type": "object",
            "properties": {k: {"type": v.get("type", "string")} for k, v in props.items()},
            "required": list(params.get("required", [])),
        }

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

        # 2.5 EXEC_MODE 命令分级校验（EVO-20260810-2549e9b6；仅 execute_command）
        if call.name == "execute_command":
            blocked = self._check_exec_mode(call.arguments)
            if blocked:
                return ToolResult(
                    status=ToolResultStatus.BLOCKED,
                    content=f"[权限拦截] {blocked}",
                    tool_call_id=call.id,
                    tool_name=call.name,
                    error_detail="EXEC_MODE 限制，该命令需人工执行",
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

    # EVO-20260810-750e985a: 工具并发控制
    _READONLY_TOOLS = frozenset(
        {
            "read_file",
            "web_fetch",
            "architecture_status",
            "search_archive",
            "search_records",
        }
    )
    _READONLY_MAX_WORKERS = 4

    def execute_many(self, calls: list[ToolCall]) -> list[ToolResult]:
        """批量执行工具调用：只读并行 / 修改串行 / 结果按声明顺序回写.

        只读工具（read_file/web_fetch/架构检索类，无副作用）同一轮并行执行以降低延迟；
        修改类工具（写文件/执行命令/调整策略等，可能有副作用）强制串行，避免并发竞争；
        所有 toolResult 严格按传入声明顺序回写（保持模型对工具执行时序的理解，约束 C4）。
        """
        readonly = [c for c in calls if c.name in self._READONLY_TOOLS]
        mutating = [c for c in calls if c.name not in self._READONLY_TOOLS]
        by_id: dict[str, ToolResult] = {}

        if readonly:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(len(readonly), self._READONLY_MAX_WORKERS)
            ) as pool:
                futures = {pool.submit(self.execute, c): c for c in readonly}
                for fut in concurrent.futures.as_completed(futures):
                    call = futures[fut]
                    result = fut.result()
                    by_id[result.tool_call_id or call.id] = result

        for c in mutating:
            result = self.execute(c)
            by_id[result.tool_call_id or c.id] = result

        return [by_id[c.id] for c in calls]

    def _result(
        self, status: ToolResultStatus, call: ToolCall, content: str, *, duration_ms: float
    ) -> ToolResult:
        result = ToolResult(
            status=status,
            content=content,
            tool_call_id=call.id,
            tool_name=call.name,
            duration_ms=duration_ms,
        )
        # EVO-d78b270c: 失败/异常/超时 → 经验驱动注入（命中 procedure 已验解法）
        if status in (ToolResultStatus.FAILURE, ToolResultStatus.ERROR, ToolResultStatus.TIMEOUT):
            result.guidance_extra = self._inject_experience_guidance(result)
        return result

    def _inject_experience_guidance(self, result: ToolResult) -> str:
        """按错误关键词检索经验库，命中 procedure 条目则提取【已验解法】段.

        fail-open: 无经验库/检索异常/未命中 → 返回空串（零回归，默认模板照常）。
        """
        store = self._memory_store
        if store is None or not result.content:
            return ""
        # 错误关键词: tool_name + error_detail/content 分词（2-40 字符有效词）
        _sep_re = re.compile(r"[\\s,;:：，。；、/|()\"'\[\]]+")
        kws: list[str] = []
        if result.tool_name:
            kws.append(result.tool_name)
        detail = result.error_detail or result.content or ""
        for tok in re.split(_sep_re, detail):
            tok = tok.strip()
            if 2 <= len(tok) <= 40:
                kws.append(tok)
        if len(kws) < 2:
            return ""
        try:
            hits = store.search(kws, top_k=3)
        except Exception:  # noqa: BLE001 — 经验检索失败降级默认模板
            return ""
        for h in hits:
            content = str(getattr(h, "content", "") or "")
            if getattr(h, "type", "") == "procedure" and "已验解法" in content:
                solution = self._extract_solution_section(content)
                if solution:
                    return f"[经验参考] {solution}"
        return ""

    @staticmethod
    def _extract_solution_section(content: str) -> str:
        """提取 procedure 条目的【已验解法】段（到 实证/反例/触发标签 前的正文）."""
        marker = "已验解法"
        idx = content.find(marker)
        if idx < 0:
            return ""
        start = idx + len(marker)
        # 跳过冒号与空白
        while start < len(content) and content[start] in ":： \n\t":
            start += 1
        end = len(content)
        for stop in ("\n实证", "\n反例", "\n触发标签"):
            pos = content.find(stop, start)
            if pos != -1:
                end = min(end, pos)
        return content[start:end].strip()

    @staticmethod
    def _summarize_output(full: str, head_chars: int = 600, tail_chars: int = 600) -> str:
        """输出分层摘要: 首部 + 尾部 + 规模 + 检索指引（命令输出关键信息常在尾部）.

        原文已由调用方完整另存至压缩档案（信息零丢失），此处仅注入摘要。
        内容未超首尾窗口时完整展示但仍带"输出摘要"标注（AI 可感知已分层）。
        """
        n = len(full)
        if n <= head_chars + tail_chars:
            return (
                f"[输出摘要] 共 {n} 字符，内容未超首尾窗口故完整展示"
                f"（原文已另存至压缩档案，可用 search_archive 检索找回）：\n{full}"
            )
        head = full[:head_chars]
        tail = full[-tail_chars:]
        return (
            f"[输出摘要] 共 {n} 字符，以下为首部/尾部关键内容"
            f"（完整内容已另存至压缩档案，可用 search_archive 检索找回）：\n"
            f"── 首部 ──\n{head}\n── 尾部 ──\n{tail}"
        )

    def _is_destructive_tool(self, name: str) -> bool:
        """是否具备破坏能力的工具（需过灾难性安全校验）."""
        return name in {"execute_command", "delete_file", "write_file", "edit_file", "append_file"}

    def _check_exec_mode(self, args: dict) -> str:
        """EXEC_MODE 校验: blocked 全禁 / readonly 只读 / allowlist 前缀白名单（空 = 不启用）."""
        command = str(args.get("command", "") or "").strip()
        if not command:
            return "缺少命令"
        if not self.exec_mode:
            return ""  # 未启用分级（默认兼容）
        if self.exec_mode == "blocked":
            return "当前 EXEC_MODE=blocked，AI 不可执行 shell 命令（需人工执行）"
        if self.exec_mode == "readonly":
            from llm_loop.tools.safety import is_readonly_command

            if not is_readonly_command(command):
                return "当前 EXEC_MODE=readonly，仅放行只读命令（该命令涉及写/变更，需人工执行）"
            return ""
        if self.exec_mode == "allowlist":
            for prefix in self.exec_allowlist:
                if command.startswith(prefix):
                    return ""
            return "命令不在白名单（EXEC_ALLOWLIST），需人工执行"
        return "未知 EXEC_MODE"

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
            # 工具直接返回文本/原始值时包装为 success（如实），继续走统一输出分层
            result = ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=str(result),
                tool_call_id=call.id,
                tool_name=call.name,
            )
        # 输出分层注入（EVO-20260811-22a7d3e1）:
        # - 超过 summary_threshold: 默认注入首/尾摘要（全文另存可检索，信息零丢失）
        # - 超过 max_output_chars（硬上限）: 全文另存 + 截断（T22 既有逻辑）
        if len(result.content) > self.summary_threshold:
            full = result.content
            self._archive_oversize_output(call, full)  # 原文完整另存（信息零丢失）
            result.content = self._summarize_output(full)
            # 硬上限安全阀: 摘要后仍超限才截断（原文已存档，无需重复存档）
            if len(result.content) > self.max_output_chars:
                result.content = (
                    result.content[: self.max_output_chars]
                    + f"\n…[结果超长，已截断，共 {len(result.content)} 字符]；完整内容已另存至压缩档案，可用 search_archive 检索找回…"
                )
        elif len(result.content) > self.max_output_chars:
            # 未超摘要阈值但超硬上限（阈值配置异常）→ 存档 + 截断（T22 既有行为）
            full = result.content
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


def tool_result_to_message(
    result: ToolResult,
    *,
    failure_guidance_enabled: bool = True,
    # 阶段4-A: 经验注入独立开关（None=跟随主开关；子代理用 True 可仅注入经验不注入默认模板）
    experience_guidance_enabled: bool | None = None,
) -> Message:
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
    # EVO-d78b270c: 经验驱动注入（独立于默认模板；开启引导时带出，未命中为空串零回归）
    # 阶段4-A: experience_guidance_enabled 独立开关（None 跟随主开关；子代理可仅开经验）
    exp_enabled = (
        failure_guidance_enabled
        if experience_guidance_enabled is None
        else experience_guidance_enabled
    )
    if exp_enabled and result.guidance_extra:
        content += "\n" + result.guidance_extra
    return Message(
        role="tool",
        content=content,
        source=MessageSource.TOOL,
        tool_call_id=result.tool_call_id,
        status=result.status,
        tool_name=result.tool_name,
        error_detail=result.error_detail,
    )


class GetToolSchemaTool:
    """按需读取工具完整 Schema（EVO-d5db88d9 懒加载配套工具）.

    lazy 模式（TOOL_SCHEMA_LAZY=1）下 LLM 只见精简索引，需要调用某工具时
    先调用本工具获取完整 JSON Schema（参数格式/必填/说明），再发起真实调用。
    """

    name = "get_tool_schema"
    description = (
        "获取指定工具的完整 JSON Schema 定义（参数格式/必填项/使用说明）。"
        "何时用: 需要调用某工具但不确定其参数格式时，先读取完整 Schema 再调用。"
        "何时不用: 已确知工具参数格式时不必调用（直接发起工具调用）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "tool_name": {"type": "string", "description": "要查询的工具名（如 read_file）"},
        },
        "required": ["tool_name"],
    }

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def execute(self, **kwargs) -> Any:
        from llm_loop.core.message import ToolResult, ToolResultStatus

        name = str(kwargs.get("tool_name", "")).strip()
        if not name:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'tool_name'（要查询的工具名）",
                tool_call_id="",
                tool_name=self.name,
            )
        try:
            tool = self._registry.get(name)
        except KeyError:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[工具不存在] 未找到工具 '{name}'。可用工具: {', '.join(self._registry.names())}",
                tool_call_id="",
                tool_name=self.name,
            )
        import json

        schema = json.dumps(
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
            ensure_ascii=False,
            indent=2,
        )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"工具 '{name}' 完整 Schema:\n{schema}",
            tool_call_id="",
            tool_name=self.name,
        )
