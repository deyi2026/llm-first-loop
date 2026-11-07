"""LFL↔LFL peer 任务通道（lfl.peer.v1）。

设计：docs/DESIGN-20261107-deepin-remote-takeover-agent-interop.md
契约：docs/schemas/lfl.peer.v1/（校验：scripts/verify_peer_schemas.py）
"""
from __future__ import annotations

from llm_loop.peer.errors import REASON_CODES, InvalidTaskTransition, PeerError
from llm_loop.peer.models import (
    AdmissionRecord,
    GrantRecord,
    NodeRecord,
    SCHEMA,
    TaskRecord,
    iso,
    parse_ts,
    utcnow,
)

__all__ = [
    "REASON_CODES",
    "SCHEMA",
    "AdmissionRecord",
    "GrantRecord",
    "InvalidTaskTransition",
    "NodeRecord",
    "PeerError",
    "TaskRecord",
    "iso",
    "parse_ts",
    "utcnow",
]
