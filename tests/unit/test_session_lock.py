"""P0-4(2026-08-15): SessionStore 跨进程写并发锁（lost update 防护）.

背景（审计发现 #8）: Web 与飞书为独立进程共享同一 data/ 目录与共享当前会话；
append/rename/trim 的 load→modify→save 全程无锁，两个写入方同时 load 同一快照后
last-writer-wins，用户消息静默丢失。修复：per-session flock（<sid>.lock）包住
load→modify→write 临界区（对齐 EventStore 既有约定）。

测试用两个 SessionStore 实例指向同一目录模拟两进程；flock 按打开文件描述符互斥，
同进程两线程经各自 open 的锁文件同样互斥，可稳定复现/验证。
"""

from __future__ import annotations

import threading

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore


def _msg(text: str) -> Message:
    return Message(role="user", content=text, source=MessageSource.USER)


def test_concurrent_append_no_lost_update(tmp_path):
    """两实例并发 append 同会话 50 次：最终消息数必须 = 50（修复前稳定丢失）."""
    store_a = SessionStore(str(tmp_path))
    store_b = SessionStore(str(tmp_path))
    sid = store_a.create()
    n_per = 25
    errors: list[Exception] = []

    def _writer(store: SessionStore, tag: str) -> None:
        try:
            for i in range(n_per):
                store.append(sid, _msg(f"{tag}-{i}"))
        except Exception as exc:  # noqa: BLE001 — 收集后统一断言
            errors.append(exc)

    t1 = threading.Thread(target=_writer, args=(store_a, "a"))
    t2 = threading.Thread(target=_writer, args=(store_b, "b"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"并发 append 抛异常: {errors[:3]}"
    final = store_a.load(sid)
    contents = {m.content for m in final.messages}
    expected = {f"a-{i}" for i in range(n_per)} | {f"b-{i}" for i in range(n_per)}
    missing = expected - contents
    assert not missing, f"并发 append 丢失 {len(missing)} 条消息（如 {sorted(missing)[:3]}）"
    assert len(final.messages) == n_per * 2


def test_concurrent_append_and_rename_no_tear(tmp_path):
    """append 与 rename 并发：rename 不丢 append 的消息（共享 save 路径互斥）."""
    store_a = SessionStore(str(tmp_path))
    store_b = SessionStore(str(tmp_path))
    sid = store_a.create()
    n = 20
    errors: list[Exception] = []

    def _appender() -> None:
        try:
            for i in range(n):
                store_a.append(sid, _msg(f"m-{i}"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def _renamer() -> None:
        try:
            for i in range(n):
                store_b.rename(sid, f"标题-{i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=_appender)
    t2 = threading.Thread(target=_renamer)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"并发 append/rename 抛异常: {errors[:3]}"
    final = store_a.load(sid)
    assert len(final.messages) == n, (
        f"rename 覆盖了 append 的消息: 期望 {n} 条, 实际 {len(final.messages)} 条"
    )


def test_shared_current_concurrent_set(tmp_path):
    """set_shared_current 并发写：锁文件互斥 + 最终文件内容合法（不撕裂）."""
    store_a = SessionStore(str(tmp_path))
    store_b = SessionStore(str(tmp_path))
    sid_a = store_a.create()
    sid_b = store_b.create()
    errors: list[Exception] = []

    def _set(store: SessionStore, sid: str, n: int) -> None:
        try:
            for _ in range(n):
                store.set_shared_current(sid)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=_set, args=(store_a, sid_a, 30))
    t2 = threading.Thread(target=_set, args=(store_b, sid_b, 30))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors
    current = store_a.get_shared_current()
    assert current in {sid_a, sid_b}, f"共享当前会话指针撕裂: {current!r}"


def test_lock_file_does_not_pollute_session_listing(tmp_path):
    """锁文件（<sid>.lock）不得出现在会话列表 / 不影响 exists 判定."""
    store = SessionStore(str(tmp_path))
    sid = store.create()
    store.append(sid, _msg("hello"))
    metas = store.list_sessions()
    assert [m.session_id for m in metas] == [sid]
    assert store.exists(sid)
