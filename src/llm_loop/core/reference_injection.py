"""Reference injection policy for INJECTION-GOVERNANCE R3/L2-2.

The module owns three invariants for automatic reference material:
1. auto catalogs are allowed only in the first K human turns or on an explicit
   task-switch signal;
2. each reference frame is at most two lines (one neutral fact + one ref);
3. session-scoped dedup is rebuilt from persisted message metadata, so it
   survives compact/restart without adding a second Session state store.

K=3 is a candidate default carried from R0; R7/L3 A/B may calibrate it later.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from llm_loop.core.injection_labels import (
    InjectionLayer,
    detect_program_layer,
    reference_has_imperative,
)

DEFAULT_REFERENCE_AUTO_TURNS = 3
MAX_REFERENCE_FACT_CHARS = 180

_TASK_SWITCH_RE = re.compile(
    r"^\s*(?:"
    r"新任务(?:[：:]|\s|$)|新的任务(?:[：:]|\s|$)|"
    r"换个话题|换一个话题|另一个问题|另外一个问题|"
    r"接下来换(?:个|一个)?(?:任务|话题|问题)|"
    r"换到(?:另一个|新的)(?:任务|话题|问题)|"
    r"new\s+task|switch\s+(?:topic|task)|another\s+(?:question|task)"
    r")",
    re.IGNORECASE,
)
_REF_TOKEN_RE = re.compile(r"\bref=([^\s；;,，。)\]}>]+)", re.IGNORECASE)


@dataclass(frozen=True)
class ReferenceAutoDecision:
    human_turn_no: int
    task_switch: bool
    allow_catalog: bool


@dataclass(frozen=True)
class ReferenceFrame:
    key: str
    content: str
    ref: str
    full: bool
    duplicate: bool


def _message_attr(message: Any, name: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(name, default)
    return getattr(message, name, default)


def _message_metadata(message: Any) -> dict[str, Any]:
    md = _message_attr(message, "metadata", {})
    return md if isinstance(md, dict) else {}


def is_human_user_message(message: Any) -> bool:
    """Whether a message is genuine user input rather than a program-user block."""
    if _message_attr(message, "role", "") != "user":
        return False
    md = _message_metadata(message)
    if md.get("program_origin") is True:
        return False
    # R1 canonical human marker is authoritative when present.
    if md.get("origin_layer") and md.get("origin_layer") != "user_instruction":
        return False
    return bool(str(_message_attr(message, "content", "") or "").strip())


def _human_user_texts(messages: Iterable[Any]) -> list[str]:
    return [
        str(_message_attr(m, "content", "") or "")
        for m in messages
        if is_human_user_message(m)
    ]


def detect_task_switch(previous_user_text: str, current_user_text: str) -> bool:
    """Conservative deterministic switch signal.

    R3 intentionally avoids semantic/LLM classification. Only explicit transition
    wording re-opens automatic reference catalogs after the front-K window.
    """
    if not str(previous_user_text or "").strip():
        return False
    return bool(_TASK_SWITCH_RE.search(str(current_user_text or "")))


def reference_auto_decision(
    messages: Iterable[Any], *, auto_turns: int = DEFAULT_REFERENCE_AUTO_TURNS
) -> ReferenceAutoDecision:
    texts = _human_user_texts(messages)
    turn_no = len(texts)
    previous = texts[-2] if len(texts) >= 2 else ""
    current = texts[-1] if texts else ""
    switched = detect_task_switch(previous, current)
    k = max(0, int(auto_turns))
    return ReferenceAutoDecision(
        human_turn_no=turn_no,
        task_switch=switched,
        allow_catalog=bool(turn_no and (turn_no <= k or switched)),
    )


def normalize_reference_content(text: str) -> str:
    return " ".join(str(text or "").split()).casefold()


def reference_key(source: str, *, ref: str = "", content: str = "") -> str:
    """Stable ref wins; normalized content hash is the fallback identity."""
    stable = str(ref or "").strip()
    if stable:
        return f"ref:{stable.casefold()}"
    normalized = normalize_reference_content(content)
    digest = hashlib.sha256(normalized.encode("utf-8", "replace")).hexdigest()[:24]
    return f"hash:{str(source or 'reference').casefold()}:{digest}"


def seen_injection_set(messages: Iterable[Any]) -> set[str]:
    """Rebuild the session-scoped seen set from durable *program* reference evidence.

    Canonical R3 metadata is authoritative. Visible ``ref=...`` parsing exists only
    for legacy program/reference messages; genuine user text must never be allowed
    to poison the dedup set merely by mentioning a reference token.
    """
    seen: set[str] = set()
    for message in messages:
        md = _message_metadata(message)
        content = str(_message_attr(message, "content", "") or "")
        layer = str(md.get("origin_layer") or "")
        canonical_user = layer == InjectionLayer.USER_INSTRUCTION.value and md.get("program_origin") is not True
        program_reference = (
            md.get("program_origin") is True
            or layer == InjectionLayer.REFERENCE.value
            or detect_program_layer(content) == InjectionLayer.REFERENCE
        )
        if canonical_user:
            continue
        if program_reference:
            one = md.get("reference_key")
            if isinstance(one, str) and one:
                seen.add(one)
            many = md.get("reference_keys")
            if isinstance(many, (list, tuple, set)):
                seen.update(str(x) for x in many if str(x))
            for match in _REF_TOKEN_RE.finditer(content):
                seen.add(reference_key("legacy", ref=match.group(1)))
    return seen


def _one_sentence_fact(text: str) -> str:
    raw = " ".join(str(text or "").split())
    if not raw:
        return "历史资料条目"
    if reference_has_imperative(raw):
        return "历史资料含动作性或指令性表述，正文未自动内联"
    # One deterministic sentence, bounded. This is a summary projection, not a
    # half-block truncation: the original remains retrievable by ref.
    parts = re.split(r"(?<=[。！？!?])\s*", raw, maxsplit=1)
    fact = (parts[0] if parts else raw).strip()
    if len(fact) > MAX_REFERENCE_FACT_CHARS:
        fact = fact[: MAX_REFERENCE_FACT_CHARS - 1].rstrip() + "…"
    return fact


def render_reference_frame(
    *,
    tag: str,
    fact: str,
    ref: str = "",
    source: str,
    seen_keys: set[str] | frozenset[str] | None = None,
    emit_seen_ref: bool = False,
) -> ReferenceFrame:
    """Render one automatic reference frame under the <=2-line invariant."""
    key = reference_key(source, ref=ref, content=fact)
    display_ref = str(ref or "").strip() or key
    seen = seen_keys or set()
    if key in seen:
        return ReferenceFrame(
            key=key,
            content=f"ref={display_ref}" if emit_seen_ref else "",
            ref=display_ref,
            full=False,
            duplicate=True,
        )
    return ReferenceFrame(
        key=key,
        content=f"[{str(tag or source)}] {_one_sentence_fact(fact)}\nref={display_ref}",
        ref=display_ref,
        full=True,
        duplicate=False,
    )


def reference_metadata(frame: ReferenceFrame, *, source: str) -> dict[str, Any]:
    return {
        "reference_key": frame.key,
        "reference_ref": frame.ref,
        "reference_source": str(source),
        "reference_full": bool(frame.full),
        "reference_duplicate": bool(frame.duplicate),
    }
