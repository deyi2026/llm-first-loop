"""P2-1(2026-08-15，审计发现)：鉴权 fail-closed + 回环 mutating 端点 Origin/CSRF 防护.

- `WEB_AUTH_REQUIRE=1` 但未配置 WEB_API_KEY：旧实现 `if not expected: return` 静默放行
  （fail-open 成无鉴权）——修复为启动拒绝（对齐 validate_binding 语义）+ 请求期 503 如实报错。
- 回环豁免部署（默认本机）的 mutating 端点此前可被任意网页跨站 POST（浏览器表单/fetch
  打 127.0.0.1）——修复为 Origin 头校验：mutating 方法带非回环 Origin → 403。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from llm_loop.web.auth import require_api_key, validate_auth_require, validate_origin_allowlist


def _cred(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class TestAuthRequireFailClosed:
    """WEB_AUTH_REQUIRE=1 无 key → fail-closed（不再静默放行）."""

    def test_require_without_key_rejects_request(self, monkeypatch):
        monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
        monkeypatch.delenv("WEB_API_KEY", raising=False)
        with pytest.raises(HTTPException) as ei:
            require_api_key(None)
        assert ei.value.status_code == 503
        assert "WEB_API_KEY" in ei.value.detail

    def test_require_without_key_refuses_startup(self, monkeypatch):
        monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
        monkeypatch.delenv("WEB_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="WEB_API_KEY"):
            validate_auth_require()

    def test_require_with_key_works(self, monkeypatch):
        monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
        monkeypatch.setenv("WEB_API_KEY", "k-" + "x" * 20)
        require_api_key(_cred("k-" + "x" * 20))  # 合法令牌放行
        with pytest.raises(HTTPException) as ei:
            require_api_key(_cred("wrong-token"))
        assert ei.value.status_code == 401

    def test_no_require_no_key_allows_local(self, monkeypatch):
        """零回归：未设 WEB_AUTH_REQUIRE 且无 key → 本地放行（语义不变）."""
        monkeypatch.delenv("WEB_AUTH_REQUIRE", raising=False)
        monkeypatch.delenv("WEB_API_KEY", raising=False)
        # WEB_ORIGIN_ALLOWLIST 非空同样令 auth_required() 为 True（P3 绑定）；
        # 宿主（LFL web 部署）环境自带该变量，须显式隔离否则假红。
        monkeypatch.delenv("WEB_ORIGIN_ALLOWLIST", raising=False)
        require_api_key(None)  # 不抛
        validate_auth_require()  # 不抛


class TestOriginAllowlistFailClosed:
    """P3(2026-09-04，安全审查)：WEB_ORIGIN_ALLOWLIST 非空（隧道公网暴露意图）无 key → 拒绝启动.

    隧道场景公网流量经本机回环进入，require_api_key 回环豁免被击穿——
    "开隧道"与"必须鉴权"在启动期绑死（fail-closed），对齐 validate_binding 哲学。
    """

    def test_allowlist_without_key_refuses_startup(self, monkeypatch):
        monkeypatch.setenv("WEB_ORIGIN_ALLOWLIST", "app.example.com,example.com")
        monkeypatch.delenv("WEB_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="WEB_API_KEY"):
            validate_origin_allowlist()

    def test_allowlist_with_key_passes(self, monkeypatch):
        monkeypatch.setenv("WEB_ORIGIN_ALLOWLIST", "app.example.com")
        monkeypatch.setenv("WEB_API_KEY", "k-" + "x" * 20)
        validate_origin_allowlist()  # 不抛：暴露意图已配令牌

    def test_no_allowlist_no_key_allows_local(self, monkeypatch):
        """零回归：无 allowlist 且无 key → 本地部署语义不变（放行）."""
        monkeypatch.delenv("WEB_ORIGIN_ALLOWLIST", raising=False)
        monkeypatch.delenv("WEB_API_KEY", raising=False)
        validate_origin_allowlist()  # 不抛

    def test_blank_allowlist_treated_as_disabled(self, monkeypatch):
        """空值=未启用公网 Origin 白名单。"""
        monkeypatch.setenv("WEB_ORIGIN_ALLOWLIST", "   ")
        monkeypatch.delenv("WEB_API_KEY", raising=False)
        validate_origin_allowlist()  # 不抛


class TestOriginGuard:
    """回环豁免部署的 Origin/CSRF 防护（mutating 方法）."""

    def _app(self, monkeypatch, build_test_engine, *, public_allowlist: str | None = None):
        monkeypatch.delenv("WEB_API_KEY", raising=False)
        monkeypatch.delenv("WEB_AUTH_REQUIRE", raising=False)
        # 宿主环境可能泄漏 WEB_ORIGIN_ALLOWLIST（auth_required() 请求期读 env，
        # 非空即启用鉴权→fail-closed 503 假红）；默认显式隔离。
        # 需要公网 Origin 的用例经 public_allowlist 显式注入（middleware 在 build 期快照）。
        if public_allowlist is None:
            monkeypatch.delenv("WEB_ORIGIN_ALLOWLIST", raising=False)
        else:
            monkeypatch.setenv("WEB_ORIGIN_ALLOWLIST", public_allowlist)
        monkeypatch.setenv("WEB_HOST", "127.0.0.1")
        from llm_loop.web import build_app

        engine, _fake = build_test_engine([{"content": "ok"}])
        return build_app(engine=engine)

    def test_cross_site_origin_post_blocked(self, monkeypatch, build_test_engine):
        from starlette.testclient import TestClient

        client = TestClient(self._app(monkeypatch, build_test_engine), base_url="http://127.0.0.1:8902")
        r = client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"Origin": "https://evil.example.com"},
        )
        assert r.status_code == 403
        assert "Origin" in r.json().get("detail", "") or "跨站" in r.json().get("detail", "")

    def test_loopback_origin_post_allowed(self, monkeypatch, build_test_engine):
        """零回归：本机页面（Origin 为回环）正常放行."""
        from starlette.testclient import TestClient

        client = TestClient(self._app(monkeypatch, build_test_engine), base_url="http://127.0.0.1:8902")
        r = client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"Origin": "http://127.0.0.1:8902"},
        )
        assert r.status_code == 200

    def test_no_origin_post_allowed(self, monkeypatch, build_test_engine):
        """零回归：无 Origin（curl/脚本/服务器间调用）放行——浏览器跨站必带 Origin."""
        from starlette.testclient import TestClient

        client = TestClient(self._app(monkeypatch, build_test_engine), base_url="http://127.0.0.1:8902")
        r = client.post("/api/v1/chat", json={"message": "hi"})
        assert r.status_code == 200


    def test_same_loopback_host_wrong_port_is_blocked(self, monkeypatch, build_test_engine):
        from starlette.testclient import TestClient

        client = TestClient(self._app(monkeypatch, build_test_engine), base_url="http://127.0.0.1:8902")
        r = client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"Origin": "http://127.0.0.1:9999"},
        )
        assert r.status_code == 403

    def test_public_allowlist_is_exact_scheme_host_port(self, monkeypatch, build_test_engine):
        from starlette.testclient import TestClient

        from llm_loop.web.auth import hash_login_password

        monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password("correct-horse-battery"))
        app = self._app(
            monkeypatch, build_test_engine, public_allowlist="https://app.example.com"
        )
        client = TestClient(app, base_url="https://app.example.com")

        exact = client.post(
            "/auth/login",
            data={"password": "wrong-password"},
            headers={"Origin": "https://app.example.com"},
        )
        assert exact.status_code == 401
        wrong_scheme = client.post(
            "/auth/login",
            data={"password": "wrong-password"},
            headers={"Origin": "http://app.example.com"},
        )
        assert wrong_scheme.status_code == 403
        wrong_port = client.post(
            "/auth/login",
            data={"password": "wrong-password"},
            headers={"Origin": "https://app.example.com:8443"},
        )
        assert wrong_port.status_code == 403

    def test_get_with_foreign_origin_allowed(self, monkeypatch, build_test_engine):
        """GET 非 mutating 不受 Origin 校验（健康检查等跨源可读无写副作用）."""
        from starlette.testclient import TestClient

        client = TestClient(self._app(monkeypatch, build_test_engine), base_url="http://127.0.0.1:8902")
        r = client.get("/health", headers={"Origin": "https://evil.example.com"})
        assert r.status_code == 200
