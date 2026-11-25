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

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from llm_loop.web.human_turn_queue import HumanTurnQueue
from llm_loop.web.queue_recovery import (
    _WAKE_MAX,
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


def test_fallback_probe_failure_does_not_block_other_sessions(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    hq.enqueue(SID, "probe-unavailable")
    hq.enqueue(SID2, "healthy-target")

    class FailingProbeRunner(_FakeRunner):
        def is_running(self, sid: str) -> bool:
            if sid == SID:
                raise RuntimeError("target probe unavailable")
            return super().is_running(sid)

    runner = FailingProbeRunner()
    fb = _fallback(_engine(tmp_path, runner), hq)

    assert fb.tick_once() == 1
    assert runner.starts == [(SID2, "healthy-target")]
    statuses = {i["session_id"]: i["status"] for i in hq.snapshot_items()}
    assert statuses == {SID: "queued", SID2: "completed"}


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


# ---------------------------------------------------------------------------
# M0 workspace/epoch 绑定（SA-RESUME-20261125）：共享 data_dir 的多进程互不
# 派发对方工作区条目；错误目标留队可查询；重启恢复与 epoch 竞态语义保持。
# ---------------------------------------------------------------------------


def test_enqueue_stamps_workspace_scope_and_is_queryable(tmp_path: Path) -> None:
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    item = hq.enqueue(SID, "绑定条目")
    assert item["workspace_scope"] == "/ws/a"
    # 快照即对外查询视图：绑定随条目可查（错误目标保留可查询状态）
    assert hq.snapshot_items()[0]["workspace_scope"] == "/ws/a"
    # 未配置 scope（遗留构造）不盖章，旧 schema 语义不变
    legacy = _hq(tmp_path)
    assert "workspace_scope" not in legacy.enqueue(SID2, "遗留条目")


def test_dispatch_claim_scope_filter_is_atomic(tmp_path: Path) -> None:
    # 同一 data_dir 先后被不同工作区进程写入/读取：顺序实例化模拟跨进程共眼
    # （HumanTurnQueue 是单进程全文件权威——并发共写不属于本层契约）。
    data = tmp_path / "data"
    item_a = HumanTurnQueue(data, workspace_scope="/ws/a").enqueue(SID, "ws-a 条目")
    item_b = HumanTurnQueue(data, workspace_scope="/ws/b").enqueue(SID, "ws-b 条目")

    # 第三工作区领取：队首（ws-a）mismatch → 队首阻断，整轮不领取（None）；
    # 条目原样留队（归属经 workspace_scope 字段可查，不额外落盘）
    hq_c = HumanTurnQueue(data, workspace_scope="/ws/c")
    assert hq_c.dispatch_claim(SID, claimed_by="web", expected_workspace_scope="/ws/c") is None
    blocked = {
        i["message"]: (i["status"], i.get("hold_reason")) for i in hq_c.snapshot_items()
    }
    assert blocked == {
        "ws-a 条目": ("queued", None),
        "ws-b 条目": ("queued", None),
    }

    # 归属工作区各自领取（新实例从磁盘重载=跨进程/重启语义）：严格 FIFO——
    # 只裁决各自队首，不越过他区条目顺延
    got_a = HumanTurnQueue(data, workspace_scope="/ws/a").dispatch_claim(
        SID, claimed_by="web", expected_workspace_scope="/ws/a"
    )
    assert got_a is not None and got_a["queue_id"] == item_a["queue_id"]
    # 在途队首（ws-a claimed）先终态，ws-b 方能轮到（不越过在途队首）
    assert HumanTurnQueue(data).mark_terminal(SID, item_a["queue_id"], "completed")
    got_b = HumanTurnQueue(data, workspace_scope="/ws/b").dispatch_claim(
        SID, claimed_by="web", expected_workspace_scope="/ws/b"
    )
    assert got_b is not None and got_b["queue_id"] == item_b["queue_id"]


def test_fallback_never_dispatches_item_bound_to_other_workspace(tmp_path: Path) -> None:
    runner = _FakeRunner()
    engine = SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        workspace_root="/ws/a",
    )
    hq_foreign = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/b")
    hq_foreign.enqueue(SID, "别家工作区的消息")
    hq_own = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    hq_own.enqueue(SID2, "本工作区消息")
    fb = _fallback(engine, hq_own)

    assert fb.tick_once() == 1

    assert runner.starts == [(SID2, "本工作区消息")]  # 隔离按目标粒度生效
    foreign = next(i for i in hq_own.snapshot_items() if i["message"] == "别家工作区的消息")
    assert foreign["status"] == "queued"  # 留队不删不改
    assert foreign["workspace_scope"] == "/ws/b"  # 绑定原样可查询


def test_fallback_dispatches_legacy_unbound_items(tmp_path: Path) -> None:
    """P1-2：fallback 对升级前无绑定条目 fail-closed——无 identity owner 证明
    不自动分配（共享 data_dir 多 workspace 归属 UNKNOWN），HOLD 留队；
    resolver 证明归属本区后方可由 fallback 派发."""
    runner = _FakeRunner()
    engine = SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        workspace_root="/ws/a",
    )
    hq = HumanTurnQueue(tmp_path / "data")  # 遗留：无绑定（升级前存量条目）
    hq.enqueue(SID, "升级前排队")
    fb = _fallback(engine, hq)

    # 无 resolver（部署面缺失）→ HOLD：server 路径与浏览器路径同约束
    assert fb.tick_once() == 0
    assert runner.starts == []
    assert hq.snapshot_items()[0]["status"] == "queued"
    assert hq.snapshot_items()[0].get("hold_reason") == "queue_hold_legacy_owner_unresolved"

    # 唯一 owner 证明归属本区 → fallback 派发（重启恢复承诺经证明路径兑现）
    hq2 = HumanTurnQueue(
        tmp_path / "data",
        workspace_scope="/ws/a",
        legacy_scope_resolver=lambda sid: "/ws/a",
    )
    fb2 = _fallback(engine, hq2)
    assert fb2.tick_once() == 1
    assert runner.starts == [(SID, "升级前排队")]


