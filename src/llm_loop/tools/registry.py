"""ToolRegistry：注册/发现/执行（design.md §2.2.2.2 / §2.1.3.3 机制二）.

核心循环只依赖本类接口（FR-TOOL-03）；execute 统一执行包裹:
参数校验 → 灾难性安全校验 → 真实执行（带超时）→ 五态如实构造。
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
import traceback
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import Any

from llm_loop.core.message import Message, MessageSource, ToolCall, ToolResult, ToolResultStatus
from llm_loop.tools.pipeline import ImmutableResult, MaterializationError
from llm_loop.tools.safety import CatastrophicGuard

logger = logging.getLogger(__name__)

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
        summary_threshold: int = 12000,  # 2026-08-15 放大字数（5000→12000）
        archive_store: Any | None = None,
        failure_guidance_enabled: bool = True,
        # EVO-d78b270c: 经验库（MemoryStore）注入——失败回执按错误关键词检索
        # procedure 经验条目，命中则注入【已验解法】段（None = 无经验库，零回归）
        memory_store: Any | None = None,
        # EVO-20260810-2549e9b6: EXEC_MODE 命令分级（默认空 = 不启用，生产由 factory 显式装配 blocked）
        exec_mode: str = "",
        exec_allowlist: str = "",
        # T5a(2026-08-14): 人工审批回调（None = 拦截即拒绝 fail-closed，零回归）
        # 回调签名: (tool_name, args_summary) -> bool（True=人工批准放行 / False=拒绝）
        # 仅 EXEC_MODE 拦截路径触发；灾难性安全硬阻断不可审批（C 类硬边界不移交）。
        approval_callback: Callable[[str, str], bool] | None = None,
        # T5a: 审批审计落盘路径（None = 不落盘；含时间/工具/参数摘要/决策，不含密钥）
        approval_audit_path: str | Path | None = None,
        # P0-1(2026-08-15): 阻断审计目录（默认守卫落盘 safety_blocks.jsonl；
        # 仅 safety_guard 未显式注入时生效；None = 不落盘，零回归）
        safety_audit_dir: str | Path | None = None,
        # task_quality 路径 A（2026-08-17）: 参数预检层（None = 关闭，零回归；
        # 注入后 execute 步骤 1 后、安全检查前执行预检，失败返回字段级引导反馈）
        precheck_layer: Any | None = None,
    ) -> None:
        self._tools: dict[str, Any] = {}
        self._lock = threading.Lock()
        self.safety = safety_guard or CatastrophicGuard(audit_dir=safety_audit_dir)
        self.tool_timeout_s = tool_timeout_s
        self.max_output_chars = max_output_chars
        self.summary_threshold = summary_threshold
        self.failure_guidance_enabled = failure_guidance_enabled
        self._memory_store = memory_store  # EVO-d78b270c: 经验库（fail-open 零回归）
        self.exec_mode = exec_mode  # readonly/allowlist/blocked（空 = 不启用分级）
        self.exec_allowlist = [s.strip() for s in (exec_allowlist or "").split(",") if s.strip()]
        self._pre_execute_hooks: list[PreExecuteHook] = []
        self.precheck_layer = precheck_layer  # task_quality 路径 A（None=关闭零回归）
        self._archive_store = archive_store  # ArchiveStore（T22 超长结果另存）
        # P0-5(2026-08-15): 显式注入的会话 id（set_session_id 写入，无 contextvar
        # 上下文时的回退值）。并发 run 期间，属性 `_session_id`（下方 property）
        # 优先读 contextvar——execute_many 只读池线程经 copy_context 传播获得
        # 本会话值，跨会话并发不再串台（审计发现 #7 修复）。
        self._session_id_explicit = ""
        # EVO-20260813-9ced1f4c: 工具执行瀑布（默认 None = 零回归；set_pipeline 显式装配）
        self._pipeline: Any = None
        # T5a: 人工审批通道（None = 拦截即拒；set_approval_callback 运行时注入）
        self._approval_callback = approval_callback
        self._approval_audit_path = Path(approval_audit_path) if approval_audit_path else None

    def set_approval_callback(self, callback: Callable[[str, str], bool] | None) -> None:
        """运行时注入/移除人工审批回调（CLI 交互模式装配；web/feishu 不注入 → fail-closed）."""
        self._approval_callback = callback

    def _approval_log(self, decision: str, tool_name: str, summary: str) -> None:
        """审批审计落盘（fail-open：审计失败不阻断执行；不写密钥/完整参数）."""
        if self._approval_audit_path is None:
            return
        try:
            self._approval_audit_path.parent.mkdir(parents=True, exist_ok=True)
            rec = {
                "ts": time.time(),
                "decision": decision,  # approved / rejected / no_callback
                "tool": tool_name,
                "args_summary": summary[:300],
            }
            with self._approval_audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("审批审计写失败（fail-open）: %s", self._approval_audit_path)

    @property
    def _session_id(self) -> str:
        """当前会话 id（P0-5: contextvar 优先，显式注入回退）."""
        try:
            from llm_loop.core.run_context import current_session_id

            sid = current_session_id.get()
            if sid:
                return sid
        except Exception:  # noqa: BLE001 — 上下文不可用时回退显式值（零回归）
            pass
        return self._session_id_explicit

    @_session_id.setter
    def _session_id(self, value: str) -> None:
        self._session_id_explicit = value

    def set_session_id(self, session_id: str) -> None:
        """由循环注入当前会话（压缩档案关联；无 contextvar 上下文时的回退值）."""
        self._session_id_explicit = session_id

    def set_pipeline(self, pipeline: Any) -> None:
        """装配工具执行瀑布（EVO-20260813-9ced1f4c）.

        pipeline 为 None 或 config.enabled=False 时主链路行为完全不变（零回归）。
        """
        self._pipeline = pipeline

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
        """注册工具（启动时装配）.

        R1(2026-08-14): 同对象重复注册（装配路径基础工具与修正工具集重名）→ 静默去重；
        不同实现的重名覆盖仍告警（防未来静默覆盖）。
        """
        with self._lock:
            existing = self._tools.get(tool.name)
            if existing is tool:
                return  # 同对象重复注册：静默（零回归）
            if existing is not None:
                import logging

                logging.getLogger(__name__).warning("工具重名覆盖: %s", tool.name)
            self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """卸载工具（EVO-20260814-488e7ef7: 注册即回滚，Cordis reversible effects）.

        返回是否真的移除（不存在返回 False，不抛异常）。卸载后：
        - execute(name) → 工具不存在 → 如实构造 failure（fail-closed，安全）
        - 可重新 register 同名工具（热更新/演进回滚通道）
        guard 规则（MonotonicGuard）为独立对象，不随工具卸载清理；但工具已不存在时
        guard.check 不再可达（execute 先查工具存在性），无残留风险。
        """
        with self._lock:
            existed = name in self._tools
            if existed:
                del self._tools[name]
            return existed

    def dispose(self) -> int:
        """批量卸载全部工具（EVO-20260814-488e7ef7，Cordis disposer 语义）.

        供测试隔离 / teardown（避免测试注册污染后续用例）。返回卸载数量。
        幂等：已空时返回 0。
        """
        with self._lock:
            n = len(self._tools)
            self._tools.clear()
            return n

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

        # 1.5 task_quality 路径 A（2026-08-17）: 参数预检（安全检查前，失败拦截不执行）
        # 缺省 None 零回归；schema 缺失/异常 fail-open 放行。
        precheck = getattr(self, "precheck_layer", None)
        if precheck is not None:
            try:
                pre_result = precheck.check(call.arguments, tool.parameters)
                if not pre_result.valid:
                    return self._result(
                        ToolResultStatus.FAILURE,
                        call,
                        pre_result.to_guidance_feedback(),
                        duration_ms=(time.perf_counter() - start) * 1000,
                    )
            except Exception:  # noqa: BLE001 — 预检异常 fail-open（不阻断主循环）
                import logging

                logging.getLogger(__name__).warning(
                    "参数预检执行异常（fail-open 放行）: %s", call.name, exc_info=True
                )

        # EVO-20260813-9ced1f4c: 参数物化边界（瀑布，默认关闭零回归）
        # 无损 JSON 物化 + 深冻结，防策略检查后被篡改；失败 → 拒绝调用（宁严勿松）
        pipeline = self._pipeline
        if pipeline is not None and pipeline.config.enabled and pipeline.config.materialize:
            from llm_loop.tools.pipeline import materialize_lossless_json

            try:
                materialized = materialize_lossless_json(call.arguments)
            except MaterializationError as exc:
                return self._result(
                    ToolResultStatus.FAILURE,
                    call,
                    f"[参数拒绝] 参数无法无损物化（{exc}），已拒绝调用（物化边界，宁严勿松）",
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
            # 物化副本替换原参数（roundtrip 独立副本防引用篡改；普通 dict 供执行）
            call = ToolCall(id=call.id, name=call.name, arguments=materialized)

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

        # 2.5 EXEC_MODE 命令分级校验（EVO-20260810-2549e9b6 + 20260814 fail-closed 覆盖所有破坏性工具）
        if self._is_destructive_tool(call.name):
            blocked = self._check_exec_mode(call.name, call.arguments)
            if blocked:
                # T5a: 人工审批通道——有回调且人工批准 → 放行继续执行；
                # 无回调 / 拒绝 / 回调异常 → 拦截（fail-closed，灾难性安全硬阻断不可审批）
                if self._approval_callback is not None:
                    summary = json.dumps(call.arguments, ensure_ascii=False)
                    try:
                        approved = bool(self._approval_callback(call.name, summary))
                    except Exception:  # noqa: BLE001 — 回调异常 fail-closed 拒绝
                        approved = False
                    self._approval_log("approved" if approved else "rejected", call.name, summary)
                    if approved:
                        logger.info("人工审批通过: %s", call.name)
                    else:
                        return ToolResult(
                            status=ToolResultStatus.BLOCKED,
                            content=f"[权限拦截] {blocked}（人工审批未通过）",
                            tool_call_id=call.id,
                            tool_name=call.name,
                            error_detail="EXEC_MODE 限制，人工审批拒绝该操作",
                            duration_ms=0.0,
                        )
                else:
                    self._approval_log("no_callback", call.name, json.dumps(call.arguments, ensure_ascii=False))
                    return ToolResult(
                        status=ToolResultStatus.BLOCKED,
                        content=f"[权限拦截] {blocked}",
                        tool_call_id=call.id,
                        tool_name=call.name,
                        error_detail="EXEC_MODE 限制，该操作需人工执行",
                        duration_ms=0.0,
                    )

        # EVO-20260813-9ced1f4c: 单调守卫（瀑布，默认关闭零回归）
        # 守卫拒绝 → BLOCKED（与灾难性安全同语义）；守卫只收紧不放松（fail-closed）
        if pipeline is not None and pipeline.config.enabled and pipeline.config.guard and pipeline._guard is not None:
            reason = pipeline._guard.check(call.name)
            if reason is not None:
                return self._result(
                    ToolResultStatus.BLOCKED,
                    call,
                    f"[单调守卫] 工具 '{call.name}' 被拒绝: {reason}",
                    duration_ms=(time.perf_counter() - start) * 1000,
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
            # EVO-20260813-9ced1f4c: post 快照（不可变 result + post 钩子，默认关闭零回归）
            if pipeline is not None and pipeline.config.enabled and pipeline._post_hooks:
                snapshot = ImmutableResult(
                    tool_name=call.name,
                    status=getattr(result, "status", "unknown"),
                    content=getattr(result, "content", ""),
                    duration_ms=duration_ms,
                    meta={"pipeline": True, "guard_checked": pipeline.config.guard},
                )
                # EVO-20260814-39a10097: post hook waterfall（block/replace）
                snapshot = pipeline.run_post_hooks(snapshot)
                if snapshot.status == ToolResultStatus.BLOCKED.value:
                    return ToolResult(
                        status=ToolResultStatus.BLOCKED,
                        content=snapshot.content,
                        tool_call_id=call.id,
                        tool_name=call.name,
                        duration_ms=duration_ms,
                    )
                if snapshot.content != getattr(result, "content", ""):
                    result.content = snapshot.content  # replace 回写
                    with contextlib.suppress(ValueError):
                        result.status = ToolResultStatus(snapshot.status)  # 未知 status 保持原样
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
            import contextvars

            # P0-5: 逐任务复制当前上下文（含 current_session_id）到池线程——
            # 只读工具（search_archive/architecture_status 等）在池线程内仍能
            # 定位本会话，跨会话并发不串台（审计发现 #7 修复）。
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(len(readonly), self._READONLY_MAX_WORKERS)
            ) as pool:
                futures = {
                    pool.submit(contextvars.copy_context().run, self.execute, c): c
                    for c in readonly
                }
                for fut in concurrent.futures.as_completed(futures):
                    call = futures[fut]
                    result = fut.result()
                    by_id[result.tool_call_id or call.id] = result

        for c in mutating:
            result = self.execute(c)
            by_id[result.tool_call_id or c.id] = result

        # 防御性取值（防程序错误向 AI 传导）: 执行路径若未能把结果写入 by_id
        # （键错位/结果丢失），不得抛 KeyError 中断整轮，而应构造 [程序异常]
        # 占位结果如实回执，交由 AI 自主决策重试/换路径。
        return [
            by_id.get(c.id)
            or ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    f"[程序异常] 工具执行结果丢失（execute_many 索引未命中 "
                    f"tool_call_id={c.id}，工具 '{c.name}'）"
                ),
                tool_call_id=c.id,
                tool_name=c.name,
            )
            for c in calls
        ]

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
        from datetime import datetime

        for h in hits:
            content = str(getattr(h, "content", "") or "")
            if getattr(h, "type", "") == "procedure" and "已验解法" in content:
                solution = self._extract_solution_section(content)
                if solution:
                    # SkillZip ReZip 借鉴（执行感知反馈环）:
                    # 1) 记录本次注入使用时间（执行感知，供后续失效判定）
                    try:
                        h.guidance_used_at = datetime.now(UTC).isoformat()
                        # 2) 若该经验已累计风险（注入后同场景仍失败）→ 附带风险提示，让 AI 谨慎参考
                        risk = int(getattr(h, "guidance_risk", 0) or 0)
                        if risk >= 2:
                            return (
                                f"[经验参考] {solution}\n"
                                f"[经验风险] 该经验已被注入 {risk} 次但同场景仍失败，"
                                f"建议谨慎参考或换用其他方法（执行感知反馈环标记）"
                            )
                        return f"[经验参考] {solution}"
                    except Exception:  # noqa: BLE001 — 记录失败不影响注入
                        return f"[经验参考] {solution}"
        # 2026-08-18 失败→经验沉淀闭环（B）: 失败且经验库无命中 → 提示 AI 主动沉淀
        # （对齐 RULE-AI-05 记忆沉淀；仅提示不强制，决策归 AI。零回归：仅失败路径追加提示）
        try:
            if store is not None and not hits:
                return (
                    "[经验沉淀提示] 本次工具失败无经验库命中。若你定位了根因/解法，"
                    "可用 save_experience 沉淀（跨会话复用，避免同类失败重复踩坑）。"
                )
        except Exception:  # noqa: BLE001 — 提示失败零影响
            pass
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
    def _archive_query_hint(call) -> str:
        """EVO-20260814-e5b045d3: 从工具调用参数提取 archive 检索建议.

        与 ArchiveStore.search 契约对齐: query 子串匹配（content/summary/key_facts/key_paths），
        tool_name 精确过滤。路径取 basename、命令取前缀，给出可直接照抄的调用示例。
        """
        name = getattr(call, "name", "") or ""
        args = getattr(call, "arguments", None) or {}
        path = str(args.get("path", "") or "").strip()
        cmd = str(args.get("command", "") or "").strip()
        if path:
            q = path.rsplit("/", 1)[-1] or path
        elif cmd:
            q = cmd[:40]
        else:
            q = ""
        if q:
            return f'search_archive(query="{q}", tool_name="{name}")'
        return f'search_archive(tool_name="{name}")'

    # 2026-08-15 截断信号强化（用户需求）：行动指引统一文案——摘要/截断回执均附。
    # 程序只发信号不替 AI 摘要（RULE-AI-00）：提炼与纳入最终总结由 AI 完成。
    _DISTILL_GUIDANCE = (
        "行动指引：中部/被省略内容不在当前上下文——继续推理前，请先把可见要点与"
        "待核实缺口提炼记录（写入你的推理链或 [[memory]] 记忆块），最终总结时请纳入"
        "这些要点与缺口说明。"
    )

    @staticmethod
    def _summarize_output(full: str, head_chars: int = 2500, tail_chars: int = 2500, call=None) -> str:
        """输出分层摘要: 首部 + 尾部 + 规模 + 检索指引（命令输出关键信息常在尾部）.

        原文已由调用方完整另存至压缩档案（信息零丢失），此处仅注入摘要。
        内容未超首尾窗口时完整展示但仍带"输出摘要"标注（AI 可感知已分层）。
        EVO-20260814-e5b045d3: 指引升级为可直接照抄的 search_archive 调用示例
        （query 取路径 basename/命令前缀 + tool_name 过滤），避免 AI 换命令重读原文空耗轮数。
        2026-08-15 放大字数：首尾窗口 600/600 → 2500/2500；附提炼要点行动指引。
        """
        hint = (
            f"查看完整原文请直接调用 {ToolRegistry._archive_query_hint(call)}"
            "（一次取回，勿换命令重复执行同一工具）"
            if call is not None
            else "可用 search_archive 检索找回"
        )
        n = len(full)
        if n <= head_chars + tail_chars:
            return (
                f"[输出摘要] 共 {n} 字符，内容未超首尾窗口故完整展示"
                f"（原文已另存至压缩档案，{hint}）：\n{full}"
            )
        head = full[:head_chars]
        tail = full[-tail_chars:]
        return (
            f"[输出摘要] 共 {n} 字符，以下为首部/尾部关键内容"
            f"（完整内容已另存至压缩档案，{hint}）：\n"
            f"── 首部 ──\n{head}\n── 尾部 ──\n{tail}\n{ToolRegistry._DISTILL_GUIDANCE}"
        )

    def _is_destructive_tool(self, name: str) -> bool:
        """是否具备破坏能力的工具（需过灾难性安全校验）."""
        return name in {"execute_command", "delete_file", "write_file", "edit_file", "append_file"}

    def _check_exec_mode(self, name: str, args: dict) -> str:
        """EXEC_MODE 校验（EVO-20260814 fail-closed 增强）.

        blocked 全禁 / readonly 只读 / allowlist 白名单 / 空 = 不启用。
        fail-closed 语义: 显式启用分级时，未匹配任何放行规则 → 拒绝（不静默放行）。
        覆盖所有破坏性工具（execute_command + write_file/edit_file/delete_file/append_file），
        不限于 execute_command（修 readonly/blocked 下写文件工具绕过分级的 fail-open 缺口）。

        Returns:
            空串 = 放行；非空串 = 拦截原因。
        """
        if not self.exec_mode:
            return ""  # 未启用分级（默认兼容，零回归）

        if self.exec_mode == "blocked":
            return "当前 EXEC_MODE=blocked，AI 不可执行变更类操作（shell/写文件，需人工执行）"

        if name == "execute_command":
            command = str(args.get("command", "") or "").strip()
            if not command:
                return "缺少命令"
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
        else:
            # 写文件类工具（edit_file/write_file/delete_file/append_file）
            if self.exec_mode == "readonly":
                return f"当前 EXEC_MODE=readonly，禁止写文件类操作（{name}），需人工执行"
            if self.exec_mode == "allowlist":
                if name in self.exec_allowlist:
                    return ""
                return f"工具 {name} 不在白名单（EXEC_ALLOWLIST），需人工执行"
        return "未知 EXEC_MODE"

    def _run_with_timeout(self, tool: Any, call: ToolCall) -> ToolResult:
        """真实执行 + 超时控制 + 输出截断标注."""
        # execute_command 可传 shell=True 场景由工具自身处理；
        # 此处统一超时控制（工具 execute 同步阻塞，用线程 + join 兜底）
        import concurrent.futures
        import contextvars

        # P0-5: 超时包裹的内层线程同样传播上下文（current_session_id 等）——
        # 工具 execute 本体在内层线程执行，缺传播则 contextvar 读到空串
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(contextvars.copy_context().run, tool.execute, **call.arguments)
        try:
            result = future.result(timeout=self.tool_timeout_s)
        except concurrent.futures.TimeoutError:
            # P1-5(审计发现 #11): 超时即放弃等待，让"超时"按时返回——
            # ① future.cancel()（运行中任务取消无效，尽力而为）;
            # ② 调用工具暴露的 terminate() 钩子（execute_command 整树杀子进程，
            #    其余工具无钩子则跳过）;
            # ③ shutdown(wait=False) 立即返回——原 with 块退出会 shutdown(wait=True)
            #    卡到工具自行结束，超时名存实亡（耗时 = 工具时长）。
            # 残余如实标注: 工作线程非 daemon 无法强杀，无钩子工具残余线程最多存活
            # 到工具自身超时/自然结束（期间解释器退出会被其阻塞等待）。
            future.cancel()
            terminate = getattr(tool, "terminate", None)
            if callable(terminate):
                with contextlib.suppress(Exception):
                    terminate()
            pool.shutdown(wait=False, cancel_futures=True)
            return ToolResult(
                status=ToolResultStatus.TIMEOUT,
                content=f"[执行超时] 工具 '{call.name}' 超过 {self.tool_timeout_s:.0f}s 未完成",
                tool_call_id=call.id,
                tool_name=call.name,
                partial_output=None,
            )
        except BaseException:
            # 工具异常路径：线程已结束，防御性 wait=False 防意外挂起
            future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        # 正常完成：线程已结束，等待回收（不泄漏）
        pool.shutdown(wait=True)
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
            result.content = self._summarize_output(full, call=call)
            # 硬上限安全阀: 摘要后仍超限才截断（原文已存档，无需重复存档）
            if len(result.content) > self.max_output_chars:
                result.content = (
                    result.content[: self.max_output_chars]
                    + f"\n…[结果超长，已截断，共 {len(result.content)} 字符"
                    f"（阈值: 摘要 {self.summary_threshold}/硬上限 {self.max_output_chars}）]；"
                    "完整内容已另存至压缩档案，可用 search_archive 检索找回…\n"
                    + self._DISTILL_GUIDANCE
                )
        elif len(result.content) > self.max_output_chars:
            # 未超摘要阈值但超硬上限（阈值配置异常）→ 存档 + 截断（T22 既有行为）
            full = result.content
            self._archive_oversize_output(call, full)
            result.content = (
                full[: self.max_output_chars]
                + f"\n…[结果超长，已截断，共 {len(full)} 字符（硬上限: {self.max_output_chars}）]；"
                "完整结果已另存至压缩档案，可用 search_archive 检索找回…\n"
                + self._DISTILL_GUIDANCE
            )
        # 约束 C1 绑定: 工具返回的 tool_call_id 必须等于声明 id（空/不一致都纠正为
        # call.id，防 execute_many 索引键错位导致 KeyError 中断整轮）
        if result.tool_call_id != call.id:
            result.tool_call_id = call.id
        if not result.tool_name:
            result.tool_name = call.name
        return result


_FAILURE_GUIDANCE = {
    "failure": "建议: 检查参数/路径/网络后重试，或改用其他更合适的工具（规则 RULE-AI-02/07）。若不确定命令/环境/调用方式，先 search_records(kind=memory) 或 search_docs 查历史执行方式（EVO-20260814-3c65c11b），禁止逐个试错探测。",
    "error": "建议: 工具执行异常，检查输入后重试，或换用等价工具完成任务。若不确定调用方式，先 search_records(kind=memory)/search_docs 查证（EVO-20260814-3c65c11b）。",
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
