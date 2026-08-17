"""跨端同步推送格式测试（2026-08-17: M51/M52/M58 脚注补齐）.

web 端展示模型/token 元数据（buildAssistantNote），飞书跨端同步 _format_push
此前只推 role+content 丢弃元数据——补脚注后两端信息一致。
"""

from __future__ import annotations

from llm_loop.core.message import Message, MessageSource
from llm_loop.feishu.cross_sync import CrossSyncWatcher


def _watcher() -> CrossSyncWatcher:
    return CrossSyncWatcher(
        session_store=None,
        session_map=None,
        reply_fn=None,
        sessions_dir="/tmp/not-used",
        max_chars=10000,
    )


def _msg(role: str, content: str, *, model_used: str = "", tokens_in: int = 0,
         tokens_out: int = 0, tokens_cache_hit: int = 0) -> Message:
    return Message(
        role=role,
        content=content,
        source=MessageSource.USER if role == "user" else MessageSource.SYSTEM,
        model_used=model_used,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_cache_hit=tokens_cache_hit,
    )


def test_push_includes_model_and_tokens():
    """assistant 消息带 model_used/tokens → 推送含模型 + 入/出 token 脚注."""
    w = _watcher()
    msgs = [
        _msg("user", "问题"),
        _msg("assistant", "回答内容", model_used="deepseek/deepseek-chat",
             tokens_in=1234, tokens_out=345, tokens_cache_hit=1100),
    ]
    out = w._format_push("测试会话", msgs)
    assert len(out) == 1
    assert "🤖 AI: 回答内容" in out[0]
    assert "—— deepseek/deepseek-chat" in out[0]
    assert "1.2k入/345出" in out[0]
    assert "缓存1.1k" in out[0]


def test_push_no_footer_without_model():
    """assistant 无 model_used（旧消息/provider 未提供）→ 不追加脚注（零回归）."""
    w = _watcher()
    msgs = [_msg("assistant", "旧回答", tokens_in=100)]
    out = w._format_push("t", msgs)
    assert "——" not in out[0]


def test_push_user_no_footer():
    """user 消息永远不加模型脚注."""
    w = _watcher()
    msgs = [_msg("user", "普通提问")]
    out = w._format_push("t", msgs)
    assert "——" not in out[0]
    assert "👤 用户: 普通提问" in out[0]


def test_push_multi_chunk_with_footer():
    """超长分段：脚注跟随各自消息，分段后仍保留."""
    w = CrossSyncWatcher(None, None, None, "/tmp/not-used", max_chars=200)
    long_content = "长" * 300
    msgs = [
        _msg("user", "问题"),
        _msg("assistant", long_content, model_used="m", tokens_in=999, tokens_out=1),
    ]
    out = w._format_push("t", msgs)
    assert len(out) > 1  # 分段
    # 全部文本中应有模型与 token（不因分段丢失）
    all_text = "\n".join(out)
    assert "—— m" in all_text
    assert "999入/1出" in all_text
