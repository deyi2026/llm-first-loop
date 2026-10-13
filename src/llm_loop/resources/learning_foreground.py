"""Explicit cloud-lane independence without weakening local foreground priority.

A host grant is an operator declaration of one additional learning call, not an
observation of provider-wide capacity. With no grant, incomplete client facts,
or a changed transport, use the existing whole-run foreground probe.
"""
from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Sequence
from urllib.parse import urlsplit


class LearningForegroundActivityProbe:
    def __init__(
        self,
        *,
        foreground_probe: Callable[[], bool],
        independent_cloud_hosts: str,
        clients: Callable[[], Sequence[object]],
    ) -> None:
        self._foreground_probe = foreground_probe
        self._hosts = frozenset(
            host.strip().lower().removesuffix(".")
            for host in independent_cloud_hosts.split(",") if host.strip()
        )
        self._clients = clients

    def _declared_cloud_endpoint(self, client: object) -> bool:
        endpoint = urlsplit(str(getattr(client, "base_url", "") or ""))
        host = (endpoint.hostname or "").removesuffix(".")
        if (
            endpoint.scheme != "https"
            or endpoint.port not in (None, 443)
            or endpoint.username is not None
            or endpoint.password is not None
            or host not in self._hosts
            or host == "localhost"
            or host.endswith((".localhost", ".local", ".internal", ".lan"))
        ):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            # Exact DNS host grant, never a wildcard or suffix match. The
            # operator declares this a cloud endpoint; DNS is not a quota fact.
            labels = host.split(".")
            return (
                len(host) <= 253
                and len(labels) >= 2
                and labels[-1][0:1].isalpha()
                and all(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in labels
                )
            )

    def active(self) -> bool:
        if self._hosts:
            try:
                clients = tuple(self._clients())
                if clients and all(self._declared_cloud_endpoint(client) for client in clients):
                    return False
            except Exception:  # noqa: BLE001 - incomplete transport facts preserve existing priority
                pass
        return self._foreground_probe()
