from __future__ import annotations

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
from llm_loop.core.message import Message, MessageSource


def _human(text: str) -> Message:
    return Message(
        role="user",
        content=text,
        source=MessageSource.USER,
        metadata=origin_metadata(InjectionLayer.USER_INSTRUCTION),
    )


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


def test_repeat_memory_hits_cannot_regain_prompt_authority() -> None:
    """The historical x18 duplication trap is structurally impossible without a producer."""
    from llm_loop.core.loop.engine import LoopEngine

    assert not hasattr(LoopEngine, "_inject_turn_memory_snapshot")


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
    exp_md = """---
title: web_fetch retrieval evidence
scenario: explicit experience hydration
root_cause: historical fact
solution: use explicit retrieval
evidence: test
tags: [web_fetch]
source: {}
status: active
created_at: "2026-08-16T00:00:00+08:00"
updated_at: "2026-08-16T00:00:00+08:00"
---
"""

    exp_dir = tmp_path / "experiences"
    exp_dir.mkdir()
    (exp_dir / "EXPERIENCE-test-web-fetch.md").write_text(exp_md, encoding="utf-8")
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
