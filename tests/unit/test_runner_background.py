"""后台 run 执行器单测（EVO 后台 run 改造，设计 v0.3）.

覆盖: 启动返回 handle+queue / delta+done 广播 / 同会话拒绝 / 订阅者退出不炸 /
异常广播 / 多订阅者全收 / disabled 回退 / 只读快照.
FakeEngine 提供 run_stream 生成器（yield delta + return result），不依赖真实引擎.
"""

from __future__ import annotations

import queue
import threading
import time
from types import SimpleNamespace

from llm_loop.core.loop.runner import (
    BackgroundRunner,
    EventBus,
    RunHandle,
)


class FakeEngine:
    """最小桩：run_stream 生成器（3 个 delta + return result）.

    delay: 每个 delta 前 sleep，制造 running 窗口（后台线程过快完成会破坏时序断言）.
    """

    def __init__(self, deltas: int = 3, *, fail: bool = False, delay: float = 0.0) -> None:
        self._deltas = deltas
        self._fail = fail
        self._delay = delay
        self.called = 0

    def run_stream(self, session_id: str, user_text: str, model: str | None = None):
        self.called += 1
        if self._fail:
            raise RuntimeError("llm boom")
        for i in range(self._deltas):
            if self._delay:
                time.sleep(self._delay)
            yield SimpleNamespace(
                text=f"t{i}", reasoning=f"r{i}", tool_round=None
            )
        return SimpleNamespace(
            session_id=session_id,
            final_answer="final",
            rounds=self._deltas,
            tool_calls=0,
        )


def _drain(q: queue.Queue, n: int, timeout: float = 5.0) -> list[dict]:
    out = []
    for _ in range(n):
        out.append(q.get(timeout=timeout))
    return out


def test_start_returns_handle_and_queue():
    eng = FakeEngine(delay=0.05)
    r = BackgroundRunner(eng)
    handle, q = r.start("s1", "hi")
    assert handle is not None and q is not None
    assert handle.status == "running"
    assert r.is_running("s1") is True
    # 收 3 delta + 1 done
    evs = _drain(q, 4)
    assert [e["type"] for e in evs] == ["delta", "delta", "delta", "done"]
    assert evs[-1]["result"].final_answer == "final"
    # 终态: handle done + registry 移除
    deadline = time.time() + 5
    while r.is_running("s1") and time.time() < deadline:
        time.sleep(0.01)
    assert r.is_running("s1") is False
    assert handle.status == "done"
    assert eng.called == 1


def test_double_start_rejected():
    eng = FakeEngine(deltas=10, delay=0.05)
    r = BackgroundRunner(eng)
    h1, q1 = r.start("s1", "hi")
    assert h1 is not None
    # 同会话第二次 start → 拒绝（B3）
    h2, q2 = r.start("s1", "again")
    assert h2 is None and q2 is None
    _drain(q1, 11)  # 10 delta + done


def test_subscriber_exit_no_crash():
    """订阅者退出（unsubscribe）后，后台继续完成不炸（B6）."""
    eng = FakeEngine(deltas=5, delay=0.05)
    r = BackgroundRunner(eng)
    handle, q = r.start("s1", "hi")
    # 收 2 个 delta 后退出
    _drain(q, 2)
    # 模拟 SSE 断连：unsubscribe 后不再 put 本队列
    # （EventBus.subscribe 返回的 q 在 start 内已注册；此处直接测：再开新订阅者收剩余）
    h2, q2 = r.start("s1", "x")
    assert h2 is None  # 同会话 running 拒绝（不影响原 run）
    # 原队列继续收剩余（unsubscribe 未调用仍可收；验证后台未中断）
    evs = _drain(q, 4)  # 剩余 3 delta + done
    assert evs[-1]["type"] == "done"
    deadline = time.time() + 5
    while r.is_running("s1") and time.time() < deadline:
        time.sleep(0.01)
    assert handle.status == "done"


def test_error_broadcast():
    eng = FakeEngine(fail=True)
    r = BackgroundRunner(eng)
    handle, q = r.start("s1", "hi")
    ev = q.get(timeout=5)
    assert ev["type"] == "error"
    assert "llm boom" in ev["error"]
    deadline = time.time() + 5
    while r.is_running("s1") and time.time() < deadline:
        time.sleep(0.01)
    assert handle.status == "error"
    assert "llm boom" in handle.error
    assert r.get_handle("s1") is None  # registry 已移除


def test_multiple_subscribers_all_receive():
    """多订阅者各收全部事件（B6 广播语义）."""
    eng = FakeEngine(deltas=2)
    r = BackgroundRunner(eng)
    handle, q1 = r.start("s1", "hi")
    # 模拟第二个订阅者：从 bus 再 subscribe（start 已建 bus——此处直接新起一个 run 测广播）
    # 直接验证: 一个 run 两个队列（EventBus 手动测）
    bus = EventBus()
    qa = bus.subscribe()
    qb = bus.subscribe()
    for i in range(3):
        bus.emit({"type": "delta", "i": i})
    bus.emit({"type": "done", "result": "R"})
    ea = _drain(qa, 4)
    eb = _drain(qb, 4)
    assert [e["type"] for e in ea] == ["delta", "delta", "delta", "done"]
    assert ea == eb  # 两订阅者收到相同事件
    # 收完原 run 队列
    _drain(q1, 3)


def test_unsubscribe_stops_delivery():
    """订阅者 unsubscribe（SSE 断连）后不再收到后续事件（B6 释放语义）."""
    eng = FakeEngine(deltas=10, delay=0.03)
    r = BackgroundRunner(eng)
    handle, q = r.start("s1", "hi")
    # 收 2 个 delta 后模拟断连：unsubscribe
    _drain(q, 2)
    r.unsubscribe("s1", q)
    # 后台继续完成（不受影响）
    deadline = time.time() + 5
    while r.is_running("s1") and time.time() < deadline:
        time.sleep(0.01)
    assert handle.status == "done"
    # 断连的队列不再收到事件（空）
    assert q.empty()