def test_fallback_passes_workspace_epoch_guard_to_runner(tmp_path: Path) -> None:
    seen = {}

    class RecordingRunner(_FakeRunner):
        def start(self, sid, message, **kwargs):
            seen.update(kwargs)
            return super().start(sid, message, **kwargs)

    runner = RecordingRunner()
    engine = SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        _workspace_epoch=3,
    )
    hq = _hq(tmp_path)
    hq.enqueue(SID, "epoch 守卫")
    _fallback(engine, hq).tick_once()

    assert seen.get("expected_workspace_epoch") == 3  # tick 采样传入 runner 既有守卫
    assert runner.starts == [(SID, "epoch 守卫")]


def test_workspace_epoch_transition_rolls_back_and_keeps_queued(tmp_path: Path) -> None:
    from llm_loop.workspace.store import WorkspaceChangedError

    class SwitchedRunner(_FakeRunner):
        def start(self, sid, message, **kwargs):
            if kwargs.get("expected_workspace_epoch") == 1:
                raise WorkspaceChangedError("请求解析会话后工作区已切换")
            return super().start(sid, message, **kwargs)

    runner = SwitchedRunner()
    engine = SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        _workspace_epoch=1,
    )
    hq = _hq(tmp_path)
    hq.enqueue(SID, "切换窗口消息")
    _fallback(engine, hq).tick_once()

    assert runner.starts == []  # 切换竞态：不启动
    assert hq.snapshot_items()[0]["status"] == "queued"  # 回滚保持 FIFO，等待下个 epoch


