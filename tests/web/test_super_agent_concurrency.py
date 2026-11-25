"""M3 隔离并发验收（SA-M2M3-20261125，goal GOAL-20261125-f05e449a）+ 二审
修复负测（SA-REVIEW-FIX-20261125）.

4-8 并行目标可复现测试：目标级失败隔离、严格 FIFO、scope/epoch 切换并发
维度、重启/重复投递/未知副作用、唤醒队列满/退避/持续消息公平性；本地
受理→派发 P95 测量。

版本说明：本文件曾在 SA-REVIEW-FIX run 开场被误覆盖（未跟踪文件无 git
保护），现按上轮终态语义（attempts/starts 显式分离、epoch fake 按代次值、
P95 终态化复用 sid、restart 走真实闸）完整重建，并叠加二审 P1-2/P2-2
负测。重建后全量重跑验证，候选冻结以重跑结果为准。

边界（如实声明）：单进程内模拟（HumanTurnQueue + QueueServerFallback 直调
+ FakeRunner），不是生产 HTTP/多进程/真实模型压测；P95 仅代表本地受理→
派发机械时延下限，生产口径以部署后实机验收为准。
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from types import SimpleNamespace

from llm_loop.web.human_turn_queue import HumanTurnQueue
from llm_loop.web.queue_recovery import QueueServerFallback

SIDS = [f"sess-par-{i:02d}" for i in range(8)]


class _MultiRunner:
    """per-sid 行为 Runner：attempts 记全部 start 尝试（含失败/回滚），
    starts 仅记成功启动；epoch 冲突按代次值区分（raise_epochs）。"""

    def __init__(self, *, fail_sids=(), busy_sids=(), raise_epochs=frozenset()):
        self.enabled = True
        self.fail_sids = set(fail_sids)
        self.busy_sids = set(busy_sids)
        self.raise_epochs = set(raise_epochs)
        self.attempts: list[tuple[str, str]] = []
        self.starts: list[tuple[str, str]] = []

    def get_handle(self, sid):
        return None

    def is_running(self, sid):
        return sid in self.busy_sids

    def is_sync_active(self, sid):
        return False

    def start(self, sid, message, **kwargs):
        self.attempts.append((sid, message))
        expected_epoch = kwargs.get("expected_workspace_epoch")
        if expected_epoch is not None and expected_epoch in self.raise_epochs:
            from llm_loop.workspace.store import WorkspaceChangedError

            raise WorkspaceChangedError("工作区切换竞态")
        if sid in self.fail_sids or sid in self.busy_sids:
            return None, None
        cb = kwargs.get("terminal_callback")
        if cb is not None:
            cb("completed", None)
        self.starts.append((sid, message))
        return SimpleNamespace(session_id=sid), None


def _mk(tmp_path: Path, runner, **kw):
    kw.setdefault("tick_s", 3600.0)
    kw.setdefault("min_age_s", 0.0)
    kw.setdefault("backoff_base_s", 30.0)
    kw.setdefault("backoff_cap_s", 120.0)
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    engine = SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        workspace_root="/ws/a",
        _workspace_epoch=1,
    )
    return QueueServerFallback(engine, hq, **kw), hq, engine


def test_eight_parallel_targets_isolation(tmp_path: Path) -> None:
    """8 并行目标（1 恒失败 + 1 busy + 6 正常）：失败退避可查询、busy 留队，
    正常目标全部完成且不被阻塞（A05 单目标粒度隔离）."""
    runner = _MultiRunner(fail_sids={SIDS[0]}, busy_sids={SIDS[1]})
    fb, hq, _ = _mk(tmp_path, runner)
    for sid in SIDS:
        hq.enqueue(sid, f"msg-{sid}")

    for _ in range(3):
        fb.tick_once()

    started_sids = {s for s, _ in runner.starts}
    ok_sids = {s for s in SIDS if s not in (SIDS[0], SIDS[1])}
    assert ok_sids <= started_sids, f"正常目标被阻塞: {ok_sids - started_sids}"
    assert SIDS[1] not in started_sids
    busy_item = next(i for i in hq.snapshot_items() if i["session_id"] == SIDS[1])
    assert busy_item["status"] == "queued"
    quarantine = fb.quarantine_status()
    assert SIDS[0] in quarantine and quarantine[SIDS[0]]["fail_streak"] >= 1
    ok_items = [i for i in hq.snapshot_items() if i["session_id"] in ok_sids]
    assert ok_items and all(i["status"] == "completed" for i in ok_items)


def test_per_session_fifo_order_across_parallel_targets(tmp_path: Path) -> None:
    """6 并行目标各 2 条：每会话派发序=入队序（严格 FIFO），无跨会话错序."""
    runner = _MultiRunner()
    fb, hq, _ = _mk(tmp_path, runner)
    for round_i in range(2):
        for sid in SIDS[:6]:
            hq.enqueue(sid, f"r{round_i}-{sid}")

    for _ in range(4):
        fb.tick_once()

    order: dict[str, list[str]] = {}
    for sid, msg in runner.starts:
        order.setdefault(sid, []).append(msg)
    assert len(runner.starts) == 12
    for sid in SIDS[:6]:
        assert order[sid] == [f"r0-{sid}", f"r1-{sid}"], f"{sid} 会话内乱序: {order[sid]}"


def test_scope_and_epoch_switch_under_parallel_targets(tmp_path: Path) -> None:
    """并发维度 scope/epoch：切换窗口（epoch=1）守卫是全局事实——全部启动
    被拒且尝试已发生（attempts），epoch 竞态不计失败退避；代次前进后全部
    成功；他区条目全程留队."""
    runner = _MultiRunner(raise_epochs={1})
    fb, hq, engine = _mk(tmp_path, runner)
    foreign = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/b")
    foreign.enqueue(SIDS[6], "别区-1")
    foreign.enqueue(SIDS[7], "别区-2")
    for sid in SIDS[:5]:
        hq.enqueue(sid, f"msg-{sid}")

    first = fb.tick_once()
    assert first == 0  # 切换窗口：全局守卫拒绝全部启动
    assert len(runner.attempts) == 5  # 尝试已发生（非静默跳过）
    assert runner.starts == []
    assert SIDS[0] not in fb.quarantine_status()  # epoch 竞态不计入失败退避

    engine._workspace_epoch = 2
    fb.tick_once()
    assert {s for s, _ in runner.starts} == set(SIDS[:5])
    scopes = {
        i["message"]: (i["status"], i.get("workspace_scope"))
        for i in hq.snapshot_items()
    }
    assert scopes["别区-1"] == ("queued", "/ws/b")
    assert scopes["别区-2"] == ("queued", "/ws/b")


def test_restart_redelivery_once_and_unknown_side_effect(tmp_path: Path) -> None:
    """重启/重复/未知副作用（真实闸）：在途 claimed 不盲重放且 FIFO 不越过；
    not_started 机械证明 → reaper 恢复执行恰一次；独立条目各执行一次、
    同条目二次领取无赢家."""
    data = tmp_path / "data"
    runner = _MultiRunner()
    fb, hq_a, _ = _mk(tmp_path, runner)
    hq_a.enqueue(SIDS[0], "已完成")
    inflight = hq_a.enqueue(SIDS[0], "在途")
    fb.tick_once()
    assert (SIDS[0], "已完成") in runner.starts
    assert runner.starts[-1][1] == "已完成"

    # 模拟崩溃：领取"在途"后进程死（claimed 留盘、无终态回写）
    hq_b = HumanTurnQueue(data, workspace_scope="/ws/a")
    got = hq_b.dispatch_claim(SIDS[0], expected_workspace_scope="/ws/a")
    assert got is not None and got["queue_id"] == inflight["queue_id"]

    # 重启实例（无 probe 事实）：在途不盲重放、不越过在途队首
    fb2, _, _ = _mk(tmp_path, runner)
    fb2._hq = HumanTurnQueue(data, workspace_scope="/ws/a")
    before = len(runner.starts)
    fb2.tick_once()
    assert runner.starts[before:] == []

    # not_started 机械证明：浏览器侧会话查询是 reaper 真实触发面（fallback
    # tick 只扫 queued，不主动碰 claimed 悬挂——既有设计）；轮询等待 reaper
    # 回滚（CI 慢机安全，不依赖固定 sleep），回滚后兜底派发
    hq_probe = HumanTurnQueue(
        data,
        workspace_scope="/ws/a",
        claim_timeout_s=0.05,
        claim_state_probe=lambda sid, qid: "not_started",
    )
    deadline = time.time() + 2.0
    actives = hq_probe.list_active(SIDS[0])
    while actives and actives[0]["status"] != "queued" and time.time() < deadline:
        time.sleep(0.01)
        actives = hq_probe.list_active(SIDS[0])  # 每次查询即 reaper 触发面
    assert actives and actives[0]["status"] == "queued"
    fb3, _, _ = _mk(tmp_path, runner)
    fb3._hq = hq_probe
    before = len(runner.starts)
    fb3.tick_once()
    assert runner.starts[before:] == [(SIDS[0], "在途")]

    # 重复投递：独立条目各自执行；同一条目二次领取无赢家
    dup = hq_probe.enqueue(SIDS[1], "重复投递-独立条目")
    got2 = hq_probe.dispatch_claim(SIDS[1], expected_workspace_scope="/ws/a")
    assert got2 is not None and got2["queue_id"] == dup["queue_id"]
    assert hq_probe.dispatch_claim(SIDS[1], expected_workspace_scope="/ws/a") is None


def test_wake_queue_full_drops_and_tick_recovers(tmp_path: Path) -> None:
    """唤醒队列满（64）：多余 poke 丢弃返回 False 不放大生产者；被丢目标由
    tick 兜底派发，不丢消息."""
    runner = _MultiRunner()
    fb, hq, _ = _mk(tmp_path, runner)
    sids = [f"sess-wake-{i:02d}" for i in range(70)]
    for sid in sids:
        hq.enqueue(sid, f"msg-{sid}")

    pokes = [fb.poke_session(sid) for sid in sids]
    assert pokes.count(False) >= 1
    assert pokes.count(True) == 64

    fb.tick_once()
    started = {s for s, _ in runner.starts}
    assert set(sids) <= started, "tick 兜底未覆盖被丢弃的唤醒目标"


def test_backoff_and_sustained_message_fairness(tmp_path: Path) -> None:
    """持续消息公平性：坏目标持续失败退避期间，好目标交替入队每轮都被派发
    （A05 目标粒度退避不饿死其他目标）。"""
    runner = _MultiRunner(fail_sids={SIDS[0]})
    fb, hq, _ = _mk(tmp_path, runner)
    good_rounds: list[int] = []
    for round_i in range(4):
        hq.enqueue(SIDS[0], f"bad-r{round_i}")
        hq.enqueue(SIDS[1], f"good-r{round_i}")
        fb.tick_once()
        good_rounds.append(runner.starts.count((SIDS[1], f"good-r{round_i}")))

    assert good_rounds == [1, 1, 1, 1], f"好目标被饿死: {good_rounds}"
    assert fb.quarantine_status()[SIDS[0]]["fail_streak"] >= 1


def test_local_accept_dispatch_latency_p95(tmp_path: Path) -> None:
    """本地受理→派发 P95 测量（100 样本，进程内直调口径；每轮终态化后复用
    sid）。口径边界：机械时延下限，不含网络/HTTP/模型路由/多进程调度；
    生产口径以实机验收为准。"""
    data = tmp_path / "data"
    q = HumanTurnQueue(data, workspace_scope="/ws/a")
    latencies: list[float] = []
    samples = 100
    for i in range(samples):
        sid = f"sess-lat-{i % 8}"
        t0 = time.perf_counter()
        item = q.enqueue(sid, f"lat-{i}")
        claimed = q.dispatch_claim(sid, expected_workspace_scope="/ws/a")
        t1 = time.perf_counter()
        assert claimed is not None and claimed["queue_id"] == item["queue_id"]
        q.mark_terminal(sid, claimed["queue_id"], "completed")  # 终态化后 sid 可复用
        latencies.append(t1 - t0)

    p50 = statistics.quantiles(latencies, n=100)[49]
    p95 = statistics.quantiles(latencies, n=100)[94]
    print(
        f"[M3 latency] samples={samples} p50={p50 * 1000:.2f}ms "
        f"p95={p95 * 1000:.2f}ms max={max(latencies) * 1000:.2f}ms"
    )
    assert p95 < 1.0, f"本地受理→派发 P95 异常: {p95:.3f}s"


# ---------------------------------------------------------------------------
# 二审修复负测（SA-REVIEW-FIX-20261125）：P1-2 全扫描绝对截止（真实 _loop
# 线程持续 poke 场景）/ P2-2 busy 竞态不计退避 + 终态 poke 恢复。
# ---------------------------------------------------------------------------


def test_sustained_pokes_do_not_starve_full_scan(tmp_path: Path) -> None:
    """P1-2：持续 poke 下全表扫描按单调时钟绝对截止有界执行——退避到期且
    无后续 poke 的目标仍被恢复（真实 _loop 线程，非手调 tick_once；旧实现
    本测试必失败：wake 永不空 ⇒ tick_once 永不执行）。fail 目标以 attempts
    恢复尝试为证（其 start 恒失败，成功派发以旁观目标 starts 为证）。"""
    runner = _MultiRunner(fail_sids={SIDS[0]})
    fb, hq, _ = _mk(
        tmp_path,
        runner,
        tick_s=1.0,
        min_age_s=0.0,
        backoff_base_s=0.5,
        backoff_cap_s=1.0,
    )
    hq.enqueue(SIDS[0], "退避到期恢复")
    hq.enqueue(SIDS[1], "持续事件旁观目标")
    fb.start()
    try:
        probe_until = time.monotonic() + 4.0
        while time.monotonic() < probe_until and (
            SIDS[0] not in fb.quarantine_status()
        ):
            time.sleep(0.05)
        assert SIDS[0] in fb.quarantine_status()
        attempts_before = len(runner.attempts)
        # 持续 poke 无条目目标：wake 永不空（旧实现下全扫描被无限饥饿）
        poke_until = time.monotonic() + 2.5
        while time.monotonic() < poke_until:
            fb.poke_session("sess-no-queue")
            time.sleep(0.05)
        assert len(runner.attempts) > attempts_before, (
            "持续 poke 期间退避到期的目标未按截止恢复尝试（全扫描被饿死）"
        )
        # 无后续 poke：恢复尝试持续发生（滞留有界解除）；旁观目标成功派发
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if (SIDS[1], "持续事件旁观目标") in runner.starts:
                break
            time.sleep(0.05)
        assert (SIDS[1], "持续事件旁观目标") in runner.starts
    finally:
        fb.stop()


def test_busy_race_without_backoff_and_terminal_poke_recover(tmp_path: Path) -> None:
    """P2-2：handle=None 且复核明确 session_busy → 不计 A05 退避（条目回滚
    留队），busy 解除后终态 poke 直达恢复派发；不明失败语义保留（复核不
    busy 才计退避，见 8 目标隔离测试的 quarantine 断言）。"""

    class _BusyRaceRunner(_MultiRunner):
        def __init__(self):
            super().__init__()
            self.race_busy = False
            self._raced = False

        def is_running(self, sid):
            return self.race_busy

        def start(self, sid, message, **kwargs):
            self.attempts.append((sid, message))
            if not self._raced:
                # 第一次：probe 通过后、start 前被并发占住（一次性竞态窗口）
                self._raced = True
                self.race_busy = True
                return None, None  # 明确 busy 竞态：handle=None
            cb = kwargs.get("terminal_callback")
            if cb is not None:
                cb("completed", None)
            self.starts.append((sid, message))
            return SimpleNamespace(session_id=sid), None

    race = _BusyRaceRunner()
    fb, hq, _ = _mk(tmp_path, race, tick_s=3600.0, min_age_s=0.0)
    hq.enqueue(SIDS[1], "busy竞态后恢复")
    fb.start()
    try:
        # 生产 enqueue 挂点触发的事件直达（_loop 无自转 tick 时事件是唯一入口）
        assert fb.poke_session(SIDS[1]) is True
        probe_until = time.monotonic() + 5.0
        while time.monotonic() < probe_until and not race.attempts:
            time.sleep(0.05)
        assert race.attempts  # 竞态尝试已发生
        assert fb.quarantine_status() == {}  # 明确 busy 竞态：不计失败退避
        assert hq.snapshot_items()[0]["status"] == "queued"  # 回滚留队
        # run 终态：busy 解除 → 终态 poke 直达恢复派发
        race.race_busy = False
        assert fb.poke_session(SIDS[1]) is True
        probe_until = time.monotonic() + 5.0
        while time.monotonic() < probe_until and not race.starts:
            time.sleep(0.05)
        assert race.starts == [(SIDS[1], "busy竞态后恢复")]
        assert fb.quarantine_status() == {}
    finally:
        fb.stop()


# ---------------------------------------------------------------------------
# SA-SCOPE-HOTFIX-20261125 动态 scope 回归：A→B→A 单例动态绑定 / provider
# 异常 fail-closed / 遗留冻结模式如实保留 / fallback 身份实时跟随引擎。
# ---------------------------------------------------------------------------


def test_dynamic_scope_provider_a_b_a_no_cross_delivery(tmp_path: Path) -> None:
    """共享 data_dir 单例跨 workspace 切换 A→B→A：provider 实时盖章（根治
    实机 q_c8a77451fdfb/q_a26bb24ce757 错章缺陷），各 scope 只领各自条目；
    同 owner 返回按新快照重验（epoch 仅记账不阻断）。"""
    data = tmp_path / "data"
    current = {"scope": "/ws/a", "epoch": 1}
    q = HumanTurnQueue(data, scope_provider=lambda: (current["scope"], current["epoch"]))
    item_a = q.enqueue(SIDS[0], "a-时代")  # 章 A@1
    current.update(scope="/ws/b", epoch=2)
    item_b = q.enqueue(SIDS[0], "b-时代")  # 同一单例章 B@2（冻结实现会错章 A）

    # B 期领取：expected 实时值 → 会话队首是 A 条目（更早创建）→ 严格 FIFO
    # 队首阻断，本轮不派发（迁移态正确语义：不越过他 scope 队首）
    assert q.dispatch_claim(SIDS[0], expected_workspace_scope=current["scope"]) is None
    # 同 owner 返回 A：旧条目按新快照重验放行（不把旧 epoch 误作永久失效）
    current.update(scope="/ws/a", epoch=3)
    got_a = q.dispatch_claim(SIDS[0], expected_workspace_scope=current["scope"])
    assert got_a is not None and got_a["queue_id"] == item_a["queue_id"]
    assert got_a["workspace_scope"] == "/ws/a" and got_a["workspace_epoch"] == 1
    # B 条目留队原样；A 条目终态结算后 B 身份回来领取（跨期不丢不串）
    snap_b = q.snapshot_items()[1]
    assert snap_b["queue_id"] == item_b["queue_id"] and snap_b["status"] == "queued"
    q.mark_terminal(SIDS[0], item_a["queue_id"], "completed")
    current.update(scope="/ws/b")
    got_b2 = q.dispatch_claim(SIDS[0], expected_workspace_scope=current["scope"])
    assert got_b2 is not None and got_b2["queue_id"] == item_b["queue_id"]
    assert got_b2["workspace_scope"] == "/ws/b" and got_b2["workspace_epoch"] == 2


def test_provider_failure_stamps_unbound_fails_closed(tmp_path: Path) -> None:
    """provider 异常 → 不盖章（无章条目），领取按 legacy resolver 裁决：
    无证明 → HOLD unresolved（fail-closed，不虚构归属）。"""
    data = tmp_path / "data"

    def _boom():
        raise RuntimeError("workspace snapshot race")

    q = HumanTurnQueue(data, scope_provider=_boom)
    item = q.enqueue(SIDS[0], "provider 挂了")
    assert "workspace_scope" not in item
    assert q.dispatch_claim(SIDS[0], expected_workspace_scope="/ws/a") is None
    snap = q.snapshot_items()[0]
    assert snap.get("hold_reason") == "queue_hold_legacy_owner_unresolved"


def test_stale_frozen_scope_legacy_mode_regression(tmp_path: Path) -> None:
    """遗留冻结模式（无 provider）如实保留旧语义：错章条目被当前工作区
    HOLD 留队（不删不改可查询），留归属/人工处置——生产装配必须走 provider."""
    data = tmp_path / "data"
    q = HumanTurnQueue(data, workspace_scope="/ws/stale-evo")
    q.enqueue(SIDS[0], "冻结模式旧值")
    current = HumanTurnQueue(data, workspace_scope="/ws/root")
    assert current.dispatch_claim(SIDS[0], expected_workspace_scope="/ws/root") is None
    snap = HumanTurnQueue(data).snapshot_items()[0]
    assert snap["status"] == "queued" and snap["workspace_scope"] == "/ws/stale-evo"


def test_fallback_current_scope_tracks_engine_switch(tmp_path: Path) -> None:
    """fallback 派发身份实时跟随 engine.workspace_root：A 期构造 fallback，
    切换到 B 后旧 scope 条目 HOLD 不错派（冻结实现会按构造值错派）；B 期
    新条目正常派发（无跨目标阻塞/串线）。"""
    runner = _MultiRunner()
    engine = SimpleNamespace(
        runner=runner,
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        workspace_root="/ws/a",
        _workspace_epoch=1,
    )
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    hq.enqueue(SIDS[0], "A 期条目")
    fb = QueueServerFallback(engine, hq, tick_s=3600.0, min_age_s=0.0)

    # 引擎切换（真实语义=workspace_root 更新+epoch 递增）；A 条目入队于切换前
    engine.workspace_root = "/ws/b"
    engine._workspace_epoch = 2
    assert fb.tick_once() == 0  # B 身份不派发 A 条目（冻结实现会错派）
    snap = hq.snapshot_items()[0]
    # scope mismatch 纯读留队（不落盘 hold_reason——归属经 workspace_scope
    # 字段即可查询；落盘会引入 stale 实例覆盖风险，见 human_turn_queue 契约）
    assert snap["status"] == "queued" and snap["workspace_scope"] == "/ws/a"
    assert "hold_reason" not in snap

    # B 期新条目（provider 生产语义入队）正常派发
    hq_b = HumanTurnQueue(tmp_path / "data", scope_provider=lambda: ("/ws/b", 2))
    fb._hq = hq_b
    hq_b.enqueue(SIDS[1], "B 期条目")
    assert fb.tick_once() == 1
    assert runner.starts == [(SIDS[1], "B 期条目")]
