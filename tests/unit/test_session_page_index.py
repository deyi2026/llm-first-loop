from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.core import session_page_index
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.session_types import SessionIdConflictError
from llm_loop.event_log.store import EventStore


def _seed(tmp_path, *, events=None):
    store = SessionStore(tmp_path / "sessions", event_store=events)
    sid = store.create()
    session = store.load(sid)
    session.messages = [
        Message(role="user", content=f"消息 {i}\n    {{ nested \\ quote \"", source=MessageSource.USER,
                metadata={"human_turn_source_id": f"feishu:page-{i}"})
        for i in range(1003)
    ]
    store.save(session)
    return store, sid, session


def test_indexed_pages_survive_store_restart_without_full_json_load(tmp_path, monkeypatch):
    store, sid, session = _seed(tmp_path)
    reopened = SessionStore(tmp_path / "sessions")

    def unexpected(*args, **kwargs):
        raise AssertionError("full history load")

    monkeypatch.setattr(reopened, "_load_from_json", unexpected)
    assert Path(session_page_index.index_path(store._path(sid))).is_file()
    for offset in (0, 50, 950, 1000, 1003, 9999):
        page = reopened.load_history_page(sid, 50, offset)
        assert page is not None
        messages, total = page
        assert total == 1003
        assert [m.content for m in messages] == [
            m.content for m in session.messages[max(0, total-offset-50):max(0, total-offset)]
        ]


def test_index_invalidated_by_external_write_and_corruption(tmp_path):
    store, sid, _ = _seed(tmp_path)
    path = Path(store._path(sid))
    index = Path(session_page_index.index_path(str(path)))
    raw = index.read_bytes()
    index.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    assert store.load_history_page(sid, 50, 0) is None
    index.write_bytes(raw)
    path.write_bytes(path.read_bytes().replace("消息 1002".encode(), "消息 2002".encode()))
    assert store.load_history_page(sid, 50, 0) is None
    assert store.load(sid).messages[-1].content.startswith("消息 2002")


def test_indexed_page_applies_event_only_retraction(tmp_path):
    events = EventStore(tmp_path / "events")
    store, sid, _ = _seed(tmp_path, events=events)
    assert store.retract_message_by_source_id("feishu:page-1002")["status"] == "retracted"
    page = store.load_history_page(sid, 50, 0)
    assert page is not None
    assert page[0][-1].content == "[RETRACTED]"
    assert page[0][-1].metadata["retracted"] is True


def test_indexed_page_never_replays_full_events(tmp_path, monkeypatch):
    events = EventStore(tmp_path / "events")
    store, sid, _ = _seed(tmp_path, events=events)
    assert store.retract_message_by_source_id("feishu:page-1002")["status"] == "retracted"
    reopened_events = EventStore(tmp_path / "events")
    reopened = SessionStore(tmp_path / "sessions", event_store=reopened_events)

    def unexpected(*args, **kwargs):
        raise AssertionError("full event replay")

    monkeypatch.setattr(reopened_events, "read", unexpected)
    monkeypatch.setattr(reopened_events, "read_cached", unexpected)
    page = reopened.load_history_page(sid, 50, 0)
    assert page is not None
    assert page[0][-1].content == "[RETRACTED]"
    assert not reopened_events._read_cache


def test_bounded_batch_rebuild_preserves_source_and_charges_budget(tmp_path):
    store, sid, _ = _seed(tmp_path)
    source = Path(store._path(sid))
    index = Path(session_page_index.index_path(str(source)))
    meta = Path(session_page_index.display_meta_path(str(source)))
    index.unlink()
    meta.unlink()
    original = source.read_bytes()
    stamp = session_page_index.source_key(source.stat())
    other = store.create()
    too_small = store.rebuild_history_views_batch([sid], max_source_bytes=len(original) - 1)
    assert too_small[0]["status"] == "budget_exhausted"
    assert not index.exists() and not meta.exists()
    result = store.rebuild_history_views_batch([sid, other], max_source_bytes=len(original))
    assert result[0] == {"session_id": sid, "status": "rebuilt", "source_bytes": len(original), "display_meta": True, "history_index": True}
    assert result[1]["status"] == "budget_exhausted"
    assert source.read_bytes() == original
    assert session_page_index.source_key(source.stat()) == stamp
    assert store.load_history_page(sid, 50, 0) is not None
    assert store.rebuild_history_views_batch([other])[0]["status"] == "metadata_only"
    with pytest.raises(ValueError):
        store.rebuild_history_views_batch([sid] * 9)


def test_batch_rebuild_skips_active_run_without_touching_source(tmp_path):
    owner, sid, _ = _seed(tmp_path)
    reader = SessionStore(tmp_path / "sessions")
    source = Path(owner._path(sid))
    index = Path(session_page_index.index_path(str(source)))
    index.unlink()
    original = source.read_bytes()
    with owner.run_owned_session(sid) as active:
        assert active is not None
        result = reader.rebuild_history_views_batch([sid])
        assert result[0]["status"] == "busy"
        assert result[0]["source_bytes"] == 0
        assert not index.exists()
    assert source.read_bytes() == original
    assert reader.rebuild_history_views_batch([sid])[0]["status"] == "rebuilt"


def test_batch_rebuild_does_not_adopt_cross_workspace_copy(tmp_path):
    store, sid, _ = _seed(tmp_path)
    other = SessionStore(tmp_path / "other", identity_root=tmp_path / "sessions")
    copied = Path(other._path(sid))
    copied.write_bytes(Path(store._path(sid)).read_bytes())
    result = other.rebuild_history_views_batch([sid])
    assert result[0]["status"] == "identity_conflict"
    assert result[0]["source_bytes"] == 0
    assert not Path(session_page_index.index_path(str(copied))).exists()
    assert not Path(session_page_index.display_meta_path(str(copied))).exists()


def test_index_deleted_with_session(tmp_path):
    store, sid, _ = _seed(tmp_path)
    index = Path(session_page_index.index_path(store._path(sid)))
    assert index.exists()
    assert store.delete(sid)
    assert not index.exists()


def test_explicit_rebuild_does_not_rewrite_legacy_source(tmp_path):
    store, sid, _ = _seed(tmp_path)
    source = Path(store._path(sid))
    index = Path(session_page_index.index_path(str(source)))
    index.unlink()
    original = source.read_bytes()
    stamp = source.stat()
    assert store.load_history_page(sid, 50, 0) is None
    assert store.rebuild_history_index(sid)
    assert source.read_bytes() == original
    assert source.stat().st_mtime_ns == stamp.st_mtime_ns
    assert store.load_history_page(sid, 50, 0) is not None


def test_indexed_read_keeps_global_session_identity_boundary(tmp_path):
    store, sid, _ = _seed(tmp_path)
    other = SessionStore(tmp_path / "other", identity_root=tmp_path / "sessions")
    # Even a copied source in another workspace must not become adoptable.
    Path(other._path(sid)).write_bytes(Path(store._path(sid)).read_bytes())
    with pytest.raises(SessionIdConflictError):
        other.load_history_page(sid, 50, 0)
