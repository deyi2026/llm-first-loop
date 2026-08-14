"""架构自省工具与 AI 自主修正工具薄壳聚合（T2，design §2.1.4.4）.

工具 schema 与执行逻辑拆分至 10 个 registry_*.py 模块; 本壳保留
CorrectionContext + 注入通道 + 审计落盘 + 聚合分派。工具总数不削减，零回归。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

# T2: 工具注册拆分聚合（10 个 registry 模块，顺序即 tool_defs/execute 遍历序）
from llm_loop.introspection import (
    registry_correction,
    registry_eval,
    registry_evolution,
    registry_experience,
    registry_feishu,
    registry_introspection,
    registry_model,
    registry_playwright,
    registry_recovery,
    registry_skills,
)
from llm_loop.introspection.status import ArchitectureStatusProvider

_REGISTRIES = (
    registry_introspection,
    registry_correction,
    registry_experience,
    registry_evolution,
    registry_eval,
    registry_feishu,
    registry_skills,
    registry_model,
    registry_recovery,
    registry_playwright,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class CorrectionContext:
    """修正工具可作用的运行时状态（由主程序装配注入）."""

    # adjust_strategy 白名单（FR-SAFE-01 排除安全边界; M57-M59 含 memory_top_k 等）
    strategy_whitelist: dict[str, dict] = field(
        default_factory=lambda: {
            "max_iterations": {"type": "integer", "min": 5, "max": 500},
            "timeout_s": {"type": "number", "min": 5, "max": 600},
            "history_budget": {"type": "integer", "min": 1000, "max": 1000000},
            "memory_top_k": {"type": "integer", "min": 1, "max": 50},
            "extract_interval_msgs": {"type": "integer", "min": 5, "max": 200},
            "retrieve_semantic_top_k": {"type": "integer", "min": 1, "max": 100},
        }
    )
    strategy: dict = field(default_factory=dict)  # 运行时策略（adjust_strategy 修改，循环消费）
    retry_executor: Callable[[str, dict], ToolResult] | None = None
    refresh_executor: Callable[[], str] | None = None
    session_id: str = ""  # 当前会话（search_archive/search_records 过滤）
    runtime: Any | None = None  # M12 T50
    evolution_store: Any | None = None  # M12 T52: EvolutionStore
    evolve_local_exec: int = 0  # 0=仅建议/1=白名单/2=全面执行
    evolve_exec_whitelist: str = ""  # 执行白名单（逗号分隔，级别 1 时生效）
    evaluator: Any | None = None  # M12 T64: SelfEvaluator
    # M48: 会话级模型覆盖 + 客户端池（model_pool=None 时工具回执"不可用"）
    model_pool: Any | None = None
    session_set_override: Callable[[str | None], None] | None = None  # switch_model 写入 override
    session_model_override: str | None = None  # 当前会话级覆盖（审计 from→to）
    summarizer: Any | None = None  # R2: search_archive(with_summary=true) LLM 摘要


class CorrectionToolRegistry:
    """修正工具薄壳聚合（T2）: tool_defs/execute 委托 10 个 registry 模块，零回归。"""

    def __init__(
        self,
        ctx: CorrectionContext,
        *,
        audit_dir: str | Path | None = None,
        status_provider: ArchitectureStatusProvider | None = None,
        archive_store: Any | None = None,
    ) -> None:
        self.ctx = ctx
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._status = status_provider
        self._archive = archive_store
        self._search_records_fn: Callable[..., list[dict]] | None = None
        self._search_docs_fn: Callable[..., list[dict]] | None = None
        self._experience_store: Any | None = None
        self._recovery_channel: Any | None = None
        self._recovery_sessions_dir: str | Path | None = None
        self._recovery_memory_dir: str | Path | None = None
        self._skills_dir: str | None = None  # B3: 插件化 Skill 目录（None=未注入零回归）

    # ── 暴露私有属性为公开名供 registry 模块访问（RegistryHost 协议）──
    _PUBLIC_MAP = {
        "audit_dir": "_audit_dir",
        "status_provider": "_status",
        "archive_store": "_archive",
        "search_records_fn": "_search_records_fn",
        "search_docs_fn": "_search_docs_fn",
        "experience_store": "_experience_store",
        "recovery_channel": "_recovery_channel",
        "recovery_sessions_dir": "_recovery_sessions_dir",
        "recovery_memory_dir": "_recovery_memory_dir",
        "skills_dir": "_skills_dir",  # B3: 插件化 Skill 目录
    }

    def __getattr__(self, name: str) -> Any:
        priv = type(self)._PUBLIC_MAP.get(name)
        if priv is not None:
            return getattr(self, priv)
        raise AttributeError(name)

    def tool_defs(self) -> list[dict]:
        defs: list[dict] = []
        for reg in _REGISTRIES:
            defs.extend(reg.tool_defs())
        return defs

    # ── 执行分派聚合（边界校验 → 执行 → 审计 → 如实回传）──
    def execute(self, name: str, arguments: dict) -> ToolResult:
        for reg in _REGISTRIES:
            result = reg.execute(name, arguments, self)
            if result is not None:
                return result
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[修正工具不存在] 未注册的修正工具 '{name}'",
            tool_call_id="",
            tool_name=name,
        )

    # ── 辅助方法（供 registry 模块经 RegistryHost 调用）──
    def current_session_id(self) -> str:
        from llm_loop.introspection.tools_status import current_session_id

        return current_session_id(self.ctx)

    def current_params(self) -> dict:
        from llm_loop.introspection.tools_status import current_params

        return current_params(self.ctx)

    # ── 审计落盘（AI 可溯源，design.md §2.3.2）──
    def _audit(self, tool_name: str, arguments: dict, result_status: str) -> None:
        if self._audit_dir is None:
            return
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "id": f"COR-{datetime.now(UTC).strftime('%Y%m%d')}",
                "ts": _now(),
                "tool_name": tool_name,
                "arguments": arguments,
                "result_status": result_status,
            }
            with (self._audit_dir / "self_correction_log.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # fail-open

    # 公开别名供 registry 模块经 RegistryHost.audit 调用
    audit = _audit

    def audit_fallback_event(
        self,
        *,
        from_model: str,
        to_model: str,
        reason: str,
        result_status: str,
        detail: str = "",
    ) -> None:
        """M49: 模型降级事件审计落盘（tool_name=model_fallback，落 self_correction_log.jsonl）."""
        if self._audit_dir is None:
            return
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "id": f"COR-{datetime.now(UTC).strftime('%Y%m%d')}",
                "ts": _now(),
                "tool_name": "model_fallback",
                "arguments": {"from": from_model, "to": to_model, "reason": reason, "detail": detail},
                "result_status": result_status,
            }
            with (self._audit_dir / "self_correction_log.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # fail-open
