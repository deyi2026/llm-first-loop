"""M52-fix: 飞书 /new·/clear 新建会话继承当前会话模型覆盖（不回落装配默认）."""

from __future__ import annotations

from llm_loop.core.session import SessionStore
from llm_loop.feishu.session_map import SessionMap


def _setup(tmp_path, owner: str = "") -> tuple[SessionStore, SessionMap]:
    store = SessionStore(tmp_path / "sessions")
    smap = SessionMap(store, tmp_path / "map.json", owner_open_id=owner)
    return store, smap


def _override(store: SessionStore, sid: str, model: str) -> None:
    sess = store.load(sid)
    sess.model_override = model
    store.save(sess)


def test_force_new_inherits_model_override_from_old_mapping(tmp_path):
    """/new 主场景：旧会话带 override → 新会话继承同一模型，且映射指向新会话."""
    store, smap = _setup(tmp_path)
    key = "p:user-a"
    old_sid = smap.get_or_create(key)
    _override(store, old_sid, "kimi/k3-256k")
    new_sid = smap.get_or_create(key, force_new=True, inherit_model_override=True)
    assert new_sid != old_sid
    assert store.load(new_sid).model_override == "kimi/k3-256k"
    assert smap.get(key) == new_sid


def test_force_new_without_inherit_keeps_none(tmp_path):
    """向后兼容：不传 inherit 时新会话回落 None（装配默认），行为不变."""
    store, smap = _setup(tmp_path)
    key = "p:user-a"
    old_sid = smap.get_or_create(key)
    _override(store, old_sid, "kimi/k3-256k")
    new_sid = smap.get_or_create(key, force_new=True)
    assert new_sid != old_sid
    assert store.load(new_sid).model_override is None


def test_owner_inherits_from_shared_current(tmp_path):
    """owner 私聊：旧映射缺失时从 owner 共享当前继承；新会话仍为共享当前."""
    store, smap = _setup(tmp_path, owner="owner-1")
    key = "p:owner-1"
    shared_sid = store.create(model_override="deepseek-v4-pro")
    store.set_shared_current(shared_sid)
    new_sid = smap.get_or_create(key, force_new=True, inherit_model_override=True)
    assert new_sid != shared_sid
    assert store.load(new_sid).model_override == "deepseek-v4-pro"
    assert store.get_shared_current() == new_sid  # owner 跨端共享保持


def test_old_session_corrupt_fail_open_to_none(tmp_path):
    """旧会话损坏 → 继承 fail-open 为 None，不阻断 /new 新建."""
    store, smap = _setup(tmp_path)
    key = "p:user-a"
    old_sid = smap.get_or_create(key)
    store._path(old_sid).write_text("{broken", encoding="utf-8")  # noqa: SLF001
    new_sid = smap.get_or_create(key, force_new=True, inherit_model_override=True)
    assert store.load(new_sid).model_override is None
