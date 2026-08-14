"""EVO-20260814: SessionStore.trim_session 会话瘦身（节 token 不损信息）."""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore


def _make_session(tmp_path: Path, n_user: int = 5, n_tool_per_user: int = 20):
    """构造一个典型对话 session（user + tool + assistant 各若干条）."""
    store = SessionStore(tmp_path)
    sid = store.create()
    store.load(sid)
    # 添加用户消息 + 每个用户消息后跟随 n_tool_per_user 条工具结果 + assistant 回复
    for i in range(n_user):
        store.append(sid, Message(role="user", content=f"用户问题 {i}: 详细的需求描述", source=MessageSource.USER))
        for j in range(n_tool_per_user):
            store.append(sid, Message(
                role="tool",
                content=f"tool {i}-{j} 详细结果: 很长很长的内容 " * 5,
                source=MessageSource.TOOL,
                tool_call_id=f"call-{i}-{j}",
                tool_name="execute_command",
            ))
        store.append(sid, Message(role="assistant", content=f"助手回答 {i}: 详细方案", source=MessageSource.USER))
    return store, sid


def test_trim_session_keeps_recent_and_summarizes_early(tmp_path):
    """保留近期 200 条完整 + 早期摘要化."""
    store, sid = _make_session(tmp_path, n_user=4, n_tool_per_user=20)
    # 4 user + 4*20 tool + 4 assistant = 4+80+4 = 88 条（用户数应调高才能测到 trim）
    # 重新做：5 user + 5*20 tool + 5 assistant = 130 条，keep=50 → 早期 80 条被摘要
    store2, sid2 = _make_session(tmp_path / "s2", n_user=5, n_tool_per_user=20)
    result = store2.trim_session(sid2, keep_recent=50)
    assert result is not None
    assert result["before"] == 110  # 5 user + 100 tool + 5 assistant
    assert result["after"] == 50
    assert result["trimmed"] == 60
    assert result["archived_to"] is not None
    assert Path(result["archived_to"]).exists()
    assert Path(result["summary_path"]).exists()
    # 加载瘦身后 session
    sess = store2.load(sid2)
    assert len(sess.messages) == 50


def test_trim_session_preserves_full_recent_messages(tmp_path):
    """瘦身后近期消息内容完整保留（不只是摘要）."""
    store, sid = _make_session(tmp_path, n_user=5, n_tool_per_user=20)
    store.trim_session(sid, keep_recent=50)
    sess = store.load(sid)
    # 最后一条 assistant 应完整保留（消息源内容）
    last_assistant = [m for m in sess.messages if m.role == "assistant"][-1]
    assert "助手回答 4" in last_assistant.content
    assert "详细方案" in last_assistant.content  # 完整内容（不是摘要截断）


def test_trim_session_summary_includes_all_roles(tmp_path):
    """早期摘要覆盖 user/assistant/tool 三种角色."""
    store, sid = _make_session(tmp_path, n_user=5, n_tool_per_user=20)
    result = store.trim_session(sid, keep_recent=50)
    summary_lines = Path(result["summary_path"]).read_text(encoding="utf-8").splitlines()
    contents = "\n".join(json.loads(line)["content"] for line in summary_lines)
    # 应包含 user/assistant/tool 三种摘要
    assert "user:" in contents
    assert "assistant:" in contents
    assert "tool:" in contents
    # tool 摘要应包含工具名
    assert "execute_command" in contents


def test_trim_session_noop_when_short(tmp_path):
    """已足够短不瘦身."""
    store, sid = _make_session(tmp_path, n_user=2, n_tool_per_user=2)
    # 2 user + 4 tool + 2 assistant = 8 条 < keep_recent=200
    result = store.trim_session(sid, keep_recent=200)
    assert result["trimmed"] == 0
    assert "已足够短" in result["note"]


def test_trim_session_none_for_missing(tmp_path):
    """会话不存在返回 None."""
    store = SessionStore(tmp_path)
    assert store.trim_session("no-such-id") is None


def test_trim_session_size_reduction(tmp_path):
    """瘦身后文件大小显著下降."""
    # 130 条 × 每条 ~200 字符 → 瘦身后 50 条同样大小，但早期 80 条摘要后很小
    store, sid = _make_session(tmp_path, n_user=5, n_tool_per_user=20)
    before_size = (tmp_path / f"{sid}.json").stat().st_size
    store.trim_session(sid, keep_recent=50)
    after_size = (tmp_path / f"{sid}.json").stat().st_size
    assert after_size < before_size  # 显著下降
