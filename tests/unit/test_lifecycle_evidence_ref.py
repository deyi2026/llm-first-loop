"""lifecycle_agency 7.1 / L19: 完整原因 durable 落盘 + ``reason_ref`` 稳定引用.

``reason_ref`` 是模型回读完整失败原因的闭环入口：展示层可截断片段，但
只要 detail 非空，完整源必落 ``data/audit/reasons/`` 且可经 ref 回读
（spec 4.4-2 禁止"仅存截断片段而声称原因已记录"）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from llm_loop.runtime.service_control import (
    EvidenceRef,
    ManagedServiceDeploymentStore,
    _durable_detail,
)


def test_write_full_round_trips_long_reason(tmp_path: Path) -> None:
    ref = EvidenceRef(tmp_path / "data")
    reason = "x" * 9000
    token = ref.write_full(reason)
    assert token.startswith("reason:")
    assert "/" not in token
    assert ref.resolve(token) == reason


def test_reason_ref_is_content_addressed(tmp_path: Path) -> None:
    ref = EvidenceRef(tmp_path / "data")
    first = ref.write_full("same reason")
    second = ref.write_full("same reason")
    assert first == second
    digest = first[len("reason:") :]
    assert digest == hashlib.sha256(b"same reason").hexdigest()


def test_resolve_rejects_malformed_ref(tmp_path: Path) -> None:
    ref = EvidenceRef(tmp_path / "data")
    assert ref.resolve("") is None
    assert ref.resolve("not-a-ref") is None
    assert ref.resolve("reason:deadbeef") is None
    assert ref.resolve("reason:" + "z" * 64) is None


def test_resolve_missing_ref_returns_none(tmp_path: Path) -> None:
    ref = EvidenceRef(tmp_path / "data")
    assert ref.resolve("reason:" + "a" * 64) is None


def test_durable_detail_keeps_full_source_beyond_snippet(tmp_path: Path) -> None:
    """展示片段被截断，但 durable 源完整可回读且二者可区分（AC-18）."""
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    full = "y" * 5000
    snippet, ref = _durable_detail(store, full)
    assert len(snippet) == 2000
    assert snippet != full
    assert ref
    assert store.evidence.resolve(ref) == full


def test_durable_detail_empty_is_empty(tmp_path: Path) -> None:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    assert _durable_detail(store, "") == ("", "")
