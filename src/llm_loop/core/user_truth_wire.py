"""R6 user-truth wire projection.

Storage/event history stays untouched.  This module only projects the initial
human-ingress request so program-origin user frames precede the exact human text
inside one provider-legal user envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from llm_loop.core.injection_labels import InjectionLayer, detect_program_layer

# Fixed and provider-neutral.  The exact user text starts immediately after this
# boundary and is never rewritten/prefixed/suffixed by R6.
USER_TRUTH_SEPARATOR = "\n\n--- [指令·用户·原文] ---\n"

# ERC Recovery Manifest predates R1 labels but is program-origin by construction.
_LEGACY_PROGRAM_CONTEXT_PREFIXES = (
    "[上下文注入·",
)


@dataclass(frozen=True)
class UserTruthWireProjection:
    messages: list[dict]
    changed: bool = False
    envelope_index: int = -1
    absorbed_indices: tuple[int, ...] = ()
    violation: str = ""


def _attr(message: Any, name: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(name, default)
    return getattr(message, name, default)


def _metadata(message: Any) -> dict[str, Any]:
    md = _attr(message, "metadata", {})
    return md if isinstance(md, dict) else {}


def _is_human_user(message: Any) -> bool:
    if _attr(message, "role", "") != "user":
        return False
    md = _metadata(message)
    if md.get("program_origin") is True:
        return False
    layer = str(md.get("origin_layer") or "")
    if layer and layer != InjectionLayer.USER_INSTRUCTION.value:
        return False
    content = str(_attr(message, "content", "") or "")
    if is_program_user_content(content):
        return False
    return True


def is_program_user_content(content: str) -> bool:
    """Recognize provider-view user content that is program-origin.

    R1-labeled appendices are authoritative.  One legacy context family is kept
    here because it is generated directly at build time and predates R1 labels.
    """
    text = str(content or "").lstrip()
    if not text:
        return False
    if detect_program_layer(text) not in (None, InjectionLayer.USER_INSTRUCTION):
        return True
    return text.startswith(_LEGACY_PROGRAM_CONTEXT_PREFIXES)


def current_ingress_user_truth(
    session_messages: Iterable[Any], turn_ref: int | None
) -> str | None:
    """Return exact current human text only for the initial LLM round of a run.

    Program frames may already follow the human message.  Once an assistant/tool
    result (or another genuine human message) exists after ``turn_ref`` we are in
    a tool-followup/next-turn state and must not move/replay the original user.
    """
    if turn_ref is None:
        return None
    messages = list(session_messages)
    if turn_ref < 0 or turn_ref >= len(messages):
        return None
    current = messages[turn_ref]
    if not _is_human_user(current):
        return None
    for message in messages[turn_ref + 1 :]:
        role = str(_attr(message, "role", "") or "")
        if role in ("assistant", "tool"):
            return None
        if role == "user" and _is_human_user(message):
            return None
    return str(_attr(current, "content", "") or "")


def project_user_truth_tail(
    messages: list[dict], user_truth: str
) -> UserTruthWireProjection:
    """Move contiguous program-user tail frames before exact current user truth.

    Only the provider view changes.  No-program requests are returned by identity
    (byte-identical fast path).  Unknown trailing user content is refused rather
    than guessed to be program-origin.
    """
    truth = str(user_truth)
    current_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "user" and str(m.get("content") or "") == truth:
            current_idx = i
            break
    if current_idx < 0:
        return UserTruthWireProjection(messages=messages, violation="user_truth_not_found")

    # Initial human-ingress projection may only have program-user frames after the
    # current truth.  Anything else is a structural ambiguity and is not swallowed.
    post_program: list[tuple[int, str]] = []
    for i in range(current_idx + 1, len(messages)):
        m = messages[i]
        if m.get("role") != "user":
            return UserTruthWireProjection(messages=messages, violation="trailing_non_user")
        content = m.get("content")
        if not isinstance(content, str) or not is_program_user_content(content):
            return UserTruthWireProjection(
                messages=messages, violation="trailing_non_program_user"
            )
        post_program.append((i, content))

    # Also collapse immediately preceding program-user frames.  They are commonly
    # persisted R3 appendices from the same ingress turn and otherwise leave a
    # consecutive-user run in front of the final envelope.
    pre_program_rev: list[tuple[int, str]] = []
    i = current_idx - 1
    while i >= 0:
        m = messages[i]
        content = m.get("content")
        if (
            m.get("role") == "user"
            and isinstance(content, str)
            and is_program_user_content(content)
        ):
            pre_program_rev.append((i, content))
            i -= 1
            continue
        break
    pre_program = list(reversed(pre_program_rev))

    programs = pre_program + post_program
    if not programs:
        return UserTruthWireProjection(messages=messages)

    start = pre_program[0][0] if pre_program else current_idx
    program_text = "\n\n".join(content for _, content in programs)
    envelope = {"role": "user", "content": program_text + USER_TRUTH_SEPARATOR + truth}
    projected = list(messages[:start]) + [envelope]
    return UserTruthWireProjection(
        messages=projected,
        changed=True,
        envelope_index=start,
        absorbed_indices=tuple(idx for idx, _ in programs),
    )
