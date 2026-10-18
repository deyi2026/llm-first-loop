"""演进批量审批：exec_override 透传与执行推进（EVO-20261018-f5f7580a）.

修复前批量路径只置 accepted：既不读 exec_override，也从不调用
maybe_auto_execute_from_engine，档位 0 下永远到不了 executing。
"""
from __future__ import annotations

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
