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
    assert "[上下文压缩]" in s["content"]
    assert "已归档" in s["content"]
    assert "ref=archive:search_archive" in s["content"]
    assert "归档内容概要" not in s["content"]


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


def test_decision_line_injected_with_active_goal(tmp_path, monkeypatch):
    """能力B决策线（injection_hygiene 5.2-3）: 有活跃 goal → 压缩产物含 [当前决策] 且一致.

    Cognitive Runtime（tasks 2.4）: 缺省 auto 走语义状态持久化不注入帧；
    本测试固定 anchor 模式验证旧决策线路径零回归。
    """
    from llm_loop.introspection.goal import GoalStore

    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COG_RUNTIME_ANCHOR_MODE", "anchor")
    store = GoalStore(tmp_path / "audit")
    g = store.create(objective="验证决策线注入", session_id="test")
    store.checkpoint(g.id, what="里程碑", evidence="e", path="p", next_step="跑专项测试")

    out = _run(max_chars=1500, append_summary=False)
    frames = [m for m in out if "[当前决策]" in str(m.get("content", ""))]
    assert frames, "压缩产物应含决策线帧"
    c = frames[0]["content"]
    assert "验证决策线注入" in c, "决策线须与活跃 goal objective 一致"
    assert "跑专项测试" in c, "决策线须带最近 checkpoint next（指针式恢复）"
    # 位置: 决策线在 [压缩关键事实] 之前（spec 5.2-1 帧首行）
    allc = "\n".join(str(m.get("content", "")) for m in out)
    di, kf = allc.find("[当前决策]"), allc.find("[压缩关键事实]")
    assert di != -1 and (kf == -1 or di < kf), "决策线应在压缩关键事实之前"


def test_decision_line_omitted_without_goal(tmp_path, monkeypatch):
    """能力B fail-open: 无活跃 goal → 决策线省略、压缩正常（spec 6-1）.

    Cognitive Runtime（tasks 2.4）: 固定 anchor 模式，测"anchor 路径下无 goal 省略"
    （缺省 auto 不注入帧，测不到该分支）。
    """
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))  # 空目录：无 goal 文件
    monkeypatch.setenv("COG_RUNTIME_ANCHOR_MODE", "anchor")
    out = _run(max_chars=1500, append_summary=False)
    assert not any("[当前决策]" in str(m.get("content", "")) for m in out)