def test_restart_same_workspace_resumes_dispatch_with_new_epoch(tmp_path: Path) -> None:
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    hq.enqueue(SID, "重启前排队")
    runner = _FakeRunner()
    engine = SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        workspace_root="/ws/a",
        _workspace_epoch=7,  # 重启后新进程代次
    )
    restarted = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")  # 从磁盘恢复
    fb = _fallback(engine, restarted)

    assert fb.tick_once() == 1
    assert runner.starts == [(SID, "重启前排队")]  # epoch 不是重启屏障
    final = restarted.snapshot_items()[0]
    assert final["status"] == "completed"
    assert final["workspace_scope"] == "/ws/a"  # 盖章跨重启保留


# ---------------------------------------------------------------------------
# M1/A05 目标失败隔离与公平调度：单目标连续失败退避不阻塞其他目标；退避可
# 查询；成功即解除；工作区切换竞态不计入失败。
# ---------------------------------------------------------------------------


class _PerSidFailRunner(_FakeRunner):
    """按目标注入 start 失败（handle=None），并记录尝试次数."""

    def __init__(self, failing=(), **kw):
        super().__init__(**kw)
        self._failing = set(failing)
        self.attempts: list[str] = []

    def start(self, sid, message, **kwargs):
        self.attempts.append(sid)
        if sid in self._failing:
            return None, None
        return super().start(sid, message, **kwargs)


def test_failing_target_defers_but_other_targets_keep_progressing(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    hq.enqueue(SID, "持续失败目标")
    hq.enqueue(SID2, "健康目标")
    runner = _PerSidFailRunner(failing={SID})
    fb = _fallback(_engine(tmp_path, runner), hq, backoff_base_s=3600.0)

    assert fb.tick_once() == 1
    assert runner.starts == [(SID2, "健康目标")]  # 失败目标不阻塞其他目标

    q = fb.quarantine_status()
    assert set(q) == {SID}
    assert q[SID]["fail_streak"] == 1
    assert q[SID]["deferred_s"] > 0

    # 退避窗口内：失败目标不再被尝试（不空转），也不阻塞其他目标的后续 tick
    assert fb.tick_once() == 0
    assert runner.attempts.count(SID) == 1
    statuses = {i["message"]: i["status"] for i in hq.snapshot_items()}
    assert statuses["持续失败目标"] == "queued"  # 退避≠丢弃，留队可查询


def test_backoff_expires_then_retries_and_success_clears(tmp_path: Path) -> None:
    hq = _hq(tmp_path)
    hq.enqueue(SID, "会恢复的目标")
    runner = _PerSidFailRunner(failing={SID})
    fb = _fallback(_engine(tmp_path, runner), hq, backoff_base_s=0.0)

    fb.tick_once()
    assert fb.quarantine_status()[SID]["fail_streak"] == 1

    fb.tick_once()  # 退避基数为 0：立即到期 → 允许重试
    assert fb.quarantine_status()[SID]["fail_streak"] == 2  # 连续失败计数增长

    runner._failing.clear()  # 目标恢复
    assert fb.tick_once() == 1
    assert fb.quarantine_status() == {}  # 派发成功即解除隔离
    statuses = {i["status"] for i in hq.snapshot_items()}
    assert statuses == {"completed"}


def test_workspace_change_failure_does_not_count_toward_backoff(tmp_path: Path) -> None:
    from llm_loop.workspace.store import WorkspaceChangedError

    class SwitchedRunner(_FakeRunner):
        def start(self, sid, message, **kwargs):
            if kwargs.get("expected_workspace_epoch") == 1:
                raise WorkspaceChangedError("工作区切换")
            return super().start(sid, message, **kwargs)

    runner = SwitchedRunner()
    engine = SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        _workspace_epoch=1,
    )
    hq = _hq(tmp_path)
    hq.enqueue(SID, "切换竞态")
    fb = _fallback(engine, hq)
    fb.tick_once()

    assert fb.quarantine_status() == {}  # 环境级回滚不计入目标失败
    assert hq.snapshot_items()[0]["status"] == "queued"


