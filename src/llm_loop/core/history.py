"""上下文构造与压缩另存（design.md §2.2.2.3 / T22 另存提取替代截断）.

- 保序提交（FR-MSG-03）
- **T22: 截断不是目的**——上下文超长时，将被丢弃的旧消息先"另存提取重要信息"
  （原文完整另存 + 关键事实/路径索引）到 ArchiveStore，再注入精简内容 +
  `[上下文压缩]` 标注（含"可查 search_archive"指引），信息零丢失。
- 记忆注入（source=memory 前置消息）
"""

from __future__ import annotations

from collections.abc import Callable

from typing import Any

from llm_loop.core.message import Message, MessageSource


def _top_keywords(messages: list["Message"], top: int = 5) -> list[str]:
    """从消息内容抽取高频词作为检索建议词（极简词频，fail-open 由调用方包裹）."""
    import re
    from collections import Counter

    stop = {
        "的", "了", "是", "在", "我", "你", "他", "她", "它", "这", "那", "个", "与", "和",
        "及", "对", "为", "从", "到", "把", "被", "也", "都", "就", "而", "但", "并", "或",
        "the", "a", "an", "is", "are", "was", "to", "of", "for", "and", "or", "in", "on",
        "with", "as", "at", "by", "from", "that", "this", "it", "we", "you", "i",
    }
    counter: Counter = Counter()
    for m in messages:
        if not m.content:
            continue
        for tok in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z][A-Za-z0-9_]{2,}", m.content):
            t = tok.lower()
            if t not in stop and len(t) >= 2:
                counter[t] += 1
    return [w for w, _ in counter.most_common(top)]


def _archive_index_dir(messages: list["Message"]) -> str:
    """生成压缩档案索引目录（数行，供 AI 主动检索；原文已另存至档案）."""
    from collections import Counter

    roles = Counter(m.role for m in messages if m.content)
    tools = Counter(m.tool_name for m in messages if m.tool_name)
    n = len(messages)
    chars = sum(len(m.content) for m in messages)
    lines = [
        f"[压缩档案目录] 本次归档 {n} 条消息（约 {chars} 字符），原文已完整另存，"
        "可用 search_archive 按关键词检索："
    ]
    if roles:
        lines.append("- 消息构成: " + ", ".join(f"{r}×{c}" for r, c in roles.most_common()))
    if tools:
        lines.append("- 工具结果: " + ", ".join(f"{t}×{c}" for t, c in tools.most_common(6)))
    words = _top_keywords(messages)
    if words:
        lines.append("- 建议检索词: " + ", ".join(words))
    return "\n".join(lines)



# archive sink: (session_id, message) -> None（由调用方装配 ArchiveStore）
ArchiveSink = Callable[[str, Message], None]


