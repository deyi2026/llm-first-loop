"""P0 轻量主统筹：RED 先行纵切验收（SA-LIGHT-COORDINATOR-P0-IMPLEMENT-20261126）.

设计依据：docs/design/DESIGN-20261126-light-coordinator-p0-v2.1.md（R31-R35）。
RED 基线：实现前本套件因 coordinator_light 模块不存在而失败——该失败即当前
瓶颈复现（协调续链需主筹模型调用/等待，无确定性直达）；实现后本文件为常驻
回归套件。全程零主筹模型调用断言=机械动作（文件+队列+只读核验）。
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from llm_loop.web.coordinator_light import (
    dispatch_task_card,
    resolve_role,
    resume_on_approval,
    resume_on_job,
)
from llm_loop.web.human_turn_queue import HumanTurnQueue


class _PokeRecorder:
    """poke 副作用记录（测试替身，替代 QueueServerFallback.poke_session）."""

    def __init__(self):
        self.pokes: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, sid: str) -> bool:
        with self._lock:
            self.pokes.append(sid)
        return True

    def count(self, sid: str) -> int:
        return self.pokes.count(sid)


class _FakeEscalationStore:
    """只读审批记录替身：token 字段存在但 resume 不得读写。"""

    def __init__(self, records: dict[str, dict]):
        self._records = records
        self.token_reads = 0

    def get(self, request_id: str) -> dict | None:
        rec = self._records.get(request_id)
        if rec is None:
            return None
        return dict(rec)

    def consume(self, request_id: str) -> None:  # resume 绝不允许走到这里
        self.token_reads += 1
        raise AssertionError("resume_on_approval 不得消费/签发 token")


def _card(sid: str, op: str, **extra) -> dict:
    return {
        "operation_id": op,
        "target_session": sid,
        "goal_id": "GOAL-TEST",
        "stage": "implement",
        "message": f"任务卡 {op}",
        **extra,
    }


# ---------------------------------------------------------------- 纵切主链


def test_dispatch_creates_durable_card_and_pokes_target(tmp_path: Path) -> None:
    """R32 确定性直达：任务卡入真实队列+审计附件落盘+目标 Worker 唤醒；零模型调用."""
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    poke = _PokeRecorder()
    receipt = dispatch_task_card(
        _card("sess-worker-a", "op-1"),
        inbox_dir=tmp_path,
        poke=poke,
        settings={"coordinator_light_role": "orchestrator"},
        queue=hq,
    )
    assert receipt["accepted"] is True
    assert receipt["queued"] is True and receipt["queue_id"]
    # durable：队列条目（权威）+ 审计附件文件真实落盘且内容完整（含 queue_id 回链）
    files = list((tmp_path / "cards").glob("*.json"))
    assert files, "任务卡附件未持久化"
    stored = json.loads(files[0].read_text(encoding="utf-8"))
    assert stored["operation_id"] == "op-1"
    assert stored["target_session"] == "sess-worker-a"
    assert stored["queue_id"] == receipt["queue_id"]
    assert poke.count("sess-worker-a") == 1


def test_dispatch_idempotent_same_operation_id(tmp_path: Path) -> None:
    """R35 幂等：同 operation_id 重复派工只入队一条、只唤醒一次."""
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    poke = _PokeRecorder()
    r1 = dispatch_task_card(
        _card("sess-a", "op-dup"),
        inbox_dir=tmp_path,
        poke=poke,
        settings={"coordinator_light_role": "orchestrator"},
        queue=hq,
    )
    r2 = dispatch_task_card(
        _card("sess-a", "op-dup"),
        inbox_dir=tmp_path,
        poke=poke,
        settings={"coordinator_light_role": "orchestrator"},
        queue=hq,
    )
    assert r1["accepted"] and r2["accepted"]
    assert r2.get("duplicate") is True
    assert len(list((tmp_path / "cards").glob("*.json"))) == 1
    assert poke.count("sess-a") == 1


def test_dispatch_role_disabled_rejected(tmp_path: Path) -> None:
    """R31 角色可配置：disabled=人工应急回退，派工明确拒绝（不落盘不唤醒）."""

    def _settings_disabled():
        return {"coordinator_light_role": "disabled"}

    poke = _PokeRecorder()
    receipt = dispatch_task_card(
        _card("sess-a", "op-x"),
        inbox_dir=tmp_path,
        poke=poke,
        settings=_settings_disabled(),
    )
    assert receipt["accepted"] is False
    assert "disabled" in str(receipt.get("reason", "")).lower() or receipt.get("reason")
    assert not list(tmp_path.rglob("*.json"))
    assert poke.pokes == []


def test_resolve_role_configurable_not_hardcoded(tmp_path: Path) -> None:
    """R31：角色从 settings/config 读取，worker/orchestrator/disabled 均合法."""
    assert resolve_role({"coordinator_light_role": "worker"}) == "worker"
    assert resolve_role({"coordinator_light_role": "orchestrator"}) == "orchestrator"
    assert resolve_role({}) in {"orchestrator", "worker", "disabled"}  # 缺省安全值
    with pytest.raises((ValueError, KeyError)):
        resolve_role({"coordinator_light_role": "not-a-role"})


# ---------------------------------------------------------------- 审批接续


def test_approval_approved_triggers_verify_and_poke_not_token(tmp_path: Path) -> None:
    """R33：真实 approved 只触发只读核验+来源唤醒；token 链路零触碰."""
    poke = _PokeRecorder()
    store = _FakeEscalationStore(
        {
            "ESC-1": {
                "status": "approved",
                "session_id": "sess-origin",
                "token_expires_at": "2026-11-27T00:00:00",
            }
        }
    )
    receipt = resume_on_approval(store, "ESC-1", poke=poke)
    assert receipt["verified"] is True and receipt["status"] == "approved"
    assert receipt["poked"] is True
    assert poke.count("sess-origin") == 1
    assert store.token_reads == 0  # 绝不触碰签发/消费链


def test_approval_non_approved_not_poked(tmp_path: Path) -> None:
    """pending/denied/expired/未知一律不唤醒（未知副作用不重放）."""
    poke = _PokeRecorder()
    store = _FakeEscalationStore(
        {
            "ESC-p": {"status": "pending", "session_id": "sess-a"},
            "ESC-d": {"status": "denied", "session_id": "sess-a"},
            "ESC-e": {"status": "expired", "session_id": "sess-a"},
        }
    )
    for rid in ("ESC-p", "ESC-d", "ESC-e"):
        receipt = resume_on_approval(store, rid, poke=poke)
        assert receipt["poked"] is False
    missing = resume_on_approval(store, "ESC-unknown", poke=poke)
    assert missing["poked"] is False and missing["verified"] is False
    assert poke.pokes == []


# ---------------------------------------------------------------- Job 接续


def test_job_terminal_resume_requires_exit0_and_sha(tmp_path: Path) -> None:
    """R34：exit0+SHA 匹配才接续；非零/SHA 不匹配不唤醒（权威分别核验）."""
    poke = _PokeRecorder()
    ok = resume_on_job(
        {"job_id": "j1", "exit_code": 0, "artifact_sha256": "ab" * 32, "owner_session": "sess-j"},
        expected_sha256="ab" * 32,
        poke=poke,
    )
    assert ok["poked"] is True and poke.count("sess-j") == 1

    bad_exit = resume_on_job(
        {"job_id": "j2", "exit_code": 1, "artifact_sha256": "ab" * 32, "owner_session": "sess-j"},
        expected_sha256="ab" * 32,
        poke=poke,
    )
    assert bad_exit["poked"] is False

    sha_mismatch = resume_on_job(
        {"job_id": "j3", "exit_code": 0, "artifact_sha256": "cd" * 32, "owner_session": "sess-j"},
        expected_sha256="ab" * 32,
        poke=poke,
    )
    assert sha_mismatch["poked"] is False
    assert poke.count("sess-j") == 1  # 仅 j1 唤醒过一次


def test_job_resume_independent_from_review_verdict(tmp_path: Path) -> None:
    """R34：Reviewer 文字 PASS 不满足 Job 接续（资格分别核验，不互相替代）."""
    poke = _PokeRecorder()
    receipt = resume_on_job(
        {
            "job_id": "j4",
            "exit_code": 0,
            "artifact_sha256": "ef" * 32,
            "owner_session": "sess-k",
            # 只有"审查文字 PASS"，没有精确 SHA 绑定凭据
            "review_verdict_text": "PASS",
        },
        expected_sha256="ef" * 32,
        poke=poke,
        require_binding=True,
    )
    assert receipt["poked"] is False
    assert "binding" in str(receipt.get("reason", ""))


# ---------------------------------------------------------------- 并行与绑定


def test_parallel_dispatch_targets_isolation(tmp_path: Path) -> None:
    """4-8 并行派工卡：各自入队直达目标、零串线（线程安全+全局互斥）."""
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    poke = _PokeRecorder()
    sids = [f"sess-par-{i}" for i in range(8)]
    barrier = threading.Barrier(8)

    def _dispatch(i: int) -> None:
        barrier.wait()
        dispatch_task_card(
            _card(sids[i], f"op-par-{i}"),
            inbox_dir=tmp_path,
            poke=poke,
            settings={"coordinator_light_role": "orchestrator"},
            queue=hq,
        )

    threads = [threading.Thread(target=_dispatch, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(list((tmp_path / "cards").glob("*.json"))) == 8
    assert all(poke.count(s) == 1 for s in sids)
    assert len(poke.pokes) == 8
    entries = [
        i for i in hq.snapshot_items() if i.get("origin") == "coordinator_light"
    ]
    assert len(entries) == 8
    assert {e["session_id"] for e in entries} == set(sids)


def test_stale_generation_card_not_resumed(tmp_path: Path) -> None:
    """R35：旧代次绑定卡不接续（run_generation 绑定，过期不重放）."""
    poke = _PokeRecorder()
    receipt = resume_on_job(
        {
            "job_id": "j5",
            "exit_code": 0,
            "artifact_sha256": "12" * 32,
            "owner_session": "sess-old",
            "bound_run_generation": "gen-100",
        },
        expected_sha256="12" * 32,
        poke=poke,
        current_run_generation="gen-200",
    )
    assert receipt["poked"] is False
    assert "generation" in str(receipt.get("reason", ""))


def test_perf_targets_are_design_goals_only() -> None:
    """防伪造守卫：性能口径必须保持"设计目标"标注，不得宣称实测达标."""
    doc = Path(__file__).resolve().parents[2] / (
        "docs/design/DESIGN-20261126-light-coordinator-p0-v2.1.md"
    )
    text = doc.read_text(encoding="utf-8")
    assert "设计目标，非实测达标声明" in text
    assert "部署前不宣称任何目标" in text


# ---------------------------------------------------------------------------
# 集成层 RED→GREEN（SA-LIGHT-COORDINATOR-P0-INTEGRATION-CORRECTION-20261126）：
# 外部实读五项 P0 缺口——真实队列接线/竞态幂等/审批绑定/job 校验/缺省角色。
# 本段测试先以当前实现真实失败（RED=缺口实证），重构后转 GREEN 常驻回归。
# ---------------------------------------------------------------------------

def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_integration_card_feeds_real_queue_worker_receipt(tmp_path: Path) -> None:
    """真实无害纵切：卡→真实队列→claim→terminal receipt→Job 接续唤醒（零 mock）."""
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    poke = _PokeRecorder()
    receipt = dispatch_task_card(
        _card("sess-w1", "op-integ-1"),
        inbox_dir=tmp_path / "inbox",
        poke=poke,
        settings={"coordinator_light_role": "orchestrator"},
        queue=hq,
    )
    assert receipt["accepted"] is True and receipt["queued"] is True
    # 真实队列可领取（旧实现卡片不入队列 → dispatch_claim 返回 None = RED 缺口）
    claimed = hq.dispatch_claim("sess-w1", expected_workspace_scope="/ws/a")
    assert claimed is not None
    assert claimed["origin"] == "coordinator_light"
    assert claimed["origin_operation_id"] == "op-integ-1"
    # Worker 正常执行 → 终态回写（durable receipt，复用既有链路）
    hq.mark_terminal("sess-w1", claimed["queue_id"], "completed")
    done = next(
        i for i in hq.snapshot_items() if i["queue_id"] == claimed["queue_id"]
    )
    assert done["status"] == "completed"
    # Job 权威回执接续（真实终态事实 → 唤醒来源会话）
    job = {
        "owner_session": "sess-w1",
        "exit_code": 0,
        "artifact_sha256": _sha(b"artifact"),
    }
    cont = resume_on_job(job, expected_sha256=_sha(b"artifact"), poke=poke)
    assert cont["poked"] is True and poke.count("sess-w1") >= 1


def test_integration_dispatch_without_queue_fails_closed(tmp_path: Path) -> None:
    """orchestrator 派工必须有队列权威：无 queue → 拒绝（不落卡不唤醒）."""
    receipt = dispatch_task_card(
        _card("sess-x", "op-noqueue"),
        inbox_dir=tmp_path / "inbox",
        poke=_PokeRecorder(),
        settings={"coordinator_light_role": "orchestrator"},
    )
    assert receipt["accepted"] is False
    assert "queue" in str(receipt.get("reason", ""))


def test_integration_same_key_conflicting_payload_rejected(tmp_path: Path) -> None:
    """同键异载荷：冲突明确拒绝（409 语义），不得误吞为 duplicate."""
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    poke = _PokeRecorder()
    first = dispatch_task_card(
        _card("sess-a", "op-conflict", instruction="do-A"),
        inbox_dir=tmp_path / "inbox",
        poke=poke,
        settings={"coordinator_light_role": "orchestrator"},
        queue=hq,
    )
    assert first["accepted"] is True and first.get("duplicate") is False
    second = dispatch_task_card(
        _card("sess-a", "op-conflict", instruction="do-B"),
        inbox_dir=tmp_path / "inbox",
        poke=poke,
        settings={"coordinator_light_role": "orchestrator"},
        queue=hq,
    )
    assert second["accepted"] is False
    assert second.get("conflict") is True
    # 队列中该 operation 恰一条，载荷仍是 do-A
    entries = [
        i for i in hq.snapshot_items() if i.get("origin_operation_id") == "op-conflict"
    ]
    assert len(entries) == 1 and "do-A" in str(entries[0]["message"])


def test_integration_same_key_same_payload_is_duplicate(tmp_path: Path) -> None:
    """同键同载荷：幂等 duplicate（不重复入队不重复唤醒）."""
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    poke = _PokeRecorder()
    dispatch_task_card(
        _card("sess-a", "op-dup", instruction="same"),
        inbox_dir=tmp_path / "inbox",
        poke=poke,
        settings={"coordinator_light_role": "orchestrator"},
        queue=hq,
    )
    again = dispatch_task_card(
        _card("sess-a", "op-dup", instruction="same"),
        inbox_dir=tmp_path / "inbox",
        poke=poke,
        settings={"coordinator_light_role": "orchestrator"},
        queue=hq,
    )
    assert again["accepted"] is True and again.get("duplicate") is True
    assert again.get("poked") is False
    entries = [
        i for i in hq.snapshot_items() if i.get("origin_operation_id") == "op-dup"
    ]
    assert len(entries) == 1


def test_integration_poke_failure_still_recoverable_via_queue(tmp_path: Path) -> None:
    """唤醒失败不产生死卡：条目已在真实队列，fallback/tick 可兜底领取."""

    class _FailPoke:
        def __call__(self, sid: str) -> bool:
            return False

    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    receipt = dispatch_task_card(
        _card("sess-r", "op-recover"),
        inbox_dir=tmp_path / "inbox",
        poke=_FailPoke(),
        settings={"coordinator_light_role": "orchestrator"},
        queue=hq,
    )
    assert receipt["accepted"] is True and receipt.get("poked") is False
    # 兜底路径（模拟 fallback tick 的同一原子入口）仍可领取执行
    claimed = hq.dispatch_claim("sess-r", expected_workspace_scope="/ws/a")
    assert claimed is not None and claimed["origin_operation_id"] == "op-recover"


def test_integration_concurrent_dispatch_single_queue_entry(tmp_path: Path) -> None:
    """8 线程同键并发：队列恰一条、恰一次 accepted、其余幂等/冲突（不双投）."""
    hq = HumanTurnQueue(tmp_path / "data", workspace_scope="/ws/a")
    results: list[dict] = []
    lock = threading.Lock()

    def _go(i: int) -> None:
        r = dispatch_task_card(
            _card("sess-c", "op-race", instruction="same"),
            inbox_dir=tmp_path / "inbox",
            poke=_PokeRecorder(),
            settings={"coordinator_light_role": "orchestrator"},
            queue=hq,
        )
        with lock:
            results.append(r)

    threads = [threading.Thread(target=_go, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    accepted = [r for r in results if r["accepted"] is True]
    assert len(accepted) == 8  # 全部被受理（1 fresh + 7 duplicate）
    fresh = [r for r in accepted if r.get("duplicate") is False]
    assert len(fresh) == 1
    entries = [
        i for i in hq.snapshot_items() if i.get("origin_operation_id") == "op-race"
    ]
    assert len(entries) == 1


def test_integration_approval_requires_context_binding(tmp_path: Path) -> None:
    """R33 补强：approved 但 goal/scope 绑定不符 → 不唤醒；revoked → 不唤醒."""
    rec = {
        "request_id": "req-b1",
        "status": "approved",
        "session_id": "sess-orig",
        "goal_id": "GOAL-A",
        "workspace_scope": "/ws/a",
    }
    store = _FakeEscalationStore({"req-b1": rec})
    poke = _PokeRecorder()
    r = resume_on_approval(
        store,
        "req-b1",
        poke=poke,
        require_binding={"goal_id": "GOAL-B", "workspace_scope": "/ws/a"},
    )
    assert r["poked"] is False and "binding" in str(r.get("reason", ""))
    rec_revoked = dict(rec, status="revoked")
    store2 = _FakeEscalationStore({"req-b1": rec_revoked})
    r2 = resume_on_approval(store2, "req-b1", poke=poke)
    assert r2["poked"] is False
    # 绑定一致 → 唤醒
    store3 = _FakeEscalationStore({"req-b1": rec})
    r3 = resume_on_approval(
        store3,
        "req-b1",
        poke=poke,
        require_binding={"goal_id": "GOAL-A", "workspace_scope": "/ws/a"},
    )
    assert r3["poked"] is True


def test_integration_job_rejects_bool_exit_code(tmp_path: Path) -> None:
    """bool False 不得等价 exit0（严格 int 类型核验，fail-closed）."""
    poke = _PokeRecorder()
    job = {
        "owner_session": "sess-j",
        "exit_code": False,  # bool，非 int 0
        "artifact_sha256": _sha(b"a"),
    }
    r = resume_on_job(job, expected_sha256=_sha(b"a"), poke=poke)
    assert r["poked"] is False


def test_integration_job_rejects_malformed_record(tmp_path: Path) -> None:
    """job 记录形状校验：缺字段/类型错 → fail-closed 拒绝（不盲 str() 转换）."""
    poke = _PokeRecorder()
    sha = _sha(b"a")
    bad_records = [
        {"exit_code": 0, "artifact_sha256": sha},  # 缺 owner
        {"owner_session": 123, "exit_code": 0, "artifact_sha256": sha},  # owner 非字符串
        {"owner_session": "s", "exit_code": "0", "artifact_sha256": sha},  # exit 非数字
        {"owner_session": "s", "exit_code": 0, "artifact_sha256": "nothex"},  # sha 非 64-hex
        "not-a-dict",
    ]
    for job in bad_records:
        r = resume_on_job(job, expected_sha256=sha, poke=poke)
        assert r["poked"] is False, f"malformed record 不得唤醒: {job!r}"


def test_integration_job_binding_must_be_sha256_hex(tmp_path: Path) -> None:
    """R34：绑定凭据必须是 64-hex 精确 SHA——任意非空值不再通过."""
    poke = _PokeRecorder()
    sha = _sha(b"artifact")
    job = {
        "owner_session": "sess-b",
        "exit_code": 0,
        "artifact_sha256": sha,
        "binding_sha256": "reviewer-said-pass",  # 非空但非 SHA
    }
    r = resume_on_job(
        job, expected_sha256=sha, poke=poke, require_binding=True
    )
    assert r["poked"] is False
    ok = dict(job, binding_sha256=sha)
    r2 = resume_on_job(ok, expected_sha256=sha, poke=poke, require_binding=True)
    assert r2["poked"] is True


def test_integration_default_role_is_disabled(tmp_path: Path) -> None:
    """R31 fail-closed：无显式配置 → disabled（普通聊天原行为；orchestrator
    必须可信服务端显式指派）."""
    assert resolve_role(None) == "disabled"
    assert resolve_role({}) == "disabled"


def test_integration_restart_rediscovers_active_cards(tmp_path: Path) -> None:
    """重启恢复：卡片入队后进程重启（新实例重载），条目仍可领取执行
    （durable 事实在队列文件，不依赖进程内存/唤醒）。"""
    data = tmp_path / "data"
    hq1 = HumanTurnQueue(data, workspace_scope="/ws/a")
    dispatch_task_card(
        _card("sess-rs", "op-restart"),
        inbox_dir=tmp_path / "inbox",
        poke=_PokeRecorder(),
        settings={"coordinator_light_role": "orchestrator"},
        queue=hq1,
    )
    hq2 = HumanTurnQueue(data, workspace_scope="/ws/a")  # 模拟重启重载
    claimed = hq2.dispatch_claim("sess-rs", expected_workspace_scope="/ws/a")
    assert claimed is not None and claimed["origin_operation_id"] == "op-restart"