# ---------------------------------------------------------------------------
# M0 P1 收口负测（SA-RESUME-20261125 续）：严格 FIFO 队首阻断 / 双领取单赢家 /
# legacy 条目 identity-owner 归属证明 / workspace 切换 scope 维度。
# ---------------------------------------------------------------------------


def test_dispatch_head_block_strict_fifo_no_skip(tmp_path: Path) -> None:
    """P1-3：他区条目在队首时整轮不领取，绝不 continue 越过队首顺延领后续."""
    data = tmp_path / "data"
    HumanTurnQueue(data, workspace_scope="/ws/b").enqueue(SID, "队首-b")
    item_a = HumanTurnQueue(data, workspace_scope="/ws/a").enqueue(SID, "第二条-a")

    got = HumanTurnQueue(data, workspace_scope="/ws/a").dispatch_claim(
        SID, claimed_by="web", expected_workspace_scope="/ws/a"
    )
    assert got is None  # 旧 continue 语义会在此错领"第二条-a"
    blocked = {
        i["message"]: (i["status"], i.get("hold_reason"))
        for i in HumanTurnQueue(data).snapshot_items()
    }
    assert blocked["队首-b"] == ("queued", None)  # mismatch 原样留队不落盘
    assert blocked["第二条-a"] == ("queued", None)

    # 归属进程到达：先领队首（阻断原因随领取清除），随后 a 方才轮到自己的条目
    got_b = HumanTurnQueue(data, workspace_scope="/ws/b").dispatch_claim(
        SID, claimed_by="web", expected_workspace_scope="/ws/b"
    )
    assert got_b is not None and got_b["message"] == "队首-b"
    assert "hold_reason" not in got_b
    assert HumanTurnQueue(data).mark_terminal(SID, got_b["queue_id"], "completed")
    got_a = HumanTurnQueue(data, workspace_scope="/ws/a").dispatch_claim(
        SID, claimed_by="web", expected_workspace_scope="/ws/a"
    )
    assert got_a is not None and got_a["queue_id"] == item_a["queue_id"]


def test_dispatch_double_claim_single_winner(tmp_path: Path) -> None:
    """双领取：一条目全宇宙单赢家；他区/重复领取者均 None 且不破坏在途队首."""
    data = tmp_path / "data"
    item = HumanTurnQueue(data, workspace_scope="/ws/a").enqueue(SID, "only")
    q_a = HumanTurnQueue(data, workspace_scope="/ws/a")
    q_b = HumanTurnQueue(data, workspace_scope="/ws/b")

    assert q_a.dispatch_claim(SID, expected_workspace_scope="/ws/a") is not None
    # 队首已 claimed（在途）→ 他区与归属方重复领取都不越过在途队首
    assert q_b.dispatch_claim(SID, expected_workspace_scope="/ws/b") is None
    assert q_a.dispatch_claim(SID, expected_workspace_scope="/ws/a") is None
    claimed = [
        i
        for i in HumanTurnQueue(data).snapshot_items()
        if i["queue_id"] == item["queue_id"] and i["status"] == "claimed"
    ]
    assert len(claimed) == 1


