"""记忆检索（design.md §2.1.3.6 机制五 / FR-MEM-02）.

边界说明（M11）: 本模块负责"记忆消息构造"（关键词+语义融合入口+source=memory 消息组装）;
语义检索算法本体在 memory/retriever.py（SemanticRetriever，同时服务 RecordSearcher 统一检索），单向依赖本模块 → retriever。

理解阶段用当前消息文本提取关键词 → MemoryStore.search 检索 →
命中条目以 source=memory 前置消息注入上下文。
"""

from __future__ import annotations

import re
from typing import Any

from llm_loop.core.reference_injection import (
    reference_metadata,
    render_reference_frame,
)
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
    session_id: str = "",
    seen_reference_keys: set[str] | frozenset[str] | None = None,
    emit_seen_refs: bool = False,
    suppressed_out: list[dict[str, str]] | None = None,
) -> list[Message]:
    """Retrieve relevant memories and project them as an R3 reference catalog.

    Automatic frames are deterministic and at most two lines: one neutral fact
    plus one stable ref. A seen stable ref is omitted by default; callers may
    request a one-line ref on an explicit task-switch turn. Original memory
    content remains available through explicit retrieval tools.
    """
    keywords = extract_keywords(text)
    keyword_hits = store.search(keywords, top_k=top_k, session_id=session_id) if keywords else []

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
        except Exception:  # noqa: BLE001 — semantic failure degrades to keyword results
            entries = keyword_hits

    if not entries:
        return []
    entries = [
        e
        for e in entries
        if getattr(e, "scope", "global") != "session"
        or (session_id and e.source_session_id == session_id)
    ]
    entries = [
        e for e in entries if getattr(e, "inject_policy", "auto") != "recall_only"
    ]
    if not entries:
        return []

    final = entries[:top_k]
    seen = seen_reference_keys or set()
    frames = []
    emitted_entries = []
    for e in final:
        ref = f"memory:{e.id}"
        frame = render_reference_frame(
            tag=f"memory:{getattr(e, 'type', 'fact')}",
            fact=str(e.content or ""),
            ref=ref,
            source="memory",
            seen_keys=seen,
            emit_seen_ref=emit_seen_refs,
        )
        if frame.duplicate and not frame.content:
            if suppressed_out is not None:
                suppressed_out.append({"source": "memory", "key": frame.key, "ref": frame.ref})
            continue
        frames.append(frame)
        emitted_entries.append(e)

    if not frames:
        return []
    try:
        store.mark_injected(emitted_entries)
    except Exception:  # noqa: BLE001 — usage counting is non-critical
        pass

    md = {
        "reference_keys": [f.key for f in frames],
        "reference_full_keys": [f.key for f in frames if f.full],
        "reference_source": "memory",
        "reference_frame_count": len(frames),
    }
    if len(frames) == 1:
        md.update(reference_metadata(frames[0], source="memory"))
    return [
        Message(
            role="system",
            content="\n\n".join(f.content for f in frames if f.content),
            source=MessageSource.MEMORY,
            metadata=md,
        )
    ]
