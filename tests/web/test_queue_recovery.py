"""排队消息恢复语义服务端化回归（SPEC-20260923-queue-recovery-server-owned）.

事故（2026-09-22 13:27 → 09-23 07:0x）：用户消息在重启窗口被持久化排队并
承诺"恢复后自动继续"，但承诺的承载是浏览器派发循环——服务重启后循环死亡，
用户等待 7 小时无响应；期间该项被取消后连刷新也无法续。

- B：barrier 窗口入队带 origin 标记；非 user 取消的此类项被恢复重排
  （新项 origin=recovery_requeue，原终态不改写）；user 取消不复活。
- A：server-fallback 派发——到期 queued 项在浏览器缺席时由服务端认领并
  执行（复用 dispatch_claim 原子 FIFO）；屏障期不派发（§8.2-2 零变化）；
  会话 busy 不抢；领取后无法启动则回滚 queued。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from llm_loop.web.human_turn_queue import HumanTurnQueue
from llm_loop.web.queue_recovery import (
    QueueServerFallback,
    recovery_requeue,
)

SID = "sess-b8938fdb"
SID2 = "sess-other"


def _hq(tmp_path: Path) -> HumanTurnQueue:
    return HumanTurnQueue(tmp_path / "data")


# ---------------------------------------------------------------------------
# B: origin 标记与恢复重排
# ---------------------------------------------------------------------------


def test_barrier_enqueue_records_origin(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    item = hq.enqueue(
        SID,
        "重启不成功",
        origin="barrier_window",
        origin_operation_id="svc-86a873",
    )
    assert item["origin"] == "barrier_window"
    assert item["origin_operation_id"] == "svc-86a873"


def test_cancel_records_cancelled_by(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    item = hq.enqueue(SID, "x")
    cancelled = hq.cancel_with_item(SID, item["queue_id"], cancelled_by="user")
    assert cancelled is not None
    assert cancelled["cancelled_by"] == "user"


def test_recovery_requeue_revives_system_cancelled_barrier_item(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    barrier_item = hq.enqueue(
        SID, "重启不成功", origin="barrier_window", origin_operation_id="svc-x"
    )
    hq.cancel_with_item(SID, barrier_item["queue_id"], cancelled_by="system")

    requeued = recovery_requeue(hq)

    assert len(requeued) == 1
    fresh = requeued[0]
    assert fresh["status"] == "queued"
    assert fresh["message"] == "重启不成功"
    assert fresh["origin"] == "recovery_requeue"
    assert fresh["origin_operation_id"] == "svc-x"
    # 原终态不改写（诚实溯源：原项保持 cancelled）
    original = next(
        i for i in hq.snapshot_items() if i["queue_id"] == barrier_item["queue_id"]
    )
    assert original["status"] == "cancelled"


def test_recovery_requeue_never_revives_user_cancel_or_unmarked(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    user_cancelled = hq.enqueue(
        SID, "用户主动放弃", origin="barrier_window", origin_operation_id="svc-x"
    )
    hq.cancel_with_item(SID, user_cancelled["queue_id"], cancelled_by="user")
    # 旧 schema 项（无 origin 标记）与普通项都不在恢复范围
    legacy = hq.enqueue(SID2, "旧消息")
    hq.cancel_with_item(SID2, legacy["queue_id"], cancelled_by="system")
    plain = hq.enqueue(SID2, "普通排队项")  # 未取消

    assert recovery_requeue(hq) == []
    assert plain["status"] == "queued"


# ---------------------------------------------------------------------------
# A: server-fallback 派发
# ---------------------------------------------------------------------------


class _FakeRunner:
    def __init__(
        self,
        *,
        busy: set[str] | None = None,
        start_ok: bool = True,
        handles: dict[str, str] | None = None,
    ):
        self.enabled = True
        self._busy = set(busy or ())
        self._start_ok = start_ok
        self._handles = dict(handles or {})
        self.starts: list[tuple[str, str]] = []

    def get_handle(self, sid):
        gen = self._handles.get(sid)
        return {"run_generation": gen} if gen is not None else None

    def is_running(self, sid: str) -> bool:
        return sid in self._busy

    def is_sync_active(self, sid: str) -> bool:
        return False

    def start(self, sid, message, **kwargs):
        self.starts.append((sid, message))
        if not self._start_ok or sid in self._busy:
            return None, None
        cb = kwargs.get("terminal_callback")
        if cb is not None:
            cb("completed", None)
        return SimpleNamespace(session_id=sid), None


def _fallback(engine, hq, **kw) -> QueueServerFallback:
    kw.setdefault("tick_s", 3600.0)
    kw.setdefault("min_age_s", 0.0)
    return QueueServerFallback(engine, hq, **kw)


def _engine(tmp_path: Path, runner) -> SimpleNamespace:
    return SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
    )


def test_fallback_dispatches_aged_queued_item_headlessly(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    hq.enqueue(SID, "重启不成功")
    runner = _FakeRunner()
    fb = _fallback(_engine(tmp_path, runner), hq)

    fb.tick_once()

    assert runner.starts == [(SID, "重启不成功")]
    item = hq.snapshot_items()[0]
    assert item["status"] == "completed"  # terminal_callback 已回写
    assert item["claimed_by"] == "server-fallback"


def test_fallback_never_races_browser_claim(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    hq.enqueue(SID, "x")
    # 浏览器先领取（原子 FIFO 单赢家）
    assert hq.dispatch_claim(SID, claimed_by="web") is not None
    runner = _FakeRunner()
    fb = _fallback(_engine(tmp_path, runner), hq)

    fb.tick_once()

    assert runner.starts == []  # 服务端认领失败（claimed=None）→ 不启动


def test_fallback_skips_busy_session_and_rolls_back_unstartable(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    hq.enqueue(SID, "busy-session")
    hq.enqueue(SID2, "start-will-fail")
    runner = _FakeRunner(busy={SID}, start_ok=False)
    fb = _fallback(_engine(tmp_path, runner), hq)

    fb.tick_once()

    assert SID not in [s for s, _ in runner.starts]
    # start 失败（handle None）→ 回滚 queued（与浏览器领取方义务一致）
    statuses = {i["message"]: i["status"] for i in hq.snapshot_items()}
    assert statuses["busy-session"] == "queued"
    assert statuses["start-will-fail"] == "queued"


def test_fallback_respects_restart_barrier(tmp_path: Path, monkeypatch) -> None:
    hq = _hq(tmp_path)
    hq.enqueue(SID, "x")
    runner = _FakeRunner()
    fb = _fallback(_engine(tmp_path, runner), hq)
    import llm_loop.web.queue_recovery as qr

    monkeypatch.setattr(
        qr,
        "task_admission_barrier",
        lambda data_dir, kind: SimpleNamespace(service="web", operation_id="svc-r", reason="restart"),
    )

    fb.tick_once()

    assert runner.starts == []
    assert hq.snapshot_items()[0]["status"] == "queued"


def test_fallback_skips_young_items(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    hq.enqueue(SID, "刚入队")
    runner = _FakeRunner()
    fb = QueueServerFallback(
        _engine(tmp_path, runner), hq, tick_s=3600.0, min_age_s=3600.0
    )

    fb.tick_once()

    assert runner.starts == []  # 项龄未到阈值，避让浏览器正常领取窗口


# ---------------------------------------------------------------------------
# interject_pending 孤儿回收：run 终止/换代后不再静默滞留到进程重启
# ---------------------------------------------------------------------------


def test_fallback_reaps_orphan_interject_when_run_ended(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    item = hq.enqueue(SID, "立即插入这条")
    hq.claim_interject(SID, item["queue_id"], run_generation="gen-1")
    # run 已终止：registry 注销 handle → get_handle 为 None；项龄阈值调高，
    # 本测试只看回收语义（接力派发见下一测试）
    runner = _FakeRunner(handles={})
    fb = QueueServerFallback(
        _engine(tmp_path, runner), hq, tick_s=3600.0, min_age_s=3600.0
    )

    fb.tick_once()

    after = hq.snapshot_items()[0]
    assert after["status"] == "queued"
    assert after["requeued_from"] == "interject_run_ended"
    assert runner.starts == []


def test_fallback_requeued_orphan_rejoins_fifo_dispatch(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    item = hq.enqueue(SID, "立即插入这条")
    hq.claim_interject(SID, item["queue_id"], run_generation="gen-1")
    runner = _FakeRunner(handles={})
    fb = _fallback(_engine(tmp_path, runner), hq)  # min_age_s=0：同 tick 接力

    fb.tick_once()

    # 回队 → 到期 queued → 服务端认领无头执行（消息必达闭环）
    assert runner.starts == [(SID, "立即插入这条")]
    final = hq.snapshot_items()[0]
    assert final["status"] == "completed"  # _FakeRunner terminal_callback 回写
    assert final.get("requeued_from") == "interject_run_ended"  # 审计标记保留


def test_fallback_reaps_interject_on_generation_change(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    item = hq.enqueue(SID, "插话")
    hq.claim_interject(SID, item["queue_id"], run_generation="gen-1")
    # 同会话已有新代 run：旧代 mailbox 不会再被消费
    runner = _FakeRunner(handles={SID: "gen-2"}, busy={SID})
    fb = _fallback(_engine(tmp_path, runner), hq)

    fb.tick_once()

    after = hq.snapshot_items()[0]
    assert after["status"] == "queued"  # 回队，不被误标 received
    assert after["requeued_from"] == "interject_run_ended"
    assert runner.starts == []  # 新代 run busy：不抢跑


def test_fallback_keeps_interject_while_run_alive_same_generation(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    item = hq.enqueue(SID, "插话")
    hq.claim_interject(SID, item["queue_id"], run_generation="gen-1")
    runner = _FakeRunner(handles={SID: "gen-1"}, busy={SID})
    fb = _fallback(_engine(tmp_path, runner), hq)

    fb.tick_once()

    after = hq.snapshot_items()[0]
    # run 活着且代次吻合：不回收，等待轮边界消费（语义归引擎）
    assert after["status"] == "interject_pending"
    assert "requeued_from" not in after
