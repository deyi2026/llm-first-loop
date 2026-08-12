"""架构状态采集/查询/上报 ArchitectureStatusProvider（design.md §2.1.4.2/2.1.4.3）.

八维架构运行状态模型:
1. current_phase 2. action_trace 3. tool_history 4. message_flow
5. memory_state 6. context_usage 7. exception_log 8. architecture_config

零侵入采集（循环事件附带完成，不新增 LLM 往返）+ 如实聚合（状态层禁止伪装）。
审计落盘: action_trace.jsonl / exception_log.jsonl。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.events import ArchitectureEvent, EventReporter


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ActionTraceItem:
    """动作轨迹条目（AI 可溯源）."""

    ts: str
    phase: str
    action_type: str
    detail: str
    session_id: str = ""

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "phase": self.phase,
            "action_type": self.action_type,
            "detail": self.detail,
        }


@dataclass
class ExceptionLogItem:
    """异常记录条目（AI 可溯源）."""

    ts: str
    phase: str
    error_type: str
    error_message: str
    reported: bool = False
    resolved: bool = False
    session_id: str = ""


@dataclass
class ToolHistoryItem:
    """工具调用历史条目（八维状态维度 3）."""

    name: str
    arguments: dict
    status: ToolResultStatus
    summary: str
    duration_ms: float = 0.0
    ts: str = ""


class ArchitectureStatusProvider:
    """架构状态采集/查询/上报（AI-serving，design.md §2.1.4）."""

    def __init__(
        self,
        *,
        audit_dir: str | Path | None = None,
        cooldown_s: float = 60.0,
        enabled: bool = True,
        config_status: Callable[[], dict] | None = None,
        archive_stats_fn: Callable[[], dict] | None = None,
        memory_stats_fn: Callable[[], dict] | None = None,  # M18 AA10: 记忆统计（补真实数据）
    ) -> None:
        self.enabled = enabled
        self.reporter = EventReporter(cooldown_s=cooldown_s)
        self._config_status = config_status or (lambda: {})
        self._archive_stats_fn = archive_stats_fn  # T23: 压缩档案统计
        self._memory_stats_fn = memory_stats_fn  # M18 AA10: 记忆统计（未注入如实标注）
        self._audit_dir = Path(audit_dir) if audit_dir else None

        self._current_phase: str = "idle"
        self._action_trace: list[ActionTraceItem] = []
        self._tool_history: list[ToolHistoryItem] = []
        self._message_flow: list[dict] = []
        self._exception_log: list[ExceptionLogItem] = []
        self._last_exception_ts: float = 0.0
        self._llm_rounds = 0
        # M49（design §5.4）: 当前降级状态（None = 未处于降级; dict = 最近一次降级）
        self._fallback_state: dict | None = None
        # T4（spec.md 5.3.1）: 待办聚合回调（纯聚合无判断，AI 一站式感知系统待办）
        self._pending_actions_fn: Callable[[], dict] | None = None

    # ── 采集（循环事件附带调用，零侵入）──
    def record_phase(self, phase: str) -> None:
        if self.enabled:
            self._current_phase = phase

    def record_action(
        self, phase: str, action_type: str, detail: str, session_id: str = ""
    ) -> None:
        if not self.enabled:
            return
        item = ActionTraceItem(
            ts=_now(), phase=phase, action_type=action_type, detail=detail, session_id=session_id
        )
        self._action_trace.append(item)
        self._write_audit("action_trace.jsonl", item.to_dict())

    def record_tool_history(self, item: ToolHistoryItem) -> None:
        if self.enabled:
            self._tool_history.append(item)
            self._tool_history = self._tool_history[-200:]  # 防膨胀

    def record_message(self, role: str, source: str, chars: int, note: str | None = None) -> None:
        if self.enabled:
            self._message_flow.append(
                {"role": role, "source": source, "chars": chars, "note": note}
            )
            self._message_flow = self._message_flow[-100:]

    def record_llm_round(self) -> None:
        if self.enabled:
            self._llm_rounds += 1

    def record_exception(self, phase: str, exc: Exception, *, session_id: str = "") -> None:
        if not self.enabled:
            return
        item = ExceptionLogItem(
            ts=_now(),
            phase=phase,
            error_type=type(exc).__name__,
            error_message=str(exc)[:500],
            session_id=session_id,
        )
        self._exception_log.append(item)
        self._exception_log = self._exception_log[-100:]
        self._write_audit(
            "exception_log.jsonl",
            {
                "ts": item.ts,
                "phase": item.phase,
                "error_type": item.error_type,
                "error_message": item.error_message,
            },
        )

    # ── 上报（推送通道，design.md §2.1.4.3）──
    def report_event(self, event: ArchitectureEvent) -> bool:
        """尝试上报事件；通过冷却则返回 True（调用方决定注入消息）."""
        if not self.enabled:
            return False
        return self.reporter.should_report(event)

    def build_report_message(self, event: ArchitectureEvent):
        return self.reporter.build_message(event)

    def _process_versions(self) -> dict:
        """进程代码版本一致性（EVO-20260811-f94e5306）；读取失败如实标注."""
        try:
            from llm_loop.introspection.proc_version import get_process_versions

            return get_process_versions()
        except Exception as exc:  # noqa: BLE001 — 读取失败如实标注（fail-open）
            return {"note": f"读取失败: {type(exc).__name__}: {exc}"}

    def _memory_stats(self) -> dict:
        """记忆统计（M18 AA10: 补真实数据；未注入/读取失败如实标注，不伪造）."""
        if self._memory_stats_fn is None:
            return {"note": "memory_state 暂不可用（未注入统计）", "entries_hint": None}
        try:
            return self._memory_stats_fn()
        except Exception as exc:  # noqa: BLE001 — 读取失败如实标注（fail-open，DFX-REL-09）
            return {
                "note": f"读取失败: {type(exc).__name__}: {exc}",
                "entries_hint": None,
            }

    # ── M49（design §5.4）: 模型降级状态（architecture_status 可见） ──
    def record_fallback(
        self, from_model: str, to_model: str, reason: str, *, session_id: str = ""
    ) -> None:
        """记录一次模型降级（仅保留最近一次,供 architecture_status 可见）.

        Args:
            from_model: 原模型引用（"provider/model" 或裸模型名）
            to_model: 降级后模型引用
            reason: 失败原因（"429 限流" / "网络不可达" / "5xx 上游错误" 等,设计原则 2 如实反馈）
            session_id: 当前会话 ID（关联降级事件与会话）
        """
        if not self.enabled:
            return
        self._fallback_state = {
            "ts": _now(),
            "from": from_model,
            "to": to_model,
            "reason": reason,
            "session_id": session_id,
        }

    def clear_fallback(self) -> None:
        """清除降级状态（下次成功调用 default 模型后由调用方调用; 当前仅在 loop.run 出口自动调用）."""
        if not self.enabled:
            return
        self._fallback_state = None

    def _fallback_status(self) -> dict:
        """降级状态摘要（architecture_status 维度, 有则显示, 无则 null/None）.

        Returns:
            dict: 含 from/to/reason/ts 字段；未处于降级态时各字段为 None
        """
        st = getattr(self, "_fallback_state", None)
        if not st:
            return {
                "active": False,
                "from": None,
                "to": None,
                "reason": None,
                "ts": None,
            }
        return {
            "active": True,
            "from": st.get("from"),
            "to": st.get("to"),
            "reason": st.get("reason"),
            "ts": st.get("ts"),
        }

    def _pending_actions(self) -> dict:
        """T4: 待办聚合（纯聚合无判断，spec.md 5.3.1 / design.md §2.2.2.2）.

        回调注入 → 调用回调返回聚合 dict（计数 + hint，无决策）；
        未注入 → {"note": "数据源未注入"}（向后兼容）；
        回调异常 → 计数字段 null + note 标注原因（fail-open 不伪造 0）。
        """
        fn = getattr(self, "_pending_actions_fn", None)
        if fn is None:
            return {"note": "数据源未注入"}
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — 聚合失败如实标注（fail-open）
            return {
                "executing_evolutions": None,
                "pending_reviews": None,
                "pending_self_evals": None,
                "hint": None,
                "note": f"待办聚合失败（{type(exc).__name__}: {exc}）",
            }

    # ── 查询（拉取通道）──
    def set_model_context_fn(self, fn) -> None:
        """注入当前模型窗口查询回调（M56 B5：AI 可查窗口后自主决策压缩）.

        fn() -> dict | None，如 {"label": "deepseek/deepseek-v4-flash", "context": 131072}；
        未注入 → snapshot 中 model_window 为 None（向后兼容）。
        """
        self._model_context_fn = fn

    def set_runtime_params_fn(self, fn) -> None:
        """注入运行时参数快照查询回调（M57 配置面收敛：AI 可查 adjust_strategy 生效值）.

        fn() -> dict，如 {"max_iterations": 30, "memory_top_k": 12}；
        未注入 → snapshot 中 runtime_params 为 None（向后兼容）。
        """
        self._runtime_params_fn = fn

    def set_context_breakdown_fn(self, fn) -> None:
        """注入上下文占用分解回调（R1: AI 经 architecture_status 可见组件级占用）.

        fn() -> dict | None；未注入 → snapshot 中 breakdown 为 None（向后兼容）。
        """
        self._context_breakdown_fn = fn

    def set_pending_actions_fn(self, fn) -> None:
        """注入待办聚合回调（T4: AI 一站式感知系统待办，纯聚合无判断）.

        fn() -> dict，如 {"executing_evolutions": 2, "pending_reviews": 1,
        "pending_self_evals": 0, "hint": "...", "note": None}；
        未注入 → snapshot 中 pending_actions 为 {"note": "数据源未注入"}（向后兼容）。
        """
        self._pending_actions_fn = fn

    def snapshot(self, session_id: str = "", dimensions: list[str] | None = None) -> dict:
        """构造八维状态快照（紧凑 JSON，维度可按需裁剪）.

        部分维度不可用时如实标注（不伪造状态）。
        """
        model_window = None
        fn = getattr(self, "_model_context_fn", None)
        if fn is not None:
            try:
                model_window = fn()
            except Exception:  # noqa: BLE001 — 窗口查询失败如实标注 None（fail-open）
                model_window = None
        runtime_params = None
        fn2 = getattr(self, "_runtime_params_fn", None)
        if fn2 is not None:
            try:
                runtime_params = fn2()
            except Exception:  # noqa: BLE001 — 参数快照失败如实标注 None（fail-open）
                runtime_params = None
        avail = {
            "current_phase": self._current_phase,
            "action_trace": [a.to_dict() for a in self._action_trace[-30:]],
            "tool_history": [
                {
                    "name": t.name,
                    "arguments": t.arguments,
                    "status": t.status.value,
                    "summary": t.summary[:120],
                    "duration_ms": round(t.duration_ms, 1),
                }
                for t in self._tool_history[-20:]
            ],
            "message_flow": self._message_flow[-20:],
            "memory_state": self._memory_stats(),
            "context_usage": {
                "llm_rounds": self._llm_rounds,
                "action_trace_count": len(self._action_trace),
                "archive": self._archive_stats_fn() if self._archive_stats_fn else None,
                # M56 B5（ANALYSIS-20260811）: 当前模型窗口（AI 可查后自主决策压缩）
                "model_window": model_window,
                # M57 配置面收敛: adjust_strategy 当前生效值（AI 可查可验证）
                "runtime_params": runtime_params,
                # R1: 组件级占用分解（AI 每轮可见，自主决策压缩/切换/开新会话）
                "breakdown": (
                    self._context_breakdown_fn()
                    if getattr(self, "_context_breakdown_fn", None)
                    else None
                ),
                "records_hint": "完整历史运行记录可用 search_records 检索（不限于内存窗口）",
            },
            "exception_log": [
                {"phase": e.phase, "error_type": e.error_type, "error_message": e.error_message}
                for e in self._exception_log[-10:]
            ],
            "architecture_config": self._config_status(),
            "process_versions": self._process_versions(),  # EVO-20260811-f94e5306
            # M49（design §5.4）: 当前降级状态（有则显示，含 from/to/reason/ts; 无则全 None）
            "model_fallback": self._fallback_status(),
            # T4（spec.md 5.3.1）: 待办聚合（纯聚合无判断，AI 一站式感知系统待办）
            "pending_actions": self._pending_actions(),
        }
        if dimensions:
            out: dict = {}
            for d in dimensions:
                out[d] = avail.get(d, {"unavailable": f"维度 '{d}' 暂不可用"})
            return out
        return avail

    # ── 工具 ──
    def _write_audit(self, filename: str, record: dict) -> None:
        if self._audit_dir is None:
            return
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            with (self._audit_dir / filename).open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            # T39: 审计失败至少日志 warning（不静默 pass，不影响主循环）
            import logging

            logging.getLogger(__name__).warning("审计写入失败（fail-open）: %s", exc)


def cleanup_audit_logs(audit_dir: str | Path, ttl_days: int) -> dict:
    """P1-3: 按 TTL 清理审计 JSONL 条目（启动时调用一次，防无限增长，fail-open）.

    逐行过滤：ts 早于 cutoff 的条目删除（有 ts 的按 ts 判，无 ts/损坏行保守保留）。
    返回 {"pruned_files": N, "pruned_entries": N}；ttl_days<=0 空操作。
    """
    if ttl_days <= 0:
        return {"pruned_files": 0, "pruned_entries": 0}
    import logging
    from datetime import UTC, datetime, timedelta

    d = Path(audit_dir)
    if not d.exists():
        return {"pruned_files": 0, "pruned_entries": 0}
    cutoff = (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat()
    total = 0
    files = 0
    for p in sorted(d.glob("*.jsonl")):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
            kept: list[str] = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    ts = json.loads(line).get("ts", "")
                    if isinstance(ts, str) and ts and ts < cutoff:
                        total += 1
                        continue
                except (json.JSONDecodeError, AttributeError):
                    pass  # 无法解析的行保守保留
                kept.append(line)
            if len(kept) < len(lines):
                if kept:
                    p.write_text("\n".join(kept) + "\n", encoding="utf-8")
                else:
                    p.unlink(missing_ok=True)
                files += 1
        except Exception:  # noqa: BLE001 — 单文件清理失败 fail-open
            logging.getLogger(__name__).warning(
                "审计清理失败（fail-open）: %s", p, exc_info=True
            )
            continue
    return {"pruned_files": files, "pruned_entries": total}
