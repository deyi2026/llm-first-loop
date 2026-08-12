"""超长单条输入前置校验测试（spec.md 5.4.1 / design.md §2.2.2.1 / tasks.md T5.5）.

断言:
1. 超长消息返回 413（非 500，区分客户端错误）
2. 413 响应含 error/detail 字段且提示如实
3. 不创建会话、不写入审计、不消耗 LLM 配额
4. 边界值（恰好等于阈值）正常进入 engine
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _make_client(engine):
    return TestClient(build_app(engine=engine))


class TestInputTooLong:
    def test_returns_413_not_500(self, build_test_engine):
        engine, _ = build_test_engine([])
        object.__setattr__(engine.settings, "history_max_chars", 100)
        client = _make_client(engine)
        resp = client.post("/api/v1/chat", json={"message": "x" * 101})
        assert resp.status_code == 413

    def test_error_and_detail_fields(self, build_test_engine):
        engine, _ = build_test_engine([])
        object.__setattr__(engine.settings, "history_max_chars", 100)
        client = _make_client(engine)
        resp = client.post("/api/v1/chat", json={"message": "x" * 101})
        body = resp.json()
        assert body["error"] == "input_too_long"
        assert "101" in body["detail"]
        assert "100" in body["detail"]

    def test_no_session_created(self, build_test_engine):
        engine, _ = build_test_engine([])
        object.__setattr__(engine.settings, "history_max_chars", 100)
        client = _make_client(engine)
        before = len(engine.session.list_sessions())
        client.post("/api/v1/chat", json={"message": "x" * 101})
        assert len(engine.session.list_sessions()) == before

    def test_no_llm_call_consumed(self, build_test_engine):
        engine, fake = build_test_engine([])
        object.__setattr__(engine.settings, "history_max_chars", 100)
        client = _make_client(engine)
        client.post("/api/v1/chat", json={"message": "x" * 101})
        assert len(fake.calls) == 0


class TestBoundaryValue:
    def test_equal_threshold_passes(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "ok"}])
        object.__setattr__(engine.settings, "history_max_chars", 100)
        client = _make_client(engine)
        resp = client.post("/api/v1/chat", json={"message": "x" * 100})
        assert resp.status_code == 200

    def test_below_threshold_passes(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "ok"}])
        object.__setattr__(engine.settings, "history_max_chars", 100)
        client = _make_client(engine)
        resp = client.post("/api/v1/chat", json={"message": "x" * 50})
        assert resp.status_code == 200
