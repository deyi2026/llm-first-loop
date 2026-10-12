"""P2-2(2026-08-15，审计发现)：upload base64 体积前置检查（解码前）.

旧实现先 b64decode 再查体积——大 payload 先吃解码内存/CPU 再被拒；
现先查 base64 字符串长度（≈4/3 原始体积），超限直接 413。
"""

from __future__ import annotations

import base64

from llm_loop.web.upload_handlers import MAX_UPLOAD_BYTES, validate_upload_b64_size


class TestB64SizeHelper:
    def test_under_limit_passes(self):
        small = base64.b64encode(b"x" * 1024).decode()
        assert validate_upload_b64_size(small) is None

    def test_over_limit_rejected(self):
        big = "A" * (MAX_UPLOAD_BYTES * 4 // 3 + 32)
        err = validate_upload_b64_size(big)
        assert err is not None
        assert "10MB" in err

    def test_boundary_slack(self):
        """恰在上限附近（+16 宽限内）放行——宽限覆盖 base64 padding/换行."""
        edge = "A" * (MAX_UPLOAD_BYTES * 4 // 3 + 10)
        assert validate_upload_b64_size(edge) is None


class TestUploadRoutePrecheck:
    def _client(self, monkeypatch, build_test_engine):
        monkeypatch.delenv("WEB_API_KEY", raising=False)
        monkeypatch.delenv("WEB_AUTH_REQUIRE", raising=False)
        monkeypatch.setenv("WEB_HOST", "127.0.0.1")
        from starlette.testclient import TestClient

        from llm_loop.web import build_app

        engine, _fake = build_test_engine([{"content": "ok"}])
        return TestClient(build_app(engine=engine))

    def test_oversized_b64_rejected_before_decode(self, monkeypatch, build_test_engine):
        """超限 base64（且含非法字符）→ 413 而非 400——证明未进入解码路径."""
        client = self._client(monkeypatch, build_test_engine)
        # 含 "!" 非法 base64 字符：若走到解码会 400；前置拦截必须 413
        payload = "!" * (MAX_UPLOAD_BYTES * 4 // 3 + 64)
        r = client.post("/api/v1/upload", json={"filename": "big.txt", "data": payload})
        assert r.status_code == 413
        assert r.json()["error"] == "upload_too_large"

    def test_small_text_upload_ok(self, monkeypatch, build_test_engine):
        """零回归：小文本文件正常处理."""
        client = self._client(monkeypatch, build_test_engine)
        data = base64.b64encode("你好，世界".encode()).decode()
        r = client.post("/api/v1/upload", json={"filename": "a.txt", "data": data})
        assert r.status_code == 200
        assert r.json()["status"] in ("ok", "degraded")

    def test_invalid_base64_still_400(self, monkeypatch, build_test_engine):
        """零回归：未超限但非法 base64 → 400（解码路径仍在）."""
        client = self._client(monkeypatch, build_test_engine)
        r = client.post("/api/v1/upload", json={"filename": "a.txt", "data": "!!!not-b64!!!"})
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_base64"