def test_dispatch_legacy_item_requires_owner_proof(tmp_path: Path) -> None:
    """P1-2：升级前无盖章条目 fail-closed——resolver 缺失/证明失败/他区一律
    HOLD 且 hold_reason 可查询；唯一 owner 证明后方可领取并回填盖章."""
    data = tmp_path / "data"
    item = HumanTurnQueue(data).enqueue(SID, "升级前存量")  # 遗留构造：无盖章

    # resolver 未注入（部署面缺失）→ HOLD unresolved
    hq0 = HumanTurnQueue(data, workspace_scope="/ws/a")
    assert hq0.dispatch_claim(SID, expected_workspace_scope="/ws/a") is None
    assert hq0.snapshot_items()[0].get("hold_reason") == "queue_hold_legacy_owner_unresolved"

    # resolver 抛异常（SessionStore 未知/多归属/删除路径）→ HOLD，不自动分配
    def _conflict(sid: str) -> str:
        raise RuntimeError("SessionIdConflictError / SessionDeletedError")

    hq1 = HumanTurnQueue(data, workspace_scope="/ws/a", legacy_scope_resolver=_conflict)
    assert hq1.dispatch_claim(SID, expected_workspace_scope="/ws/a") is None
    assert hq1.snapshot_items()[0].get("hold_reason") == "queue_hold_legacy_owner_unresolved"

    # 证明归属他区 → HOLD other
    hq2 = HumanTurnQueue(
        data, workspace_scope="/ws/a", legacy_scope_resolver=lambda sid: "/ws/other"
    )
    assert hq2.dispatch_claim(SID, expected_workspace_scope="/ws/a") is None
    assert (
        hq2.snapshot_items()[0].get("hold_reason") == "queue_hold_legacy_owner_other_workspace"
    )

    # 唯一 owner 证明归属本区（含路径归一：尾斜杠）→ 领取并回填盖章
    hq3 = HumanTurnQueue(
        data, workspace_scope="/ws/a", legacy_scope_resolver=lambda sid: "/ws/a/"
    )
    got = hq3.dispatch_claim(SID, expected_workspace_scope="/ws/a")
    assert got is not None and got["queue_id"] == item["queue_id"]
    assert got["workspace_scope"] == "/ws/a"  # 证明后回填，防后续重复解析漂移
    assert "hold_reason" not in got


def test_workspace_switch_scope_dimension(tmp_path: Path) -> None:
    """workspace 切换（scope 维度）：切后新进程不领旧 scope 条目，绑定原样留队；
    切换/运行竞态由 epoch 守卫覆盖（见 test_workspace_epoch_transition_*）。"""
    data = tmp_path / "data"
    HumanTurnQueue(data, workspace_scope="/ws/old").enqueue(SID, "旧工作区条目")

    hq_new = HumanTurnQueue(data, workspace_scope="/ws/new")
    assert hq_new.dispatch_claim(SID, expected_workspace_scope="/ws/new") is None
    snap = hq_new.snapshot_items()[0]
    assert snap["status"] == "queued"
    assert snap["workspace_scope"] == "/ws/old"  # 留归属进程/人工恢复


# ---------------------------------------------------------------------------
# M0 验收边界补充（主筹交叉核验 2026-11-25）：在途队首阻断 / 独立实例并发
# 单赢家 / legacy HOLD 与另实例 claim 竞争 / 跨实例 enqueue 不覆盖。
# ---------------------------------------------------------------------------


def test_dispatch_inflight_head_blocks_following_items(tmp_path: Path) -> None:
    """同会话两条、首条 claimed 在途：第二条不得被领取（不越过在途队首）；
    首条终态后第二条正常派发."""
    data = tmp_path / "data"
    q = HumanTurnQueue(data, workspace_scope="/ws/a")
    first = q.enqueue(SID, "首条")
    second = q.enqueue(SID, "第二条")
    claimed = q.dispatch_claim(SID, expected_workspace_scope="/ws/a")
    assert claimed is not None and claimed["queue_id"] == first["queue_id"]

    # 首条 claimed 在途 → 同会话第二条本轮不得派发
    assert q.dispatch_claim(SID, expected_workspace_scope="/ws/a") is None
    assert q.claimed_item(SID, second["queue_id"]) is None
    assert q.snapshot_items()[1]["status"] == "queued"

    # 首条终态 → 第二条可领（release 回滚同理回到队首）
    assert q.mark_terminal(SID, first["queue_id"], "completed")
    got = q.dispatch_claim(SID, expected_workspace_scope="/ws/a")
    assert got is not None and got["queue_id"] == second["queue_id"]


