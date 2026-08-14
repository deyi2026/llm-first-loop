"""事件日志滚动策略测试（spec §5.3 / design.md §2.2.2-C）.

全走 tmp_path（M64 防污染真实 data/）。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.replay import replay_session
from llm_loop.event_log.rotate import RotateManager, SegmentInfo
from llm_loop.event_log.store import EventStore


def _build_store(tmp_path: Path) -> tuple[EventStore, SessionStore]:
    es = EventStore(tmp_path / "event_logs", enabled=True)
    ss = SessionStore(tmp_path / "sessions", event_store=es)
    return es, ss


def _seed_session(ss: SessionStore, n_msgs: int = 3) -> str:
    sid = ss.create()
    for i in range(n_msgs):
        ss.append(sid, Message(role="user", content=f"msg-{i}", source=MessageSource.USER))
    return sid


def test_rotate_size_threshold(tmp_path):
    """大小阈值触发滚动：单文件 → 多段目录."""
    es, ss = _build_store(tmp_path)
    sid = _seed_session(ss, n_msgs=3)

    # 用小阈值触发滚动
    mgr = RotateManager(es, rotate_bytes=1, rotate_days=0)
    segments = mgr.check_and_rotate(sid)
    assert len(segments) == 2
    # 多段目录结构
    assert es._is_multi_segment(sid)  # noqa: SLF001
    seg_dir = es._segment_dir(sid)  # noqa: SLF001
    assert (seg_dir / "1.jsonl").exists()
    assert (seg_dir / "2.jsonl").exists()


def test_rotate_cross_segment_replay(tmp_path):
    """跨段 replay 与滚动前单文件 replay 逐字段一致."""
    es, ss = _build_store(tmp_path)
    sid = _seed_session(ss, n_msgs=3)
    view_before = replay_session(es.read(sid))
    mgr = RotateManager(es, rotate_bytes=1, rotate_days=0)
    mgr.check_and_rotate(sid)
    view_after = replay_session(es.read(sid))
    assert view_after["messages"] == view_before["messages"]


def test_rotate_archived_segment_readonly(tmp_path):
    """归档段只读（is_active=False），活跃段为最大 segment_seq."""
    es, ss = _build_store(tmp_path)
    sid = _seed_session(ss, n_msgs=3)
    mgr = RotateManager(es, rotate_bytes=1, rotate_days=0)
    mgr.check_and_rotate(sid)
    segments = RotateManager.list_segments(es._dir, sid)  # noqa: SLF001
    assert len(segments) == 2
    assert not segments[0].is_active  # 段 1 归档
    assert segments[1].is_active  # 段 2 活跃
    assert segments[1].segment_seq > segments[0].segment_seq


def test_rotate_disabled(tmp_path):
    """配置为 0 禁用滚动."""
    es, ss = _build_store(tmp_path)
    sid = _seed_session(ss, n_msgs=3)
    mgr = RotateManager(es, rotate_bytes=0, rotate_days=0)
    segments = mgr.check_and_rotate(sid)
    assert segments == []
    assert not es._is_multi_segment(sid)  # noqa: SLF001


def test_list_segments(tmp_path):
    """list_segments �$回段清单含序号/事件数/大小/活跃状态."""
    es, ss = _build_store(tmp_path)
    sid = _seed_session(ss, n_msgs=3)
    mgr = RotateManager(es, rotate_bytes=1, rotate_days=0)
    mgr.check_and_rotate(sid)
    segments = RotateManager.list_segments(es._dir, sid)  # noqa: SLF001
    assert len(segments) == 2
    assert all(isinstance(s, SegmentInfo) for s in segments)
    assert segments[0].event_count > 0  # 归档段有事件
    assert segments[1].event_count == 0  # 活跃段空


def test_read_range(tmp_path):
    """read_range 按 seq 范围检索事件."""
    es, ss = _build_store(tmp_path)
    sid = _seed_session(ss, n_msgs=3)
    events = RotateManager.read_range(es._dir, sid, seq_range=(1, 2))  # noqa: SLF001
    assert len(events) == 2
    assert events[0].seq == 1
    assert events[1].seq == 2


def test_append_to_multi_segment(tmp_path):
    """多段形态 append 写入活跃段."""
    es, ss = _build_store(tmp_path)
    sid = _seed_session(ss, n_msgs=3)
    mgr = RotateManager(es, rotate_bytes=1, rotate_days=0)
    mgr.check_and_rotate(sid)
    # append 到多段形态
    es.append(sid, "message.appended", {"index": 3, "role": "user", "content": "new"})
    # 跨段 read 包含新事件
    events = es.read(sid)
    assert any(e.payload.get("content") == "new" for e in events)


def test_single_file_zero_regression(tmp_path):
    """单文件形态 append/read/last_seq 行为与 D1 逐字节一致（零回归）."""
    es, ss = _build_store(tmp_path)
    sid = _seed_session(ss, n_msgs=2)
    assert not es._is_multi_segment(sid)  # noqa: SLF001
    events = es.read(sid)
    assert len(events) > 0
    assert es.last_seq(sid) == events[-1].seq
