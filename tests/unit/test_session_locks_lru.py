"""P2-3(2026-08-15，审计发现)：session_locks LRU 上限 + 建会话/取锁原子性.

- 旧实现 `locks[session_id] = Lock()` 无界增长（每会话一把锁常驻内存）。
- 无 session_id 的并发首请求：get_shared→create→set_shared 与取锁不在同一把 guard 内，
  两线程可各自建会话（后者覆盖共享当前，前者会话成孤儿）。
"""

from __future__ import annotations

import threading

from llm_loop.web.routes import _SESSION_LOCKS_MAX, _get_session_lock


class _FakeAppState:
    def __init__(self):
        self.session_locks = {}


class _FakeRequest:
    def __init__(self):
        self.app = type("A", (), {"state": _FakeAppState()})()


class TestSessionLocksLRU:
    def test_lru_cap_evicts_idle(self):
        req = _FakeRequest()
        locks = [_get_session_lock(req, f"s{i}") for i in range(_SESSION_LOCKS_MAX + 50)]
        assert len(req.app.state.session_locks) <= _SESSION_LOCKS_MAX
        # 最新保留、最老淘汰
        assert _get_session_lock(req, f"s{_SESSION_LOCKS_MAX + 49}") is locks[-1]
        assert "s0" not in req.app.state.session_locks  # noqa: F601

    def test_held_lock_survives_eviction_scan(self):
        """持有中的锁不被淘汰（淘汰跳过 locked 项——防互斥失效）."""
        req = _FakeRequest()
        held = _get_session_lock(req, "held")
        held.acquire()
        try:
            for i in range(_SESSION_LOCKS_MAX + 50):
                _get_session_lock(req, f"x{i}")
            # held 会话的锁对象仍是同一把（未被淘汰后重建）
            assert _get_session_lock(req, "held") is held
        finally:
            held.release()

    def test_disabled_returns_none(self):
        """零回归：session_locks=None（SESSION_CONCURRENCY_LOCK=false）→ 无锁."""
        req = _FakeRequest()
        req.app.state.session_locks = None
        assert _get_session_lock(req, "s1") is None


class TestCreateThenLockAtomicity:
    def _client(self, monkeypatch, build_test_engine):
        monkeypatch.delenv("WEB_API_KEY", raising=False)
        monkeypatch.delenv("WEB_AUTH_REQUIRE", raising=False)
        monkeypatch.setenv("WEB_HOST", "127.0.0.1")
        from starlette.testclient import TestClient

        from llm_loop.web import build_app

        engine, _fake = build_test_engine([{"content": f"r{i}"} for i in range(32)])
        return TestClient(build_app(engine=engine)), engine

    def test_concurrent_first_chat_single_session(self, monkeypatch, build_test_engine):
        """8 线程并发无 sid 首聊 → 恰好建 1 个会话、全部共用同一 session_id."""
        client, engine = self._client(monkeypatch, build_test_engine)
        # 拉宽竞态窗口：create 后 sleep 再设共享（无 guard 时必双建）
        import time

        orig_create = engine.session.create
        create_calls = []
        guard = threading.Lock()

        def slow_create(*a, **kw):
            sid = orig_create(*a, **kw)
            with guard:
                create_calls.append(sid)
            time.sleep(0.05)  # 竞态窗口
            return sid

        monkeypatch.setattr(engine.session, "create", slow_create)
        # 不打 get_shared_current：真实实现会在 T1 设共享后让 T2 看到（guard 语义验证点）

        results: list[str] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(8)

        def post_chat():
            try:
                barrier.wait(timeout=5)
                r = client.post("/api/v1/chat", json={"message": "hi"})
                assert r.status_code == 200, r.text[:200]
                results.append(r.json()["session_id"])
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=post_chat) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not errors, f"并发请求异常: {errors[:2]}"
        assert len(set(results)) == 1, f"并发首聊建了多个会话: {set(results)}"
        assert len(create_calls) == 1, f"create 被调用 {len(create_calls)} 次（竞态未闭合）"
