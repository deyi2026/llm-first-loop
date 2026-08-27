"""2026-08-21 (追加式压缩): 归档后追加确定性摘要——前缀稳定 + 语义连贯.

验证:
- _append_summary_enabled=True 时归档后追加摘要消息（确定性字节）
- 默认 False 零回归（不追加）
- 摘要格式含归档计数/字符数/search_archive 提示
"""
from __future__ import annotations

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource


def _msgs(n: int) -> list[Message]:
    out = []
    for i in range(n):
        out.append(Message(role="user", content=f"用户问题{i}", source=MessageSource.USER))
        out.append(Message(role="assistant", content=f"回答{i}" + "x" * 50, source=MessageSource.SYSTEM))
    return out


def _run(max_chars: int = 1500, append_summary: bool = False) -> list[dict]:
    archived: list[Message] = []
    return build_history_messages(
        _msgs(30),
        "system",
        max_chars=max_chars,
        session_id="test",
        archive_sink=lambda sid, m: archived.append(m),
        head_keep_chars=2000,
        _append_summary_enabled=append_summary,
    )


def test_append_summary_enabled_adds_summary():
    """启用后归档 → 追加摘要消息（含归档计数/字符数/search_archive 提示）."""
    out = _run(max_chars=1500, append_summary=True)
    summaries = [m for m in out if m.get("metadata", {}).get("archived_summary")]
    assert len(summaries) >= 1, "应追加归档摘要"
    s = summaries[0]
    assert s["role"] == "user"
    assert "[上下文归档摘要]" in s["content"]
    assert "已归档" in s["content"]
    assert "search_archive" in s["content"]


def test_append_summary_disabled_zero_regression():
    """默认 False 不追加摘要（零回归）."""
    out = _run(max_chars=1500, append_summary=False)
    summaries = [m for m in out if m.get("metadata", {}).get("archived_summary")]
    assert len(summaries) == 0


def test_append_summary_deterministic():
    """同输入两次构建 → 摘要字节相同（确定性, 缓存前缀稳定）."""
    out1 = _run(max_chars=1500, append_summary=True)
    out2 = _run(max_chars=1500, append_summary=True)
    s1 = [m for m in out1 if m.get("metadata", {}).get("archived_summary")][0]["content"]
    s2 = [m for m in out2 if m.get("metadata", {}).get("archived_summary")][0]["content"]
    assert s1 == s2, "同输入摘要必须相同（前缀稳定）"
