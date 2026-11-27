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
                "bound_run_generation": "run-live-1",
                "message": "job 权威接续验证卡",
            },
        },
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert enq.status_code == 200 and enq.json()["accepted"] is True
    qid = enq.json()["queue_id"]

    # 真实 Job：registry.create 真进程（wait 立即 0 → watcher 置 completed/exit0）；
    # origin_run_generation 以 contextvar 盖章=run-live-1（与派工卡声明匹配）
    registry = JobRegistry.instance()
    import io as _io

    from llm_loop.core.run_context import current_run_generation as _crun

    _gen_token = _crun.set("run-live-1")
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
        origin_operation_id="op-jobauth",
    )
    _crun.reset(_gen_token)
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

    # SA-PR145-EXACT-JOB-BINDING 幂等：同 job 二次接续 → duplicate 不重放
    dup = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": job_id, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert dup.status_code == 200
    dup_body = dup.json()
    assert dup_body.get("duplicate") is True and dup_body.get("resumed") is False


def test_live_resume_job_rejects_stale_or_unbound_jobs(tmp_path, build_test_engine) -> None:
    """主筹隔离负测实证三路径收口：同 owner/scope 旧代次 Job、缺 workspace_root、
    缺 session_id 一律拒绝（不同 owner 任意旧成功 Job 不可冒认当前候选）."""
    import io as _io
    import os as _os
    import time as _time
    from types import SimpleNamespace

    from llm_loop.core.run_context import current_run_generation as _crun
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

    class _FB:
        def poke_session(self, sid: str) -> bool:
            return True

    app.state.queue_server_fallback = _FB()
    client = TestClient(app)
    sid = engine.session.create()
    sha = "a" * 64

    enq = client.post(
        "/api/v1/coordinator/light/dispatch",
        json={
            "operation_id": "op-stale",
            "target_session": sid,
            "payload": {
                "owner_session": sid,
                "goal_id": "GOAL-J",
                "candidate_sha256": sha,
                "bound_run_generation": "run-new",
                "message": "旧代次拒绝验证卡",
            },
        },
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert enq.status_code == 200
    qid = enq.json()["queue_id"]

    registry = JobRegistry.instance()

    def _mk_job(run_gen: str, *, session_id: str = sid, workspace_root: str = str(ws)):
        tok = _crun.set(run_gen)
        try:
            return registry.create(
                SimpleNamespace(pid=_os.getpid(), wait=lambda: 0, stdout=_io.StringIO(), stderr=_io.StringIO()),
                "echo stale-probe",
                session_id=session_id,
                workspace_root=workspace_root,
                executor="execute_command",
            )
        finally:
            _crun.reset(tok)

    old_job = _mk_job("run-old")
    _thread_probe = __import__("threading").Thread(
        target=registry._watch_completion, args=(old_job,), daemon=True
    )
    _thread_probe.start()
    deadline = _time.time() + 5.0
    while _time.time() < deadline:
        snap = registry.snapshot(old_job, session_id=sid)
        if isinstance(snap, dict) and snap.get("state") in {"completed", "failed"}:
            break
        _time.sleep(0.02)
    assert snap.get("state") == "completed"

    # ① 同 owner/scope 旧代次 Job → 409 generation mismatch（不唤醒）
    stale = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": old_job, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert stale.status_code == 409
    assert "generation mismatch" in stale.text

    # ② job 缺 workspace_root → 归属不明拒绝（404/409，不唤醒）
    noscope_job = _mk_job("run-new", workspace_root="")
    noscope = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": noscope_job, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert noscope.status_code in (404, 409)
    assert "workspace" in noscope.text

    # ③ job 缺 session_id → owner 绑定缺失拒绝（不回退派工声明）
    nosess_job = _mk_job("run-new", session_id="")
    nosess = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": nosess_job, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert nosess.status_code in (404, 409)
    assert "session_id" in nosess.text

    # ④ 已接续其他 Job 的卡片 → 409 一卡一 Job（先接续匹配代次的真 Job）
    from llm_loop.core.run_context import current_run_generation as _cr2

    tok2 = _cr2.set("run-new")
    good_job = registry.create(
        SimpleNamespace(pid=_os.getpid(), wait=lambda: 0, stdout=_io.StringIO(), stderr=_io.StringIO()),
        "echo stale-probe-good",
        session_id=sid,
        workspace_root=str(ws),
        executor="execute_command",
        origin_operation_id="op-stale",
    )
    _cr2.reset(tok2)
    _tg = __import__("threading").Thread(
        target=registry._watch_completion, args=(good_job,), daemon=True
    )
    _tg.start()
    deadline = _time.time() + 5.0
    while _time.time() < deadline:
        gsnap = registry.snapshot(good_job, session_id=sid)
        if isinstance(gsnap, dict) and gsnap.get("state") in {"completed", "failed"}:
            break
        _time.sleep(0.02)
    ok = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": good_job, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert ok.status_code == 200 and ok.json().get("poked") is True
    other = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": old_job, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert other.status_code == 409 and (
        "已接续其他" in other.text or "mismatch" in other.text
    )  # stale Job：代次/operation 任一守卫先拒均合法（幂等面在其后）


