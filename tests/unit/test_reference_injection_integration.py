from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
from llm_loop.core.message import Message, MessageSource


def _human(text: str) -> Message:
    return Message(
        role="user",
        content=text,
        source=MessageSource.USER,
        metadata=origin_metadata(InjectionLayer.USER_INSTRUCTION),
    )


def test_memory_front_k_gate_skips_retrieval_after_k() -> None:
    from tests.unit.test_memory_turn_snapshot import _MemStore, _engine, _entry, _snapshots

    class CountingStore(_MemStore):
        def __init__(self, entries):
            super().__init__(entries)
            self.search_count = 0

        def search(self, *args, **kwargs):
            self.search_count += 1
            return super().search(*args, **kwargs)

    store = CountingStore([_entry("m1", "database migration runbook")])
    eng = _engine(store)
    eng.settings.reference_auto_turns = 3
    sess = SimpleNamespace(messages=[], session_id="s1")

    for turn in range(1, 5):
        sess.messages.append(_human(f"继续 database migration 第{turn}轮"))
        turn_ref = len(sess.messages) - 1
        eng._inject_turn_memory_snapshot(sess, sess.messages[-1].content, turn_ref)

    # turns 1-3 are eligible; stable-ref dedup means only turn1 emits a body.
    # turn4 is gated before retrieval, so search runs only three times.
    assert store.search_count == 3
    assert len(_snapshots(sess)) == 1
    assert _snapshots(sess)[0].metadata.get("reference_key") == "ref:memory:m1"


def test_memory_task_switch_reopens_catalog_with_seen_pointer_only() -> None:
    from tests.unit.test_memory_turn_snapshot import _MemStore, _engine, _entry, _snapshots

    store = _MemStore(
        [
            _entry("m1", "database migration runbook"),
            _entry("m2", "postgres backup restore checklist"),
        ]
    )
    eng = _engine(store)
    eng.settings.reference_auto_turns = 3
    sess = SimpleNamespace(messages=[], session_id="s1")

    # First exposure of m1.
    sess.messages.append(_human("database migration"))
    eng._inject_turn_memory_snapshot(sess, "database migration", len(sess.messages) - 1)
    assert len(_snapshots(sess)) == 1

    # Burn through K without matching new material; turn4 is closed.
    for text in ("继续当前工作", "保持当前任务", "继续处理"):
        sess.messages.append(_human(text))
        eng._inject_turn_memory_snapshot(sess, text, len(sess.messages) - 1)

    # Explicit switch reopens the catalog. Query hits seen m1 via "database" and new m2.
    text = "换个话题：database postgres backup restore"
    sess.messages.append(_human(text))
    eng._inject_turn_memory_snapshot(sess, text, len(sess.messages) - 1)
    snaps = _snapshots(sess)
    assert len(snaps) == 2
    switched = snaps[-1]
    assert "ref=memory:m1" in switched.content
    assert "[memory:fact] database migration runbook" not in switched.content
    assert "[memory:fact] postgres backup restore checklist" in switched.content
    assert "ref=memory:m2" in switched.content
    assert switched.metadata.get("reference_full_keys") == ["ref:memory:m2"]


def test_experience_front_k_gate_and_switch_pointer(tmp_path) -> None:
    """E08: front-K/task-switch can reopen retrieval choice, never automatic catalog prompt."""
    from llm_loop.core.loop.tool_exec import _ToolExecMixin
    from tests.unit.test_tool_experience_inject import _Stub, _make_exp_dir

    stub = _Stub(True, _make_exp_dir(tmp_path))
    stub.settings.reference_auto_turns = 3
    for text in ("抓取页面", "继续", "继续", "继续", "换个话题：重新抓取网页"):
        stub.messages.append(_human(text))
        stub._current_turn_ref = len(stub.messages) - 1
        _ToolExecMixin._inject_experience_tips(stub, stub, ["web_fetch"])
    tips = [m for m in stub.messages if (m.metadata or {}).get("injection_kind") == "experience_tip"]
    assert tips == []

