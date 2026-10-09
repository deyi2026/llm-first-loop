"""FR-05：MCP HTTP OAuth 与凭证绑定（设计 §8.2）.

- 缺凭证可诊断：credential_ref 指向未定义 env → McpCredentialError
  （附服务器名与 ref，不泄漏值）
- client_credentials（S2S）：401 → 资源/AS 元数据发现 → DCR → 换取 → 重放成功；
  令牌按（资源源, credential_ref）缓存复用
- 授权码 + PKCE：McpAuthRequiredError 携带授权 URL；外部完成授权后
  complete_authorization(code, state) 交换令牌（AS 校验 S256 verifier）
- 身份隔离：同端点不同 credential_ref → 各自令牌与身份，不共享
"""

import pytest

from llm_loop.tools.mcp_auth import (
    McpAuthRequiredError,
    McpCredentialError,
)
from llm_loop.tools.mcp_client import McpConnection, McpServerSpec
from tests.fixtures.fake_mcp_http_server import FakeMcpHttpServer
from tests.fixtures.fake_mcp_oauth_server import FakeOAuthAuthorizationServer


def _gated_pair() -> tuple[FakeOAuthAuthorizationServer, FakeMcpHttpServer]:
    oauth = FakeOAuthAuthorizationServer()
    mcp = FakeMcpHttpServer("modern", token_gate=oauth)
    return oauth, mcp


def _spec(url: str, credential_ref: str | None = None) -> McpServerSpec:
    return McpServerSpec(name="srv", type="http", url=url, credential_ref=credential_ref)


def test_missing_credential_diagnosable(monkeypatch):
    """缺凭证：报错点名服务器与 credential_ref（不泄漏值），不静默降级."""
    oauth, mcp = _gated_pair()
    try:
        monkeypatch.delenv("MCP_TEST_SECRET_NOPE", raising=False)
        conn = McpConnection(
            _spec(mcp.url, credential_ref="env:MCP_TEST_SECRET_NOPE"),
            call_timeout=10,
            probe_timeout_s=2,
        )
        with pytest.raises(McpCredentialError) as excinfo:
            conn.connect()
        message = str(excinfo.value)
        assert "srv" in message, "错误应点名服务器"
        assert "env:MCP_TEST_SECRET_NOPE" in message, "错误应点名 credential_ref"
        assert "MCP_TEST_SECRET_NOPE" in excinfo.value.ref
    finally:
        mcp.close()
        oauth.close()


def test_client_credentials_flow_and_cache(monkeypatch):
    """S2S：401 → 发现 → DCR → client_credentials 换取 → 重放成功；令牌缓存复用."""
    oauth, mcp = _gated_pair()
    try:
        monkeypatch.setenv("MCP_TEST_CC_SECRET", "s2s-secret-A")
        conn = McpConnection(
            _spec(mcp.url, credential_ref="env:MCP_TEST_CC_SECRET"),
            call_timeout=10,
            probe_timeout_s=2,
        )
        tools = conn.connect()
        assert tools, "OAuth 后应拉到工具清单"
        bearer = conn.transport.oauth.cached_bearer()
        assert bearer and oauth.is_valid_token(bearer)
        assert oauth.token_identity(bearer) == "s2s-secret-A"
        assert oauth.register_count >= 1, "应经动态客户端注册"
        exchanges = oauth.token_exchange_count

        conn2 = McpConnection(
            _spec(mcp.url, credential_ref="env:MCP_TEST_CC_SECRET"),
            call_timeout=10,
            probe_timeout_s=2,
        )
        assert conn2.connect(), "同身份复用缓存令牌（预置 Bearer，无 401）"
        assert oauth.token_exchange_count == exchanges, "缓存有效时不重复换取"
        conn.close()
        conn2.close()
    finally:
        mcp.close()
        oauth.close()


def test_authorization_code_pkce(monkeypatch):
    """交互式：McpAuthRequiredError 带 URL/state → 外部授权 → code 交换（PKCE 校验）."""
    oauth, mcp = _gated_pair()
    try:
        conn = McpConnection(_spec(mcp.url), call_timeout=10, probe_timeout_s=2)
        with pytest.raises(McpAuthRequiredError) as excinfo:
            conn.connect()
        auth_error = excinfo.value
        assert auth_error.authorization_url.startswith(oauth.url)
        assert auth_error.state

        result = oauth.authorize(auth_error.authorization_url)  # 模拟用户授权
        conn.transport.oauth.complete_authorization(result["code"], auth_error.state)
        tools = conn.connect()
        assert tools, "授权码换令牌后应可连接"
        assert oauth.pkce_verified, "AS 必须校验过 PKCE verifier↔challenge"
        conn.close()
    finally:
        mcp.close()
        oauth.close()


def test_identity_isolation_same_endpoint(monkeypatch):
    """同端点不同 credential_ref：各自令牌与身份，互不共享（授权与服务隔离）."""
    oauth, mcp = _gated_pair()
    try:
        monkeypatch.setenv("MCP_TEST_ID_A", "identity-A")
        monkeypatch.setenv("MCP_TEST_ID_B", "identity-B")
        conn_a = McpConnection(
            _spec(mcp.url, credential_ref="env:MCP_TEST_ID_A"),
            call_timeout=10,
            probe_timeout_s=2,
        )
        conn_b = McpConnection(
            _spec(mcp.url, credential_ref="env:MCP_TEST_ID_B"),
            call_timeout=10,
            probe_timeout_s=2,
        )
        assert conn_a.connect()
        assert conn_b.connect()
        bearer_a = conn_a.transport.oauth.cached_bearer()
        bearer_b = conn_b.transport.oauth.cached_bearer()
        assert bearer_a and bearer_b and bearer_a != bearer_b
        assert oauth.token_identity(bearer_a) == "identity-A"
        assert oauth.token_identity(bearer_b) == "identity-B"
        assert oauth.token_exchange_count >= 2, "两身份各自换取"
        conn_a.close()
        conn_b.close()
    finally:
        mcp.close()
        oauth.close()
