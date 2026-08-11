"""会话状态快照测试（EVO-20260811-9ccdec97）."""
from llm_loop.core.loop import build_session_snapshot_text


def test_snapshot_basic():
    text = build_session_snapshot_text(message_count=42, memory_count=7)
    assert "会话状态快照" in text
    assert "消息 42 条" in text and "记忆 7 条" in text
    assert "定位漂移" in text  # 校准引导


def test_snapshot_with_evolution_summary():
    text = build_session_snapshot_text(
        message_count=10, memory_count=1,
        evolution_summary={"pending_review": 5, "executed": 12, "executing": 0},
    )
    assert "pending_review=5" in text and "executed=12" in text


def test_snapshot_without_summary_omits_evolution():
    text = build_session_snapshot_text(message_count=3, memory_count=0, evolution_summary=None)
    assert "演进待办" not in text