def build_history_messages(
    session_messages: list[Message],
    system_prompt: str,
    max_chars: int = 1000000,
    *,
    session_id: str = "",
    archive_sink: ArchiveSink | None = None,
    summarizer: Any | None = None,  # EVO-9794797e: 主动压缩摘要器（可 None 走纯另存）
) -> list[dict]:
    """组装提交 LLM 的消息序列（保序 + 超长另存压缩 + 如实标注）.

    Args:
        session_messages: 会话消息序列（保序）.
        system_prompt: 系统提示词.
        max_chars: 上下文注入字符预算.
        session_id: 当前会话（另存归档用）.
        archive_sink: 压缩另存回调（将被丢弃的消息逐条另存，信息零丢失）.

    Returns:
        LLM 协议消息列表（dict）。压缩发生时消息序列含 `[上下文压缩]` 标注。
    """
    out: list[dict] = []
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})

    total_chars = sum(len(m.content) for m in session_messages)
    if total_chars <= max_chars:
        for m in session_messages:
            out.append(m.to_llm_dict())
        return out

    # ── 超长: 从最新往回保留，最旧的先"另存提取"再精简注入（不静默丢弃）──
    # ── M40 修复（tool_calls 配对原子性）: assistant(tool_calls) 与其紧跟的 tool 响应
    #    组成"配对组"整体保留/归档/精简——否则 LLM 协议报
    #    "assistant with tool_calls must be followed by tool messages"（HTTP 400）──
    atomic_groups: list[list[Message]] = []
    i = 0
    n = len(session_messages)
    while i < n:
        m = session_messages[i]
        if m.role == "assistant" and m.tool_calls:
            # 配对组: assistant(tool_calls) + 其后连续的 tool 响应（保持协议配对原子性）
            group = [m]
            j = i + 1
            while j < n and session_messages[j].role == "tool":
                group.append(session_messages[j])
                j += 1
            atomic_groups.append(group)
            i = j
        else:
            atomic_groups.append([m])
            i += 1

    kept_groups: list[list[Message]] = []
    archived: list[Message] = []
    budget = max_chars
    for group in reversed(atomic_groups):
        group_len = sum(len(mm.content) for mm in group)
        if budget - group_len < 0 and kept_groups:
            archived.extend(group)  # 整组归档（配对原子性：不拆散）
            continue
        if group_len > budget and not kept_groups:
            # 最新组单条/整组超限: 另存全文 + 精简注入（组内字段保留，仅 content 截断）
            archived.extend(group)
            trimmed_group: list[Message] = []
            for mm in group:
                trimmed = (
                    mm.content[: max(budget - 100, 100)]
                    + "\n…[本消息已压缩，完整内容已另存，可用 search_archive 检索]…"
                )
                trimmed_group.append(
                    Message(
                        role=mm.role,
                        content=trimmed,
                        source=mm.source,
                        tool_call_id=mm.tool_call_id,
                        status=mm.status,
                        tool_name=mm.tool_name,
                        error_detail=mm.error_detail,
                        tool_calls=mm.tool_calls,
                        reasoning_content=mm.reasoning_content,  # M20 THK-04: 压缩后回传链不因截断断裂
                        metadata=mm.metadata,
                    )
                )
                budget -= len(trimmed)
            kept_groups.insert(0, trimmed_group)
            continue
        kept_groups.insert(0, group)
        budget -= group_len

    # 另存被丢弃消息（信息零丢失）
    if archive_sink is not None and session_id and archived:
        for m in archived:
            try:
                archive_sink(session_id, m)
            except Exception:
                import logging

                logging.getLogger(__name__).warning("archive sink 异常（fail-open）", exc_info=True)

    for group in kept_groups:
        for m in group:
            out.append(m.to_llm_dict())
    if archived:
        # EVO-9794797e: 主动压缩——对将被丢弃的旧消息生成语义摘要注入上下文
        # （替代纯丢弃：模型仍能感知旧结论；原文已另存保信息零丢失，fail-open）
        # EVO-20260811-1e68f400: 附加压缩档案目录（主动检索意识，fail-open）
        extras: list[Message] = []
        if summarizer is not None:
            archived_text = "\n".join(m.content for m in archived if m.content)[-20000:]
            if archived_text.strip():
                try:
                    summary_result = summarizer.summarize(archived_text)
                    if summary_result.summary:
                        src_note = f"（来源: {summary_result.source}"
                        if summary_result.note:
                            src_note += f"，{summary_result.note}"
                        src_note += "）"
                        extras.append(
                            Message(
                                role="system",
                                content=(
                                    f"[上下文压缩摘要] 以下为被压缩旧消息的语义摘要 {src_note}：\n"
                                    f"{summary_result.summary}\n"
                                    f"（原文已完整另存至压缩档案，可用 search_archive 检索）"
                                ),
                                source=MessageSource.SYSTEM,
                            )
                        )
                except Exception:
                    import logging

                    logging.getLogger(__name__).warning(
                        "压缩摘要生成失败（fail-open）", exc_info=True
                    )

        # 档案目录（无论摘要是否成功均注入，保证"有什么可找"可见）
        try:
            idx_dir = _archive_index_dir(archived)
            if idx_dir:
                extras.append(
                    Message(role="system", content=idx_dir, source=MessageSource.SYSTEM)
                )
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "压缩档案目录生成失败（fail-open）", exc_info=True
            )

        from llm_loop.feedback.honesty import compression_message

        extras.append(
            compression_message(len(archived), sum(len(a.content) for a in archived))
        )
        for i, em in enumerate(extras):
            out.insert(1 + i, em.to_llm_dict())
    return out