def test_live_resume_job_real_subprocess_end_to_end(tmp_path, build_test_engine) -> None:
    """真正 subprocess 纵切：Popen 真进程经 registry 监听置 completed →
    resume-job 端点唤醒（替换 SimpleNamespace 假 proc，可宣称真实进程执行）."""
    import hashlib as _hl
    import subprocess as _sp
    import time as _time

    from llm_loop.core.run_context import current_run_generation as _crun
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

    class _FB:
        def poke_session(self, sid: str) -> bool:
            return True

    app.state.queue_server_fallback = _FB()
    client = TestClient(app)
    sid = engine.session.create()
    sha = _hl.sha256(b"real-subprocess-candidate").hexdigest()

    enq = client.post(
        "/api/v1/coordinator/light/dispatch",
        json={
            "operation_id": "op-subproc",
            "target_session": sid,
            "payload": {
                "owner_session": sid,
                "goal_id": "GOAL-J",
                "candidate_sha256": sha,
                "bound_run_generation": "run-sub",
                "message": "真进程接续验证卡",
            },
        },
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert enq.status_code == 200
    qid = enq.json()["queue_id"]

    registry = JobRegistry.instance()
    real_proc = _sp.Popen(
        [_sp.sys.executable, "-c", "import time; time.sleep(0.2)"],
        stdout=_sp.PIPE,
        stderr=_sp.PIPE,
    )
    tok = _crun.set("run-sub")
    job_id = registry.create(
        real_proc,
        "python -c sleep",
        session_id=sid,
        workspace_root=str(ws),
        executor="execute_command",
        origin_operation_id="op-subproc",
    )
    _crun.reset(tok)
    import threading as _threading

    _threading.Thread(target=registry._watch_completion, args=(job_id,), daemon=True).start()
    deadline = _time.time() + 10.0
    while _time.time() < deadline:
        snap = registry.snapshot(job_id, session_id=sid)
        if isinstance(snap, dict) and snap.get("state") in {"completed", "failed"}:
            break
        _time.sleep(0.05)
    assert snap.get("state") == "completed" and snap.get("exit_code") == 0

    ok = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": job_id, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json().get("poked") is True


# ---------------------------------------------------------------------------
# SA-PR145-FINAL-ATOMIC-RESUME 三例 P1 负测（主筹 2026-11-27 11:41 隔离测试
# 实失败三例的收口固化）：①无关联 Job 冒认；②并发双唤醒；③cards 写失败
# 重放。真实 _resume_job_from_registry 路径 + 临时目录 + 内存 poke 计数，
# 零生产副作用。
# ---------------------------------------------------------------------------


class _CountingFallback:
    """poke 计数替身（真实 accepted 事实口径：返回 True 计数一次）."""

    def __init__(self) -> None:
        self.wake: list[str] = []
        self._lock = threading.Lock()

    def poke_session(self, sid: str) -> bool:
        with self._lock:
            self.wake.append(sid)
        return True


def _atomic_resume_harness(tmp_path, build_test_engine, *, operation_id: str):
    """公共 harness：engine+token+真实 fallback 计数 + 派工卡（含
    bound_run_generation）→ 返回 (client, engine, sid, sha, qid, fb)."""
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
    fb = _CountingFallback()
    app.state.queue_server_fallback = fb
    client = TestClient(app)
    sid = engine.session.create()
    sha = hashlib.sha256(b"artifact-candidate").hexdigest()
    enq = client.post(
        "/api/v1/coordinator/light/dispatch",
        json={
            "operation_id": operation_id,
            "target_session": sid,
            "payload": {
                "owner_session": sid,
                "goal_id": "GOAL-ATOMIC",
                "candidate_sha256": sha,
                "bound_run_generation": "run-atomic",
                "message": "原子接续验证卡",
            },
        },
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert enq.status_code == 200 and enq.json()["accepted"] is True
    return client, engine, sid, sha, enq.json()["queue_id"], fb, ws


def _completed_job(registry, sid: str, ws, *, operation_id: str, gen: str = "run-atomic") -> str:
    import io as _io
    import os as _os

    from llm_loop.core.run_context import current_run_generation as _crun

    token = _crun.set(gen)
    proc = SimpleNamespace(pid=_os.getpid(), wait=lambda: 0, stdout=_io.StringIO(), stderr=_io.StringIO())
    job_id = registry.create(
        proc,
        "echo atomic-resume",
        session_id=sid,
        workspace_root=str(ws),
        executor="execute_command",
        origin_operation_id=operation_id,
    )
    _crun.reset(token)
    import threading as _threading
    import time as _time

    _threading.Thread(target=registry._watch_completion, args=(job_id,), daemon=True).start()
    deadline = _time.time() + 5.0
    while _time.time() < deadline:
        snap = registry.snapshot(job_id, session_id=sid)
        if isinstance(snap, dict) and snap.get("state") in {"completed", "failed"}:
            break
        _time.sleep(0.02)
    assert snap.get("state") == "completed" and snap.get("exit_code") == 0
    return job_id


def test_p1_unbound_job_cannot_claim_operation(tmp_path, build_test_engine) -> None:
    """P1-1：同 owner/scope/同 generation 但创建时未绑定 operation 的成功 Job
    → 409 operation binding mismatch，零唤醒（不可冒认）."""

    from llm_loop.tools.builtin.job_registry import JobRegistry

    client, engine, sid, sha, qid, fb, ws = _atomic_resume_harness(
        tmp_path, build_test_engine, operation_id="op-bound"
    )
    registry = JobRegistry.instance()
    # 无关联 Job：同 owner/scope/gen，但 create 不传 origin_operation_id
    unbound = _completed_job(registry, sid, ws, operation_id="")
    r = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": unbound, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert r.status_code == 409 and "operation binding mismatch" in r.text
    before = len(fb.wake)  # dispatch 入队 poke 已计一次；拒绝不再增加
    # 关联 Job → 正常接续（对照：守卫不误伤）
    good = _completed_job(registry, sid, ws, operation_id="op-bound")
    r2 = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": good, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert r2.status_code == 200 and r2.json().get("poked") is True
    assert len(fb.wake) == before + 1  # 仅对照接续新增一次


def test_p1_concurrent_resume_wakes_once(tmp_path, build_test_engine) -> None:
    """P1-2：并发两次同一接续请求（Barrier 同步）→ 恰一次唤醒、一次幂等拒绝
    （wake_count==1，原子标记单赢家）."""
    import threading as _threading

    from llm_loop.tools.builtin.job_registry import JobRegistry

    client, engine, sid, sha, qid, fb, ws = _atomic_resume_harness(
        tmp_path, build_test_engine, operation_id="op-conc"
    )
    job_id = _completed_job(JobRegistry.instance(), sid, ws, operation_id="op-conc")
    barrier = _threading.Barrier(2)
    results: list = []
    lock = threading.Lock()

    def _go() -> None:
        barrier.wait()
        r = client.post(
            "/api/v1/coordinator/light/resume-job",
            json={"job_id": job_id, "queue_id": qid, "expected_sha256": sha},
            headers={"X-Coordinator-Token": _TOKEN},
        )
        with lock:
            results.append((r.status_code, r.json()))

    threads = [_threading.Thread(target=_go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    poked = [b for _, b in results if b.get("poked") is True]
    assert len(poked) == 1, f"并发双唤醒: {results}"
    before = len(fb.wake)
    r_after = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": job_id, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert r_after.json().get("duplicate") is True
    assert len(fb.wake) == before  # 并发后重复请求零新增唤醒
    assert len(results) == 2
    # 非赢家必然 duplicate（原子幂等拒绝重放）
    dup = [b for _, b in results if b.get("poked") is not True]
    assert dup and (dup[0].get("duplicate") is True or dup[0].get("poked") is False)


def test_p1_cards_write_failure_never_replays(tmp_path, build_test_engine) -> None:
    """P1-3：cards 审计写失败（OSError）不影响接续事实（幂等权威在队列原子
    标记）；重复请求 duplicate 不重放（wake_count==1）；重启重载同样幂等."""

    import llm_loop.web.coordinator_light as _cl
    from llm_loop.tools.builtin.job_registry import JobRegistry

    client, engine, sid, sha, qid, fb, ws = _atomic_resume_harness(
        tmp_path, build_test_engine, operation_id="op-writefail"
    )
    job_id = _completed_job(JobRegistry.instance(), sid, ws, operation_id="op-writefail")

    orig = _cl._atomic_write_json

    def _boom(*a, **k):
        raise OSError("simulated disk full")

    _cl._atomic_write_json = _boom
    try:
        r1 = client.post(
            "/api/v1/coordinator/light/resume-job",
            json={"job_id": job_id, "queue_id": qid, "expected_sha256": sha},
            headers={"X-Coordinator-Token": _TOKEN},
        )
        assert r1.status_code == 200 and r1.json().get("poked") is True
        wake_after_first = len(fb.wake)  # dispatch poke + 接续 poke
    finally:
        _cl._atomic_write_json = orig

    r2 = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": job_id, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert r2.status_code == 200 and r2.json().get("duplicate") is True
    assert r2.json().get("poked") is False
    assert len(fb.wake) == wake_after_first  # 重复请求零新增唤醒

    # 重启恢复：新队列实例重载 → 异 Job conflict / 同 job duplicate 均不重放
    engine_settings_data = str(engine.settings.data_dir)
    q_restarted = HumanTurnQueue(engine_settings_data, workspace_scope=str(ws))
    m_same = q_restarted.mark_resumed_once(qid, job_id)
    assert m_same["duplicate"] is True and m_same.get("marked") is False
    m_other = q_restarted.mark_resumed_once(qid, "job-other")
    assert m_other.get("conflict") is True and m_other.get("marked") is False


def test_resume_rollback_after_refusal_allows_clean_retry(tmp_path, build_test_engine) -> None:
    """独审 P1 回归：标记后 resume_on_job 拒绝（candidate 不匹配）→ unmark
    回滚有效（响应不含误导性 duplicate），重试（正确 candidate）正常接续
    （不卡死 duplicate；拒绝路径零唤醒）."""

    from llm_loop.tools.builtin.job_registry import JobRegistry

    client, engine, sid, sha, qid, fb, ws = _atomic_resume_harness(
        tmp_path, build_test_engine, operation_id="op-retry"
    )
    job_id = _completed_job(JobRegistry.instance(), sid, ws, operation_id="op-retry")

    # post-mark 拒绝路径：poke 返回 False（唤醒失败）→ resume_on_job poked
    # False → unmark 回滚（回滚后不得虚报 duplicate）
    class _FailPoke:
        def poke_session(self, sid: str) -> bool:
            return False

    app_state = client.app.state
    app_state.queue_server_fallback = _FailPoke()
    wake_before_bad = len(fb.wake)  # dispatch 入队 poke 历史；拒绝请求零新增
    r_bad = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": job_id, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert r_bad.status_code == 200
    body_bad = r_bad.json()
    assert body_bad.get("poked") is False
    assert body_bad.get("duplicate") is not True  # 回滚后不得虚报 duplicate
    assert len(fb.wake) == wake_before_bad  # poke 失败：零新增唤醒

    # 重试（恢复真实 fallback，正确 candidate）→ 正常接续（回滚有效，不卡死）
    app_state.queue_server_fallback = fb
    r_ok = client.post(
        "/api/v1/coordinator/light/resume-job",
        json={"job_id": job_id, "queue_id": qid, "expected_sha256": sha},
        headers={"X-Coordinator-Token": _TOKEN},
    )
    assert r_ok.status_code == 200 and r_ok.json().get("poked") is True
    assert fb.wake.count(sid) == 2  # dispatch poke + 正确接续 poke，恰两次
