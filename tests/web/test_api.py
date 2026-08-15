"""Web API 端点测试（M36，FakeLLM 装配零真实冒烟）.

用例 1-14：对话成功/会话复用/422 系列/500 异常/透传/健康检查/会话列表/删除确认/会话不存在。
复用 tests/conftest.py 的 build_test_engine fixture（既有装配，不复制逻辑）。
"""

from pathlib import Path

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


def test_chat_response_tool_calls_passthrough(build_test_engine, fake_settings):
    """P2-1: 后端 ChatResponse.tool_calls 透传链路（前端可消费数据源成立，零后端改动）."""
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
    assert body["tool_calls"] and body["tool_calls"][0]["name"] == "read_file"
    assert body["tool_calls"][0]["arguments"] == {"path": "/no/such"}


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
    """根路径 M37 起返回聊天页面 HTML（不再是 JSON 服务信息）."""
    engine, fake = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<!DOCTYPE html>" in resp.text
    assert len(fake.calls) == 0  # 根路径不调 LLM
    info = client.get("/api/info")
    assert info.status_code == 200
    assert info.json()["service"] == "llm-first-loop-web"


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


def test_get_session_messages(build_test_engine, fake_settings):
    engine, _ = build_test_engine([{"content": "回答"}])
    client = _make_client(engine)
    sid = client.post("/api/v1/chat", json={"message": "你好"}).json()["session_id"]
    resp = client.get(f"/api/v1/sessions/{sid}/messages")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == sid
    roles = [m["role"] for m in body["messages"]]
    assert "user" in roles
    assert "assistant" in roles


def test_get_session_messages_not_found(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/api/v1/sessions/nope/messages")
    assert resp.status_code == 404


def test_chat_model_passthrough(build_test_engine, fake_settings):
    """per-call 模型经池解析：provider/model → 裸模型名透传给 LLM 调用（Web 模型切换）."""
    engine, fake = build_test_engine([{"content": "用 pro 模型回答"}])
    client = _make_client(engine)
    # "default" 为 L0 合成单 provider id（fake.local），"fake-model" 为其唯一模型
    resp = client.post("/api/v1/chat", json={"message": "x", "model": "default/fake-model"})
    assert resp.status_code == 200
    assert resp.json()["final_answer"] == "用 pro 模型回答"
    assert fake.calls and fake.calls[0]["model"] == "fake-model"


def test_chat_model_unavailable_honest(build_test_engine, fake_settings):
    """per-call 模型不在注册表 → 如实 [模型不可用] 反馈，不静默降级、不调 LLM."""
    engine, fake = build_test_engine([])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "x", "model": "nonexistent/model-xyz"})
    assert resp.status_code == 200
    body = resp.json()
    assert "[模型不可用]" in body["final_answer"]
    assert "nonexistent/model-xyz" in body["final_answer"]
    assert len(fake.calls) == 0  # 未调 LLM


def test_chat_model_omitted_uses_default(build_test_engine, fake_settings):
    """不传 model 时透传 None（引擎用装配默认模型）."""
    engine, fake = build_test_engine([{"content": "ok"}])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "x"})
    assert resp.status_code == 200
    assert fake.calls and fake.calls[0]["model"] is None


