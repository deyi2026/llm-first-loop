"""飞书桥续聊上下文连续性（CONT）.

续聊锚点读取（execution-cursor → checkpoint 三层降级）+ 续聊前现场完整性
预检（repair_status 如实外显）。只读、不改账本/游标/会话；不得修改用户
turn 的 provenance。

- ``ResumeAnchor``：锚点（来源 + 当前子项 + 下一步）。
- ``ResumeAnchorReader``：三层优先级读锚点（execution-cursor → checkpoint → none）。
- ``ResumeCoordinator``：组合锚点 + 现场预检，供 ``_try_handle_continue_command`` 决策。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_EXECUTION_CURSOR = "execution-cursor"
SOURCE_CHECKPOINT = "checkpoint"
SOURCE_NONE = "none"

REPAIR_REPAIRED = "repaired"
REPAIR_REPAIRABLE = "repairable"
REPAIR_FAILED = "repair_failed"
REPAIR_NO_EVENT_LOG = "no_event_log"


@dataclass(kw_only=True)
class ResumeAnchor:
    """续聊进度锚点（source 可审计，对齐 spec 6.2 / FTR-DFX-07）."""

    source: str  # "execution-cursor" | "checkpoint"
    current_sub_item: str = ""  # 当前进行到哪（cursor.current_sub_item / checkpoint.what）
    next_step: str = ""  # 下一步（cursor.next_step / checkpoint.next）


@dataclass(kw_only=True)
class ResumePrep:
    """续聊准备产物（锚点 + 来源 + 现场预检）."""

    anchor: ResumeAnchor | None
    anchor_source: str  # "execution-cursor" | "checkpoint" | "none"
    repair_status: str  # "repaired" | "repairable" | "repair_failed" | "no_event_log"


class ResumeAnchorReader:
    """三层优先级读取续聊锚点（ADR-5）；读取失败/漂移 fail-open 降级 none."""

    def read_anchor(self, session_id: str, audit_dir: str) -> ResumeAnchor | None:
        goal = self._active_goal(session_id, audit_dir)
        if not goal or not goal.get("id"):
            return None
        goal_id = str(goal["id"])
        # 1) execution-cursor 优先（若已落地；未落地则跳过，不依赖其存在）
        cursor_anchor = self._read_cursor(goal_id, session_id, audit_dir)
        if cursor_anchor is not None:
            return cursor_anchor
        # 2) checkpoint 兜底（当前已实现）
        checkpoints = goal.get("checkpoints") or []
        if checkpoints:
            cp = checkpoints[-1] or {}
            return ResumeAnchor(
                source=SOURCE_CHECKPOINT,
                current_sub_item=str(cp.get("what", "") or ""),
                next_step=str(cp.get("next", "") or ""),
            )
        return None

    @staticmethod
    def _active_goal(session_id: str, audit_dir: str) -> dict | None:
        from llm_loop.introspection.goal import GoalStore, GoalStoreCorruptionError

        try:
            return GoalStore(audit_dir).get(prefer_session_id=session_id)
        except GoalStoreCorruptionError as exc:
            logger.warning("续聊锚点读取：Goal 存储损坏，降级 none: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001 — 锚点读取失败 fail-open 不阻断续聊
            logger.warning("续聊锚点读取失败（fail-open，降级 none）: %s", exc)
            return None

    @staticmethod
    def _read_cursor(goal_id: str, session_id: str, audit_dir: str) -> ResumeAnchor | None:
        from llm_loop.introspection.task_store import TaskStore

        get_cursor = getattr(TaskStore, "get_cursor", None)
        if not callable(get_cursor):
            return None  # execution-cursor 底座未落地 → 回退 checkpoint
        try:
            cursor = get_cursor(TaskStore(audit_dir), goal_id, session_id)
        except Exception as exc:  # noqa: BLE001 — 游标读取失败降级
            logger.debug("execution-cursor 读取失败（降级 checkpoint）: %s", exc)
            return None
        if not cursor:
            return None
        return ResumeAnchor(
            source=SOURCE_EXECUTION_CURSOR,
            current_sub_item=str(getattr(cursor, "current_sub_item", "") or ""),
            next_step=str(getattr(cursor, "next_step", "") or ""),
        )


class ResumeCoordinator:
    """续聊入口一次性产出锚点 + 现场预检（只读，不改引擎对账行为）."""

    def __init__(self: ResumeCoordinator, reader: ResumeAnchorReader | None = None) -> None:
        self._reader = reader or ResumeAnchorReader()

    def prepare_resume(self, session_id: str, engine: Any) -> ResumePrep:
        audit_dir = self._audit_dir(engine)
        anchor = self._reader.read_anchor(session_id, audit_dir)
        anchor_source = anchor.source if anchor is not None else SOURCE_NONE
        repair_status = self._precheck_repair(session_id, engine)
        return ResumePrep(
            anchor=anchor,
            anchor_source=anchor_source,
            repair_status=repair_status,
        )

    @staticmethod
    def _audit_dir(engine: Any) -> str:
        settings = getattr(engine, "settings", None)
        ad = getattr(settings, "audit_dir", None)
        if ad is None:
            return "data/audit"
        return str(ad)

    @staticmethod
    def _precheck_repair(session_id: str, engine: Any) -> str:
        """只读现场完整性预检（ADR-6）：事件日志 vs 内存消息是否落后/可重放."""
        estore = getattr(engine, "_event_store", None)
        try:
            sess = engine.session.load(session_id)
        except Exception:  # noqa: BLE001 — 会话加载失败视为无现场
            sess = None
        if estore is None or not getattr(estore, "enabled", False) or not estore.exists(session_id):
            return REPAIR_NO_EVENT_LOG
        try:
            events = estore.read(session_id)
            el_count = sum(1 for e in events if getattr(e, "type", "") == "message.appended")
        except Exception:  # noqa: BLE001 — 事件读取失败无法判定
            return REPAIR_FAILED
        mem_count = len(getattr(sess, "messages", []) or [])
        if el_count <= mem_count:
            return REPAIR_REPAIRED  # 现场不落后，无需修复
        try:
            replayed = engine.session._load_from_event_log(session_id)  # noqa: SLF001
        except Exception:  # noqa: BLE001 — 重放异常
            replayed = None
        return REPAIR_REPAIRABLE if replayed is not None else REPAIR_FAILED
