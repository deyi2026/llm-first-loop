"""Web 远程监听鉴权（M36，P1）。

WEB_API_KEY + Authorization: Bearer，回环默认豁免，
远程绑定 + 未配置 key → 启动报错退出（不静默降级）。
"""

import hmac
import ipaddress
import os
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


def _web_api_key() -> str:
    """WEB_API_KEY（env 直读，对齐 config.py 既有 env 直读范式）."""
    return os.environ.get("WEB_API_KEY", "").strip()


def is_loopback(host: str) -> bool:
    """监听地址是否为回环（127.0.0.1 / localhost / ::1）."""
    if host in {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> None:
    """远程访问令牌校验（仅 HTTP 层访问控制，核心零改动）.

    回环默认豁免；WEB_AUTH_REQUIRE=1 时回环也要求令牌。

    P2-1(2026-08-15)：fail-closed——WEB_AUTH_REQUIRE=1 但未配置 WEB_API_KEY
    属于配置错误（显式要求鉴权却不可能通过），旧实现静默放行等于无鉴权；
    现 503 如实报错（启动期由 validate_auth_require 拦截，请求期兜底防御）。
    """
    expected = _web_api_key()
    if not expected:
        if os.environ.get("WEB_AUTH_REQUIRE", "").strip() == "1":
            raise HTTPException(
                status_code=503,
                detail=(
                    "WEB_AUTH_REQUIRE=1 但未配置 WEB_API_KEY——鉴权配置错误，拒绝服务"
                    "（fail-closed：要么配置 key，要么关闭 WEB_AUTH_REQUIRE）。"
                ),
            )
        return  # 未配置 key 时由启动校验拦截远程绑定；本地无 key 放行

    if os.environ.get("WEB_AUTH_REQUIRE", "").strip() != "1":
        host = os.environ.get("WEB_HOST", "127.0.0.1")
        if is_loopback(host):
            return  # 回环默认豁免

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="缺少 Authorization: Bearer 令牌。")
    if not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="令牌无效。")


def validate_auth_require() -> None:
    """P2-1: WEB_AUTH_REQUIRE=1 但未配置 WEB_API_KEY → 启动拒绝（对齐 validate_binding 语义）."""
    if os.environ.get("WEB_AUTH_REQUIRE", "").strip() == "1" and not _web_api_key():
        raise RuntimeError(
            "WEB_AUTH_REQUIRE=1 但未配置 WEB_API_KEY：显式要求鉴权却没有可校验的令牌，"
            "fail-closed 拒绝启动——请配置 WEB_API_KEY 或关闭 WEB_AUTH_REQUIRE。"
        )


def validate_binding(host: str) -> None:
    """远程绑定校验：非回环 + 未配置 WEB_API_KEY → 启动报错退出."""
    if not is_loopback(host) and not _web_api_key():
        raise RuntimeError(
            "远程监听（WEB_HOST 非回环）须配置 WEB_API_KEY（Authorization: Bearer 令牌）才能启动；"
            "本机使用请保持 WEB_HOST=127.0.0.1。"
        )
