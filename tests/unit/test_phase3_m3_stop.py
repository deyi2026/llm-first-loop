"""Phase3 M3（G3）：停止四态 + 副作用登记面.

事实基线（M0 报告审查修订版）：
- 生产装配已有两层回收（terminate_session + factory.py:731 JobRegistry hook），
  M3 不新增回收，只做「可枚举可查询」。
- F5：cancel 回执≠本地终止（无撤销工具可拖住 run 终态）——四态里两者分开。
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.loop.side_effects import SideEffectRegistry
from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import current_session_id
from llm_loop.tools.builtin.job_registry import JobRegistry
from llm_loop.web import build_app


def _se(tmp_path):
    se = SideEffectRegistry.instance()
    se.configure(str(tmp_path / "se"))
    return se


def _wait_job_terminal(job_id, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = JobRegistry.instance().snapshot(job_id) or {}
        if str(snap.get("state", "")).lower() in ("done", "killed", "error", "cancelled"):
            return snap
        time.sleep(0.02)
    return JobRegistry.instance().snapshot(job_id) or {}


def test_four_states_bg_job_revocable(build_test_engine, tmp_path):
    """S04 生产装配口径：requested→dispatched_stopped(0.1ms 级)→local_terminated，
    revocable 副作用被既有 hook 回收，external_unknown 空（显式声明）."""
    engine, _fake = build_test_engine(
        [
            {
                "content": "慢",
                "tool_calls": [
                    ToolCall(
                        id="m3slow", name="execute_command", arguments={"command": "sleep 8"}
                    )
                ],
            },
            {"content": "final"},
        ]
    )
    _se(tmp_path)
    engine.registry.add_session_cancel_hook(JobRegistry.instance().cancel_session)  # 对齐 factory.py:731
    sid = engine.session.create()
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    job_id = None
    try:
        _h, _q = runner.start(sid, "跑长工具")  # run 活跃是 cancel 的前提（live-run 语义）
        tool = engine.registry.get("execute_command")
        deadline = time.monotonic() + 3.0
        while not getattr(tool, "_active_procs", {}) and time.monotonic() < deadline:
            time.sleep(0.01)
        # run 期间派生后台 job（生产形态：模型在 run 内启动后台任务）
        from llm_loop.core.run_context import current_run_generation

        gen = (runner.get_handle(sid) or {}).get("run_generation")
        tok = current_session_id.set(sid)
        tok_gen = current_run_generation.set(gen)
        try:
            res = engine.registry.execute(
                ToolCall(
                    id="m3a",
                    name="execute_command",
                    arguments={"command": "sleep 30", "run_in_background": True},
                )
            )
        finally:
            current_session_id.reset(tok)
            current_run_generation.reset(tok_gen)
        assert res.status.value == "success", res.content
        job_id = res.content.split("job_id=")[1].split()[0]
        assert _wait_job_terminal(job_id, 1.0).get("state", "running") == "running"

        r = client.get("/api/v1/chat/stop-state", params={"session_id": sid})
        body = r.json()
        assert body["state"] == "idle"  # 未请求停止
        assert body["no_known_external_side_effects"] is False
        assert body["external_unknown_count"] == 0  # revocable 不进 unknown 面

        assert runner.cancel(sid) is True
        snap = _wait_job_terminal(job_id)
        assert str(snap.get("state", "")).lower() in ("killed", "cancelled"), snap

        r2 = client.get("/api/v1/chat/stop-state", params={"session_id": sid}).json()
        assert r2["state"] in ("dispatched_stopped", "local_terminated")
        assert r2["requested_at"] and r2["dispatched_stopped_at"]
        assert r2["dispatched_stopped_count"] >= 1  # revocable 已被派发停止
        assert r2["no_known_external_side_effects"] is True  # 空清单显式声明

        # 等 run 句柄清空（无在途 run；cancel 后 registry 已空）→ local_terminated + 精确时刻
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and r2["state"] != "local_terminated":
            time.sleep(0.05)
            r2 = client.get("/api/v1/chat/stop-state", params={"session_id": sid}).json()
        assert r2["state"] == "local_terminated"
        assert r2["local_terminated_at"] >= r2["dispatched_stopped_at"]
    finally:
        if job_id:
            JobRegistry.instance().cancel_session(sid)


def test_external_unknown_and_confirm(build_test_engine, tmp_path):
    """不可撤销副作用（浏览器 mutation 类）：external_unknown 可枚举 → 人工 confirm（无 TTL）."""
    engine, _fake = build_test_engine([{"content": "ok"}])
    se = _se(tmp_path)
    sid = engine.session.create()
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    try:
        eff = se.register(
            sid, "browser_operate", "click:提交按钮", "browser_mutation",
            revocable=False, detail="不可自动撤销",
        )
        _h, q = runner.start(sid, "run")
        assert runner.cancel(sid) is True
        body = client.get("/api/v1/chat/stop-state", params={"session_id": sid}).json()
        assert body["external_unknown_count"] == 1
        entry = body["external_unknown"][0]
        assert entry["tool"] == "browser_operate" and "click" in entry["target"]
        assert entry["manual_check_hint"]  # 人工核验指引存在
        assert body["external_all_confirmed"] is False
        # 无人为确认前，二次查询不自动转 confirmed（D5：禁 TTL）
        time.sleep(0.2)
        assert client.get("/api/v1/chat/stop-state", params={"session_id": sid}).json()[
            "external_all_confirmed"
        ] is False

        r = client.post(
            "/api/v1/chat/stop-state/confirm",
            json={"session_id": sid, "effect_id": eff, "confirmed_by": "user-a", "note": "页面已回滚"},
        )
        assert r.status_code == 200
        body2 = client.get("/api/v1/chat/stop-state", params={"session_id": sid}).json()
        assert body2["external_all_confirmed"] is True
        assert body2["external_unknown"][0]["confirmed_at"] is not None

        nf = client.post(
            "/api/v1/chat/stop-state/confirm",
            json={"session_id": sid, "effect_id": "se-9999", "confirmed_by": "user-a"},
        )
        assert nf.status_code == 404
    finally:
        runner.cancel(sid)


def test_f5_dual_clock_stop(build_test_engine, tmp_path):
    """F5 双口径：cancel 回执快，本地终止被无撤销 in-flight 工具拖住——
    停止态在拖尾期=dispatched_stopped(run_alive)，工具自然结束后→local_terminated."""
    import threading

    engine, _fake = build_test_engine(
        [
            {
                "content": "副作用",
                "tool_calls": [ToolCall(id="m3c", name="side_effect_slow", arguments={})],
            },
            {"content": "final"},
        ]
    )
    _se(tmp_path)
    started, finished = threading.Event(), threading.Event()

    class SideEffectSlow:
        name = "side_effect_slow"
        description = "无 terminate_session 的慢副作用工具（测试桩）"

        def execute(self):
            started.set()
            time.sleep(2.0)
            finished.set()
            return "副作用完成"

    engine.registry.register(SideEffectSlow())
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    try:
        _h, q = runner.start(sid, "触发")
        assert started.wait(3.0)
        t_cancel = time.perf_counter()
        assert runner.cancel(sid) is True
        cancel_ms = (time.perf_counter() - t_cancel) * 1000
        assert cancel_ms < 500  # 回执快（布尔 ACK；≠物理闭环）

        body = client.get("/api/v1/chat/stop-state", params={"session_id": sid}).json()
        assert body["run_alive"] is True
        assert body["state"] == "dispatched_stopped"  # 拖尾期：已派发停止但本地未终止

        finished.wait(6.0)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            body = client.get("/api/v1/chat/stop-state", params={"session_id": sid}).json()
            if body["state"] == "local_terminated":
                break
            time.sleep(0.05)
        assert body["state"] == "local_terminated"
        assert body["local_terminated_at"] >= body["requested_at"] + 1.0  # 被工具时长拖住
    finally:
        runner.cancel(sid)


def test_assembly_consistency_pin():
    """装配一致性钉子（M0 审查新增项）：factory 必须同时注册 JobRegistry hook 与
    SideEffectRegistry.configure；漂移即红（tests/conftest 不装配属已知差异，见
    factory 注释与 M0 报告 §4）。"""
    src = (Path(__file__).resolve().parents[2] / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    assert "add_session_cancel_hook(_job_registry.cancel_session)" in src
    assert "SideEffectRegistry.instance().configure(" in src
