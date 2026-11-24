from __future__ import annotations

import os
from pathlib import Path

from llm_loop.core import session as session_module
from llm_loop.core import session_page_index
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore


def _clear_cache():
    with session_module._SESSION_META_CACHE_LOCK:
        session_module._SESSION_META_CACHE.clear()


def _seed(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    parent = store.create()
    sid = store.create(parent_id=parent, title="测试会话")
    s = store.load(sid)
    s.messages = [Message(role="user", content="正文" * 100, source=MessageSource.USER,
                          metadata={"ingress_channel": "cli"}) for _ in range(1000)]
    store.save(s)
    return store, sid, parent


def test_cold_display_list_reads_only_metadata(tmp_path, monkeypatch):
    store, sid, _ = _seed(tmp_path)
    expected = [m.to_dict() for m in store.list_sessions()]
    _clear_cache()
    reopened = SessionStore(tmp_path / "sessions")

    def unexpected(*args, **kwargs):
        raise AssertionError("canonical JSON parse in cold display list")

    monkeypatch.setattr(session_module.json, "load", unexpected)
    assert [m.to_dict() for m in reopened.list_sessions(display_only=True)] == expected
    path = Path(session_page_index.display_meta_path(store._path(sid)))
    if os.name == "posix":
        assert path.stat().st_mode & 0o077 == 0


def test_display_sidecar_never_becomes_parent_or_ingress_authority(tmp_path):
    store, sid, parent = _seed(tmp_path)
    path = store._path(sid)
    meta = next(m.to_dict() for m in store.list_sessions() if m.session_id == sid)
    meta.update(parent_id="forged-parent", origin_channel="web")
    assert session_page_index.publish_display_meta(path, meta, session_page_index.source_key(os.stat(path)))
    _clear_cache()
    displayed = next(m for m in store.list_sessions(display_only=True) if m.session_id == sid)
    assert displayed.parent_id == "forged-parent"
    assert store.parent_id_of(sid) == parent
    assert store.get_meta(sid).origin_channel == "cli"
    _clear_cache()
    store.list_sessions(display_only=True)
    assert next(m for m in store.list_sessions() if m.session_id == sid).origin_channel == "cli"


def test_display_sidecar_invalidates_and_legacy_rebuild_is_read_only(tmp_path):
    store, sid, _ = _seed(tmp_path)
    source = Path(store._path(sid))
    sidecar = Path(session_page_index.display_meta_path(str(source)))
    sidecar.write_bytes(b"corrupt")
    _clear_cache()
    assert next(m for m in store.list_sessions(display_only=True) if m.session_id == sid).title == "测试会话"
    sidecar.unlink()
    raw = source.read_bytes()
    assert store.rebuild_display_meta(sid)
    assert source.read_bytes() == raw
    source.write_bytes(raw.replace("测试会话".encode(), "变更会话".encode()))
    _clear_cache()
    assert next(m for m in store.list_sessions(display_only=True) if m.session_id == sid).title == "变更会话"
    assert store.delete(sid)
    assert not sidecar.exists()


def test_sidecar_write_failure_does_not_prevent_canonical_save(tmp_path, monkeypatch):
    store, sid, _ = _seed(tmp_path)
    original = session_page_index.os.replace

    def fail_display(source, target):
        if str(target).endswith(".display-meta"):
            raise PermissionError("synthetic sidecar write failure")
        return original(source, target)

    monkeypatch.setattr(session_page_index.os, "replace", fail_display)
    s = store.load(sid)
    s.title = "canonical survives"
    store.save(s)
    _clear_cache()
    assert next(m for m in store.list_sessions(display_only=True) if m.session_id == sid).title == s.title
    assert store.load(sid).title == s.title


def test_physical_delete_does_not_claim_success_if_private_sidecar_remains(tmp_path, monkeypatch):
    store, sid, _ = _seed(tmp_path)
    original = os.unlink

    def fail_display(path, *args, **kwargs):
        if str(path).endswith(".display-meta"):
            raise PermissionError("synthetic sidecar deletion failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", fail_display)
    assert not store.delete(sid)
    assert Path(session_page_index.display_meta_path(store._path(sid))).exists()
