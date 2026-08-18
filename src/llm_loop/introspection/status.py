"""架构状态采集/查询/上报 ArchitectureStatusProvider（design.md §2.1.4.2/2.1.4.3）.

八维架构运行状态模型:
1. current_phase 2. action_trace 3. tool_history 4. message_flow
5. memory_state 6. context_usage 7. exception_log 8. architecture_config

零侵入采集（循环事件附带完成，不新增 LLM 往返）+ 如实聚合（状态层禁止伪装）。
审计落盘: action_trace.jsonl / exception_log.jsonl。
"""

from __future__ import annotations

import json
import re
import threading
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
        workspace_changed_fn: Callable[[], dict | None] | None = None,  # P1-12: 工作区变更检测
    ) -> None:
        self.enabled = enabled
        self.reporter = EventReporter(cooldown_s=cooldown_s)
        self._config_status = config_status or (lambda: {})
        self._archive_stats_fn = archive_stats_fn  # T23: 压缩档案统计
        self._memory_stats_fn = memory_stats_fn  # M18 AA10: 记忆统计（未注入如实标注）
        self._workspace_changed_fn = workspace_changed_fn  # P1-12: 工作区变更（guard 检测）
        self._audit_dir = Path(audit_dir) if audit_dir else None

        self._current_phase: str = "idle"
        # P0-5(2026-08-15): 阶段按会话分桶（并发 run 不互改对方 current_phase；
        # _current_phase 保留为"最近写入值"兼容快照缺省路径）
        self._phases: dict[str, str] = {}
        self._phases_guard = threading.Lock()
        self._action_trace: list[ActionTraceItem] = []
        self._tool_history: list[ToolHistoryItem] = []
        self._message_flow: list[dict] = []
        self._exception_log: list[ExceptionLogItem] = []
        self._last_exception_ts: float = 0.0
        self._llm_rounds = 0
        # R2/A6(2026-08-14): 程序故障计数（fail-open 事件聚合，AI 经 architecture_status 感知
        # "程序故障率"——程序故障本身对 AI 可见可应对，对齐 RULE-AI-04）
        self._program_faults: dict[str, int] = {}
        # M49（design §5.4）: 当前降级状态（None = 未处于降级; dict = 最近一次降级）
        self._fallback_state: dict | None = None
        # T4（spec.md 5.3.1）: 待办聚合回调（纯聚合无判断，AI 一站式感知系统待办）
        self._pending_actions_fn: Callable[[], dict] | None = None
        # P2-2: 备份状态回调（AI 经 architecture_status.recovery 感知待恢复备份）
        self._recovery_status_fn: Callable[[], dict] | None = None
        # EVO-20260818（spec §5.4.1-2）: 缓存健康/cache_guard 快照回调（未注入 → None 零回归）
        self._cache_health_fn: Callable[[], dict | None] | None = None
        self._cache_guard_fn: Callable[[str], dict | None] | None = None  # session 透传（grill-me Q11）

    # ── 采集（循环事件附带调用，零侵入）──
    def record_phase(self, phase: str) -> None:
        if self.enabled:
            # P0-5: 按 contextvar 会话分桶（无上下文 → 全局桶）；并发 run 各记各的
            try:
                from llm_loop.core.run_context import current_session_id

                sid = current_session_id.get()
            except Exception:  # noqa: BLE001 — 上下文不可用落全局桶（零回归）
                sid = ""
            with self._phases_guard:
                self._phases[sid] = phase
                self._current_phase = phase  # 兼容：最近写入值

    def _phase_for(self, session_id: str = "") -> str:
        """快照取阶段：会话桶优先 → 全局桶 → 最近写入值（如实回退链）."""
        try:
            from llm_loop.core.run_context import current_session_id

            ctx_sid = current_session_id.get()
        except Exception:  # noqa: BLE001
            ctx_sid = ""
        with self._phases_guard:
            for key in (session_id, ctx_sid, ""):
                if key and key in self._phases:
                    return self._phases[key]
            return self._current_phase

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

    def record_program_fault(self, kind: str) -> None:
        """R2/A6: 程序故障计数（fail-open 事件聚合，kind 如 memory/session_persist/event_write/llm_call）.

        供 engine 各 fail-open 点调用；自身 fail-open（异常不影响主流程）；
        计数供 architecture_status.program_faults 展示（AI 可感知程序故障率）。
        """
        try:
            if self.enabled:
                self._program_faults[kind] = self._program_faults.get(kind, 0) + 1
        except Exception:  # noqa: BLE001 — 计数失败 fail-open
            pass

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

    def _recovery_status(self) -> dict:
        """P2-2: 备份状态感知（spec.md 5.3.1 规则 4 / design §2.3.2.7）.

        回调注入 → 调用回调返回备份状态 dict（pending_count/oldest_backup_at/by_type）；
        未注入 → {"note": "数据源未注入"}（向后兼容）；
        回调异常 → 如实标注原因（fail-open 不伪造为零）。
        """
        fn = getattr(self, "_recovery_status_fn", None)
        if fn is None:
            return {"note": "数据源未注入"}
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — 状态查询失败如实标注（fail-open）
            return {
                "pending_count": None,
                "oldest_backup_at": None,
                "by_type": {"session": None, "memory_stats": None},
                "note": f"备份状态读取失败（{type(exc).__name__}: {exc}）",
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

    def set_recovery_status_fn(self, fn) -> None:
        """注入备份状态查询回调（P2-2: AI 经 architecture_status.recovery 感知）.

        fn() -> dict，如 {"pending_count": 2, "oldest_backup_at": "...",
        "by_type": {"session": 1, "memory_stats": 1}, "note": None}；
        未注入 → snapshot 中 recovery 为 {"note": "数据源未注入"}（向后兼容）。
        """
        self._recovery_status_fn = fn

    def set_cache_health_fn(self, fn) -> None:
        """注入 cache_health 快照回调（EVO-20260818 spec §5.4.1-2）.

        fn() -> dict | None（CacheHealthMonitor.snapshot）；未注入 → context_usage.cache_health
        为 None（向后兼容）。与既有 set_context_breakdown_fn 同构。
        """
        self._cache_health_fn = fn

    def set_cache_guard_fn(self, fn) -> None:
        """注入 cache_guard 快照回调（EVO-20260818 spec §5.4.1-2，grill-me Q11）.

        fn(session_id: str) -> dict | None（PromptGuard.snapshot——窗口 per-session，
        snapshot() 透传当前会话，空串=最近活跃会话聚合）；未注入 → 字段 None。
        """
        self._cache_guard_fn = fn

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
            "current_phase": self._phase_for(session_id),
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
                # EVO-20260818（spec §5.4.1-2）: 缓存健康/cache_guard 快照（fail-open——
                # 回调异常字段置 None 不抛穿 architecture_status）
                "cache_health": self._cache_health_snapshot(),
                "cache_guard": self._cache_guard_snapshot(session_id),
                "records_hint": "完整历史运行记录可用 search_records 检索（不限于内存窗口）",
            },
            "exception_log": [
                {"phase": e.phase, "error_type": e.error_type, "error_message": e.error_message}
                for e in self._exception_log[-10:]
            ],
            "architecture_config": self._config_status(),
            # P1-12(2026-08-16): 工作区变更检测（guard 检测 .env/providers.json/src/skills 变化
            # 后写 flag → AI 经 architecture_status 自查可见; None = 无变更/未配置）
            "workspace_changed": (
                self._workspace_changed_fn() if self._workspace_changed_fn else None
            ),
            "process_versions": self._process_versions(),  # EVO-20260811-f94e5306
            # M49（design §5.4）: 当前降级状态（有则显示，含 from/to/reason/ts; 无则全 None）
            "model_fallback": self._fallback_status(),
            # T4（spec.md 5.3.1）: 待办聚合（纯聚合无判断，AI 一站式感知系统待办）
            "pending_actions": self._pending_actions(),
            # P2-2: 备份状态（AI 经 architecture_status.recovery 感知待恢复备份）
            "recovery": self._recovery_status(),
            # R2/A6: 程序故障计数（fail-open 聚合，AI 可感知"程序故障率"）
            "program_faults": dict(self._program_faults),
        }
        # EVO-20260818 防御归一化: dimensions 可能被模型传成字符串/其他类型——
        # 字符串按字符迭代会导致"维度 'c' 暂不可用"（按字符拆解 bug）;
        # 非列表一律回落全量（绝不按字符拆）。
        if isinstance(dimensions, str):
            dimensions = [
                d.strip() for d in re.split(r"[,，\s]+", dimensions) if d.strip()
            ] or None
        if not isinstance(dimensions, list):
            dimensions = None
        if dimensions:
            out: dict = {}
            for d in dimensions:
                out[d] = avail.get(
                    d,
                    {
                        "unavailable": f"维度 '{d}' 暂不可用",
                        "available_dimensions": sorted(avail.keys()),
                    },
                )
            return out
        return avail

    # ── 缓存快照辅助（fail-open）──
    def _cache_health_snapshot(self) -> dict | None:
        if getattr(self, "_cache_health_fn", None) is None:
            return None
        try:
            return self._cache_health_fn()
        except Exception:  # noqa: BLE001 — 回调异常如实置 None
            return None

    def _cache_guard_snapshot(self, session_id: str) -> dict | None:
        if getattr(self, "_cache_guard_fn", None) is None:
            return None
        try:
            return self._cache_guard_fn(session_id)
        except Exception:  # noqa: BLE001 — 回调异常如实置 None
            return None

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
                except (json.JSONDecodeError, AttributeError) as exc:
                    # fail-open：无法解析的行保守保留
                    logging.getLogger(__name__).debug("审计行解析失败，保守保留（fail-open）: %s", exc)
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
