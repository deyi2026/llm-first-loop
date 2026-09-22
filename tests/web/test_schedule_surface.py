"""Web schedule surface（对齐 DSH Schedule Catalog）: 会话级机械提醒事实 + 显式取消.

契约（feature/webui-schedule-catalog-20260922）：
- 只读投影 data/schedule.json 中本会话的提醒（与 ScheduleTool 同一文件、同一派生路径）；
  不派生语义、不伪造状态——overdue 与否由前端用 trigger_at 与本地时钟计算。
- 宿主/租约/wake 授权内部字段（lease_owner/lease_until/wake_owner_pid/...）不外泄。
- 取消是显式用户动作，owner-scoped：跨会话取消 404，绝不碰其他会话条目。
- capability manifest 声明 schedule，精简后端自动隐藏入口。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.core.scheduler import ScheduleStore
from llm_loop.web import build_app


def _client(engine) -> TestClient:
    return TestClient(build_app(engine=engine))


def _store(engine) -> ScheduleStore:
    """与 factory._schedule_store 完全相同的路径派生（同文件即同事实源）."""
    settings = getattr(engine, "settings", None)
    data_dir = Path(getattr(settings, "data_dir", "./data"))
    return ScheduleStore((data_dir).resolve() / "schedule.json")


def test_schedule_surface_projects_session_scoped_facts(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    sid = engine.session.create()
    other = engine.session.create()
    store = _store(engine)
    store.add("check background jobs", after=60.0, session_id=sid)
    store.add("other session private", after=60.0, session_id=other)
    store.add(
        "repeat watchdog",
        after=60.0,
        repeat_interval=300.0,
        max_count=5,
        session_id=sid,
    )

    resp = _client(engine).get(f"/api/v1/sessions/{sid}/schedule")
    assert resp.status_code == 200
    body = resp.json()
    rows = body["schedule"]
    assert body["count"] == 2
    assert sorted(r["message"] for r in rows) == ["check background jobs", "repeat watchdog"]

    once = next(r for r in rows if r["message"] == "check background jobs")
    every = next(r for r in rows if r["message"] == "repeat watchdog")
    assert once["kind"] == "once"
    assert once["trigger_at"] > 0
    assert every["kind"] == "every"
    assert every["every_seconds"] == 300
    assert every["max_count"] == 5
    assert every["session_id"] == sid

    # 机械内部字段不外泄（对齐 jobs 面不透出 workspace_root 的惯例）
    for row in rows:
        for leaked in (
            "lease_owner",
            "lease_until",
            "wake_owner_pid",
            "wake_started_at",
            "retry_count",
            "retry_deadline_at",
            "goal_id",
            "goal_generation",
        ):
            assert leaked not in row


def test_schedule_surface_unknown_session_404(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    resp = _client(engine).get("/api/v1/sessions/no-such-session/schedule")
    assert resp.status_code == 404
    assert resp.json()["error"] == "session_not_found"


def test_schedule_cancel_is_owner_scoped_and_explicit(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    sid = engine.session.create()
    other = engine.session.create()
    store = _store(engine)
    target = store.add("mine to cancel", after=60.0, session_id=sid)
    keep = store.add("other session keeps", after=60.0, session_id=other)

    client = _client(engine)
    cross = client.post(f"/api/v1/sessions/{other}/schedule/{target}/cancel")
    assert cross.status_code == 404

    ok = client.post(f"/api/v1/sessions/{sid}/schedule/{target}/cancel")
    assert ok.status_code == 200
    assert ok.json()["status"] == "ok"

    remaining = {row["sid"]: row for row in store.list()}
    assert target not in remaining
    assert keep in remaining

    again = client.post(f"/api/v1/sessions/{sid}/schedule/{target}/cancel")
    assert again.status_code == 404


def test_capability_manifest_declares_schedule(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    resp = _client(engine).get("/api/v1/capabilities")
    assert resp.status_code == 200
    caps = resp.json()["capabilities"]
    assert caps.get("schedule") is True
