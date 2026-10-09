"""Leaf opt-in isolated-transport context for both budget and process modules.

There must be no runtime import cycle between physical budget enforcement
and its exclusive transport implementation.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


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
