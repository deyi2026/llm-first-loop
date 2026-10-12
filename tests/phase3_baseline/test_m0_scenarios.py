"""Phase3 M0 验收基线：12 场景实测（docs/phase3-interjectable-assistant-design.md §6）.

基线原则：
- 只记录真实行为与时延；§6「预期」列是待验证假设，不做预期断言。
- 每场景独立 JSON 落盘 reports/phase3/m0/S##.json（请求/响应、时间戳链、
  queue 状态迁移、engine 动作事件），供聚合为 docs/phase3-m0-baseline.md。
- assert 仅做机械健全性检查（脚手架本身没坏：HTTP 可达、文件可写），
  预期与实测的差异正是本次基线要产出的东西，记录而非掩盖。
- S07/S08/S09（预算 CAS 注入 / wake 一次性 / wake 重启恢复）按方案 §6 说明：
  以存量回归测试的运行结果作为基线证据（行为真值由其定义）。
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import current_session_id
from llm_loop.web import build_app
from llm_loop.web.human_turn_queue import HumanTurnQueue

REPO = Path(__file__).resolve().parents[2]
# 基线输出目录参数化（默认 m0；重跑指定 PHASE3_REPORT_DIR 防覆盖原始记录——
# 见 reports/phase3/m0/README.md 的 01:41 覆盖事故）
REPORT_DIR = REPO / os.environ.get(
    "PHASE3_REPORT_DIR", "reports/phase3/m0"
).lstrip("/")
REPORT_DIR = Path(os.path.abspath(REPORT_DIR))
REPORT_DIR.mkdir(parents=True, exist_ok=True)

INTERJECT_TEXT = "改用方案B，不要等了"


class Rec:
    """场景记录器：步骤流水 + 墙钟时刻 + 时延 + 行为事实，finally 落盘。"""

    def __init__(self, sid: str, title: str) -> None:
        self.data = {
            "scenario": sid,
            "title": title,
            "ran_under": os.environ.get("PHASE3_RAN_UNDER", "M1-in-progress"),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "steps": [],
            "wall": {},
            "dur_ms": {},
            "obs": {},
            "endpoints": {},
        }

    def step(self, name: str, **facts) -> None:
        entry = {"t": round(time.time(), 3), "step": name}
        entry.update(facts)
        self.data["steps"].append(entry)

    def wall(self, key: str, t: float | None = None) -> None:
        self.data["wall"][key] = round(t if t is not None else time.time(), 3)

    def dur(self, key: str, ms: float) -> None:
        self.data["dur_ms"][key] = round(ms, 1)

    def obs(self, key: str, value) -> None:
        self.data["obs"][key] = value

    def http(self, key: str, resp, **extra) -> None:
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001 — 非 JSON 响应如实记录
            body = {"_raw": resp.text[:500]}
        self.data["endpoints"][key] = {
            "status": resp.status_code,
            "body": body,
            **extra,
        }

    def write(self, status: str = "ok", error: str | None = None) -> None:
        self.data["finished_at"] = datetime.now().isoformat(timespec="seconds")
        self.data["status"] = status
        if error:
            self.data["error"] = str(error)[:2000]
        path = REPORT_DIR / f"{self.data['scenario']}.json"
        path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


def _wait_tool_started(engine, tool_name: str = "execute_command", timeout: float = 3.0) -> bool:
    tool = engine.registry.get(tool_name)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if getattr(tool, "_active_procs", None):
            return True
        time.sleep(0.01)
    return False


def _wait_run_done(q, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            ev = q.get_nowait()
        except Exception:  # noqa: BLE001
            time.sleep(0.02)
            continue
        if ev.get("type") in ("done", "error"):
            return ev
    return {"type": "timeout"}


def _hq_of(client: TestClient, engine) -> HumanTurnQueue:
    """取 app.state 中按 data_dir 缓存的队列单例（与 routes 同一实例）."""
    store = getattr(client.app.state, "human_turn_queues", None) or {}
    data_dir = str(Path(getattr(engine.settings, "data_dir", "./data")).expanduser().resolve())
    if data_dir in store:
        return store[data_dir]
    assert store, "no human_turn_queues in app.state"
    return next(iter(store.values()))


def _hq_item(hq: HumanTurnQueue, sid: str, qid: str) -> dict | None:
    """按 queue_id 读条目终态（snapshot_items 含终态项的公开投影）."""
    for it in hq.snapshot_items():
        if it.get("queue_id") == qid and it.get("session_id") == sid:
            return it
    return None


def _interject(client: TestClient, sid: str, queue_id: str, gen: str):
    return client.post(
        "/api/v1/chat/queue/interject",
        json={"session_id": sid, "queue_id": queue_id, "run_generation": gen},
    )


def _session_hits(engine, sid: str, text: str) -> list[dict]:
    sess = engine.session.load(sid)
    out = []
    for m in sess.messages:
        if text in (m.content or ""):
            out.append(
                {
                    "role": m.role,
                    "metadata_keys": sorted((m.metadata or {}).keys()),
                    "content_head": (m.content or "")[:160],
                }
            )
    return out


def _model_saw_text(fake, text: str) -> dict:
    """第几次 LLM 调用、哪个消息位置看到插话文本."""
    seen = []
    for i, call in enumerate(getattr(fake, "calls", [])):
        for j, m in enumerate(call.get("messages", [])):
            content = m.get("content") if isinstance(m, dict) else None
            if isinstance(content, str) and text in content:
                seen.append({"call_index": i, "msg_index": j, "role": m.get("role")})
    return {"seen_at": seen, "llm_call_count": len(getattr(fake, "calls", []))}


# ────────────────────────────────────────────────────────────────────
# S01 长工具运行中插话（主路径）
# ────────────────────────────────────────────────────────────────────
def test_s01_interject_during_long_tool(build_test_engine):
    engine, fake = build_test_engine(
        [
            {
                "content": "先跑慢命令",
                "tool_calls": [
                    ToolCall(
                        id="s01c1",
                        name="execute_command",
                        arguments={"command": "sleep 2.5"},
                    )
                ],
            },
            {"content": "final-after-tool"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    rec = Rec("S01", "长工具运行中插话（主路径）")
    try:
        rec.wall("run_started")
        _h, q = runner.start(sid, "请执行慢命令")
        assert _wait_tool_started(engine), "脚手架失效：工具未启动"
        rec.wall("tool_running")
        rec.obs("tool_running_at_enqueue", True)

        t0 = time.perf_counter()
        r1 = client.post(
            "/api/v1/chat/queue",
            json={"session_id": sid, "message": INTERJECT_TEXT},
        )
        rec.dur("t_enqueue_ack_ms", (time.perf_counter() - t0) * 1000)
        rec.http("POST /queue", r1)
        assert r1.status_code == 202, "脚手架失效：入队非 202"
        queue_id = r1.json()["queue_id"]

        gen = (runner.get_handle(sid) or {}).get("run_generation")
        rec.obs("run_generation_present", bool(gen))

        t1 = time.perf_counter()
        r2 = _interject(client, sid, queue_id, gen)
        rec.dur("t_interject_ack_ms", (time.perf_counter() - t1) * 1000)
        rec.http("POST /queue/interject", r2)
        rec.wall("interject_accepted")

        tool = engine.registry.get("execute_command")
        rec.obs("tool_still_running_at_interject", bool(tool._active_procs))

        final = _wait_run_done(q, timeout=40)
        rec.wall("run_done")
        rec.obs("run_final_event", final.get("type"))

        hq = _hq_of(client, engine)
        item = _hq_item(hq, sid, queue_id) or {}
        rec.obs("item_terminal_state", item.get("status"))
        ts = item
        for k in ("created_at", "interject_requested_at", "received_at", "terminal_at"):
            if ts.get(k) and "created_at" in ts and k != "created_at":
                rec.dur(f"{k}_minus_created_at_ms", (ts[k] - ts["created_at"]) * 1000)

        rec.obs("session_hits", _session_hits(engine, sid, INTERJECT_TEXT))
        rec.obs("model_visibility", _model_saw_text(fake, INTERJECT_TEXT))
        _result = final.get("result")
        rec.obs("final_answer", getattr(_result, "final_answer", None) or str(_result)[:200] if _result is not None else None)
    finally:
        runner.cancel(sid)
        rec.write()


# ────────────────────────────────────────────────────────────────────
# S02 空闲插话（无 live run）
# ────────────────────────────────────────────────────────────────────
def test_s02_interject_idle(build_test_engine):
    engine, _fake = build_test_engine([{"content": "ok"}])
    # 不设置 runner：空闲态（engine.runner 为 None）
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    rec = Rec("S02", "空闲插话（无 live run）")
    try:
        r1 = client.post(
            "/api/v1/chat/queue",
            json={"session_id": sid, "message": "有人在吗"},
        )
        rec.http("POST /queue", r1)
        assert r1.status_code == 202, "脚手架失效：入队非 202"
        queue_id = r1.json()["queue_id"]

        r2 = _interject(client, sid, queue_id, "gen-not-exist")
        rec.http("POST /queue/interject", r2)
        rec.obs("interject_status", r2.status_code)
        rec.obs("interject_error_code", (r2.json() if r2.headers.get("content-type", "").startswith("application/json") else {}).get("error"))

        r3 = client.get(f"/api/v1/chat/queue?session_id={sid}")
        rec.http("GET /queue", r3)
        items = r3.json().get("items", [])
        rec.obs("item_state_after_failed_interject", [i.get("status") for i in items])
        rec.obs("queue_untouched", all(i.get("claimed_by") is None for i in items))
    finally:
        rec.write()


# ────────────────────────────────────────────────────────────────────
# S03 临界竞态：run 刚结束 / 过期 generation
# ────────────────────────────────────────────────────────────────────
def test_s03_interject_race(build_test_engine):
    engine, _fake = build_test_engine(
        [
            {
                "content": "慢",
                "tool_calls": [
                    ToolCall(
                        id="s03c1",
                        name="execute_command",
                        arguments={"command": "sleep 2.0"},
                    )
                ],
            },
            {"content": "done"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    rec = Rec("S03", "临界竞态：run 运行中错代 / run 结束后插话")
    try:
        _h, q = runner.start(sid, "run")
        assert _wait_tool_started(engine), "脚手架失效"
        # (a) 运行中 + 错误 generation
        r1 = client.post(
            "/api/v1/chat/queue",
            json={"session_id": sid, "message": "竞态测试A"},
        )
        qid_a = r1.json()["queue_id"]
        ra = _interject(client, sid, qid_a, "stale-gen-xyz")
        rec.http("interject_wrong_gen", ra)
        rec.obs("wrong_gen_status", ra.status_code)

        # (b) run 结束后（handle 清理路径）
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        final = _wait_run_done(q, timeout=30)
        rec.obs("run_done_before_interject", final.get("type"))
        time.sleep(0.2)  # 让 runner 收尾清理 handle
        r2 = client.post(
            "/api/v1/chat/queue",
            json={"session_id": sid, "message": "竞态测试B"},
        )
        qid_b = r2.json()["queue_id"]
        rb = _interject(client, sid, qid_b, gen or "gen-from-ended-run")
        rec.http("interject_after_run_end", rb)
        rec.obs("after_end_status", rb.status_code)
        rec.obs("after_end_error", (rb.json() if rb.headers.get("content-type", "").startswith("application/json") else {}).get("error"))

        # (c) 等待 reaper 把 (a) 的 claimed 悬挂项回收（若转 claimed）
        hq = _hq_of(client, engine)
        states = {}
        for _ in range(10):
            states = {i["queue_id"]: i["status"] for i in hq.list_active(sid)}
            if states:
                time.sleep(0.3)
        rec.obs("queue_states_end", states)
    finally:
        runner.cancel(sid)
        rec.write()


# ────────────────────────────────────────────────────────────────────
# S04 停止后台 execute_command job（terminate_session 路径）
# ────────────────────────────────────────────────────────────────────
def test_s04_stop_background_job(build_test_engine):
    engine, _fake = build_test_engine([{"content": "ok"}])
    from llm_loop.tools.builtin.job_registry import JobRegistry

    sid = engine.session.create()
    rec = Rec("S04", "停止后台 execute_command job")
    # 【2026-10-13 审查修正】生产装配在 factory.py:731 注册
    # registry.add_session_cancel_hook(JobRegistry.instance().cancel_session)；
    # tests/conftest.py 装配缺该 hook——01:32 原始运行按残缺装配测得「job 存活」，
    # 属装配差异而非生产缺口。本重跑显式对齐生产装配（hook 记录两者口径）。
    engine.registry.add_session_cancel_hook(JobRegistry.instance().cancel_session)
    rec.obs("assembly", "production_fair: session_cancel_hook registered (factory.py:731)")
    job_id = None
    try:
        token = current_session_id.set(sid)
        try:
            result = engine.registry.execute(
                ToolCall(
                    id="s04bg",
                    name="execute_command",
                    arguments={"command": "sleep 30", "run_in_background": True},
                )
            )
        finally:
            current_session_id.reset(token)
        content = result.content or ""
        rec.obs("bg_start_result_head", content[:300])
        m = re.search(r"job_id[\"':=\s]+([A-Za-z0-9_\-]+)", content)
        assert m, f"脚手架失效：未从结果中解析到 job_id: {content[:300]}"
        job_id = m.group(1)
        jr = JobRegistry.instance()
        snap0 = jr.snapshot(job_id)
        rec.obs("job_state_before_stop", {k: v for k, v in (snap0 or {}).items() if k in ("status", "state", "running", "pid")})

        t0 = time.perf_counter()
        cancelled = engine.registry.cancel_session(sid)
        stop_wall = time.perf_counter()
        rec.obs("cancel_session_count", cancelled)
        rec.dur("cancel_session_call_ms", (stop_wall - t0) * 1000)

        deadline = time.monotonic() + 2.0
        snap1 = None
        while time.monotonic() < deadline:
            snap1 = jr.snapshot(job_id)
            status = (snap1 or {}).get("status") or (snap1 or {}).get("state")
            if status and status != "running":
                break
            time.sleep(0.05)
        rec.wall("job_terminal_observed")
        rec.dur("stop_to_terminal_observed_ms", (time.perf_counter() - t0) * 1000)
        rec.obs("job_state_after_stop", snap1)
    finally:
        if job_id:
            # 清理尽力而为：不影响基线记录落盘（fail-open）
            with contextlib.suppress(Exception):
                JobRegistry.instance().cancel_session(sid)
        rec.write()


# ────────────────────────────────────────────────────────────────────
# S05 无 terminate_session 的副作用工具（盲点实证）
# ────────────────────────────────────────────────────────────────────
def test_s05_stop_side_effect_blindspot(build_test_engine):
    engine, fake = build_test_engine(
        [
            {
                "content": "副作用",
                "tool_calls": [
                    ToolCall(
                        id="s05c1",
                        name="fake_side_effect",
                        arguments={"seconds": 4.0},
                    )
                ],
            },
            {"content": "never-reached"},
        ]
    )
    rec = Rec("S05", "无 terminate_session 的副作用工具：run 停止后工具仍活")

    class FakeSideEffect:
        name = "fake_side_effect"
        description = "模拟无 terminate_session 的长副作用工具（S05 专用）"
        parameters = {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"],
        }
        started = threading.Event()
        finished = threading.Event()

        def execute(self, seconds: float = 4.0) -> str:
            self.started.set()
            time.sleep(seconds)
            self.finished.set()
            return "side effect completed"

    tool = FakeSideEffect()
    engine.registry.register(tool)
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    try:
        _h, q = runner.start(sid, "触发副作用工具")
        assert tool.started.wait(timeout=3.0), "脚手架失效：副作用工具未启动"
        rec.wall("side_effect_started")
        rec.obs("tool_has_terminate_session", hasattr(tool, "terminate_session"))

        t0 = time.perf_counter()
        ok = runner.cancel(sid)
        cancel_done = time.perf_counter()
        rec.obs("runner_cancel_returned", ok)
        rec.dur("runner_cancel_ms", (cancel_done - t0) * 1000)
        final = _wait_run_done(q, timeout=15)
        run_done = time.perf_counter()
        rec.obs("run_final_event", final.get("type"))
        rec.dur("cancel_to_run_done_ms", (run_done - t0) * 1000)

        # 【2026-10-13 审查修正】原始报告把时序写反了。真实语义（两版记录一致）：
        # cancel 立即回执，但 run 终态事件等待无 terminate_session 的 in-flight
        # 工具自然结束才发出（本地终止可被工具时长拖住——G3 t_stop_local 口径输入）。
        time.sleep(0.3)
        rec.obs(
            "side_effect_finished_before_run_done",
            tool.finished.is_set(),
        )
        rec.obs(
            "run_done_waited_for_tool",
            (run_done - t0) * 1000 >= 3000,
        )  # 工具 4s：done 若被拖住，cancel→done ≥3s
        tool.finished.wait(timeout=4.5)  # 等自然结束，避免悬挂线程
        rec.obs("side_effect_finished_eventually", tool.finished.is_set())
        rec.obs("total_side_effect_duration_ms", (time.perf_counter() - t0) * 1000)
    finally:
        runner.cancel(sid)
        rec.write()


# ────────────────────────────────────────────────────────────────────
# S06 前台长工具停止（预算/本地终止路径）
# ────────────────────────────────────────────────────────────────────
def test_s06_stop_foreground_tool(build_test_engine):
    engine, fake = build_test_engine(
        [
            {
                "content": "前台慢",
                "tool_calls": [
                    ToolCall(
                        id="s06c1",
                        name="execute_command",
                        arguments={"command": "sleep 30"},
                    )
                ],
            },
            {"content": "never-reached"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    rec = Rec("S06", "前台长工具停止：requested→local_terminated")
    try:
        _h, q = runner.start(sid, "跑30秒前台命令")
        assert _wait_tool_started(engine), "脚手架失效"
        rec.wall("tool_started")

        t0 = time.perf_counter()
        ok = runner.cancel(sid)
        cancel_done = time.perf_counter()
        rec.obs("runner_cancel_returned", ok)
        rec.dur("runner_cancel_ms", (cancel_done - t0) * 1000)
        final = _wait_run_done(q, timeout=10)
        rec.dur("cancel_to_run_terminal_ms", (time.perf_counter() - t0) * 1000)
        rec.obs("run_final_event", final.get("type"))
        sess = engine.session.load(sid)
        rec.obs("session_message_count", len(sess.messages))
        rec.obs("llm_call_count", len(getattr(fake, "calls", [])))
        rec.obs(
            "final_session_texts",
            [m.content[:80] for m in sess.messages[-3:]],
        )
    finally:
        runner.cancel(sid)
        rec.write()


# ────────────────────────────────────────────────────────────────────
# S07/S08/S09：存量回归测试作为基线证据（见文件头说明）
# ────────────────────────────────────────────────────────────────────
def _run_pytest(args: list[str]) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *args, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=600,
    )
    tail = (proc.stdout or "").strip().splitlines()[-8:]
    return {"cmd": "pytest " + " ".join(args), "returncode": proc.returncode, "tail": tail}


def test_s07_budget_cas_injection_evidence():
    rec = Rec("S07", "预算 CAS 失败注入（存量测试证据）")
    try:
        out = _run_pytest(["tests/unit/test_task_budget_transport_stop.py"])
        rec.data["evidence"] = out
        rec.obs("verdict", "pass" if out["returncode"] == 0 else "fail")
    finally:
        rec.write()


def test_s08_wake_one_shot_evidence():
    rec = Rec("S08", "wake 一次性（存量测试证据）")
    try:
        out = _run_pytest(
            ["tests/unit/test_schedule_wake.py", "tests/unit/test_wake_jobs_projection.py"]
        )
        rec.data["evidence"] = out
        rec.obs("verdict", "pass" if out["returncode"] == 0 else "fail")
    finally:
        rec.write()


def test_s09_wake_restart_recovery_evidence():
    rec = Rec("S09", "wake 重启恢复（存量测试证据）")
    try:
        out = _run_pytest(
            ["tests/unit/test_schedule_restart_recovery.py", "tests/unit/test_schedule_durability.py"]
        )
        rec.data["evidence"] = out
        rec.obs("verdict", "pass" if out["returncode"] == 0 else "fail")
    finally:
        rec.write()


# ────────────────────────────────────────────────────────────────────
# S10 空内容 / 超长内容插话
# ────────────────────────────────────────────────────────────────────
def test_s10_empty_and_oversize(build_test_engine):
    engine, fake = build_test_engine(
        [
            {
                "content": "慢",
                "tool_calls": [
                    ToolCall(
                        id="s10c1",
                        name="execute_command",
                        arguments={"command": "sleep 2.0"},
                    )
                ],
            },
            {"content": "final"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    rec = Rec("S10", "空内容 / 超长内容插话")
    try:
        _h, q = runner.start(sid, "run")
        assert _wait_tool_started(engine), "脚手架失效"

        r_empty = client.post(
            "/api/v1/chat/queue", json={"session_id": sid, "message": ""}
        )
        rec.http("POST /queue empty", r_empty)
        rec.obs("empty_accepted", r_empty.status_code)

        big = "超长" * 50000  # 100k 字符
        t0 = time.perf_counter()
        r_big = client.post(
            "/api/v1/chat/queue", json={"session_id": sid, "message": big}
        )
        rec.dur("t_enqueue_100k_chars_ms", (time.perf_counter() - t0) * 1000)
        rec.http("POST /queue 100k", r_big, note="body 截断记录")
        if r_big.status_code == 202:
            rec.data["endpoints"]["POST /queue 100k"]["body"] = {
                k: v for k, v in (r_big.json() or {}).items() if k != "message"
            }
        rec.obs("oversize_accepted", r_big.status_code)

        empty_id = r_empty.json().get("queue_id") if r_empty.status_code == 202 else None
        big_id = r_big.json().get("queue_id") if r_big.status_code == 202 else None
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        if empty_id:
            ri = _interject(client, sid, empty_id, gen)
            rec.http("interject empty", ri)
        if big_id:
            rb = _interject(client, sid, big_id, gen)
            rec.http("interject 100k", rb)

        final = _wait_run_done(q, timeout=60)
        rec.obs("run_final_event", final.get("type"))
        sess = engine.session.load(sid)
        empty_msgs = [
            m.content[:60] for m in sess.messages if m.role == "user" and not (m.content or "").strip()
        ]
        rec.obs("empty_user_messages_in_session", len(empty_msgs))
        rec.obs("session_messages_count", len(sess.messages))
        # 大文本是否进入模型上下文
        big_seen = any("超长" in (m.get("content") or "") for c in getattr(fake, "calls", []) for m in c.get("messages", []) if isinstance(m.get("content"), str))
        rec.obs("big_text_reached_model_context", big_seen)
        hq = _hq_of(client, engine)
        for label, qid in (("empty_item", empty_id), ("big_item", big_id)):
            if qid:
                item = _hq_item(hq, sid, qid) or {}
                rec.obs(f"{label}_terminal_state", item.get("status"))
    finally:
        runner.cancel(sid)
        rec.write()


# ────────────────────────────────────────────────────────────────────
# S11 并发 100 次 interject 同一 queue_id
# ────────────────────────────────────────────────────────────────────
def test_s11_concurrent_interject(build_test_engine):
    engine, fake = build_test_engine(
        [
            {
                "content": "慢",
                "tool_calls": [
                    ToolCall(
                        id="s11c1",
                        name="execute_command",
                        arguments={"command": "sleep 2.0"},
                    )
                ],
            },
            {"content": "final"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    rec = Rec("S11", "并发 100 次 interject 同一 queue_id")
    try:
        _h, q = runner.start(sid, "run")
        assert _wait_tool_started(engine), "脚手架失效"
        r1 = client.post(
            "/api/v1/chat/queue",
            json={"session_id": sid, "message": "并发冲单一项"},
        )
        queue_id = r1.json()["queue_id"]
        gen = (runner.get_handle(sid) or {}).get("run_generation")

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(
                pool.map(lambda _: _interject(client, sid, queue_id, gen), range(100))
            )
        elapsed = (time.perf_counter() - t0) * 1000
        codes = [r.status_code for r in results]
        rec.dur("t_100_concurrent_interjects_ms", elapsed)
        rec.obs("status_202_count", codes.count(202))
        rec.obs("status_409_count", codes.count(409))
        rec.obs("other_status_counts", {c: codes.count(c) for c in set(codes) if c not in (202, 409)})
        errs: dict[str, int] = {}
        for r in results:
            if r.status_code != 202:
                try:
                    e = r.json().get("error", "unknown")
                except Exception:  # noqa: BLE001
                    e = "non-json"
                errs[e] = errs.get(e, 0) + 1
        rec.obs("non_202_error_codes", errs)

        final = _wait_run_done(q, timeout=60)
        rec.obs("run_final_event", final.get("type"))
        rec.obs("session_hits", _session_hits(engine, sid, "并发冲单一项"))
        rec.obs("model_visibility", _model_saw_text(fake, "并发冲单一项"))
    finally:
        runner.cancel(sid)
        rec.write()


# ────────────────────────────────────────────────────────────────────
# S12 重启恢复：interject_pending → queued
# ────────────────────────────────────────────────────────────────────
def test_s12_restart_recovery(tmp_path):
    rec = Rec("S12", "进程重启后 interject_pending 恢复 + 孤儿回收")
    try:
        hq = HumanTurnQueue(str(tmp_path / "q"))
        sid = "sess-s12"
        item = hq.enqueue(sid, "重启恢复测试")
        qid = item["queue_id"]
        rec.obs("enqueued_state", item["status"])

        claimed = hq.claim_interject(sid, qid, run_generation="gen-1")
        rec.obs("claim_returned_state", (claimed or {}).get("status"))
        cur = _hq_item(hq, sid, qid) or {}
        rec.obs("after_claim_state", cur.get("status"))

        # 模拟进程重启：同一磁盘路径新建实例
        hq2 = HumanTurnQueue(str(tmp_path / "q"))
        after = _hq_item(hq2, sid, qid) or {}
        rec.obs("after_restart_state", after.get("status"))
        rec.obs("after_restart_requeued_from", after.get("requeued_from"))

        # 孤儿回收路径：claim 后 run 结束（runs_alive 返回 None）
        item2 = hq2.enqueue(sid, "孤儿回收测试")
        qid2 = item2["queue_id"]
        hq2.claim_interject(sid, qid2, run_generation="gen-2")
        released = hq2.reap_orphan_interjects(lambda s: None)
        rec.obs("reap_released_ids", released)
        item2_after = _hq_item(hq2, sid, qid2) or {}
        rec.obs("orphan_after_reap_state", item2_after.get("status"))
        rec.obs("orphan_after_reap_requeued_from", item2_after.get("requeued_from"))
        rec.obs("message_intact_after_recovery", item2_after.get("message") == "孤儿回收测试")
    finally:
        rec.write()
