"""程序辅助组件故障增强反馈（M17 FR-REVIEW-AI-03 / design §8.3.1 拆分）.

从 core/loop.py `_fault_feedback`（:409-462）逐字搬移：分类器 + 预算可用时附加可自愈性
与可修复行动建议；否则维持 T39 三件套语义；selfheal_log 审计落盘 fail-open。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.core.message import Message

logger = logging.getLogger(__name__)


def build_fault_feedback_message(
    component: str,
    exc: Exception,
    *,
    fault_classifier: Any | None,
    selfheal_budget: Any | None,
    audit_dir: str | Path | None,
) -> Message:
    """程序辅助组件故障增强反馈（M12 T49 语义逐字保留）.

    分类器 + 预算可用时附加可自愈性与可修复行动建议；否则维持 T39 三件套语义；
    selfheal_log 审计落盘 fail-open（DFX-REL-06/08）。
    """
    from llm_loop.feedback.honesty import program_error_message

    classification = None
    healable = None
    actions: tuple[str, ...] = ()
    remaining = None
    if fault_classifier is not None:
        try:
            classification = fault_classifier.classify(component, exc)
            healable = classification.healable
            actions = classification.suggested_actions
        except Exception:
            classification = None
    if selfheal_budget is not None:
        try:
            selfheal_budget.can_attempt(component, type(exc).__name__)
            remaining = selfheal_budget.remaining(component, type(exc).__name__)
        except Exception:
            remaining = None
    msg = program_error_message(
        component,
        exc,
        classification=classification,
        healable=healable,
        suggested_actions=actions,
        budget_remaining=remaining,
    )
    # M12: selfheal_log 审计落盘（可 search_records 检索）
    try:
        if audit_dir is None:
            return msg
        dir_path = Path(audit_dir)
        dir_path.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "component": component,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:300],
            "healable": bool(healable) if healable is not None else None,
            "category": classification.category if classification else None,
            "suggested_actions": list(actions),
            "budget_remaining": remaining,
        }
        with (dir_path / "selfheal_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.warning("selfheal_log 落盘失败（fail-open）", exc_info=True)
    return msg
