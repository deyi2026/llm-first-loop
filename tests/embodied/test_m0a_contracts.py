"""M0-A 六项必跑合同（DESIGN v2.3 §11.1.1）。每一项都断言动作计数与状态码，
不依赖错误消息字符串。环境：纯内存双桩（stubs.py），零真机/零外网副作用。"""
from __future__ import annotations

import socket
from pathlib import Path

import pytest
from stubs import (
    OBSERVATION_TTL_MS,
    STOP_SAMPLE_INTERVAL_MS,
    DeniedError,
    SimClock,
    StubExecutor,
    StubOracle,
)


def _fresh_executor() -> tuple[SimClock, StubOracle, StubExecutor]:
    clock = SimClock()
    oracle = StubOracle()
    return clock, oracle, StubExecutor(clock, oracle)


def _exec(ex, oracle, grant, obs, intent_key, semantic, skill, params):
    return ex.execute_skill(
        grant_version=grant,
        scene_epoch=oracle.scene_epoch,
        observation_ref=obs.observation_ref,
        intent_key=intent_key,
        semantic_fingerprint=semantic,
        skill=skill,
        params=params,
    )


# ── 合同 1：observation epoch / TTL 边界；无关观察变化不活锁 ──────────────
def test_observation_epoch_ttl(side_effect_sentinel):
    clock, oracle, ex = _fresh_executor()
    grant = ex.issue_grant()

    # 关键场景变化 → 旧 epoch 观察整体失效（含显式 scene_epoch 参数不匹配）
    obs = ex.observe()
    oracle.bump_scene()
    with pytest.raises(DeniedError) as ei:
        _exec(ex, oracle, grant, obs, "i1", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert ei.value.code == "OBSERVATION_STALE_SCENE"
    assert ex.executed_count == 0  # 拒绝 → 零动作

    # 半开区间三点（v2.3 §5.2）：TTL-1ms → 在 [acquired, acquired+TTL) 内，允许执行
    obs2 = ex.observe()
    clock.advance(OBSERVATION_TTL_MS - 1.0)
    receipt = _exec(ex, oracle, grant, obs2, "i1", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert receipt.status == "RUNNING"
    assert ex.executed_count == 1

    # == TTL → now 抵达区间上界 acquired+TTL；半开区间不含上界 → 拒绝
    obs3 = ex.observe()
    clock.advance(OBSERVATION_TTL_MS)
    with pytest.raises(DeniedError) as ei:
        _exec(ex, oracle, grant, obs3, "i2", "place-tray", "place", {"tray_id": "tray-A"})
    assert ei.value.code == "OBSERVATION_STALE_TTL"
    assert ex.executed_count == 1

    # TTL+1ms → 越过区间上界 → 拒绝
    obs4 = ex.observe()
    clock.advance(OBSERVATION_TTL_MS + 1.0)
    with pytest.raises(DeniedError) as ei:
        _exec(ex, oracle, grant, obs4, "i3", "place-tray", "place", {"tray_id": "tray-A"})
    assert ei.value.code == "OBSERVATION_STALE_TTL"
    assert ex.executed_count == 1

    # 无关观察帧风暴（在 TTL 窗口内演练）：不推进 epoch、既有观察仍可用 → 无活锁
    obs5 = ex.observe()
    for _ in range(50):
        ex.bump_irrelevant_frame()
    clock.advance(OBSERVATION_TTL_MS - 1.0)  # now - acquired = TTL-1，仍在半开区间内
    receipt2 = _exec(ex, oracle, grant, obs5, "i4", "place-tray", "place", {"tray_id": "tray-A"})
    assert receipt2.status == "RUNNING"
    assert ex.executed_count == 2
    assert oracle.scene_epoch == 2  # 无关帧未推进 epoch


# ── 合同 2：UNKNOWN → HOLD_WRITE；新 key/同语义重发拒绝；仅可信结案解除 ──
def test_unknown_holds_write_and_reconcile(side_effect_sentinel):
    clock, oracle, ex = _fresh_executor()
    grant = ex.issue_grant()
    obs = ex.observe()

    # 回执丢失 → UNKNOWN（动作已发生，账本计数 1，终态不可达）
    ex.fault_drop_receipt = True
    receipt = _exec(ex, oracle, grant, obs, "u1", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert receipt.status == "UNKNOWN"
    assert ex.executed_count == 1
    assert ex.get_action_status(receipt.action_id).status == "UNKNOWN"

    # 机械冻结自证：UNKNOWN 后写权由双桩自动冻结（不依赖调用方显式登记）
    assert ex.unknown_holds  # 合同 2：超时进入 UNKNOWN/HOLD_WRITE（机械行为）
    ex.mark_unknown("u1")  # 幂等入口：重复登记不改变冻结事实
    with pytest.raises(DeniedError) as ei:  # 新 key 拒
        _exec(ex, oracle, grant, obs, "u2", "place-tray", "place", {"tray_id": "tray-A"})
    assert ei.value.code == "WRITE_FROZEN_UNKNOWN"
    with pytest.raises(DeniedError) as ei:  # 同键同语义重发也拒（不自动重试）
        _exec(ex, oracle, grant, obs, "u1", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert ei.value.code == "WRITE_FROZEN_UNKNOWN"
    assert ex.executed_count == 1  # 冻结期零新增动作

    # 非可信来源结案拒绝
    with pytest.raises(DeniedError) as ei:
        ex.reconcile_unknown("u1", resolved_by="model_claim", release=True)
    assert ei.value.code == "RECONCILE_SOURCE_NOT_TRUSTED"

    # 崩溃重启：UNKNOWN 冻结（持久语义）仍在
    ex.crash_restart()
    with pytest.raises(DeniedError) as ei:
        _exec(ex, oracle, grant, obs, "u3", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert ei.value.code == "WRITE_FROZEN_UNKNOWN"

    # 可信账本结案 → 解除 → 恢复可执行（重启后观察缓存已清，重新观察）
    ex.reconcile_unknown("u1", resolved_by="trusted_ledger", release=True)
    ex.fault_drop_receipt = False
    obs2 = ex.observe()
    receipt2 = _exec(ex, oracle, grant, obs2, "u4", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert receipt2.status == "RUNNING"
    assert ex.executed_count == 2


# ── 合同 3：幂等（同键同参同 action_id；同键异参拒）+ 崩溃恢复不重发 ─────
def test_idempotency_and_crash_recovery(side_effect_sentinel):
    clock, oracle, ex = _fresh_executor()
    grant = ex.issue_grant()
    obs = ex.observe()

    receipt1 = _exec(ex, oracle, grant, obs, "p1", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert receipt1.status == "RUNNING"
    receipt2 = _exec(ex, oracle, grant, obs, "p1", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert receipt2.action_id == receipt1.action_id  # 同键同参 → 同一 action_id
    assert receipt2.status == "RUNNING"
    assert ex.executed_count == 1  # 绝不重复执行

    with pytest.raises(DeniedError) as ei:  # 同键异参 → 拒
        _exec(ex, oracle, grant, obs, "p1", "pick-cube-red", "pick", {"target_id": "cube-blue"})
    assert ei.value.code == "INTENT_CONFLICT"
    with pytest.raises(DeniedError) as ei:  # 同键同参异语义 → 拒
        _exec(ex, oracle, grant, obs, "p1", "pick-something-else", "pick", {"target_id": "cube-red"})
    assert ei.value.code == "INTENT_CONFLICT"
    assert ex.executed_count == 1

    # in-flight + 崩溃重启：账本对账为 INTERRUPTED，不假装成功
    ex.fault_delay_ms = 50.0
    receipt3 = _exec(ex, oracle, grant, obs, "p2", "place-tray", "place", {"tray_id": "tray-A"})
    assert receipt3.status == "RUNNING"
    assert ex.get_action_status(receipt3.action_id).status == "RUNNING"  # 未到完成时刻
    assert ex.executed_count == 2  # 基线：p1+p2 各执行一次
    ex.crash_restart()
    status_after = ex.get_action_status(receipt3.action_id)
    assert status_after.status == "INTERRUPTED"

    # 重启后同键同参 → 返回原 action_id 与账本状态；不重发未知动作
    receipt4 = _exec(ex, oracle, grant, obs, "p2", "place-tray", "place", {"tray_id": "tray-A"})
    assert receipt4.action_id == receipt3.action_id
    assert receipt4.status == "INTERRUPTED"
    assert ex.executed_count == 2  # 重放零新增执行（仍是 p1+p2 各一次）


# ── 合同 4：grant 撤销；STOP_REQUESTED ≠ STOPPED_CONFIRMED；缺证据保持 HOLD ──
def test_grant_revoke_and_stop_semantics(side_effect_sentinel):
    clock, oracle, ex = _fresh_executor()
    grant_v1 = ex.issue_grant()
    ex.revoke_grant(grant_v1)
    obs = ex.observe()
    with pytest.raises(DeniedError) as ei:  # 旧 grant_version 拒绝
        _exec(ex, oracle, grant_v1, obs, "s0", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert ei.value.code == "GRANT_REVOKED"
    assert ex.executed_count == 0

    grant_v2 = ex.issue_grant()
    receipt = _exec(ex, oracle, grant_v2, obs, "s1", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert receipt.status == "RUNNING"
    assert ex.executed_count == 1

    # STOP_REQUESTED ≠ STOPPED_CONFIRMED（两段时基分别记录）
    assert ex.stop() == "STOP_REQUESTED"
    assert ex.stop_requested_at_ms is not None
    assert ex.stop_confirmed_at_ms is None
    assert ex.stop_state() == "STOP_REQUESTED"
    # 样本不足 → STOP_UNCONFIRMED，confirmed 仍为空
    assert ex.poll_stop_confirmation() == "STOP_UNCONFIRMED"
    assert ex.stop_confirmed_at_ms is None
    # 停止请求后新动作 fail-closed 拒绝（保持 HOLD）
    with pytest.raises(DeniedError) as ei:
        _exec(ex, oracle, grant_v2, obs, "s2", "place-tray", "place", {"tray_id": "tray-A"})
    assert ei.value.code == "STOP_PENDING_HOLD"
    assert ex.executed_count == 1
    # 确认窗口超期、证据不足 → 保持 STOP_UNCONFIRMED（fail-closed sticky）
    clock.advance(600.0)
    assert ex.poll_stop_confirmation() == "STOP_UNCONFIRMED"
    assert ex.poll_stop_confirmation() == "STOP_UNCONFIRMED"
    assert ex.stop_confirmed_at_ms is None

    # 正常确认路径（独立实例）：两次间隔采样 → STOPPED_CONFIRMED
    clock2, oracle2, ex2 = _fresh_executor()
    ex2.issue_grant()
    assert ex2.stop() == "STOP_REQUESTED"
    assert ex2.poll_stop_confirmation() == "STOP_UNCONFIRMED"  # 首采样
    clock2.advance(STOP_SAMPLE_INTERVAL_MS)
    assert ex2.poll_stop_confirmation() == "STOPPED_CONFIRMED"
    assert ex2.stop_confirmed_at_ms is not None
    assert ex2.stop_requested_at_ms is not None
    assert ex2.stop_confirmed_at_ms >= ex2.stop_requested_at_ms  # 两段时基各自成立


# ── 合同 5：Oracle 隔离（特权值不外泄）+ 假成功不得进 VERIFIED ───────────
def test_oracle_isolation_and_false_success(side_effect_sentinel):
    clock, oracle, ex = _fresh_executor()
    grant = ex.issue_grant()
    obs = ex.observe()

    # 模型可见观察不含任何 Oracle 特权键（正向白名单：可见键只能是这些非特权键）
    assert set(obs.visible.keys()) <= {"robot_id", "scene_epoch", "held_visible", "known_targets"}
    assert not any(key.startswith("oracle") for key in obs.visible)

    # 先真：真实世界效果满足逐动作后置条件 → VERIFIED
    receipt_true = _exec(ex, oracle, grant, obs, "f1", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert ex.get_action_status(receipt_true.action_id).status == "SUCCEEDED"
    assert ex.verify_with_oracle(receipt_true.action_id) == "VERIFIED"
    assert ex.ledger[receipt_true.action_id].oracle_verified is True
    assert oracle.verify() is False  # 夹持≠已放到目标托盘

    # 后假：执行端自报成功（未知对象，世界零变化）→ 逐动作验收拒绝；先前的 VERIFIED 不传染
    receipt_fake = _exec(ex, oracle, grant, obs, "f2", "pick-cube-ghost", "pick", {"target_id": "cube-ghost"})
    assert ex.get_action_status(receipt_fake.action_id).status == "SUCCEEDED"  # 宣称≠验证
    ex.claim_success(receipt_fake.action_id, evidence_ref="ev:fake:claimed")
    assert ex.verify_with_oracle(receipt_fake.action_id) == "EXECUTED_UNVERIFIED"
    entry_fake = ex.ledger[receipt_fake.action_id]
    assert entry_fake.claimed_success is True
    assert entry_fake.oracle_verified is False
    assert ex.get_action_status(receipt_fake.action_id).status != "VERIFIED"
    assert ex.executed_count == 2

    # 未定态不得置 VERIFIED：RUNNING 与 crash 后 INTERRUPTED 一律拒收验收
    ex.fault_delay_ms = 300.0
    receipt_pending = _exec(ex, oracle, grant, obs, "f3", "place-tray", "place", {"tray_id": "tray-B"})
    assert ex.get_action_status(receipt_pending.action_id).status == "RUNNING"
    with pytest.raises(DeniedError) as ei:
        ex.verify_with_oracle(receipt_pending.action_id)
    assert ei.value.code == "VERIFY_NOT_TERMINAL"
    assert ex.get_action_status(receipt_pending.action_id).status != "VERIFIED"
    ex.crash_restart()
    assert ex.get_action_status(receipt_pending.action_id).status == "INTERRUPTED"
    with pytest.raises(DeniedError) as ei:
        ex.verify_with_oracle(receipt_pending.action_id)
    assert ei.value.code == "VERIFY_NOT_TERMINAL"


# ── P0 回归：未知托盘不能产生可验证的放置效果 ─────────────────────
def test_place_unknown_tray_cannot_claim_verified(side_effect_sentinel):
    """未知托盘不能改变世界，也不能借先前成功动作洗白验收。"""
    _, oracle, ex = _fresh_executor()
    grant = ex.issue_grant()
    obs = ex.observe()
    picked = _exec(ex, oracle, grant, obs, "g1", "pick-red", "pick", {"target_id": "cube-red"})
    assert ex.get_action_status(picked.action_id).status == "SUCCEEDED"
    assert ex.verify_with_oracle(picked.action_id) == "VERIFIED"
    assert oracle.verify() is False

    ghost = _exec(ex, oracle, grant, obs, "g2", "place-ghost", "place", {"tray_id": "tray-ghost"})
    assert ex.get_action_status(ghost.action_id).status == "SUCCEEDED"
    ex.claim_success(ghost.action_id, evidence_ref="ev:claimed:ghost")
    ghost_effect = oracle.effect_of(ghost.action_id)
    assert ghost_effect is not None
    assert ghost_effect["world_changed"] is False
    assert ex.verify_with_oracle(ghost.action_id) == "EXECUTED_UNVERIFIED"
    assert ex.ledger[ghost.action_id].oracle_verified is False
    assert oracle.verify() is False
    assert ex.executed_count == 2

    # 未知托盘失败不得偷偷释放对象；随后合法放置可恢复，且旧失败不可被追认。
    correct = _exec(ex, oracle, grant, obs, "g3", "place-goal", "place", {"tray_id": "tray-A"})
    assert ex.get_action_status(correct.action_id).status == "SUCCEEDED"
    assert ex.verify_with_oracle(correct.action_id) == "VERIFIED"
    assert oracle.verify() is True
    assert ex.verify_with_oracle(ghost.action_id) == "EXECUTED_UNVERIFIED"
    assert ex.executed_count == 3


# ── P1 回归：夹持与错误放置都不是任务完成 ──────────────────────
def test_goal_requires_actual_placement_not_held_or_wrong_tray(side_effect_sentinel):
    """仅抓住目标、空放、放错托盘均不得满足全局目标。"""
    _, oracle, ex = _fresh_executor()
    grant = ex.issue_grant()
    obs = ex.observe()
    assert oracle.verify() is False

    empty = _exec(ex, oracle, grant, obs, "h1", "place-empty", "place", {"tray_id": "tray-A"})
    assert ex.get_action_status(empty.action_id).status == "SUCCEEDED"
    assert ex.verify_with_oracle(empty.action_id) == "EXECUTED_UNVERIFIED"
    assert oracle.verify() is False

    picked = _exec(ex, oracle, grant, obs, "h2", "pick-red", "pick", {"target_id": "cube-red"})
    assert ex.get_action_status(picked.action_id).status == "SUCCEEDED"
    assert ex.verify_with_oracle(picked.action_id) == "VERIFIED"
    assert oracle.verify() is False  # 物体还在夹爪中

    wrong = _exec(ex, oracle, grant, obs, "h3", "place-wrong", "place", {"tray_id": "tray-B"})
    assert ex.get_action_status(wrong.action_id).status == "SUCCEEDED"
    wrong_effect = oracle.effect_of(wrong.action_id)
    assert wrong_effect is not None
    assert wrong_effect["world_changed"] is True
    assert ex.verify_with_oracle(wrong.action_id) == "EXECUTED_UNVERIFIED"
    assert oracle.verify() is False  # 已释放，但不是目标托盘

    again = _exec(ex, oracle, grant, obs, "h4", "repick-red", "pick", {"target_id": "cube-red"})
    assert ex.get_action_status(again.action_id).status == "SUCCEEDED"
    assert ex.verify_with_oracle(again.action_id) == "VERIFIED"
    assert oracle.verify() is False

    correct = _exec(ex, oracle, grant, obs, "h5", "place-correct", "place", {"tray_id": "tray-A"})
    assert ex.get_action_status(correct.action_id).status == "SUCCEEDED"
    assert ex.verify_with_oracle(correct.action_id) == "VERIFIED"
    assert ex.verify_with_oracle(correct.action_id) == "VERIFIED"  # 幂等验收
    assert oracle.verify() is True
    assert ex.verify_with_oracle(wrong.action_id) == "EXECUTED_UNVERIFIED"
    assert ex.executed_count == 5


# ── 合同 6：零真机/零外网副作用（哨兵拦截 + 双桩计数双口径 + 源码静态断言）──
def test_no_hardware_or_network_side_effect(side_effect_sentinel):
    # 静态面：双桩源码不得引用任何网络/进程/系统调用入口
    stub_src = (Path(__file__).resolve().parent / "stubs.py").read_text(encoding="utf-8")
    for forbidden in ("import socket", "import subprocess", "urllib", "requests", "httpx", "os.system", "open(", "eval(", "exec("):
        assert forbidden not in stub_src, f"stub source must not contain: {forbidden}"

    # 拦截能力自证（不触网）：哨兵替换后的 socket 构造必须拒绝并计数，证明拦截器激活
    with pytest.raises(AssertionError):
        socket.socket()
    assert side_effect_sentinel.blocked == ["socket.socket"]
    side_effect_sentinel.blocked.clear()  # 清除自证计数，只保留业务流程证据

    # 动态面：完整闭环（观察→执行→状态→停止确认→Oracle 验收）全部走内存
    clock, oracle, ex = _fresh_executor()
    grant = ex.issue_grant()
    obs = ex.observe()
    receipt = _exec(ex, oracle, grant, obs, "z1", "pick-cube-red", "pick", {"target_id": "cube-red"})
    assert ex.get_action_status(receipt.action_id).status == "SUCCEEDED"
    assert ex.stop() == "STOP_REQUESTED"
    assert ex.poll_stop_confirmation() == "STOP_UNCONFIRMED"
    clock.advance(STOP_SAMPLE_INTERVAL_MS)
    assert ex.poll_stop_confirmation() == "STOPPED_CONFIRMED"
    assert ex.verify_with_oracle(receipt.action_id) == "VERIFIED"

    # 双口径零副作用证据
    assert ex.nw_calls == 0
    assert ex.hw_calls == 0
    assert side_effect_sentinel.blocked == []
