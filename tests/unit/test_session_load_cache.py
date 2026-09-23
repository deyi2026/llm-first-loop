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
