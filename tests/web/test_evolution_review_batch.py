"""演进批量审批：exec_override 透传与执行推进（EVO-20261018-f5f7580a）.

修复前批量路径只置 accepted：既不读 exec_override，也从不调用
maybe_auto_execute_from_engine，档位 0 下永远到不了 executing。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from llm_loop.introspection.evolution import EvolutionStore
from llm_loop.web import build_app
from llm_loop.web import routes as web_routes


def _client(build_test_engine, tmp_path, monkeypatch):
    engine, _ = build_test_engine([{"content": "你好"}])
    store = EvolutionStore(tmp_path / "evolution")
    monkeypatch.setattr(web_routes, "_evolution_store_from", lambda _engine: store)
    return TestClient(build_app(engine=engine)), store


def _status(store: EvolutionStore, evo_id: str) -> str:
    return next(s["status"] for s in store.list() if s["id"] == evo_id)


def test_batch_accept_with_exec_override_reaches_executing(build_test_engine, tmp_path, monkeypatch):
    client, store = _client(build_test_engine, tmp_path, monkeypatch)
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")  # 非边界

    resp = client.post(
        "/api/v1/evolution/review-batch",
        json={"decision": "accepted", "items": [{"id": sug.id, "decision": "accepted"}], "exec_override": True},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok_count"] == 1
    assert _status(store, sug.id) == "executing"


def test_batch_accept_without_override_stays_accepted(build_test_engine, tmp_path, monkeypatch):
    client, store = _client(build_test_engine, tmp_path, monkeypatch)
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")

    resp = client.post(
        "/api/v1/evolution/review-batch",
        json={"decision": "accepted", "items": [{"id": sug.id, "decision": "accepted"}]},
    )

    body = resp.json()
    assert body["ok_count"] == 1
    assert _status(store, sug.id) == "accepted"
    assert "等待人工执行" in body["results"][0]["message"]


def test_batch_skips_boundary_items_even_with_override(build_test_engine, tmp_path, monkeypatch):
    client, store = _client(build_test_engine, tmp_path, monkeypatch)
    sug = store.submit(content="调整安全策略", impact_scope="safety")  # 涉边界

    resp = client.post(
        "/api/v1/evolution/review-batch",
        json={"decision": "accepted", "items": [{"id": sug.id, "decision": "accepted"}], "exec_override": True},
    )

    body = resp.json()
    assert body["ok_count"] == 0
    assert body["results"][0].get("skipped") is True
    assert _status(store, sug.id) == "pending_review"


def test_batch_item_level_override_overrides_default(build_test_engine, tmp_path, monkeypatch):
    client, store = _client(build_test_engine, tmp_path, monkeypatch)
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")

    resp = client.post(
        "/api/v1/evolution/review-batch",
        json={
            "decision": "accepted",
            "items": [{"id": sug.id, "decision": "accepted", "exec_override": False}],
            "exec_override": True,
        },
    )

    body = resp.json()
    assert body["ok_count"] == 1
    assert _status(store, sug.id) == "accepted"


def test_batch_rejects_non_boolean_override(build_test_engine, tmp_path, monkeypatch):
    """授权标志必须严格布尔：JSON "false" 字符串不得被强转成"已授权"。"""
    client, store = _client(build_test_engine, tmp_path, monkeypatch)
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")

    resp = client.post(
        "/api/v1/evolution/review-batch",
        json={"decision": "accepted", "items": [{"id": sug.id}], "exec_override": "false"},
    )

    assert resp.status_code == 400
    assert "布尔" in resp.json()["detail"]
    assert _status(store, sug.id) == "pending_review"


# ---------- 来源会话：投影 / locator / 审计（DESIGN-20261030-v1） ----------
_SID = "11111111-2222-3333-4444-555555555555"
_SID2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class _FakeWorkspaceStore:
    def __init__(self, current, workspaces):
        self._current = current
        self._workspaces = workspaces

    def get_current(self):
        return self._current

    def list(self):
        return list(self._workspaces)


def _ws(ws_id: str, path: str):
    return SimpleNamespace(id=ws_id, path=path)


def _write_session(sessions_dir: Path, ws_id: str, sid: str) -> None:
    target = sessions_dir / ws_id / f"{sid}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"id": sid}), encoding="utf-8")


def _attach_store(engine, monkeypatch, current, others):
    monkeypatch.setattr(
        engine, "workspace_store", _FakeWorkspaceStore(current, [current, *others]), raising=False
    )


def _audit_rows(engine) -> list[dict]:
    path = Path(engine.settings.data_dir) / "audit" / "evolution_review_log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _client3(build_test_engine, tmp_path, monkeypatch, store_dir=None):
    engine, _ = build_test_engine([{"content": "你好"}])
    store = EvolutionStore(store_dir or (tmp_path / "evolution"))
    monkeypatch.setattr(web_routes, "_evolution_store_from", lambda _engine: store)
    return TestClient(build_app(engine=engine)), store, engine


def test_list_projects_session_id_including_empty(build_test_engine, tmp_path, monkeypatch):
    client, _store, engine = _client3(build_test_engine, tmp_path, monkeypatch)
    # list 直接读 <data_dir>/audit/evolution_suggestions.jsonl，store 要落在同一处
    store = EvolutionStore(Path(engine.settings.data_dir) / "audit")
    with_sid = store.submit(content="带来源", impact_scope="timeout_s", session_id=_SID)
    without = store.submit(content="旧记录", impact_scope="timeout_s")

    rows = {r["id"]: r for r in client.get("/api/v1/evolution/list").json()["suggestions"]}

    assert rows[with_sid.id]["session_id"] == _SID
    assert rows[without.id]["session_id"] == ""


def test_detail_projects_session_id(build_test_engine, tmp_path, monkeypatch):
    audit_dir = tmp_path / "audit"
    client, store, _engine = _client3(build_test_engine, tmp_path, monkeypatch, store_dir=audit_dir)
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    sug = store.submit(content="带来源", impact_scope="timeout_s", session_id=_SID)

    body = client.get("/api/v1/evolution/detail", params={"id": sug.id}).json()

    assert body["id"] == sug.id
    assert body["session_id"] == _SID


def test_review_response_and_audit_carry_session_id(build_test_engine, tmp_path, monkeypatch):
    client, store, engine = _client3(build_test_engine, tmp_path, monkeypatch)
    sug = store.submit(content="带来源", impact_scope="timeout_s", session_id=_SID)

    body = client.post(
        "/api/v1/evolution/review", json={"id": sug.id, "decision": "rejected", "reason": "不符合当前优先级"}
    ).json()

    assert body["session_id"] == _SID
    rows = [r for r in _audit_rows(engine) if r["id"] == sug.id]
    assert rows and rows[-1]["suggestion_session_id"] == _SID


def test_review_audit_empty_session_id_for_legacy(build_test_engine, tmp_path, monkeypatch):
    client, store, engine = _client3(build_test_engine, tmp_path, monkeypatch)
    sug = store.submit(content="旧记录", impact_scope="timeout_s")

    body = client.post(
        "/api/v1/evolution/review", json={"id": sug.id, "decision": "rejected", "reason": "不做"}
    ).json()

    assert body["session_id"] == ""
    rows = [r for r in _audit_rows(engine) if r["id"] == sug.id]
    assert rows and rows[-1]["suggestion_session_id"] == ""


def test_batch_results_carry_session_id_per_item(build_test_engine, tmp_path, monkeypatch):
    client, store, _engine = _client3(build_test_engine, tmp_path, monkeypatch)
    a = store.submit(content="A", impact_scope="timeout_s", session_id=_SID)
    b = store.submit(content="B", impact_scope="timeout_s")

    body = client.post(
        "/api/v1/evolution/review-batch",
        json={"decision": "accepted", "items": [{"id": a.id}, {"id": b.id}]},
    ).json()

    by_id = {r["id"]: r for r in body["results"]}
    assert by_id[a.id]["session_id"] == _SID
    assert by_id[b.id]["session_id"] == ""


def test_locator_hits_current_workspace(tmp_path, build_test_engine, monkeypatch):
    client, _store, engine = _client3(build_test_engine, tmp_path, monkeypatch)
    sessions = Path(engine.settings.sessions_dir)
    cur = _ws("--cur--", "/tmp/cur")
    _attach_store(engine, monkeypatch, cur, [])
    _write_session(sessions, "--cur--", _SID)

    body = client.get("/api/v1/evolution/session-locator", params={"session_id": _SID}).json()

    assert body == {
        "ok": True,
        "available": True,
        "session_id": _SID,
        "workspace_id": "--cur--",
        "workspace_path": "/tmp/cur",
        "current": True,
    }


def test_locator_hits_last_of_many_workspaces(tmp_path, build_test_engine, monkeypatch):
    """真实环境有 178 个工作区；定位器不得截断扫描（回归：曾计划只扫 38 个）。"""
    client, _store, engine = _client3(build_test_engine, tmp_path, monkeypatch)
    sessions = Path(engine.settings.sessions_dir)
    cur = _ws("--cur--", "/tmp/cur")
    others = [_ws(f"--ws-{i:03d}--", f"/tmp/ws-{i:03d}") for i in range(45)]
    _attach_store(engine, monkeypatch, cur, others)
    _write_session(sessions, others[-1].id, _SID2)

    body = client.get("/api/v1/evolution/session-locator", params={"session_id": _SID2}).json()

    assert body["available"] is True
    assert body["workspace_id"] == others[-1].id
    assert body["workspace_path"] == others[-1].path
    assert body["current"] is False


def test_locator_not_found_and_identity_only(tmp_path, build_test_engine, monkeypatch):
    client, _store, engine = _client3(build_test_engine, tmp_path, monkeypatch)
    sessions = Path(engine.settings.sessions_dir)
    cur = _ws("--cur--", "/tmp/cur")
    _attach_store(engine, monkeypatch, cur, [])
    (sessions / ".identity").mkdir(parents=True, exist_ok=True)
    (sessions / ".identity" / f"{_SID2}.json").write_text("{}", encoding="utf-8")

    missing = client.get("/api/v1/evolution/session-locator", params={"session_id": _SID}).json()
    identity = client.get("/api/v1/evolution/session-locator", params={"session_id": _SID2}).json()

    assert missing["available"] is False and missing["reason"] == "not_found"
    assert identity["available"] is False and identity["reason"] == "identity_only"


def test_locator_rejects_invalid_shape(tmp_path, build_test_engine, monkeypatch):
    client, _store, engine = _client3(build_test_engine, tmp_path, monkeypatch)
    _attach_store(engine, monkeypatch, _ws("--cur--", "/tmp/cur"), [])

    for bad in ("", "abc", "../etc/passwd", "a/b", "<mirror-verify>"):
        resp = client.get("/api/v1/evolution/session-locator", params={"session_id": bad})
        assert resp.status_code == 400, bad
        assert resp.json()["error"] == "invalid_params", bad


def test_locator_fail_open_when_store_raises(tmp_path, build_test_engine, monkeypatch):
    client, _store, engine = _client3(build_test_engine, tmp_path, monkeypatch)

    class _Boom:
        def get_current(self):
            return None

        def list(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(engine, "workspace_store", _Boom(), raising=False)

    resp = client.get("/api/v1/evolution/session-locator", params={"session_id": _SID})

    assert resp.status_code == 200
    assert resp.json()["available"] is False
    assert resp.json()["reason"] == "locator_failed"
