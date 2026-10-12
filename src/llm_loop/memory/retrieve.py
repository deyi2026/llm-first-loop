"""Lightweight keyword extraction for explicit memory retrieval.

Memory is durable/on-demand state. This module deliberately does not construct
model-visible memory messages or choose which memories belong in the prompt.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on",
    "and", "or", "for", "with", "at", "by", "from", "as", "please", "请",
    "的", "了", "是", "在", "和", "与", "我", "你", "他", "它", "这个", "那个",
}


def extract_keywords(text: str, limit: int = 12) -> list[str]:
    """Extract bounded lexical terms without deciding memory relevance/applicability."""
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(text.lower()):
        if token in _STOP_WORDS or len(token) < 2:
            continue
        if token.isascii():
            tokens.append(token)
    for block in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(block) < 2:
            continue
        for i in range(len(block) - 1):
            bigram = block[i : i + 2]
            if bigram not in _STOP_WORDS:
                tokens.append(bigram)
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return seen[:limit]
