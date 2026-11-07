"""PeerTask / PeerGrant 状态机（与 receipt.schema.json 的 state 枚举对齐）。

设计 §5.3：``submitted → admitted → queued → running → succeeded``，失败分支见下表。
刻意与 Human Turn Queue 同构以便复用 reaper 思路，但不混流（D8：身份与审计不同）。
"""
from __future__ import annotations

from datetime import datetime

from llm_loop.peer.errors import InvalidTaskTransitionError
from llm_loop.peer.models import GrantRecord, parse_ts

TASK_STATES: tuple[str, ...] = (
    "submitted",
    "admitted",
    "queued",
    "running",
    "succeeded",
    "failed",
    "blocked",
    "denied",
    "cancelled",
    "unknown_outcome",
)

TERMINAL_STATES: frozenset[str] = frozenset(
    {"succeeded", "failed", "denied", "cancelled"}
)

# 允许的执行器/控制端迁移。denied 只能由准入（副作用前）产生，故任何非终局态都可被拒。
_TRANSITIONS: dict[str, frozenset[str]] = {
    "submitted": frozenset({"admitted", "denied", "cancelled", "failed"}),
    "admitted": frozenset({"queued", "denied", "cancelled", "failed"}),
    "queued": frozenset({"running", "denied", "cancelled", "failed"}),
    "running": frozenset({"succeeded", "failed", "blocked", "unknown_outcome", "cancelled"}),
    "blocked": frozenset({"running", "failed", "cancelled"}),
    "unknown_outcome": frozenset({"succeeded", "failed", "cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "denied": frozenset(),
    "cancelled": frozenset(),
}


def can_transition(src: str, dst: str) -> bool:
    if src not in _TRANSITIONS:
        raise InvalidTaskTransitionError(f"unknown source state: {src}")
    return dst in _TRANSITIONS[src]


def require_transition(src: str, dst: str) -> None:
    if not can_transition(src, dst):
        raise InvalidTaskTransitionError(f"illegal peer task transition: {src} -> {dst}")


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def grant_is_expired(grant: GrantRecord, now: datetime) -> bool:
    return parse_ts(grant.expires_at) <= now


def grant_is_exhausted(grant: GrantRecord) -> bool:
    return grant.tasks_used >= grant.max_tasks_total


def derive_grant_state(grant: GrantRecord, now: datetime) -> str:
    """运行期有效状态：revoked > expired > exhausted > active。"""
    if grant.state == "revoked" or grant.revoked_at:
        return "revoked"
    if grant_is_expired(grant, now):
        return "expired"
    if grant_is_exhausted(grant):
        return "exhausted"
    return "active"
