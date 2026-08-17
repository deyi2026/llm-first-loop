"""演进自动执行资格判定与执行引擎（design.md §6.1.1/6.1.2/6.1.6/6.1.7 + §7.1.1 移交）.

T55 范围: EVOLVE_LOCAL_EXEC 三级化后的判定纯函数（无 IO，可直接单测）:
- exec_level(): 读取当前生效权限级别（0=仅建议/1=白名单局部执行/2=全面执行）
- in_exec_whitelist(): 级别 1 白名单命中判定（按影响范围/模块/动作类型）
- can_auto_exec(): 自动执行资格判定链（边界 → 权限级别 → 白名单），返回如实原因

T57/T69 范围: EvolutionExecutor 执行引擎 + ExecutionOutcome 结果记录 + evolution_exec_log 审计落盘
（M16 审计 FR-AUDIT-AI-01/03/05/06 移交: 验证/回滚模块删除，判定与动作交 AI，程序保留
状态机 + 审计 + 引导）:
- AutoExecPlan: accepted 演进自动执行判定（纯判定无 IO）
- maybe_auto_execute(): can_auto_exec 判定 → 允许则 accepted→executing + 审计 + 执行引导
- complete(): AI 执行完成登记（executor=ai，executing→executed + 如实汇报验证/回滚结论）
- manual_complete(): 人工执行通道（涉边界 accepted 演进人工完成标记 executed）

判定顺序铁律（EXEC-03 最高优先，不因 accepted 放宽）:
  边界（复用 EvolutionStore._touches_boundary，命中即拒）→ 权限级别（EXEC-01）→ 白名单（EXEC-08，级别 1 时）。
执行载体（移交后）: AI 经修正工具（adjust_strategy/retry_tool/refresh_config/恢复工具）自主执行，
程序不代 AI 调用修正工具——程序只保留状态推进、审计落盘与如实标注（程序最小化，design.md 7.1.1）。
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from llm_loop.config import _env_evolve_level
from llm_loop.introspection.evolution import (
    EvolutionStatus,
    EvolutionStore,
    EvolutionSuggestion,
)

_VERIFY_GUIDE = (
    "验证结论请由 AI 自行对比执行前后架构状态（architecture_status）并如实汇报"
    "（RULE-AI-06 子规则 1）——程序不做硬判定。"
)
_ROLLBACK_GUIDE = (
    "失败/未达预期可经 adjust_strategy 复位白名单参数或经恢复工具还原临时状态，"
    "回滚后如实汇报（RULE-AI-06 子规则 2）——程序不代 AI 回滚。"
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def exec_level() -> int:
    """读取当前生效演进执行权限级别（0/1/2，非法回退 0）."""
    return _env_evolve_level("EVOLVE_LOCAL_EXEC")


def in_exec_whitelist(
    suggestion: EvolutionSuggestion,
    whitelist: tuple[str, ...],
) -> bool:
    """执行白名单命中判定（EXEC-08，级别 1 时）.

    M16 审计（FR-AUDIT-AI-15）: 未配置白名单（空元组）→ False（无白名单授权，不自动执行），
    须人工显式配置白名单才启用级别 1 自动执行；
    配置后按影响范围/模块/动作类型子串匹配（不区分大小写）:
    impact_scope / content 命中，或 actions 内 tool_name/scope 命中 → 放行。
    """
    if not whitelist:
        return False
    hay_fields = [suggestion.impact_scope, suggestion.content]
    for action in getattr(suggestion, "actions", []) or []:
        if isinstance(action, dict):
            hay_fields.append(str(action.get("tool_name", "")))
            hay_fields.append(str(action.get("scope", "")))
    hay = " ".join(hay_fields).lower()
    return any(w.strip().lower() and w.strip().lower() in hay for w in whitelist)


def can_auto_exec(
    suggestion: EvolutionSuggestion,
    *,
    level: int,
    whitelist: tuple[str, ...] = (),
) -> tuple[bool, str]:
    """自动执行资格判定（EXEC-01/03/08，纯函数无 IO）.

    返回 (允许?, 原因): 允许 → (True, "")；
    不允许 → (False, 如实原因: "仅建议级" / "涉边界需人工执行" / "不在执行白名单"（级别 1 空白名单
    补充 "未配置白名单"））。
    判定顺序: 边界（EXEC-03，最高优先）→ 权限级别（EXEC-01）→ 白名单（EXEC-08，级别 1 时）。
    """
    # 1. 边界判定（EXEC-03，最高优先）: 独立重查，不因 accepted 放宽（DFX-SEC-05）
    if suggestion.requires_human or EvolutionStore._touches_boundary(
        suggestion.impact_scope, suggestion.content
    ):
        return False, "涉边界需人工执行"
    # 2. 权限级别（EXEC-01）
    if level <= 0:
        return False, "仅建议级"
    if level >= 2:
        return True, ""
    # 3. 白名单（EXEC-08，仅级别 1 时）: 空白名单（未配置）→ 不自动执行（FR-AUDIT-AI-15）
    if not whitelist:
        return False, "不在执行白名单（未配置白名单，级别 1 需人工显式配置后自动执行）"
    if in_exec_whitelist(suggestion, whitelist):
        return True, ""
    return False, "不在执行白名单"


@dataclass(frozen=True)
class AutoExecPlan:
    """accepted 演进自动执行判定（移交后保留面: 状态机 + 审计 + 引导，纯判定无 IO）.

    M16 审计（FR-AUDIT-AI-01/05）: 取代原"can_auto_exec 元组返回"，集中表达判定结果。
    """

    suggestion_id: str
    allowed: bool
    reason: str  # 拒绝原因: "仅建议级" / "涉边界需人工执行" / "不在执行白名单"
    level: int
    boundary: bool  # 涉边界标记（审计记录，DFX-SEC-05）


@dataclass
class ExecutionOutcome:
    """一次演进执行的完整结果（EXEC-04/05/06，如实记录；字段向后兼容）.

    M16 审计（FR-AUDIT-AI-01）字段语义收敛:
    - status: 移除 verifying 中间态（程序不做验证）
    - verify_result: unverified（程序不做硬判定，AI 自主验证后经 complete 汇报 ai_reported）
    - rollback_result: none（程序不代 AI 回滚，AI 自主回滚后经 complete 汇报 ai_reported）
    """

    suggestion_id: str
    executor: Literal["ai", "human"]  # 执行者（EXEC-06 审计）
    actions: list[dict]  # 已登记执行动作（AI 执行后由 complete 回传）
    status: Literal["executing", "executed", "failed", "rolled_back"]
    verify_result: Literal["unverified", "ai_reported"] = "unverified"  # 程序不做硬判定
    rollback_result: Literal["none", "ai_reported"] = "none"  # 程序不做硬判定
    note: str = ""  # 如实说明（含验证/回滚引导）
    error: str = ""  # M19 FIX-01: 状态未推进如实标注（如"状态未推进（建议不存在）"；不影响审计）
    ts_start: str = ""
    ts_end: str = ""

    def to_dict(self) -> dict:
        return {
            "id": f"EVOEXEC-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}",
            "suggestion_id": self.suggestion_id,
            "executor": self.executor,
            "ts_start": self.ts_start,
            "ts_end": self.ts_end,
            "actions": self.actions,
            "status": self.status,
            "verify_result": self.verify_result,
            "rollback_result": self.rollback_result,
            "note": self.note,
        }


class EvolutionExecutor:
    """accepted 演进自动执行（移交后: 状态机 + 审计 + 引导；执行动作/验证/回滚交 AI）.

    M16 审计（FR-AUDIT-AI-01/03/05/06）: 移除 ExecutionVerifier/ExecutionRollback 模块与
    verifier/rollback 参数——程序不代 AI 调修正工具、不做硬验证/硬回滚；执行动作/验证判定/
    回滚动作由 AI 经修正工具自主完成，规则由 RULE-AI-06 子规则 1/2/4 承载（design.md 7.1.1/7.4）。
    程序保留面: 状态机（七态）+ 审计落盘（evolution_exec_log）+ 如实标注。
    """

    def __init__(
        self,
        *,
        exec_level: int,
        whitelist: tuple[str, ...] = (),
        store: EvolutionStore | None = None,
        audit_dir: str | Path | None = None,
    ) -> None:
        self._level = exec_level
        self._whitelist = tuple(whitelist)
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._store = store

    # ── 审计落盘（EXEC-06，fail-open 复用 corrections._audit 模式）──
    def _audit_exec(self, outcome: ExecutionOutcome, boundary: dict) -> None:
        if self._audit_dir is None:
            return
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            record = outcome.to_dict()
            record["boundary"] = boundary
            with (self._audit_dir / "evolution_exec_log.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # fail-open（DFX-REL-06）

    def _transition(self, suggestion_id: str, status: EvolutionStatus, **fields: str) -> None:
        """状态流转（store 注入时生效；未注入则跳过，不阻塞执行）."""
        if self._store is None:
            return
        with contextlib.suppress(OSError, ValueError):
            # fail-open（状态流转失败不阻塞执行结果回传）
            self._store.transition(suggestion_id, status=status, **fields)

    # ── 执行入口 ──
    def maybe_auto_execute(self, suggestion: EvolutionSuggestion) -> ExecutionOutcome | None:
        """accepted 后: can_auto_exec 判定 → 允许则状态 accepted→executing + 审计 + [执行引导]；
        不允许 → None（保持 accepted + 如实标注"等待人工执行"）."""
        plan = self.plan(suggestion)
        boundary = {
            "touches_boundary": plan.boundary,
            "reason": plan.reason,
        }
        if not plan.allowed:
            self._audit_exec(
                ExecutionOutcome(
                    suggestion_id=suggestion.id,
                    executor="ai",
                    actions=list(suggestion.actions),
                    status="failed",
                    note=f"未自动执行: {plan.reason}（保持 accepted，等待人工执行）",
                    ts_start=_now(),
                    ts_end=_now(),
                ),
                boundary=boundary,
            )
            return None
        # 允许 → accepted→executing（执行动作/验证/回滚交 AI，程序只推进状态 + 审计 + 引导）
        ts_start = _now()
        self._transition(suggestion.id, status="executing")
        outcome = ExecutionOutcome(
            suggestion_id=suggestion.id,
            executor="ai",
            actions=list(suggestion.actions),
            status="executing",
            verify_result="unverified",  # 程序不做硬判定，如实标注（FR-AUDIT-AI-01）
            rollback_result="none",
            note=(
                "已置 executing，请经修正工具（adjust_strategy/retry_tool/refresh_config/恢复工具）"
                "自主落地执行并如实汇报验证/回滚结论（RULE-AI-06）。" + _VERIFY_GUIDE
            ),
            ts_start=ts_start,
            ts_end="",
        )
        self._audit_exec(outcome, boundary=boundary)
        return outcome

    def plan(self, suggestion: EvolutionSuggestion) -> AutoExecPlan:
        """自动执行判定（纯判定，返回 AutoExecPlan；can_auto_exec 判定链）."""
        allowed, reason = can_auto_exec(suggestion, level=self._level, whitelist=self._whitelist)
        boundary = suggestion.requires_human or EvolutionStore._touches_boundary(
            suggestion.impact_scope, suggestion.content
        )
        return AutoExecPlan(
            suggestion_id=suggestion.id,
            allowed=allowed,
            reason=reason,
            level=self._level,
            boundary=boundary,
        )

    def complete(
        self,
        suggestion_id: str,
        *,
        actions: list[dict] | None = None,
        note: str = "",
    ) -> ExecutionOutcome:
        """AI 执行完成登记（executor=ai）: executing→executed + 审计.

        note 如实回传 AI 自主验证/回滚结论（RULE-AI-06 子规则 1/2 汇报）——
        程序不校验 note 真伪，如实记录（DFX-REL-06: 不伪装通过，也不代 AI 判定）。

        M19 FIX-01 纵深防御: 直接调 store.transition 并捕获异常（不再经 _transition 的
        suppress 吞异常——该 suppress 使"建议不存在"与"读取异常"都返回 None 无法区分）:
        target is None（read 正常但无该 id）→ outcome.error 标注"状态未推进（建议不存在）"；
        OSError/ValueError（read/write 异常）→ fail-open（error 不标，现状语义 DFX-REL-08）。
        """
        ts_end = _now()
        error = ""
        if self._store is not None:
            try:
                target = self._store.transition(
                    suggestion_id, status="executed", executed_at=_now()
                )
                if target is None:
                    error = "状态未推进（建议不存在）"
            except (OSError, ValueError):
                pass  # fail-open: 状态流转异常不阻断（DFX-REL-08）
        outcome = ExecutionOutcome(
            suggestion_id=suggestion_id,
            executor="ai",
            actions=list(actions) if actions else [],
            status="executed",
            verify_result="ai_reported" if note.strip() else "unverified",
            rollback_result="none",
            note=note or "AI 执行完成登记（验证结论见 AI 汇报，RULE-AI-06）",
            ts_start="",
            ts_end=ts_end,
        )
        outcome.error = error  # M19 FIX-01: 状态未推进如实标注（不影响 status/审计落盘）
        self._audit_exec(outcome, boundary={"touches_boundary": False, "reason": "ai-complete"})
        return outcome

    def manual_complete(self, suggestion_id: str, result: str) -> ExecutionOutcome:
        """人工执行完成标记（EXEC-03 验收: 涉边界演进人工通道）; executor=human.

        result: 人工执行结果说明（如实记录）。状态流转: accepted → executed（executor=human）。
        """
        self._transition(suggestion_id, status="executed", executed_at=_now())
        outcome = ExecutionOutcome(
            suggestion_id=suggestion_id,
            executor="human",
            actions=[],
            status="executed",
            verify_result="unverified",
            rollback_result="none",
            note=result,
            ts_start=_now(),
            ts_end=_now(),
        )
        self._audit_exec(outcome, boundary={"touches_boundary": False, "reason": "human"})
        return outcome


def maybe_auto_execute_from_engine(engine, store, target: dict) -> str:
    """accepted 后按权限分级自动执行（公共入口：CLI / 飞书审批共用，防行为分叉）.

    自 cli._maybe_auto_execute 提取（EVO-20260817 飞书审批 UX，方案 ④）。
    返回提示文本（调用方打印/回执），不抛异常。
    """
    from llm_loop.introspection.evolution import EvolutionSuggestion

    level = int(getattr(engine.correction_ctx, "evolve_local_exec", 0) or 0)
    if level == 0:
        return (
            f"[等待人工执行] 当前为仅建议模式（EVOLVE_LOCAL_EXEC=0），"
            f"{target['id']} 由人工执行。"
        )
    whitelist_raw = getattr(engine.correction_ctx, "evolve_exec_whitelist", "") or ""
    whitelist = (
        tuple(w.strip() for w in whitelist_raw.split(",") if w.strip()) if whitelist_raw else ()
    )
    suggestion = EvolutionSuggestion(**target)
    executor = EvolutionExecutor(
        exec_level=level,
        whitelist=whitelist,
        store=store,
        audit_dir=getattr(engine.settings, "audit_dir", None),
    )
    outcome = executor.maybe_auto_execute(suggestion)
    if outcome is None:
        return (
            f"[等待人工执行] {target['id']} 不满足自动执行条件"
            "（边界/权限/白名单），由人工执行。"
        )
    return (
        f"[自动执行] {target['id']} → {outcome.status}（executor={outcome.executor} "
        f"verify={outcome.verify_result} rollback={outcome.rollback_result}）: "
        f"{outcome.note[:120]}"
    )