def test_session_digest_reference_projection_is_two_lines_and_seen_once() -> None:
    from llm_loop.core.session_digest import SessionDigest

    digest = SessionDigest("s1")
    digest.append("call-1", "read_file", "[状态: success] config loaded", {"path": "x"})
    frames = digest.render_reference_frames()
    assert len(frames) == 1
    assert frames[0].content.count("\n") == 1
    assert frames[0].key == "ref:digest:call-1"
    assert "archive_tool=read_file" in frames[0].content
    assert digest.render_reference_frames(seen_keys={frames[0].key}) == []


def test_compaction_keeps_real_user_anchor_not_summary_echo() -> None:
    from llm_loop.core.history import build_history_messages

    archived: list[Message] = []
    task = "请分析这篇头条文章的内容"
    msgs = [
        _human("很老的早期历史" + "A" * 400),
        _human(task),
        Message(role="user", content="[相关记忆] 注入噪声" + "D" * 150, source=MessageSource.USER),
        Message(role="user", content="[声明提醒] 注入噪声" + "E" * 150, source=MessageSource.USER),
    ]
    out = build_history_messages(
        msgs,
        system_prompt="SYS",
        max_chars=250,
        session_id="s1",
        archive_sink=lambda _sid, m: archived.append(m),
    )
    exact_human = [m for m in out if m.get("role") == "user" and m.get("content") == task]
    assert len(exact_human) == 1
    assert all(m.content != task for m in archived)
    assert not any("压缩关键事实" in str(m.get("content", "")) for m in out)


def test_eighteen_repeat_memory_hits_yield_one_full_snapshot() -> None:
    """09c44093 trap: x18 repeated stable ref -> exactly one full frame per session."""
    from tests.unit.test_memory_turn_snapshot import _MemStore, _engine, _entry, _snapshots

    class CountingStore(_MemStore):
        def __init__(self, entries):
            super().__init__(entries)
            self.search_count = 0

        def search(self, *args, **kwargs):
            self.search_count += 1
            return super().search(*args, **kwargs)

    store = CountingStore([_entry("m1", "database migration runbook")])
    eng = _engine(store)
    eng.settings.reference_auto_turns = 20  # isolate dedup from the front-K gate
    sess = SimpleNamespace(messages=[], session_id="repeat-18")
    for turn in range(18):
        text = f"database migration followup {turn}"
        sess.messages.append(_human(text))
        eng._inject_turn_memory_snapshot(sess, text, len(sess.messages) - 1)

    assert store.search_count == 18
    snaps = _snapshots(sess)
    assert len(snaps) == 1
    assert snaps[0].metadata.get("reference_full_keys") == ["ref:memory:m1"]
    assert snaps[0].content.count("database migration runbook") == 1


def test_hotcard_auto_projection_is_two_line_file_pointer() -> None:
    from llm_loop.core.loop.hotcard import _render_card_text

    text = _render_card_text(
        {
            "anchor": "继续生产部署并立即执行切换",
            "active_goals": [
                {
                    "id": "g1",
                    "objective": "必须继续旧目标",
                    "checkpoint_next": "立即执行下一阶段",
                }
            ],
            "pending_evolutions": ["e1"],
        },
        ref_path="data/handoff/task_hotcard.json",
    )
    lines = text.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[任务热卡]")
    assert lines[1] == "ref=file:data/handoff/task_hotcard.json"
    assert "继续生产部署" not in text
    assert "必须继续旧目标" not in text
    assert "立即执行下一阶段" not in text