def test_dispatch_concurrent_same_scope_single_winner(tmp_path: Path) -> None:
    """两个独立实例、相同 scope、Barrier 同步并发领取同一 qid：恰好一个赢家
    （写侧全局互斥：flock + 锁内 fresh reload，非仅实例内锁）."""
    data = tmp_path / "data"
    HumanTurnQueue(data, workspace_scope="/ws/a").enqueue(SID, "contested")
    qa = HumanTurnQueue(data, workspace_scope="/ws/a")
    qb = HumanTurnQueue(data, workspace_scope="/ws/a")
    barrier = threading.Barrier(2)
    results: list = []

    def _claim(store: HumanTurnQueue) -> None:
        barrier.wait()
        results.append(store.dispatch_claim(SID, expected_workspace_scope="/ws/a"))

    threads = [threading.Thread(target=_claim, args=(s,)) for s in (qa, qb)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r is not None]
    assert len(winners) == 1  # 全局单赢家：另一实例拿到 None
    claimed = [i for i in HumanTurnQueue(data).snapshot_items() if i["status"] == "claimed"]
    assert len(claimed) == 1 and claimed[0]["message"] == "contested"


def test_legacy_hold_then_other_instance_claim(tmp_path: Path) -> None:
    """legacy HOLD 写入与另实例 claim 竞争：A 实例（无 resolver）HOLD 落盘后，
    B 实例（锁内 fresh reload）经 identity owner 证明领取并清除 hold_reason."""
    data = tmp_path / "data"
    HumanTurnQueue(data).enqueue(SID, "legacy")

    a = HumanTurnQueue(data, workspace_scope="/ws/a")  # 无 resolver → HOLD
    assert a.dispatch_claim(SID, expected_workspace_scope="/ws/a") is None
    assert a.snapshot_items()[0].get("hold_reason") == "queue_hold_legacy_owner_unresolved"

    b = HumanTurnQueue(
        data, workspace_scope="/ws/a", legacy_scope_resolver=lambda sid: "/ws/a"
    )
    got = b.dispatch_claim(SID, expected_workspace_scope="/ws/a")
    assert got is not None and got["message"] == "legacy"
    assert "hold_reason" not in got  # HOLD 事实随领取清除，不阻断归属方
    assert got["workspace_scope"] == "/ws/a"


def test_enqueue_across_instances_no_clobber(tmp_path: Path) -> None:
    """跨实例 enqueue 不覆盖：写路径 flock + fresh reload，独立实例顺序写入
    各自条目都保留（全文件覆盖写在 stale 内存视图下会丢他实例条目）."""
    data = tmp_path / "data"
    ia = HumanTurnQueue(data, workspace_scope="/ws/a")
    ib = HumanTurnQueue(data, workspace_scope="/ws/b")
    ia.enqueue(SID, "a 条目")
    ib.enqueue(SID2, "b 条目")  # ib 构造先于 ia 写入（stale 视图）也不丢
    items = HumanTurnQueue(data).snapshot_items()
    assert {i["message"] for i in items} == {"a 条目", "b 条目"}


def test_fresh_reload_preserves_live_interject_pending(tmp_path: Path) -> None:
    """fresh reload（写路径/新实例）不重排 live interject_pending：活性证明
    （claim_state_probe=runner+lease 事实）通过时 handoff 保持 pending；
    只能被真实重启（无 probe 证明）或孤儿活性证明回收，不能被其他线程/
    实例的普通写路径破坏成 queued（重复派发回归）."""
    data = tmp_path / "data"
    live = lambda sid, qid: "active"  # noqa: E731 — 机械活性事实：run 仍在

    a = HumanTurnQueue(data, claim_state_probe=live)
    item = a.enqueue(SID, "插话")
    assert a.claim_interject(SID, item["queue_id"], run_generation="gen-1")

    # 另一独立实例的构造与写路径（flock + fresh reload）不破坏 live handoff
    b = HumanTurnQueue(data, claim_state_probe=live)
    b.enqueue(SID2, "无关条目")

    # 用带 probe 的既有实例做纯读快照（裸构造实例会按"无活性证明"恢复 pending）
    snap = b.snapshot_items()
    assert snap[0]["status"] == "interject_pending"
    assert snap[0]["queue_id"] == item["queue_id"]


