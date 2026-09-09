"""R5/L2-3 identity Q&A filtering for long-term summary projections.

The canonical conversation/archive body remains untouched.  This module only decides
whether a message belongs to a short identity-Q&A episode so derived summaries can
collapse it to a neutral placeholder instead of preserving model/self-description
as durable task context.

An identity episode starts at a genuine human identity question and extends until the
next genuine human message.  Program-origin user messages, tool calls/results and the
assistant response inside that interval remain part of the same episode.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from llm_loop.core.injection_labels import detect_program_layer
from llm_loop.core.reference_injection import is_human_user_message

_IDENTITY_PLACEHOLDER = "[身份问答 x {count} 轮，已略——本会话主体任务见下]"

# Deliberately conservative.  The detector recognizes direct self/model identity
# questions, not arbitrary discussion *about* identity systems or quoted examples.
_ZH_IDENTITY_RE = re.compile(
    r"^\s*(?:(?:请问|想问(?:一下|下)?|告诉我|能否告诉我)[，,:：\s]*)?(?:"
    r"(?:你|您)(?:现在|当前|到底|究竟)?(?:是)?谁(?:[？?。！!\s]|$)|"
    r"(?:你|您)(?:现在|当前|到底|究竟)?(?:用的|使用的|运行的|底层(?:用的|是)?)?"
    r"(?:是)?(?:什么|哪个|哪一个)(?:大模型|模型|llm)(?:[？?。！!，,；;：:\s]|$)|"
    r"(?:你|您)(?:的)?(?:底层模型|模型身份)(?:是)?(?:什么|哪个|哪一个)?"
    r"(?:[？?。！!，,；;：:\s]|$)|"
    r"(?:介绍(?:一下|下)?(?:你自己|自己)|自我介绍)(?:[？?。！!，,；;：:\s]|$)|"
    r"(?:你|您)(?:是)?(?:由谁|谁)(?:开发|创建|训练|制作)(?:的)?"
    r"(?:[？?。！!，,；;：:\s]|$)|"
    r"(?:当前会话|这个会话)(?:现在)?(?:用的|使用的|运行的|是)?"
    r"(?:什么|哪个|哪一个)(?:大模型|模型)(?:[？?。！!，,；;：:\s]|$)|"
    r"(?:你|您)是\s*(?:gpt|qwen|glm|deepseek|minimax|claude|gemini|llama|mistral|kimi)"
    r"[\w.\- ]*(?:模型)?\s*[吗么？?]?\s*$"
    r")",
    re.IGNORECASE,
)
_EN_IDENTITY_RE = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"who\s+are\s+you|"
    r"what\s+(?:model|llm)\s+(?:are\s+you|are\s+you\s+running|is\s+this)|"
    r"which\s+(?:model|llm)\s+(?:are\s+you|are\s+you\s+running|is\s+this)|"
    r"introduce\s+yourself|"
    r"who\s+(?:made|created|developed|trained)\s+you"
    r")(?:[?.!,;:\s]|$)",
    re.IGNORECASE,
)

# If a direct identity question is bundled with an unrelated work instruction, keep the
# whole user turn as task context.  Identity filtering must never erase real work.


_ZH_CAPABILITY_RE = re.compile(
    r"^\s*(?:(?:请|请问)[，,:：\s]*)?(?:"
    r"(?:你|您)(?:能|会)(?:做|干)什么|"
    r"(?:你|您)(?:有|具备)(?:哪些|什么)(?:能力|功能)|"
    r"(?:你|您)有哪些(?:能力|功能)|"
    r"介绍(?:一下|下)?(?:你|您)的(?:能力|功能)|"
    r"我能(?:用|让)(?:你|您)(?:做|干)什么"
    r")(?:[？?。！!，,；;：:\s]|$)",
    re.IGNORECASE,
)
_EN_CAPABILITY_RE = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"what\s+can\s+you\s+do|"
    r"what\s+are\s+your\s+capabilities|"
    r"what\s+capabilities\s+do\s+you\s+have"
    r")(?:[?.!,;:\s]|$)",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"[？?!！。;；\n]+")
_IDENTITY_FOLLOWUP_RE = re.compile(
    r"^\s*(?:"
    r"(?:由谁|谁)(?:开发|创建|训练|制作)(?:[/、](?:开发|创建|训练|制作))*(?:的)?|"
    r"由(?:哪个公司|哪家公司)(?:开发|创建|训练|制作)(?:[/、](?:开发|创建|训练|制作))*(?:的)?|"
    r"(?:请)?(?:先)?(?:核验|确认)(?:当前会话)?(?:真实)?(?:模型)?身份.*(?:作答|回答)|"
    r"(?:禁止|不要)凭.*(?:训练先验|先验).*(?:自报|声明).*(?:身份|模型)|"
    r"who\s+(?:made|created|developed|trained)\s+you"
    r")\s*$",
    re.IGNORECASE,
)

_NON_IDENTITY_TASK_RE = re.compile(
    r"(?:顺便|同时|另外|然后|并且|再|还要|以及).{0,32}"
    r"(?:修复|修改|分析|实现|部署|审查|调试|写(?:代码|文件|文档)?|执行|运行|测试|"
    r"检查(?:代码|文件|项目)|生成(?:代码|文件|文档)|"
    r"fix|modify|analy[sz]e|implement|deploy|review|debug|write|run|test|inspect|generate)",
    re.IGNORECASE | re.DOTALL,
)


def _content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content", "") or "")
    return str(getattr(message, "content", "") or "")


_LEGACY_PROGRAM_USER_PREFIXES = (
    "[上下文注入·非新指令]",
    "[上下文注入]",
)


def _is_human_boundary(message: Any) -> bool:
    """Genuine human boundary, including compatibility with pre-R1 program-user history.

    Current R1 metadata is authoritative.  Only messages without an explicit origin layer
    fall back to visible legacy-wrapper detection; a real user is allowed to literally type
    strings such as ``[声明提醒]`` without being reclassified as program-origin.
    """
    if not is_human_user_message(message):
        return False
    metadata = (
        message.get("metadata") if isinstance(message, dict) else getattr(message, "metadata", {})
    ) or {}
    if metadata.get("origin_layer") == "user_instruction":
        return True
    text = _content(message).lstrip()
    if text.startswith(_LEGACY_PROGRAM_USER_PREFIXES):
        return False
    return detect_program_layer(text) is None


def render_identity_summary_placeholder(count: int) -> str:
    """Return the only durable summary representation allowed for identity Q&A."""
    return _IDENTITY_PLACEHOLDER.format(count=max(1, int(count)))


def _is_direct_identity_clause(value: str) -> bool:
    return bool(
        _ZH_IDENTITY_RE.search(value)
        or _EN_IDENTITY_RE.search(value)
        or _ZH_CAPABILITY_RE.search(value)
        or _EN_CAPABILITY_RE.search(value)
    )


def is_identity_question(text: str) -> bool:
    """Whether *text itself* is primarily a direct assistant/model identity question.

    The whole turn must be identity-only.  After the first direct identity clause, every
    remaining sentence must itself be another identity question or a narrow verification
    instruction about that identity.  This prevents mixed turns such as
    ``你现在是什么模型？上一轮我让你记了什么？`` from losing the real task.
    """
    value = " ".join(str(text or "").strip().split())
    if not value or len(value) > 320:
        return False
    if _NON_IDENTITY_TASK_RE.search(value):
        return False
    clauses = [c.strip(" \t，,：:") for c in _SENTENCE_SPLIT_RE.split(value) if c.strip()]
    if not clauses or not _is_direct_identity_clause(clauses[0]):
        return False
    return all(
        _is_direct_identity_clause(clause) or bool(_IDENTITY_FOLLOWUP_RE.search(clause))
        for clause in clauses[1:]
    )


def identity_episode_map(messages: Sequence[Any]) -> dict[int, int]:
    """Map each identity-episode message index to its identity-question start index."""
    out: dict[int, int] = {}
    active_start: int | None = None
    for idx, message in enumerate(messages):
        if _is_human_boundary(message):
            if is_identity_question(_content(message)):
                active_start = idx
                out[idx] = idx
            else:
                active_start = None
            continue
        if active_start is not None:
            out[idx] = active_start
    return out


def identity_episode_start(messages: Sequence[Any], index: int) -> int | None:
    """Return the current identity episode's start for one message, if any.

    The backward scan stops at the nearest genuine human turn, so program-user/tool
    traffic cannot reset the boundary.  This keeps the helper stateless and safe across
    compact/restart without adding another session state store.
    """
    if index < 0 or index >= len(messages):
        return None
    for cursor in range(index, -1, -1):
        message = messages[cursor]
        if _is_human_boundary(message):
            return cursor if is_identity_question(_content(message)) else None
    return None
