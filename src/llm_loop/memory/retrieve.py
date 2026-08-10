"""记忆检索（design.md §2.1.3.6 机制五 / FR-MEM-02）.

边界说明（M11）: 本模块负责"记忆消息构造"（关键词+语义融合入口+source=memory 消息组装）;
语义检索算法本体在 memory/retriever.py（SemanticRetriever，同时服务 RecordSearcher 统一检索），单向依赖本模块 → retriever。

理解阶段用当前消息文本提取关键词 → MemoryStore.search 检索 →
命中条目以 source=memory 前置消息注入上下文。
"""

from __future__ import annotations

import re
from typing import Any

from llm_loop.core.message import Message, MessageSource
from llm_loop.memory.store import MemoryStore

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_STOP_WORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "to",
    "of",
    "in",
    "on",
    "and",
    "or",
    "for",
    "with",
    "at",
    "by",
    "from",
    "as",
    "please",
    "请",
    "的",
    "了",
    "是",
    "在",
    "和",
    "与",
    "我",
    "你",
    "他",
    "它",
    "这个",
    "那个",
}


def extract_keywords(text: str, limit: int = 12) -> list[str]:
    """从消息文本提取检索关键词（P0 简单切分）.

    英文按单词；中文按相邻两字 2-gram（中文无空格，整句连写时按字切分）。
    """
    tokens: list[str] = []
    # 英文单词
    for t in _TOKEN_RE.findall(text.lower()):
        if t in _STOP_WORDS or len(t) < 2:
            continue
        if t.isascii():
            tokens.append(t)
    # 中文 2-gram（仅对非 ascii 的连续中文块）
    for block in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(block) < 2:
            continue
        for i in range(len(block) - 1):
            bigram = block[i : i + 2]
            if bigram not in _STOP_WORDS:
                tokens.append(bigram)
    seen: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
    return seen[:limit]


def build_memory_messages(
    text: str,
    store: MemoryStore,
    top_k: int = 5,
    *,
    semantic_retriever: Any | None = None,
) -> list[Message]:
    """检索相关记忆并构造 source=memory 的前置消息（FR-MEM-02 / P1 语义检索）.

    语义检索可用时先语义召回（mode 标注）；否则关键词兜底。
    无命中 → 空列表（不伪造记忆）；检索异常由调用方捕获标注。
    """
    keywords = extract_keywords(text)
    keyword_hits = store.search(keywords, top_k=top_k) if keywords else []

    # P1 语义检索（预算内，失败/不可用如实降级为关键词）
    note = ""
    entries = keyword_hits
    if semantic_retriever is not None and semantic_retriever.semantic_available():
        try:
            result = semantic_retriever.search(
                text,
                top_k=top_k,
                scope="memory",
                memory=store,
                keyword_results=[
                    {"kind": "memory", "id": e.id, "content": e.content, "key": f"memory:{e.id}"}
                    for e in keyword_hits
                ],
            )
            entries = []
            for h in result.entries:
                e = store._by_id(h.get("id", ""))  # noqa: SLF001
                if e is not None:
                    entries.append(e)
            if result.mode == "keyword" and result.note:
                note = result.note
            elif result.mode != "keyword":
                note = f"语义检索生效（mode={result.mode}）"
        except Exception as exc:  # noqa: BLE001 — 语义失败不阻塞，如实降级
            note = f"语义检索不可用：{exc}，已降级为关键词检索"
            entries = keyword_hits

    if not entries:
        return []
    lines = [f"- [{e.type}] {e.content}" for e in entries[:top_k]]
    if note:
        lines.insert(0, f"[记忆检索] {note}")
    return [
        Message(
            role="system",
            content="[相关记忆]\n" + "\n".join(lines),
            source=MessageSource.MEMORY,
        )
    ]
