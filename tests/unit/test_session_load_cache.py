"""SessionStore.load 读缓存回归（2026-09-23 切换会话慢事故）.

web 切换会话与 fingerprint 轮询（messages?limit=1）都走全量 session.load：
大会话（1-5MB、数千消息）每次重复 json.load + 逐条 _message_from_dict，
单次 0.1-0.8s，切换/轮询串行放大到秒级。修复 = _load_from_json 层
(mtime_ns, size) 键控读缓存；overlay/retraction 仍每次现算（事件流独立变化）。

契约：
- 文件未变 → 重复 load 不重复 parse；
- save / 外部文件变更 → 失效重 parse（读到新内容）；
- 返回浅结构副本（messages 列表独立）——调用方追加消息互不可见。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.core import session as session_mod
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore


def _store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "sessions")


def test_repeated_load_parses_once(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    sid = store.create()
    seed = store.load(sid)
    for i in range(3):
        seed.messages.append(Message(role="user", content=f"m{i}", source=MessageSource.USER))
    store.save(seed)
    store.load(sid)  # 预热（此次允许 parse）

    calls = {"n": 0}
    orig = session_mod._message_from_dict

    def counting(m):
        calls["n"] += 1
        return orig(m)

    monkeypatch.setattr(session_mod, "_message_from_dict", counting)
    s2 = store.load(sid)
    assert s2.session_id == sid
    assert calls["n"] == 0  # 文件未变 → 命中缓存，零重解析（非空文件：未缓存时应为 3）


def test_save_invalidates_cache(tmp_path) -> None:
    store = _store(tmp_path)
    sid = store.create()
    first = store.load(sid)
    first.messages.append(Message(role="user", content="hello", source=MessageSource.USER))
    store.save(first)

    reloaded = store.load(sid)
    assert len(reloaded.messages) == len(first.messages)


def test_external_file_change_invalidates(tmp_path) -> None:
    store = _store(tmp_path)
    sid = store.create()
    assert store.load(sid).title == "" or store.load(sid) is not None

    p = tmp_path / "sessions" / f"{sid}.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["title"] = "externally-changed"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    assert store.load(sid).title == "externally-changed"


def test_loaded_sessions_are_structurally_isolated(tmp_path) -> None:
    store = _store(tmp_path)
    sid = store.create()
    a = store.load(sid)
    b = store.load(sid)
    assert a is not b
    assert a.messages is not b.messages
    before = len(b.messages)
    a.messages.append(Message(role="user", content="extra", source=MessageSource.USER))
    assert len(b.messages) == before  # 调用方追加互不可见


def _seed_sized_session(store: SessionStore, content: str) -> tuple[str, int]:
    sid = store.create()
    session = store.load(sid)
    session.messages.append(Message(role="user", content=content, source=MessageSource.USER))
    store.save(session)
    return sid, Path(store._path(sid)).stat().st_size


def test_source_byte_budget_evicts_least_recently_used(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    a, a_size = _seed_sized_session(store, "a" * 4096)
    b, b_size = _seed_sized_session(store, "b" * 4096)
    c, c_size = _seed_sized_session(store, "c" * 4096)
    budget = max(a_size + b_size, a_size + c_size, b_size + c_size)
    monkeypatch.setattr(store, "_SESSION_JSON_CACHE_SOURCE_BYTES_LIMIT", budget)
    store.load(a)
    store.load(b)
    store.load(a)  # a is now newer than b
    store.load(c)
    assert list(store._session_json_cache) == [a, c]
    assert sum(entry[0][1] for entry in store._session_json_cache.values()) <= budget


def test_oversized_session_is_exact_but_not_retained(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    small, small_size = _seed_sized_session(store, "small")
    content = "large transcript " * 2048
    large, large_size = _seed_sized_session(store, content)
    assert large_size > small_size
    monkeypatch.setattr(store, "_SESSION_JSON_CACHE_SOURCE_BYTES_LIMIT", small_size)
    store.load(small)
    assert store.load(large).messages[-1].content == content
    assert list(store._session_json_cache) == [small]
    assert store.load(large).messages[-1].content == content
    assert large not in store._session_json_cache


def test_external_growth_evicts_previous_cached_object(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    sid, size = _seed_sized_session(store, "small")
    monkeypatch.setattr(store, "_SESSION_JSON_CACHE_SOURCE_BYTES_LIMIT", size)
    store.load(sid)
    assert sid in store._session_json_cache
    path = Path(store._path(sid))
    data = json.loads(path.read_text(encoding="utf-8"))
    content = "expanded " * 4096
    data["messages"][-1]["content"] = content
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert store.load(sid).messages[-1].content == content
    assert sid not in store._session_json_cache


def test_replacement_between_stat_and_open_charges_opened_file(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    sid, size = _seed_sized_session(store, "small")
    monkeypatch.setattr(store, "_SESSION_JSON_CACHE_SOURCE_BYTES_LIMIT", size)
    path = Path(store._path(sid))
    data = json.loads(path.read_text(encoding="utf-8"))
    content = "replacement " * 4096
    data["messages"][-1]["content"] = content
    replacement = path.with_suffix(".replacement")
    replacement.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    original_open = open

    def replace_before_open(file, *args, **kwargs):
        if Path(file) == path and replacement.exists():
            replacement.replace(path)
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", replace_before_open)
    assert store._load_from_json(sid).messages[-1].content == content
    assert sid not in store._session_json_cache


def test_entry_count_still_bounded(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    ids = [_seed_sized_session(store, str(i))[0] for i in range(3)]
    monkeypatch.setattr(store, "_SESSION_JSON_CACHE_LIMIT", 2)
    for sid in ids:
        store.load(sid)
    assert list(store._session_json_cache) == ids[1:]
