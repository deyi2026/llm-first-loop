"""M2：持久边界、按位置区分的持久失败与本地恢复（`T-M2-4`）。

对应需求：`RTM-REC-01/02/05/06/07/08/10/11/13/14`、`RTM-TOL-12`。

不变量：

- **持久边界**仅含：已提交输入 / 任务链接 / 工具事实 / 必要恢复状态；
  临时字幕、全部音频分片、未使用预览 **不进任务 Journal**（`RTM-REC-01`）；
- **持久失败按位置区分**（`RTM-REC-02`）：派发前必要记录失败 → 不确认已派发；
  派发后结果保存失败 → 如实保留已发生事实并标 `outcome_unknown`；可选诊断失败 → 不改已确认状态；
- 恢复**不等于恰好一次**；本地栈**无远端恢复令牌** → **本地会话重建**（`RTM-REC-05/06/07/08`）；
- 「先拉真实状态」与「离线草稿明确提交」，**不自动按当前页面执行过时语音**（`RTM-REC-10/11`）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PersistedFactKind(StrEnum):
    """持久边界允许的事实类型。"""

    COMMITTED_INPUT = "committed_input"
    TASK_LINK = "task_link"
    TOOL_FACT = "tool_fact"
    RECOVERY_STATE = "recovery_state"


EXCLUDED_FROM_JOURNAL: frozenset[str] = frozenset(
    {"interim_caption", "audio_chunk", "audio_frame", "unused_preview"}
)


class PersistenceFailurePosition(StrEnum):
    """持久失败位置（按位置区分处理，`RTM-REC-02`）。"""

    BEFORE_DISPATCH = "before_dispatch"
    AFTER_DISPATCH = "after_dispatch"
    OPTIONAL_DIAGNOSTIC = "optional_diagnostic"


class PersistenceWriteError(RuntimeError):
    """持久失败：调用方须按 `position` 区别处理，**不得**一律禁止确认。"""

    def __init__(self, position: PersistenceFailurePosition, detail: str = "") -> None:
        super().__init__(f"persistence failed at {position.value}: {detail}")
        self.position = position


def persistence_failure_disposition(position: PersistenceFailurePosition) -> str:
    """按位置给出处理口径（**已发生的事实必须如实保留**）。"""
    if position is PersistenceFailurePosition.BEFORE_DISPATCH:
        return "do_not_confirm_dispatched"
    if position is PersistenceFailurePosition.AFTER_DISPATCH:
        return "keep_facts_and_mark_outcome_unknown"
    return "ignore_and_preserve_confirmed_state"


@dataclass(frozen=True)
class PersistedFact:
    kind: PersistedFactKind
    session_id: str
    key: str
    payload: dict

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PersistedFactKind):
            raise TypeError("kind must be PersistedFactKind")
        if not self.session_id or not self.key:
            raise ValueError("session_id and key are required")


class RealtimeFactStore:
    """内存事实底座（可替换为持久实现）；**只**承载持久边界事实。"""

    def __init__(self) -> None:
        self._facts: dict[str, list[PersistedFact]] = {}

    def persist(self, fact: PersistedFact) -> None:
        if fact.kind.value in EXCLUDED_FROM_JOURNAL or fact.key in EXCLUDED_FROM_JOURNAL:
            raise ValueError(
                "interim captions / audio chunks / unused previews must not enter the task journal"
            )
        self._facts.setdefault(fact.session_id, []).append(fact)

    def facts(self, session_id: str, *, kind: PersistedFactKind | None = None) -> tuple[PersistedFact, ...]:
        items = self._facts.get(session_id, [])
        if kind is None:
            return tuple(items)
        return tuple(f for f in items if f.kind is kind)

    def recovery_bundle(self, session_id: str) -> dict[str, tuple[PersistedFact, ...]]:
        return {
            kind.value: self.facts(session_id, kind=kind)
            for kind in PersistedFactKind
        }


@dataclass(frozen=True)
class RebuildPlan:
    """本地会话重建计划（**不承诺恰好一次**）。"""

    recovery_mode: str
    committed_inputs: tuple[str, ...]
    task_links: tuple[str, ...]
    tool_facts: tuple[str, ...]
    exactness: str = "at_least_once_no_exactly_once_guarantee"


class LocalSessionRebuilder:
    """本地恢复：从已提交输入、任务链接与工具事实**本地重建**（无远端令牌）。"""

    def rebuild(self, bundle: dict[str, tuple[PersistedFact, ...]]) -> RebuildPlan:
        committed = tuple(f.payload.get("text", "") for f in bundle.get(PersistedFactKind.COMMITTED_INPUT.value, ()))
        links = tuple(f.key for f in bundle.get(PersistedFactKind.TASK_LINK.value, ()))
        tools = tuple(f.key for f in bundle.get(PersistedFactKind.TOOL_FACT.value, ()))
        return RebuildPlan(
            recovery_mode="local_rebuild_only",
            committed_inputs=committed,
            task_links=links,
            tool_facts=tools,
        )


@dataclass(frozen=True)
class StaleDraftDecision:
    """离线草稿：**不得**自动按当前页面执行过时语音（`RTM-REC-10/11`）。"""

    requires_explicit_commit: bool
    reason: str


def decide_stale_draft(*, captured_page_epoch: int, current_page_epoch: int) -> StaleDraftDecision:
    if captured_page_epoch == current_page_epoch:
        return StaleDraftDecision(requires_explicit_commit=False, reason="page_unchanged")
    return StaleDraftDecision(
        requires_explicit_commit=True,
        reason="page_changed_since_capture_do_not_auto_execute",
    )