def test_interject_received_cas_across_fresh_reload(tmp_path: Path) -> None:
    """received 正常 CAS：pending→received 基于磁盘最新态判定（fresh reload
    后仍通过），且 CAS 单次生效、重复标记失败."""
    data = tmp_path / "data"
    live = lambda sid, qid: "active"  # noqa: E731

    a = HumanTurnQueue(data, claim_state_probe=live)
    item = a.enqueue(SID, "插话")
    assert a.claim_interject(SID, item["queue_id"], run_generation="gen-1")

    b = HumanTurnQueue(data, claim_state_probe=live)  # 独立实例：CAS 基于磁盘最新态
    assert b.mark_interject_received(SID, item["queue_id"], consumed_via="round_start")
    snap = HumanTurnQueue(data).snapshot_items()
    assert snap[0]["status"] == "interject_received"
    assert snap[0]["consumed_via"] == "round_start"
    assert not b.mark_interject_received(SID, item["queue_id"])  # CAS 单次


def test_only_real_restart_recovers_pending(tmp_path: Path) -> None:
    """仅真实重启恢复 pending 为 queued：运行期写路径（fresh reload）不重排；
    活性证明通过（probe=active）的新实例构造不重排；无 probe 证明（信箱
    不可达事实）才恢复 durable queued 意图。孤儿回收另有活性证明路径."""
    data = tmp_path / "data"
    live = lambda sid, qid: "active"  # noqa: E731

    a = HumanTurnQueue(data, claim_state_probe=live)
    item = a.enqueue(SID, "插话")
    assert a.claim_interject(SID, item["queue_id"], run_generation="gen-1")

    # 运行期写路径：同实例/他实例 fresh reload 均不动 pending
    a.enqueue(SID2, "另一条")
    assert HumanTurnQueue(data, claim_state_probe=live).snapshot_items()[0][
        "status"
    ] == "interject_pending"

    # 真实重启：新进程无 probe 可证明活性（信箱不可达）→ 一次性恢复 queued
    c = HumanTurnQueue(data)
    snap = c.snapshot_items()
    assert snap[0]["status"] == "queued"
    assert snap[0]["requeued_from"] == "interject_process_restart"


# ---------------------------------------------------------------------------
# M1 事件唤醒（SA-M1M3-20261125-1236）：已知目标确定性直达、有界、与
# min_age/tick 分离；附 M0 遗留跨进程 live pending 接管边界证明。
# ---------------------------------------------------------------------------


def test_poke_direct_dispatch_ignores_min_age(tmp_path: Path) -> None:
    """事件直达不受 min_age 约束：age≈0 条目 tick 不派发（60s 兜底挡住），
    poke 路径即时派发——正常空闲路径不再依赖 15s tick + 60s min_age."""
    runner = _FakeRunner()
    engine = SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        workspace_root="/ws/a",
    )
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    hq.enqueue(SID, "刚入队")
    fb = _fallback(engine, hq, min_age_s=60.0)  # 显式生产默认（fixture 默认 0 便于旧测）

    assert fb.tick_once() == 0  # 兜底路径：min_age 挡住新条目（节奏不变）
    assert runner.starts == []
    assert fb.poke_session(SID) is True
    assert fb._wake.get_nowait() == SID  # 唤醒已入队，_loop 将即时消费
    assert fb._dispatch_session_now(SID) == 1  # 事件直达：跳过 min_age
    assert runner.starts == [(SID, "刚入队")]


