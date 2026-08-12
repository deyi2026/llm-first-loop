"""会话级并发锁测试（spec.md 5.4.1 / design.md §2.1.3.4 / tasks.md T5.4）.

断言:
1. 锁启用时同会话连续请求都成功（不死锁）
2. 不同会话并行不互相阻塞
3. 锁超时返回 503 + 如实提示
4. SESSION_CONCURRENCY_LOCK=false 时退化为无锁（向后兼容）
"""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from llm_loop.web import build_app
from llm_loop.web import routes as routes_module


def _make_client(engine):
    return TestClient(build_app(engine=engine))


class TestLockEnabled:
    def test_same_session_sequential_succeeds(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "一"}, {"content": "二"}])
        client = _make_client(engine)
        r1 = client.post("/api/v1/chat", json={"message": "一"})
        sid = r1.json()["session_id"]
        r2 = client.post("/api/v1/chat", json={"message": "二", "session_id": sid})
        assert r1.status_code == 200 and r2.status_code == 200

    def test_different_sessions_not_blocked(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "a"}, {"content": "b"}])
        client = _make_client(engine)
        sid1 = engine.session.create()
        sid2 = engine.session.create()
        r1 = client.post("/api/v1/chat", json={"message": "a", "session_id": sid1})
        r2 = client.post("/api/v1/chat", json={"message": "b", "session_id": sid2})
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["session_id"] != r2.json()["session_id"]


class TestLockTimeout:
    def test_timeout_returns_503(self, build_test_engine, monkeypatch):
        monkeypatch.setattr(routes_module, "_LOCK_TIMEOUT_S", 0.1)
        engine, _ = build_test_engine([{"content": "ok"}])
        client = _make_client(engine)
        r1 = client.post("/api/v1/chat", json={"message": "init"})
        sid = r1.json()["session_id"]
        lock = client.app.state.session_locks[sid]
        holder = threading.Thread(target=lock.acquire)
        holder.start()
        holder.join()
        try:
            resp = client.post("/api/v1/chat", json={"message": "blocked", "session_id": sid})
            assert resp.status_code == 503
            assert resp.json()["error"] == "session_busy"
        finally:
            lock.release()


class TestLockDisabled:
    def test_backward_compat_no_lock(self, build_test_engine, monkeypatch):
        monkeypatch.setenv("SESSION_CONCURRENCY_LOCK", "false")
        engine, _ = build_test_engine([{"content": "ok"}])
        client = _make_client(engine)
        resp = client.post("/api/v1/chat", json={"message": "hi"})
        assert resp.status_code == 200
        assert client.app.state.session_locks is None
