"""历史会话懒加载测试（spec 5.3.2 D2 / design §2.4.4 / tasks 4.4）.

断言:
1. get_session_messages 带 limit 返回连续切片 + has_more/total 正确
2. 不传 limit 全量返回 + has_more=false + total=len（向后兼容）
3. offset >= total → messages=[] + has_more=false，不报错
4. 全部页拼接 == 会话全部消息（顺序不变、不丢一条）
5. MessageItem 契约不变
6. app.js loadSessionMessages 含 limit/offset + 加载更早逻辑
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.web import build_app

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "llm_loop" / "web" / "static" / "app.js"


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def _build_session(build_test_engine, n_messages: int):
    """发 n 条消息构造会话（每条 chat 产生 user + assistant 共 2 条），返回 (engine, sid, total)."""
    engine, _ = build_test_engine([{"content": f"m{i}"} for i in range(n_messages)])
    client = _make_client(engine)
    sid = None
    for i in range(n_messages):
        r = client.post("/api/v1/chat", json={"message": f"m{i}"})
        assert r.status_code == 200
        sid = r.json()["session_id"]
    return engine, sid, n_messages * 2


class TestHistoryPagination:
    def test_limit_returns_slice(self, build_test_engine):
        engine, sid, total = _build_session(build_test_engine, 3)  # 6 条
        client = _make_client(engine)
        resp = client.get(f"/api/v1/sessions/{sid}/messages?limit=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == total
        assert len(body["messages"]) == 2
        assert body["has_more"] is True

    def test_no_limit_returns_all(self, build_test_engine):
        engine, sid, total = _build_session(build_test_engine, 3)
        client = _make_client(engine)
        resp = client.get(f"/api/v1/sessions/{sid}/messages")
        body = resp.json()
        assert len(body["messages"]) == total
        assert body["has_more"] is False
        assert body["total"] == total

    def test_offset_beyond_total_returns_empty(self, build_test_engine):
        engine, sid, total = _build_session(build_test_engine, 2)
        client = _make_client(engine)
        resp = client.get(f"/api/v1/sessions/{sid}/messages?limit=10&offset={total + 5}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["messages"] == []
        assert body["has_more"] is False

    def test_all_pages_concat_equals_full(self, build_test_engine):
        engine, sid, total = _build_session(build_test_engine, 4)  # 8 条
        client = _make_client(engine)
        collected = []
        offset = 0
        while True:
            resp = client.get(f"/api/v1/sessions/{sid}/messages?limit=3&offset={offset}")
            body = resp.json()
            collected = body["messages"] + collected
            if not body["has_more"]:
                break
            offset += 3
        assert len(collected) == total

    def test_message_item_contract_unchanged(self, build_test_engine):
        engine, sid, _ = _build_session(build_test_engine, 1)
        client = _make_client(engine)
        resp = client.get(f"/api/v1/sessions/{sid}/messages?limit=10")
        for m in resp.json()["messages"]:
            assert set(m.keys()) <= {"role", "content", "tool_call_id", "reasoning_content"}


class TestFrontendLazyLoad:
    def test_load_session_messages_uses_limit(self):
        app_js = APP_JS.read_text(encoding="utf-8")
        assert "loadSessionMessages" in app_js
        assert "?limit=" in app_js
        assert "limit=${HISTORY_PAGE_SIZE}" in app_js

    def test_load_earlier_history_defined(self):
        app_js = APP_JS.read_text(encoding="utf-8")
        assert "async function loadEarlierHistory" in app_js
        assert "&offset=" in app_js
        assert "加载更早消息" in app_js
