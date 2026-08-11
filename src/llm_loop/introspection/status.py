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

    # ── 查询（拉取通道）──
    def snapshot(self, session_id: str = "", dimensions: list[str] | None = None) -> dict:
        """构造八维状态快照（紧凑 JSON，维度可按需裁剪）.

        部分维度不可用时如实标注（不伪造状态）。
        """
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
