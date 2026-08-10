"""Web API 端点测试（M36，FakeLLM 装配零真实冒烟）.

用例 1-14：对话成功/会话复用/422 系列/500 异常/透传/健康检查/会话列表/删除确认/会话不存在。
复用 tests/conftest.py 的 build_test_engine fixture（既有装配，不复制逻辑）。
"""

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def test_chat_success_creates_session(build_test_engine, fake_settings):
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "你好"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_answer"] == "你好"
    assert body["session_id"]
    assert engine.session.exists(body["session_id"])


def test_chat_reuses_session(build_test_engine, fake_settings):
    engine, _ = build_test_engine([{"content": "一"}, {"content": "二"}])
    client = _make_client(engine)
    r1 = client.post("/api/v1/chat", json={"message": "一"}).json()
    sid = r1["session_id"]
    before = len(engine.session.list_sessions())
    r2 = client.post("/api/v1/chat", json={"message": "二", "session_id": sid})
    assert r2.status_code == 200
    assert r2.json()["session_id"] == sid
    assert len(engine.session.list_sessions()) == before  # 复用不新增


def test_chat_missing_message_422(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={})
    assert resp.status_code == 422


def test_chat_empty_message_422(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": ""})
    assert resp.status_code == 422


def test_chat_non_string_message_422(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": 123})
    assert resp.status_code == 422


def test_chat_engine_error_500(build_test_engine, fake_settings):
    def boom(_calls):
        raise RuntimeError("fake engine failure")

    engine, _ = build_test_engine([boom])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "x"})
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "internal_error"
    assert "fake engine failure" in body["detail"]


def test_chat_verification_note_passthrough(build_test_engine, fake_settings):
    from llm_loop.core.message import ToolCall
    from llm_loop.llm.client import LLMResponse

    tc = ToolCall(id="call_1", name="read_file", arguments={"path": "/no/such"})
    responses = [
        LLMResponse(content="", tool_calls=[tc], provider="fake"),
        LLMResponse(content="最终回答", tool_calls=[], provider="fake"),
    ]
    engine, _ = build_test_engine(responses)
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "读文件"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_answer"] == "最终回答"
    assert "verification_note" in body


def test_chat_truncated_passthrough(build_test_engine, fake_settings):
    engine, _ = build_test_engine([{"content": "ok"}])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "x"})
    assert resp.status_code == 200
    assert "truncated" in resp.json()


def test_health_no_llm_call(build_test_engine, fake_settings):
    engine, fake = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "llm-first-loop-web"
    assert len(fake.calls) == 0  # 健康检查不调 LLM


def test_root_returns_service_info(build_test_engine, fake_settings):
    engine, fake = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "llm-first-loop-web"
    assert "api/v1/chat" in str(body["endpoints"])
    assert len(fake.calls) == 0  # 根路径不调 LLM


def test_list_sessions(build_test_engine, fake_settings):
    engine, _ = build_test_engine([{"content": "a"}])
    client = _make_client(engine)
    client.post("/api/v1/chat", json={"message": "a"})
    resp = client.get("/api/v1/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["sessions"][0]["session_id"]


def test_delete_session_requires_confirm(build_test_engine, fake_settings):
    engine, _ = build_test_engine([{"content": "a"}])
    client = _make_client(engine)
    sid = client.post("/api/v1/chat", json={"message": "a"}).json()["session_id"]
    resp = client.delete(f"/api/v1/sessions/{sid}")
    assert resp.status_code == 409  # 无 confirm 拒绝
    assert engine.session.exists(sid)  # 未删除


def test_delete_session_confirm_ok(build_test_engine, fake_settings):
    engine, _ = build_test_engine([{"content": "a"}])
    client = _make_client(engine)
    sid = client.post("/api/v1/chat", json={"message": "a"}).json()["session_id"]
    resp = client.delete(f"/api/v1/sessions/{sid}?confirm=true")
    assert resp.status_code == 200
    assert not engine.session.exists(sid)


def test_delete_session_not_found(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.delete("/api/v1/sessions/does-not-exist?confirm=true")
    assert resp.status_code == 404


def test_chat_session_not_found_no_create(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    before = len(engine.session.list_sessions())
    resp = client.post("/api/v1/chat", json={"message": "x", "session_id": "nope"})
    assert resp.status_code == 404
    assert len(engine.session.list_sessions()) == before  # 不静默新建