def test_seen_set_survives_real_sessionstore_restart(tmp_path) -> None:
    from llm_loop.core.reference_injection import seen_injection_set
    from llm_loop.core.session import SessionStore

    store = SessionStore(tmp_path / "sessions")
    sid = store.create()
    sess = store.load(sid)
    sess.messages.append(_human("database migration"))
    persisted = Message(
        role="user",
        content="[资料·记忆/经验]\n[memory:fact] database migration runbook\nref=memory:m1",
        source=MessageSource.USER,
        metadata={
            "program_origin": True,
            "origin_layer": "reference",
            "reference_key": "ref:memory:m1",
            "reference_keys": ["ref:memory:m1"],
        },
    )
    sess.messages.append(persisted)
    store.save(sess)

    restarted = SessionStore(tmp_path / "sessions").load(sid)
    assert seen_injection_set(restarted.messages) == {"ref:memory:m1"}


def test_search_records_hydrates_memory_ref_and_enforces_session_scope(tmp_path) -> None:
    from llm_loop.introspection.search import RecordSearcher
    from llm_loop.memory.store import MemoryEntry, MemoryStore

    memory = MemoryStore(tmp_path / "memory")
    memory.save_entry(
        MemoryEntry(
            id="m-global",
            type="fact",
            content="global database migration runbook",
            keywords=["database"],
        )
    )
    memory.save_entry(
        MemoryEntry(
            id="m-session",
            type="fact",
            content="private session deployment note",
            keywords=["deployment"],
            scope="session",
            source_session_id="s1",
        )
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", memory_store=memory)

    global_hit = searcher.search(
        kind="memory", query="memory:m-global", limit=5, session_id="s2"
    )
    assert [x["key"] for x in global_hit] == ["memory:m-global"]

    own_hit = searcher.search(
        kind="memory", query="memory:m-session", limit=5, session_id="s1"
    )
    assert [x["key"] for x in own_hit] == ["memory:m-session"]
    assert searcher.search(
        kind="memory", query="memory:m-session", limit=5, session_id="s2"
    ) == []
    # Empty query must not enumerate another session's private memory either.
    other_listing = searcher.search(kind="memory", query="", limit=10, session_id="s2")
    assert "m-session" not in {x["id"] for x in other_listing}


def test_search_records_hydrates_experience_ref(tmp_path) -> None:
    from llm_loop.experiences.store import ExperienceStore
    from llm_loop.introspection.search import RecordSearcher
    from tests.unit.test_tool_experience_inject import _EXP_MD

    exp_dir = tmp_path / "experiences"
    exp_dir.mkdir()
    (exp_dir / "EXPERIENCE-test-web-fetch.md").write_text(_EXP_MD, encoding="utf-8")
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        experience_store=ExperienceStore(exp_dir),
    )
    hits = searcher.search(
        kind="experience",
        query="experience:EXPERIENCE-test-web-fetch",
        limit=5,
    )
    assert len(hits) == 1
    assert hits[0]["key"] == "experience:EXPERIENCE-test-web-fetch"
    assert hits[0]["file"] == "EXPERIENCE-test-web-fetch.md"


def test_digest_ref_hydrates_after_archive_compaction(tmp_path) -> None:
    from llm_loop.core.session_digest import SessionDigest
    from llm_loop.introspection.search import RecordSearcher
    from llm_loop.memory.archive import ArchiveStore

    digest = SessionDigest("s1")
    digest.append(
        "call-1",
        "read_file",
        "[状态: success] UNIQUE_DIGEST_FACT config loaded",
        {"path": "config.py"},
    )
    frame = digest.render_reference_frames()[0]
    assert frame.ref.startswith("digest:call-1;")

    archive = ArchiveStore(tmp_path / "archives")
    archive.archive(
        "s1",
        role="tool",
        source="tool",
        content="[状态: success] UNIQUE_DIGEST_FACT config loaded",
        tool_name="read_file",
        tool_call_id="call-1",
    )
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        archive_store=archive,
    )
    hits = searcher.search(kind="archive", query=frame.ref, limit=5, session_id="s1")
    assert len(hits) == 1
    assert hits[0]["tool_call_id"] == "call-1"
    assert "UNIQUE_DIGEST_FACT" in hits[0]["content_preview"]