def test_resume_subscribes_existing_run():
    """resume=True 且同会话已有 running → 返回 (None, 新订阅队列)（重连订阅已有 run）."""
    eng = FakeEngine(deltas=8, delay=0.03)
    r = BackgroundRunner(eng)
    h1, q1 = r.start("s1", "hi")
    assert h1 is not None
    # resume 订阅（模拟刷新/切回）
    h2, q2 = r.start("s1", "", resume=True)
    assert h2 is None and q2 is not None
    # 两个订阅者都收到全部事件（广播）
    evs1 = _drain(q1, 9)  # 8 delta + done
    evs2 = _drain(q2, 9)
    assert evs1[-1]["type"] == "done" and evs2[-1]["type"] == "done"
    assert [e["type"] for e in evs1] == [e["type"] for e in evs2]
    deadline = time.time() + 5
    while r.is_running("s1") and time.time() < deadline:
        time.sleep(0.01)
    assert h1.status == "done"
    # done 后 resume → 无 handle → (None, None)
    h3, q3 = r.start("s1", "", resume=True)
    assert h3 is None and q3 is None


def test_disabled_returns_none():
    r = BackgroundRunner(FakeEngine(), enabled=False)
    handle, q = r.start("s1", "hi")
    assert handle is None and q is None
    assert r.is_running("s1") is False


def test_handle_snapshot_readonly():
    handle = RunHandle(session_id="s1")
    snap = handle.snapshot()
    snap["status"] = "hacked"
    assert handle.status == "running"  # 快照修改不影响原 handle


# ── EVO-20260817 审查 P0-3: 同步 vs 后台并发互斥（双向） ──

class _SyncEngine(FakeEngine):
    """带同步活跃注册表的 engine 桩（模拟真实 engine._sync_active）."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self._sync_guard = threading.Lock()
        self._sync_active: set[str] = set()


def test_sync_active_blocks_background_start():
    """同步 run 活跃时，后台 start 同会话 → (None, None) 拒绝（竞写防护）."""
    eng = _SyncEngine()
    with eng._sync_guard:
        eng._sync_active.add("sess-1")  # 模拟同步 run 进行中
    r = BackgroundRunner(eng)
    handle, q = r.start("sess-1", "hi")
    assert handle is None and q is None
    # 其他会话不受影响
    handle2, q2 = r.start("sess-2", "hi")
    assert handle2 is not None and q2 is not None
    r.unsubscribe("sess-2", q2)


def test_resume_after_done_returns_none(monkeypatch):
    """审查中危: done 广播后 registry pop 前 resume → (None, None)，不订阅空队列.

    修复前该窗口 resume 返回新订阅队列 → SSE 连接永不终结（空队列永挂）。
    """
    eng = FakeEngine(delay=0.05)
    r = BackgroundRunner(eng)
    handle, q = r.start("sess-d", "hi")
    assert handle is not None
    # 等 run 完成（drain 全部事件）——完成后 _consume 设置 status=done 后 pop
    _drain(q, 3)  # 3 个 delta
    done_evt = q.get(timeout=5.0)
    assert done_evt["type"] == "done"
    # 此刻 handle 已 done，但 pop 可能尚未执行（竞态窗口）——直接模拟该窗口状态
    with r._guard:
        # 手动把 handle 放回 registry（模拟 done 后未 pop 的窗口）
        r._registry["sess-d"] = handle
    handle2, q2 = r.start("sess-d", "hi", resume=True)
    assert handle2 is None and q2 is None, "终态 run 不应可订阅"
    # 清理
    with r._guard:
        r._registry.pop("sess-d", None)


def test_eventbus_replay_history():
    """EVO-20260818（DSH 014）: EventBus 重放缓冲——新订阅者先收到已生成事件.

    刷新/切回场景：resume 订阅先重放 run 期间 delta，再收实时。缓存零影响（不改历史序列）.
    """
    bus = EventBus()
    # 先 emit 2 条（run 期间产生）
    bus.emit({"type": "answer_delta", "data": "你好"})
    bus.emit({"type": "answer_delta", "data": "世界"})
    # 新订阅者（模拟刷新后 resume）→ 应先收到已生成 2 条
    q = bus.subscribe()
    first = q.get(timeout=1.0)
    second = q.get(timeout=1.0)
    assert first["data"] == "你好"
    assert second["data"] == "世界"
    # 之后实时事件也能收到
    bus.emit({"type": "answer_delta", "data": "!"})
    third = q.get(timeout=1.0)
    assert third["data"] == "!"


def test_eventbus_replay_bounded():
    """重放缓冲有界（_HISTORY_MAX 内），超限丢弃最旧."""
    bus = EventBus()
    for i in range(EventBus._HISTORY_MAX + 50):
        bus.emit({"type": "answer_delta", "data": str(i)})
    q = bus.subscribe()
    # 应只回放最近 _HISTORY_MAX 条（丢弃最旧 50）
    first = q.get(timeout=1.0)
    assert int(first["data"]) == 50  # 0-49 被丢弃


def test_eventbus_replay_after_subscribe_live_only():
    """订阅后 emit → 只实时收（不重复重放）."""
    bus = EventBus()
    q = bus.subscribe()
    assert q.empty()
    bus.emit({"type": "answer_delta", "data": "live"})
    got = q.get(timeout=1.0)
    assert got["data"] == "live"
    # 不会重复收到旧事件
    assert q.empty()