def test_poke_safe_when_busy_or_backoff_and_bounded(tmp_path: Path) -> None:
    """busy/A05 退避中 poke 安全（留队不放大失败）；唤醒队列有界，满则如实
    丢弃不阻塞生产者（tick 兜底不丢条目）."""
    runner = _FakeRunner(busy={SID})
    engine = SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        workspace_root="/ws/a",
    )
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    hq.enqueue(SID, "busy 会话条目")
    fb = _fallback(engine, hq)

    assert fb._dispatch_session_now(SID) == 0  # busy：留队待终态事件
    assert runner.starts == []
    assert hq.snapshot_items()[0]["status"] == "queued"

    fb._record_start_failure(SID2)  # A05 退避中：poke 不放大失败目标
    assert fb._dispatch_session_now(SID2) == 0

    for i in range(_WAKE_MAX):
        assert fb.poke_session(f"s{i}") is True
    assert fb.poke_session(SID) is False  # 队列满：如实丢弃（有界）


def test_event_wake_drains_within_five_seconds(tmp_path: Path) -> None:
    """端到端 P95 证据：poke 后后台线程即时消费派发（<5s），15s tick 与
    60s min_age 均不参与该路径."""
    runner = _FakeRunner()
    engine = SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        workspace_root="/ws/a",
    )
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    hq.enqueue(SID, "事件派发")
    fb = _fallback(engine, hq, min_age_s=60.0)  # 事件路径与 min_age 无关（更强证明）
    fb.start()
    try:
        t0 = time.monotonic()
        assert fb.poke_session(SID) is True
        deadline = time.monotonic() + 5.0
        while not runner.starts and time.monotonic() < deadline:
            time.sleep(0.02)
        elapsed = time.monotonic() - t0
        assert runner.starts == [(SID, "事件派发")]
        assert elapsed < 5.0  # 事件路径 P95≤5s（实测为毫秒级）
    finally:
        fb.stop()


def test_cross_process_live_pending_takeover_stays_safe(tmp_path: Path) -> None:
    """M0 遗留接管证明（未知副作用禁止重放）：A 进程 live interject_pending
    被 B 进程（无 probe 证明）构造期恢复为 queued 后——B 的派发被 scope
    阻断（fallback 与浏览器同约束）；A 进程 run 仍活被 liveness 挡住不重放；
    已知边界：原 pending 信箱事实被一次性恢复为 durable queued 意图，终态
    由 A 进程 run/终态收敛（与 M0 现状同级，非本次引入）."""
    data = tmp_path / "data"
    probe_active = lambda sid, qid: "active"  # noqa: E731 — A 进程 run 活性事实

    hq_a = HumanTurnQueue(
        data, workspace_scope="/ws/a", claim_state_probe=probe_active
    )
    item = hq_a.enqueue(SID, "live handoff")
    assert hq_a.claim_interject(SID, item["queue_id"], run_generation="gen-1")

    # B 进程（scope=/ws/b，无 probe）：构造期恢复 pending→queued
    hq_b = HumanTurnQueue(data, workspace_scope="/ws/b")
    assert hq_b.snapshot_items()[0]["status"] == "queued"
    # B 派发被 scope 阻断（tick 与浏览器同一路径的 scope 队首裁决）
    runner_b = _FakeRunner()
    fb_b = _fallback(
        SimpleNamespace(
            runner=runner_b,
            settings=SimpleNamespace(data_dir=str(data)),
            workspace_root="/ws/b",
        ),
        hq_b,
    )
    assert fb_b.tick_once() == 0
    assert runner_b.starts == []
    assert hq_b.dispatch_claim(SID, expected_workspace_scope="/ws/b") is None

    # A 进程 run 仍活：fallback liveness 挡住（不重放），条目留队待收敛
    runner_a = _FakeRunner(busy={SID}, handles={SID: "gen-1"})
    hq_a2 = HumanTurnQueue(
        data, workspace_scope="/ws/a", claim_state_probe=probe_active
    )
    fb_a = _fallback(
        SimpleNamespace(
            runner=runner_a,
            settings=SimpleNamespace(data_dir=str(data)),
            workspace_root="/ws/a",
        ),
        hq_a2,
    )
    assert fb_a.tick_once() == 0
    assert runner_a.starts == []
    assert hq_a2.snapshot_items()[0]["status"] == "queued"  # 留队不删不改
