"""INJECTION-GOVERNANCE R4: bounded program-recovery boundary.

Program recovery is executable program control, but it is not user intent and must
never become durable conversational task history.  The only supported recovery
action is represented by an enum and rendered from a fixed template so callers
cannot smuggle open-ended work into the recovery block.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from llm_loop.core.injection_labels import (
    InjectionLayer,
    detect_program_layer,
    origin_metadata,
    render_program_appendix,
)
from llm_loop.core.message import Message, MessageSource


PROGRAM_RECOVERY_SLOT = "program_recovery"


class ProgramRecoveryAction(StrEnum):
    """Closed set of executable recovery actions."""

    RETRY_CURRENT_REQUEST_ONCE = "retry_current_request_once"


_ACTION_TEXT: dict[ProgramRecoveryAction, str] = {
    ProgramRecoveryAction.RETRY_CURRENT_REQUEST_ONCE: (
        "在已重建上下文中重试本轮请求一次"
    ),
}


def render_program_recovery(
    action: ProgramRecoveryAction = ProgramRecoveryAction.RETRY_CURRENT_REQUEST_ONCE,
) -> str:
    """Render one closed-scope recovery block from a registered action.

    The boundary line explicitly defines PROGRAM_RECOVERY as the sole executable
    exception inside program-origin material.  It does not create a new user task;
    after the one recovery action the current human text remains authoritative.
    """
    resolved = ProgramRecoveryAction(action)
    body = (
        f"恢复动作={_ACTION_TEXT[resolved]}。\n"
        "边界=本块是程序附录中的唯一可执行恢复例外，非用户新指令；"
        "恢复完成后，任务边界仍以当前用户原话为准。"
    )
    return render_program_appendix(body, InjectionLayer.PROGRAM_RECOVERY)


def make_program_recovery_message(
    *,
    turn_ref: Any,
    action: ProgramRecoveryAction = ProgramRecoveryAction.RETRY_CURRENT_REQUEST_ONCE,
) -> Message:
    """Create one ephemeral recovery slot message; callers must not persist it as history."""
    resolved = ProgramRecoveryAction(action)
    return Message(
        role="system",
        content=render_program_recovery(resolved),
        source=MessageSource.SYSTEM,
        metadata=origin_metadata(
            InjectionLayer.PROGRAM_RECOVERY,
            injection_kind="program_recovery",
            recovery_ephemeral=True,
            recovery_action=str(resolved),
            recovery_turn_ref=turn_ref,
        ),
    )


def is_program_recovery_message(message: Message) -> bool:
    """Recognize current or legacy recovery history that must not remain executable."""
    meta = message.metadata or {}
    if meta.get("injection_kind") == "program_recovery":
        return True
    # Legacy fallback is allowed only for non-human sources.  A real user is free to
    # type strings such as "[程序续跑]" without having their instruction filtered.
    return (
        message.source is not MessageSource.USER
        and detect_program_layer(message.content) is InjectionLayer.PROGRAM_RECOVERY
    )