def test_list_models_endpoint(build_test_engine, fake_settings):
    """GET /api/v1/models 返回候选模型列表 + 当前装配模型."""
    engine, fake = build_test_engine([{"content": "a"}])
    client = _make_client(engine)
    resp = client.get("/api/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    assert "models" in body and body["models"]
    assert body["current"] in body["models"]
    assert len(fake.calls) == 0  # 不调 LLM


# ── M56 Web/飞书会话同步：置顶 + 来源 + SSE + 飞书推送 ──


def test_session_pin_endpoint(build_test_engine, fake_settings):
    """POST /api/v1/sessions/{id}/pin?pinned=true 置顶；列表 pinned=True 且置顶优先."""
    engine, _ = build_test_engine([{"content": "a"}, {"content": "b"}])
    client = _make_client(engine)
    client.post("/api/v1/chat", json={"message": "a"})
    sid_b = client.post("/api/v1/chat", json={"message": "b"}).json()["session_id"]
    # 置顶 b（后创建的 b 本来排在前面；置顶后仍第一）
    resp = client.post(f"/api/v1/sessions/{sid_b}/pin?pinned=true")
    assert resp.status_code == 200
    assert resp.json()["pinned"] is True
    sessions = client.get("/api/v1/sessions").json()["sessions"]
    assert sessions[0]["session_id"] == sid_b and sessions[0]["pinned"] is True
    # 取消置顶
    resp = client.post(f"/api/v1/sessions/{sid_b}/pin?pinned=false")
    assert resp.status_code == 200
    sessions = client.get("/api/v1/sessions").json()["sessions"]
    assert sessions[0]["pinned"] is False


def test_session_pin_not_found(build_test_engine, fake_settings):
    """置顶不存在的会话 → 404."""
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.post("/api/v1/sessions/nope/pin?pinned=true")
    assert resp.status_code == 404


def test_list_sessions_includes_pinned_and_channel(build_test_engine, fake_settings):
    """列表透传 pinned/channel（M56）."""
    engine, _ = build_test_engine([{"content": "a"}])
    client = _make_client(engine)
    sid = client.post("/api/v1/chat", json={"message": "a"}).json()["session_id"]
    sessions = client.get("/api/v1/sessions").json()["sessions"]
    item = next(s for s in sessions if s["session_id"] == sid)
    assert item["pinned"] is False
    assert item["channel"] == "web"


def test_chat_feishu_channel_push(build_test_engine, fake_settings, monkeypatch):
    """飞书来源会话发消息 → 后台推送到飞书（mock 推送，fail-open）."""
    import llm_loop.web.feishu_push as fp

    pushed = []
    monkeypatch.setattr(fp, "push_web_chat_to_feishu", lambda channel, user_text, answer: pushed.append((channel, user_text, answer)))
    engine, _ = build_test_engine([{"content": "第一答"}, {"content": "回答内容"}])
    client = _make_client(engine)
    sid = client.post("/api/v1/chat", json={"message": "web 消息"}).json()["session_id"]
    engine.session.set_channel(sid, "feishu:group:oc_test_chat")
    resp = client.post("/api/v1/chat", json={"message": "第二句", "session_id": sid})
    assert resp.status_code == 200
    assert pushed, "飞书来源会话应触发推送"
    channel, user_text, answer = pushed[0]
    assert channel == "feishu:group:oc_test_chat"
    assert user_text == "第二句"
    assert answer == "回答内容"


def test_chat_web_channel_no_push(build_test_engine, fake_settings, monkeypatch):
    """Web 来源会话发消息不触发飞书推送."""
    import llm_loop.web.feishu_push as fp

    pushed = []
    monkeypatch.setattr(fp, "push_web_chat_to_feishu", lambda channel, user_text, answer: pushed.append(1))
    engine, _ = build_test_engine([{"content": "ok"}])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "x"})
    assert resp.status_code == 200
    assert not pushed


def test_sse_events_endpoint(build_test_engine, fake_settings):
    """SSE 端点已注册 + 指纹变化检测正确（无限流不做 HTTP 级流读，冒烟阶段 curl 验证）."""
    from llm_loop.web.routes import _sessions_fingerprint

    engine, _ = build_test_engine([{"content": "a"}])
    client = _make_client(engine)
    client.post("/api/v1/chat", json={"message": "a"})
    # 指纹变化检测：写入新会话文件后指纹应变化
    fp_before = _sessions_fingerprint(engine.settings.sessions_dir)
    engine.session.create()
    fp_after = _sessions_fingerprint(engine.settings.sessions_dir)
    assert fp_before != fp_after
    # 端点已注册（OpenAPI schema）
    schema = client.get("/openapi.json").json()
    assert "/api/v1/events" in schema["paths"]
    # 端点信息含在 /api/info
    info = client.get("/api/info").json()
    assert "GET /api/v1/events" in info["endpoints"]


# ── 2026-08-15: SSE 命名事件修复（此前 data 内嵌 type，浏览器按默认 message 处理，
#    addEventListener("sessions_updated") 永不触发 → Web 端必须手动刷新）──