def test_compaction_archive_pointer_has_retrievable_original(tmp_path) -> None:
    from llm_loop.core.history import build_history_messages
    from llm_loop.introspection.search import RecordSearcher
    from llm_loop.memory.archive import ArchiveStore

    archive = ArchiveStore(tmp_path / "archives")
    unique = "UNIQUE_COMPACT_ORIGINAL database migration evidence"
    msgs = [
        _human(unique + " A" * 500),
        _human("newer context " + "B" * 400),
        _human("latest task"),
    ]

    def sink(sid: str, msg: Message) -> None:
        archive.archive(
            sid,
            role=msg.role,
            source=msg.source.value,
            content=msg.content,
            tool_name=msg.tool_name,
            tool_call_id=msg.tool_call_id,
            status=msg.status.value if msg.status else None,
        )

    out = build_history_messages(
        msgs,
        system_prompt="SYS",
        max_chars=350,
        session_id="s1",
        archive_sink=sink,
    )
    assert not any("ref=archive:search_archive" in str(m.get("content", "")) for m in out)
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        archive_store=archive,
    )
    hits = searcher.search(
        kind="archive",
        query="UNIQUE_COMPACT_ORIGINAL",
        limit=5,
        session_id="s1",
    )
    assert hits
    assert any("UNIQUE_COMPACT_ORIGINAL" in h["content_preview"] for h in hits)


def test_memory_same_call_duplicate_id_emits_one_full_frame() -> None:
    from llm_loop.memory.retrieve import build_memory_messages
    from tests.unit.test_memory_turn_snapshot import _MemStore, _entry

    entry = _entry("m1", "database migration runbook")

    class DuplicateStore(_MemStore):
        def search(self, *args, **kwargs):
            return [entry, entry]

    msgs = build_memory_messages(
        "database migration",
        DuplicateStore([entry]),
        top_k=5,
    )
    assert len(msgs) == 1
    assert msgs[0].content.count("ref=memory:m1") == 1
    assert msgs[0].metadata.get("reference_full_keys") == ["ref:memory:m1"]



def test_experience_same_call_duplicate_ref_emits_once(tmp_path) -> None:
    """E08: duplicate experience candidates are not even queried on the automatic path."""
    from llm_loop.core.loop.tool_exec import _ToolExecMixin
    from tests.unit.test_tool_experience_inject import _Stub, _make_exp_dir

    stub = _Stub(True, _make_exp_dir(tmp_path))
    stub.messages.append(_human("抓取页面"))
    _ToolExecMixin._inject_experience_tips(stub, stub, ["web_fetch"])
    tips = [m for m in stub.messages if (m.metadata or {}).get("injection_kind") == "experience_tip"]
    assert tips == []

def test_semantic_memory_candidates_respect_session_scope(tmp_path) -> None:
    from llm_loop.memory.embedder import HashEmbedder
    from llm_loop.memory.retriever import SemanticRetriever
    from llm_loop.memory.store import MemoryEntry, MemoryStore

    memory = MemoryStore(tmp_path / "memory")
    memory.save_entry(
        MemoryEntry(
            id="global",
            type="fact",
            content="shared alpha fact",
            keywords=["alpha"],
        )
    )
    memory.save_entry(
        MemoryEntry(
            id="private-s1",
            type="fact",
            content="private beta fact",
            keywords=["beta"],
            scope="session",
            source_session_id="s1",
        )
    )
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=tmp_path / "memory")

    s2 = retriever._candidates("memory", "s2", memory, None)  # noqa: SLF001
    assert {x["id"] for x in s2} == {"global"}
    s1 = retriever._candidates("memory", "s1", memory, None)  # noqa: SLF001
    assert {x["id"] for x in s1} == {"global", "private-s1"}
