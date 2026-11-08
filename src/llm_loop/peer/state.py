"""PeerTask / PeerGrant 状态机（与 receipt.schema.json 的 state 枚举对齐）。

设计 §5.3：``submitted → admitted → queued → running → succeeded``，失败分支见下表。
刻意与 Human Turn Queue 同构以便复用 reaper 思路，但不混流（D8：身份与审计不同）。

监督通道（DESIGN-20261108 §2.1）：``submitted → awaiting_supervision`` 是"已收到、
尚未获准执行"的暂停态。它出现在准入之前，因此不消耗 grant 额度，也不占执行器并发
名额；确认后重新走 ``admitted``，拒绝/超时/取消都直接收尾。
"""
from __future__ import annotations

from datetime import datetime

from llm_loop.peer.errors import InvalidTaskTransitionError
from llm_loop.peer.models import GrantRecord, parse_ts

TASK_STATES: tuple[str, ...] = (
    "submitted",
    "awaiting_supervision",
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
    "submitted": frozenset(
        {"awaiting_supervision", "admitted", "denied", "cancelled", "failed"}
    ),
    "awaiting_supervision": frozenset({"admitted", "denied", "cancelled", "failed"}),
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


# 唯一允许"改写终局"的边：产物被篡改后 succeeded → failed（DESIGN T8）。
# 刻意只开这一条：其它终局态仍然不可改写，避免"事后改历史"变成常态。
_QUARANTINE: dict[str, frozenset[str]] = {"succeeded": frozenset({"failed"})}


def can_quarantine(src: str, dst: str) -> bool:
    return dst in _QUARANTINE.get(src, frozenset())


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
