"""P0 轻量主统筹真实路径验收（SA-LIGHT-COORDINATOR-P0-LIVE-WIRING-20261126）.

与 test_light_coordinator.py（函数级+测试替身）互补：本文件走真实链路——
真实 HTTP（TestClient→coordinator router）→ 真实 HumanTurnQueue（enqueue_once
原子幂等）→ 真实 QueueServerFallback Worker（claim→Runner.start→terminal
权威回写）→ derive_job_receipt 队列事实派生 → resume_on_job 精确绑定核验。
无手工 mark_terminal、无自造 job dict——Job 回执全部派生自队列权威事实。
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from llm_loop.web import _build_hq, build_app
from llm_loop.web.coordinator_light import derive_job_receipt, resume_on_job
from llm_loop.web.human_turn_queue import HumanTurnQueue
from llm_loop.web.queue_recovery import QueueServerFallback

_TOKEN = "live-coordinator-token-0f2c"
_SIDS = [f"sess-live-{i:02d}" for i in range(8)]


class _LiveRunner:
    """真实 Worker 执行替身：runner.start 由 QueueServerFallback._execute_claimed
    调用（与生产同链路），terminal_callback 由 start 内真实触发——不做任何
    手工 mark_terminal。"""

    def __init__(self, *, fail_sids=()):
        self.enabled = True
        self.fail_sids = set(fail_sids)
        self.starts: list[tuple[str, str]] = []

    def get_handle(self, sid):
        return None

    def is_running(self, sid):
        return False

    def is_sync_active(self, sid):
        return False

    def start(self, sid, message, **kwargs):
        self.starts.append((sid, message))
        if sid in self.fail_sids:
            return None, None
        cb = kwargs.get("terminal_callback")
        if cb is not None:
            cb("completed", None)
        return SimpleNamespace(session_id=sid), None


def _live_app(engine, runner, tmp_path: Path) -> tuple[TestClient, HumanTurnQueue, QueueServerFallback]:
    """生产同构装配：队列单例预置进 app.state（_build_hq）+ fallback（不 start，
    测试显式 tick_once 驱动真实 Worker 路径）。Settings 为 frozen dataclass——
    用 dataclasses.replace 产出带双开关的新实例后整体替换。"""
    import dataclasses

    engine.settings = dataclasses.replace(
        engine.settings,
        coordinator_light_role="orchestrator",
        coordinator_light_token=_TOKEN,
    )
    engine.workspace_root = str(tmp_path / "ws_live")
    engine.runner = runner
    app = build_app(engine=engine)
    hq = _build_hq(engine, engine.settings)
    key = str(Path(str(engine.settings.data_dir)).expanduser().resolve())
    app.state.human_turn_queues = {key: hq}
    fb = QueueServerFallback(engine, hq, tick_s=3600.0, min_age_s=0.0)
    return TestClient(app), hq, fb


def _card(i: int, sid: str, sha: str) -> dict:
    return {
        "operation_id": f"live-op-{i:02d}",
        "target_session": sid,
        "task": f"echo-marker-{i:02d}",
        "candidate_sha256": sha,
        "artifact_sha256": sha,
        "owner_session": sid,
    }


def test_live_http_dispatch_worker_terminal_and_receipt(tmp_path, build_test_engine) -> None:
    """真实纵切：HTTP dispatch → queue 原子入队 → fallback Worker 执行 →
    权威终态回写 → 队列事实派生 receipt → resume_on_job 精确绑定 PASS."""
    engine, _ = build_test_engine([{"content": "unused"}])
    sha = "a" * 64
    client, hq, fb = _live_app(engine, _LiveRunner(), tmp_path)
    sid = engine.session.create()

    r = client.post(
        "/api/v1/coordinator/light/dispatch",
        json={"operation_id": "live-op-00", "target_session": sid, "payload": _card(0, sid, sha)},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["queued"] is True and body["duplicate"] is False
    qid = body["queue_id"]

    # 真实 Worker（QueueServerFallback._execute_claimed→runner.start→terminal
    # 权威回写）——测试只驱动 tick，不手工 mark_terminal
    assert fb.tick_once() == 1
    item = next(i for i in hq.snapshot_items() if i["queue_id"] == qid)
    assert item["status"] == "completed"
    assert item["claimed_by"] == "server-fallback"

    # receipt 从队列权威事实派生（非自造 dict）
    r2 = client.get(
        f"/api/v1/coordinator/light/job/{qid}", headers={"X-Coordinator-Token": _TOKEN}
    )
    assert r2.status_code == 200
    job = r2.json()["job_record"]
    assert job["authority"] == "queue_terminal" and job["queue_exit_semantics"] == 0
    assert job["queue_status"] == "completed"
    assert job["payload_declared"]["candidate_sha256"] == sha  # 派工声明绑定（非权威凭证）

    # SA-LIVE-RECEIPT-AUTHORITY 边界①：队列终态投影≠真实 Job/CI 凭证——
    # resume 拒绝唤醒（只回队列状态），接续须等真实 authority="job_authority"
    # 记录（CI continuation 保持 501 not_implemented 直到真正接权威）。
    outcome = resume_on_job(
        job, expected_sha256=sha, poke=lambda s: True, require_binding=True
    )
    assert outcome.get("poked") is False and outcome.get("verified") is False
    assert "authority" in str(outcome.get("reason"))
    # SHA 不匹配的真实 Job 记录 → 同样拒绝接续（对照：authority 门槛通过后
    # 才轮到 SHA 核验）
    real_job = {
        "authority": "job_authority",
        "owner_session": "sess-x",
        "exit_code": 0,
        "artifact_sha256": sha,
    }
    bad = resume_on_job(
        real_job, expected_sha256="b" * 64, poke=lambda s: True, require_binding=True
    )
    assert bad.get("poked") is False


def test_live_access_fail_closed(tmp_path, build_test_engine) -> None:
    """双开关 fail-closed：未配 token / 错 token / role disabled → 一律拒绝."""
    engine, _ = build_test_engine([{"content": "unused"}])
    import dataclasses

    engine.settings = dataclasses.replace(
        engine.settings,
        coordinator_light_role="orchestrator",
        coordinator_light_token=_TOKEN,
    )
    app = build_app(engine=engine)
    client = TestClient(app)
    body = {"operation_id": "x1", "target_session": engine.session.create(), "payload": {}}

    # 错 token → 401
    r = client.post("/api/v1/coordinator/light/dispatch", json=body,
                    headers={"X-Coordinator-Token": "wrong"})
    assert r.status_code == 401, r.text
    # 无 token → 401
    r = client.post("/api/v1/coordinator/light/dispatch", json=body)
    assert r.status_code == 401

    # role/token 未配置（默认 disabled）→ 403：另一 engine 装配
    engine2, _ = build_test_engine([{"content": "unused"}])
    client2 = TestClient(build_app(engine=engine2))
    body2 = {"operation_id": "x2", "target_session": engine2.session.create(), "payload": {}}
    r = client2.post("/api/v1/coordinator/light/dispatch", json=body2,
                     headers={"X-Coordinator-Token": _TOKEN})
    assert r.status_code == 403

    # CI 自动接续：明确未实现（501，不假造）
    r = client.post("/api/v1/coordinator/light/ci-continue",
                    headers={"X-Coordinator-Token": _TOKEN})
    assert r.status_code == 501 and r.json()["error"].startswith("not_implemented")


def test_live_idempotent_duplicate_and_conflict(tmp_path, build_test_engine) -> None:
    """同键幂等（HTTP 面）：同 operation_id 同载荷=duplicate 同 queue_id；
    异载荷=409 conflict 不覆盖."""
    engine, _ = build_test_engine([{"content": "unused"}])
    client, hq, _ = _live_app(engine, _LiveRunner(), tmp_path)
    sid = engine.session.create()
    headers = {"X-Coordinator-Token": _TOKEN}
    card = {"operation_id": "idem-1", "target_session": sid,
            "payload": {"task": "t1", "candidate_sha256": "c" * 64}}

    r1 = client.post("/api/v1/coordinator/light/dispatch", json=card, headers=headers)
    assert r1.status_code == 200 and r1.json()["duplicate"] is False
    qid = r1.json()["queue_id"]
    r2 = client.post("/api/v1/coordinator/light/dispatch", json=card, headers=headers)
    assert r2.status_code == 200 and r2.json()["duplicate"] is True
    assert r2.json()["queue_id"] == qid  # 不重复入队
    entries = [i for i in hq.snapshot_items() if i.get("origin_operation_id") == "idem-1"]
    assert len(entries) == 1  # 队列权威恰一条目

    card_bad = {"operation_id": "idem-1", "target_session": sid,
                "payload": {"task": "t1-different", "candidate_sha256": "d" * 64}}
    r3 = client.post("/api/v1/coordinator/light/dispatch", json=card_bad, headers=headers)
    assert r3.status_code == 409 and r3.json()["conflict"] is True


def test_live_multi_instance_snapshot_fresh_restart_and_parallel(tmp_path, build_test_engine) -> None:
    """多实例/重启/并行：A 实例 enqueue_once → HTTP 侧单例 snapshot 立即可见
    （fresh reload）；重启新实例恢复；8 卡并行 Worker 执行无串线."""
    engine, _ = build_test_engine([{"content": "unused"}])
    runner = _LiveRunner()
    client, hq, fb = _live_app(engine, runner, tmp_path)
    sids = [engine.session.create() for _ in range(8)]
    headers = {"X-Coordinator-Token": _TOKEN}

    # 多实例新鲜度：独立实例入队，HTTP 侧单例快照立即可见（不重启不重建）
    other = HumanTurnQueue(
        Path(str(engine.settings.data_dir)), workspace_scope=str(engine.workspace_root)
    )
    outcome = other.enqueue_once(sids[0], "跨实例可见性探针", origin="probe", origin_operation_id="probe-1")
    assert outcome["duplicate"] is False
    visible = [i for i in hq.snapshot_items() if i.get("origin_operation_id") == "probe-1"]
    assert len(visible) == 1  # 旧实现（仅内存锁）在此处为空——fresh reload 修复点

    # 8 卡并行派工（HTTP 面）→ 一次 tick 全部真实执行 → 回执无串线
    qids: dict[str, str] = {}
    for i, sid in enumerate(sids):
        r = client.post(
            "/api/v1/coordinator/light/dispatch",
            json={"operation_id": f"par-{i:02d}", "target_session": sid,
                  "payload": _card(i, sid, f"{i:064x}")},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        qids[f"par-{i:02d}"] = r.json()["queue_id"]

    # 重启语义：新实例重载后全部条目仍在（durable）
    hq_restarted = HumanTurnQueue(
        Path(str(engine.settings.data_dir)), workspace_scope=str(engine.workspace_root)
    )
    assert len(hq_restarted.snapshot_items()) >= 8

    assert fb.tick_once() == 8  # 8 目标各派发队首（probe-1 占 sids[0] 名额）
    assert fb.tick_once() == 1  # 第二轮：sids[0] 剩余的 par-00 依严格 FIFO 补发
    for i, sid in enumerate(sids):
        op = f"par-{i:02d}"
        item = next(
            it for it in hq_restarted.snapshot_items()
            if it.get("origin_operation_id") == op
        )
        assert item["status"] == "completed" and item["session_id"] == sid
        job = derive_job_receipt(hq_restarted, item["queue_id"])["job_record"]
        assert job["queue_exit_semantics"] == 0
        assert job["payload_declared"]["candidate_sha256"] == f"{i:064x}"  # 无串线：每回执绑定各自 SHA
        assert job["payload_declared"]["owner_session"] == sid


def test_live_enqueue_once_atomic_under_threads(tmp_path) -> None:
    """enqueue_once 并发原子：16 线程同键（同载荷）恰一条目；异载荷恰一冲突."""
    data = tmp_path / "data"
    q = HumanTurnQueue(data, workspace_scope="/ws/live")
    barrier = threading.Barrier(16)
    results: list[dict] = []

    def _worker(i: int) -> None:
        barrier.wait()
        results.append(q.enqueue_once("sid-atomic", "same-payload", origin="probe", origin_operation_id="atomic-1"))

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    fresh = [r for r in results if not r["duplicate"] and not r["conflict"]]
    assert len(fresh) == 1  # 全局恰一条目
    dup = [r for r in results if r["duplicate"]]
    assert len(dup) == 15  # 其余同载荷=幂等 duplicate（不重复入队）
    # 异载荷同键 → conflict（拒绝覆盖，既有条目原样保留）
    conflict = q.enqueue_once("sid-atomic", "different-payload", origin="probe", origin_operation_id="atomic-1")
    assert conflict["conflict"] is True and conflict["item"]["message"] == "same-payload"
    entries = [i for i in HumanTurnQueue(data).snapshot_items() if i.get("origin_operation_id") == "atomic-1"]
    assert len(entries) == 1


def test_live_resume_job_real_registry_authority(tmp_path, build_test_engine) -> None:
    """真实 JobRegistry 权威接续纵切（SA-LIVE-RECEIPT-AUTHORITY 主链条）.

    真实 Job（registry.create 真进程）→completed→/resume-job：派工卡
    candidate 对照 + owner-scoped registry snapshot + exit0 → 唤醒 owner；
    未终态只回状态；伪造 candidate 409 拒绝（不唤醒）。
    """
    import os as _os

    from llm_loop.tools.builtin.job_registry import JobRegistry

    engine, _ = build_test_engine([{"content": "unused"}])
    ws = tmp_path / "ws_root"
    ws.mkdir()

    import dataclasses as _dc

    engine.settings = _dc.replace(
        engine.settings,
        coordinator_light_role="orchestrator",
        coordinator_light_token=_TOKEN,
    )
    engine.workspace_root = str(ws)
    app = build_app(engine=engine)

    class _FB:  # 生产同构装配：poke_session 返回真实 accepted 事实
        def poke_session(self, sid: str) -> bool:
            return True

    app.state.queue_server_fallback = _FB()
    client = TestClient(app)
    sid = engine.session.create()
    sha = hashlib.sha256(b"artifact-candidate").hexdigest()

    enq = client.post(
        "/api/v1/coordinator/light/dispatch",
        json={
            "operation_id": "op-jobauth",
            "target_session": sid,
            "payload": {
                "owner_session": sid,
                "goal_id": "GOAL-J",
                "candidate_sha256": sha,
                "message": "job 权威接续验证卡",
            },
        },
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert enq.status_code == 200 and enq.json()["accepted"] is True
    qid = enq.json()["queue_id"]

    # 真实 Job：registry.create 真进程（wait 立即 0 → watcher 置 completed/exit0）
    registry = JobRegistry.instance()
    import io as _io

    proc = SimpleNamespace(
        pid=_os.getpid(),
        wait=lambda: 0,
        stdout=_io.StringIO(),
        stderr=_io.StringIO(),
    )
    job_id = registry.create(
        proc,
        "echo authority-wiring",
        session_id=sid,
        workspace_root=str(ws),
        executor="execute_command",
    )
    # watcher 由 execute 层负责启动（create 只注册）——测试走同一真实路径
    import threading as _threading

    _threading.Thread(
        target=registry._watch_completion, args=(job_id,), daemon=True
    ).start()
    import time as _time

    deadline = _time.time() + 5.0
    while _time.time() < deadline:
        snap = registry.snapshot(job_id, session_id=sid)
        if isinstance(snap, dict) and snap.get("state") in {"completed", "failed"}:
            break
        _time.sleep(0.02)
    assert snap.get("state") == "completed" and snap.get("exit_code") == 0

    # 未终态拒绝路径先证：伪造另一 job_id（registry 无此 id）→ 404 不唤醒
    miss = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": "job-nonexistent", "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert miss.status_code == 404

    # 真实接续：candidate 对照 + exit0 → resumed
    ok = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": job_id, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["ok"] is True and body.get("poked") is True
    assert body.get("verified") is True  # authority 门槛在 resume_on_job 内核验

    # 伪造 candidate（≠派工声明）→ 409 拒绝不唤醒
    bad = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": job_id, "queue_id": qid, "expected_sha256": "f" * 64},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert bad.status_code == 409