def test_sse_named_event_frame_format():
    """命名事件帧带 `event:` 行（浏览器按命名事件分发的前置条件）."""
    from llm_loop.web.routes import _sse_event

    frame = _sse_event("sessions_updated", {"type": "sessions_updated"})
    assert frame.startswith("event: sessions_updated\n")
    assert "data: {\"type\": \"sessions_updated\"}" in frame
    assert frame.endswith("\n\n")
    conn = _sse_event("connected", {"type": "connected"})
    assert conn.startswith("event: connected\n")


def test_sse_route_uses_named_event_helper():
    """端点使用 _sse_event 生成帧（防回退 data 内嵌 type 格式的回归守护）."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "web" / "routes.py"
    text = src.read_text(encoding="utf-8")
    assert '_sse_event("sessions_updated"' in text
    assert '_sse_event("connected"' in text
    assert 'yield "data: ' not in text  # 旧格式（无 event: 行）不再出现


# ── Web V2（2026-08-15）：/ui/v2 挂载并存（原版 / 不动；产物缺失不挂载） ──

def test_ui_v2_mounted_when_dist_present(build_test_engine, fake_settings, tmp_path, monkeypatch):
    """webui/dist 存在（UI_V2_DIR 注入）→ /ui/v2 挂载并可取 index.html."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>Web V2</body></html>", encoding="utf-8")
    monkeypatch.setenv("UI_V2_DIR", str(dist))
    engine, _ = build_test_engine([{"content": "a"}])
    client = _make_client(engine)
    resp = client.get("/ui/v2/")
    assert resp.status_code == 200
    assert "Web V2" in resp.text


def test_ui_v2_not_mounted_without_dist(build_test_engine, fake_settings, tmp_path, monkeypatch):
    """无构建产物（CI/未构建）→ /ui/v2 不挂载（404），原版 / 不受影响."""
    monkeypatch.setenv("UI_V2_DIR", str(tmp_path / "nonexistent"))
    engine, _ = build_test_engine([{"content": "a"}])
    client = _make_client(engine)
    assert client.get("/ui/v2/").status_code == 404
    assert client.get("/").status_code in (200, 307)  # 原版入口不受影响


def test_ui_v2_assets_same_origin_api(build_test_engine, fake_settings, tmp_path, monkeypatch):
    """V2 静态资源与 API 同源（base=/ui/v2/ 的 assets 可解析）."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        '<script type="module" src="/ui/v2/assets/index-x.js"></script>', encoding="utf-8"
    )
    (dist / "assets").mkdir()
    (dist / "assets" / "index-x.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("UI_V2_DIR", str(dist))
    engine, _ = build_test_engine([{"content": "a"}])
    client = _make_client(engine)
    assert client.get("/ui/v2/assets/index-x.js").status_code == 200


# ── 2026-08-15：消息反馈（对齐 DSH ui-message-feedback） ──

def test_feedback_appends_jsonl(build_test_engine, fake_settings, tmp_path, monkeypatch):
    """反馈 → data/feedback.jsonl 追加（含 role/note），会话内容不变."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([{"content": "回答内容"}])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "你好"})
    sid = resp.json()["session_id"]
    before = engine.session.load(sid)
    r = client.post(
        f"/api/v1/sessions/{sid}/feedback",
        json={"message_index": 1, "feedback": "up", "note": "回答准确"},
    )
    assert r.status_code == 200
    lines = (Path(engine.settings.data_dir) / "feedback.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = __import__("json").loads(lines[0])
    assert rec["session_id"] == sid and rec["feedback"] == "up" and rec["note"] == "回答准确"
    assert rec["role"] == "assistant"
    after = engine.session.load(sid)
    assert len(after.messages) == len(before.messages)  # 会话内容未被反馈修改


def test_feedback_validations(build_test_engine, fake_settings, tmp_path, monkeypatch):
    """非法 feedback / 越界 index → 400 如实."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([{"content": "a"}])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "hi"})
    sid = resp.json()["session_id"]
    assert (
        client.post(
            f"/api/v1/sessions/{sid}/feedback",
            json={"message_index": 0, "feedback": "sideways"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/v1/sessions/{sid}/feedback",
            json={"message_index": 999, "feedback": "up"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/sessions/nonexistent/feedback",
            json={"message_index": 0, "feedback": "up"},
        ).status_code
        == 404
    )
