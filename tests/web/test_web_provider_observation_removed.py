"""web-carveout M3 改写：webui 观测面移除断言（D1）。

原 test_chatgpt_binding_observability.py（6 测试：provider-binding 报告 /
bindings/health / gc-plan / gc 确认）针对的路由族与 notifier 挂载已随
chatgpt 页面 client 一并剥离至 lfl-web-providers；store 层语义由独立项目
测试锁定（test_chatgpt_surface / test_chatgpt_binding_health /
test_chatgpt_binding_notifications，143 passed）。本文件锁定中间件侧
「确已移除」的当前真相：端点 404、app.state 无 notifier。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _client(engine) -> TestClient:
    return TestClient(build_app(engine=engine))


def test_binding_observation_routes_removed(build_test_engine):
    engine, _ = build_test_engine([])
    sid = engine.session.create()
    client = _client(engine)
    assert (
        client.get(f"/api/v1/sessions/{sid}/provider-binding").status_code == 404
    )
    assert client.get("/api/v1/chatgpt-web/bindings/health").status_code == 404
    assert client.get("/api/v1/chatgpt-web/bindings/gc-plan").status_code == 404
    assert client.post("/api/v1/chatgpt-web/bindings/gc", json={}).status_code == 404


def test_binding_alert_notifier_state_removed(build_test_engine):
    engine, _ = build_test_engine([])
    app = build_app(engine=engine)
    assert not hasattr(app.state, "chatgpt_binding_alert_notifier")
