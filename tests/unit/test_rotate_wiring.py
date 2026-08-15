"""P1-1(2026-08-15): RotateManager 生产接线（审计发现 #9）.

实证缺陷：
- RotateManager 从未接线到生产——只有 CLI event-rotate-status 读段清单，
  check_and_rotate 生产无人调用，事件日志永不滚动。
- `_is_multi_segment` 检查在 flock 外，与 `_migrate_to_segments` 之间存在竞态
  （双进程同见单文件形态 → 双重迁移互相覆盖丢数据）。
- 迁移后活跃段 seq 从 1 重启（_append_locked 只读活跃文件）→ 跨段合并后
  seq 重复（1..N 与 1..M 交织），replay/read_range 语义被破坏。

修复：EventStore.append 在同一把会话级稳定锁内 检查+滚动+追加；seq 全局续号；
引擎 run 末 fail-open 检查钩子。
"""

from __future__ import annotations

import threading

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.rotate import RotateManager
from llm_loop.event_log.store import EventStore


def _build(tmp_path, *, rotate_bytes=1024, rotate_days=0):
    es = EventStore(tmp_path / "event_logs", enabled=True)
    rm = RotateManager(es, rotate_bytes=rotate_bytes, rotate_days=rotate_days)
    es.set_rotate_manager(rm)
    ss = SessionStore(tmp_path / "sessions", event_store=es)
    return es, rm, ss


def test_append_triggers_rotation_when_wired(tmp_path):
    """接线后：append 达到大小阈值自动迁移多段（无需外部显式调用 check_and_rotate）."""
    es, _rm, ss = _build(tmp_path, rotate_bytes=200)  # 极小阈值
    sid = ss.create()
    for i in range(8):
        ss.append(sid, Message(role="user", content=f"消息{i}" + "长" * 30, source=MessageSource.USER))
    assert es._is_multi_segment(sid), "接线后 append 未触发自动滚动"  # noqa: SLF001


def test_unwired_store_never_rotates(tmp_path):
    """零回归：未接线的 EventStore 保持单文件形态（D1 行为不变）."""
    es = EventStore(tmp_path / "event_logs", enabled=True)
    ss = SessionStore(tmp_path / "sessions", event_store=es)
    sid = ss.create()
    for i in range(8):
        ss.append(sid, Message(role="user", content=f"消息{i}" + "长" * 30, source=MessageSource.USER))
    assert not es._is_multi_segment(sid)  # noqa: SLF001


def test_seq_continues_across_segments(tmp_path):
    """迁移后追加的事件 seq 全局续号（跨段合并无重复 seq）."""
    es, _rm, ss = _build(tmp_path, rotate_bytes=200)
    sid = ss.create()
    for i in range(8):
        ss.append(sid, Message(role="user", content=f"m{i}" + "长" * 30, source=MessageSource.USER))
    events = es.read(sid)
    seqs = [e.seq for e in events]
    assert len(seqs) == len(set(seqs)), f"跨段 seq 重复: {seqs}"
    assert seqs == sorted(seqs), f"跨段 seq 未递增: {seqs}"


def test_concurrent_append_and_rotate_no_lost_event(tmp_path):
    """双实例并发 append + 滚动竞态：事件零丢失、seq 全局唯一（审计 #9 竞态闭合）."""
    es1, _rm1, ss = _build(tmp_path, rotate_bytes=300)
    es2 = EventStore(tmp_path / "event_logs", enabled=True)
    es2.set_rotate_manager(RotateManager(es2, rotate_bytes=300, rotate_days=0))
    sid = ss.create()
    errors: list[Exception] = []

    def _writer(store, tag, n):
        try:
            for i in range(n):
                store.append(sid, "message.appended",
                             {"index": i, "role": "user", "content": f"{tag}-{i}-" + "x" * 40})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=_writer, args=(es1, "a", 15))
    t2 = threading.Thread(target=_writer, args=(es2, "b", 15))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors, f"并发写抛异常: {errors[:2]}"
    events = es1.read(sid)
    contents = {e.payload.get("content", "")[:4] for e in events if e.type == "message.appended"}
    assert len([c for c in contents if c.startswith("a-")]) + len(
        [c for c in contents if c.startswith("b-")]
    ) == 30, f"并发写丢事件: 仅 {len(contents)} 条 message.appended 内容前缀"
    seqs = [e.seq for e in events]
    assert len(seqs) == len(set(seqs)), f"并发下 seq 重复: {sorted(seqs)}"


def test_check_rotate_public_hook(tmp_path):
    """引擎 run 末钩子形态：check_rotate 公开方法 fail-open（未接线/禁用均不抛）."""
    es_plain = EventStore(tmp_path / "plain", enabled=True)
    es_plain.check_rotate("nonexistent")  # 未接线 → 无行为不抛
    es, _rm, ss = _build(tmp_path, rotate_bytes=200)
    sid = ss.create()
    for i in range(6):
        ss.append(sid, Message(role="user", content=f"m{i}" + "长" * 30, source=MessageSource.USER))
    es.check_rotate(sid)  # 显式调用幂等（append 接线可能已触发，二次调用不多滚）
    segs = RotateManager.list_segments(tmp_path / "event_logs", sid)
    assert segs, "check_rotate 后仍无段信息"
