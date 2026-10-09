"""Leaf opt-in isolated-transport context for both budget and process modules.

There must be no runtime import cycle between physical budget enforcement
and its exclusive transport implementation.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class IsolatedTransportProfile:
    """Trusted explicit worker transport; never taken from model output."""

    verify: bool | str = True
    proxy: str | None = None

    def __post_init__(self) -> None:
        if self.verify is False:
            raise ValueError("isolated_transport_tls_verify_required")
        if not (self.verify is True or isinstance(self.verify, str) and self.verify):
            raise ValueError("isolated_transport_verify_invalid")
        if self.proxy is not None and (
            not isinstance(self.proxy, str) or not self.proxy.startswith("http://")
        ):
            raise ValueError("isolated_transport_proxy_requires_explicit_http_url")


_ISOLATED_PROFILE: ContextVar[IsolatedTransportProfile | None] = ContextVar(
    "lfl_i5d_isolated_provider_transport", default=None
)


def active_isolated_transport_profile() -> IsolatedTransportProfile | None:
    """Observe the trusted binding; never activate an unapproved process."""
    return _ISOLATED_PROFILE.get()


@contextmanager
def bind_isolated_provider_transport(profile: IsolatedTransportProfile) -> Iterator[None]:
    """Qualified operator/test opt-in, never automatically installed by Web."""
    if not isinstance(profile, IsolatedTransportProfile):
        raise TypeError("isolated_transport_profile_required")
    scope = _ISOLATED_PROFILE.set(profile)
    try:
        yield
    finally:
        _ISOLATED_PROFILE.reset(scope)


def qualify_loopback_provider_proxy(value: object) -> str | None:
    """Strict operator proxy shape: plain http:// loopback host, explicit port.

    Returns the canonical value, or None when absent/invalid. No credentials,
    path, query, fragment, https, socks, or non-loopback egress is accepted.
    """
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 256:
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme != "http"
        or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
        or port is None or not 1 <= port <= 65535
        or parts.username is not None or parts.password is not None
        or parts.query or parts.fragment
        or parts.path not in ("", "/")
    ):
        return None
    return value


_AUTHORIZED_PROVIDER_PROXY: ContextVar[str | None] = ContextVar(
    "lfl_admin_once_authorized_provider_proxy", default=None
)


def active_authorized_provider_proxy() -> str | None:
    """The operator-pinned loopback proxy of the active admin-once plan, if any."""
    return _AUTHORIZED_PROVIDER_PROXY.get()


@contextmanager
def bind_authorized_provider_proxy(proxy: str | None) -> Iterator[None]:
    """Bind only the qualified value; an unqualified explicit input is fatal."""
    qualified = qualify_loopback_provider_proxy(proxy)
    if proxy is not None and qualified is None:
        raise ValueError("authorized_provider_proxy_loopback_http_required")
    token = _AUTHORIZED_PROVIDER_PROXY.set(qualified)
    try:
        yield
    finally:
        _AUTHORIZED_PROVIDER_PROXY.reset(token)
