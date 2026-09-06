"""Compression runtime SoT and projected-wire trigger regressions."""

from __future__ import annotations

from typing import Literal

from llm_loop.core import history as history_mod
from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource


def _msg(
    role: Literal["user", "assistant", "tool", "system"],
    content: str,
    *,
    injected_system: bool = False,
) -> Message:
    return Message(
        role=role,
        content=content,
        source=MessageSource.SYSTEM if role == "system" else MessageSource.USER,
        metadata={"injected_system": True} if injected_system else {},
    )


def test_compress_target_ratio_reads_runtime_env_after_module_import(monkeypatch):
    """Late .env loading must still control compression target ratio."""
    monkeypatch.setenv("COMPRESS_TARGET_RATIO", "0.5")
    assert history_mod._compress_target_ratio() == 0.5
    monkeypatch.setenv("COMPRESS_TARGET_RATIO", "0.7")
    assert history_mod._compress_target_ratio() == 0.7


def test_non_wire_injected_system_does_not_trigger_compaction():
    """Messages explicitly excluded from provider wire cannot create pressure."""
    visible = [_msg("user", f"u{i}:" + "x" * 990) for i in range(8)]
    injected = _msg("system", "[架构上报]" + "y" * 990, injected_system=True)
    compacted = [False]
    archived: list[Message] = []

    out = build_history_messages(
        [*visible, injected],
        "",
        max_chars=10_000,
        compact_ratio=0.85,
        session_id="s-projected-wire",
        archive_sink=lambda _sid, msg: archived.append(msg),
        skip_injected_system=True,
        compacted_out=compacted,
    )

    assert compacted == [False]
    assert archived == []
    assert sum(len(str(m.get("content") or "")) for m in out) < 8_500
    assert all("[架构上报]" not in str(m.get("content") or "") for m in out)


def test_cache_boundary_protects_cached_prefix_as_atomic_groups(monkeypatch):
    """An explicit exact provider boundary must survive suffix compaction byte-for-byte."""
    monkeypatch.setenv("COMPRESS_TARGET_RATIO", "0.6")
    msgs = [_msg("user", f"m{i:02d}:" + (chr(65 + i) * 996)) for i in range(12)]
    archived: list[Message] = []
    stats: list[dict] = []

    out = build_history_messages(
        msgs,
        "",
        max_chars=10_000,
        compact_ratio=0.85,
        session_id="s-boundary",
        archive_sink=lambda _sid, msg: archived.append(msg),
        cache_archive_provider="glm",
        cache_protected_prefix_messages=99,  # final-wire index is observability only
        cache_protected_prefix_chars=4_000,
        compact_view_stats=stats,
    )

    contents = [str(m.get("content") or "") for m in out]
    assert contents[:4] == [m.content for m in msgs[:4]]
    assert all(m not in archived for m in msgs[:4])
    assert archived
    assert stats[0]["cache_boundary_mode"] == "protected"
    assert stats[0]["cache_protected_messages"] == 4
    assert stats[0]["cache_boundary_reported_messages"] == 99


def test_cache_boundary_insufficient_suffix_emits_epoch_reset(monkeypatch):
    """An explicit exact protected prefix may reset the epoch if no safe suffix room remains."""
    monkeypatch.setenv("COMPRESS_TARGET_RATIO", "0.6")
    msgs = [_msg("user", f"m{i:02d}:" + (chr(65 + i) * 996)) for i in range(12)]
    archived: list[Message] = []
    stats: list[dict] = []

    build_history_messages(
        msgs,
        "",
        max_chars=10_000,
        compact_ratio=0.85,
        session_id="s-epoch-reset",
        archive_sink=lambda _sid, msg: archived.append(msg),
        cache_archive_provider="glm",
        cache_protected_prefix_messages=9,
        cache_protected_prefix_chars=9_000,
        compact_view_stats=stats,
    )

    assert archived
    assert stats[0]["cache_boundary_mode"] == "epoch_reset"
    assert stats[0]["cache_protected_messages"] >= 9


def test_boundary_soft_pressure_without_archive_is_not_reported_as_compaction(monkeypatch):
    """Crossing the soft line alone is not a compact event if no bytes are removed."""
    monkeypatch.setenv("COMPRESS_TARGET_RATIO", "0.6")
    msgs = [_msg("user", f"m{i:02d}:" + (chr(65 + i) * 996)) for i in range(9)]
    compacted: list[bool] = []
    archived: list[Message] = []

    build_history_messages(
        msgs,
        "",
        max_chars=10_000,
        compact_ratio=0.85,
        session_id="s-soft-only",
        archive_sink=lambda _sid, msg: archived.append(msg),
        cache_archive_provider="glm",
        cache_protected_prefix_messages=8,
        cache_protected_prefix_chars=8_000,
        compacted_out=compacted,
    )

    assert archived == []
    assert compacted == [False]
