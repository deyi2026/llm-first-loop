from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from llm_loop.config import Settings
from llm_loop.core.message import Message, MessageSource, ToolCall
from llm_loop.memory.evidence import (
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceLedgerStore,
    EvidenceRef,
    ManifestProjector,
    OwnerScope,
    Provenance,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
    render_recovery_manifest,
)


def _settings(tmp_path: Path, *, mode: str = "enforce", manifest_limit: int = 8) -> Settings:
    return Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / mode),
        extract_enabled=False,
        evidence_mode=mode,
        evidence_manifest_limit=manifest_limit,
        tool_pipeline_enabled=False,
        history_max_chars=200000,
    )


def _manifest(messages: list[dict]) -> str:
    hits = [
        str(row.get("content") or "")
        for row in messages
        if str(row.get("content") or "").startswith(
            "[上下文注入·Evidence Recovery Manifest·非新指令]"
        )
    ]
    assert len(hits) <= 1
    return hits[0] if hits else ""


def _build_engine(tmp_path: Path, *, mode: str = "enforce", manifest_limit: int = 8):
    from llm_loop.factory import build_engine

    settings = _settings(tmp_path, mode=mode, manifest_limit=manifest_limit)
    return settings, build_engine(settings)


def _capture_tool_evidence(engine, sid: str, path: Path) -> str:
    engine.registry.set_session_id(sid)
    result = engine.registry.execute(
        ToolCall(id="tool-evidence-1", name="read_file", arguments={"path": str(path)})
    )
    assert result.evidence_ref
    return result.evidence_ref


def test_manifest_is_tail_regenerated_and_provider_neutral(tmp_path):
    _, engine = _build_engine(tmp_path)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    evidence_file = tmp_path / "evidence.txt"
    evidence_file.write_text("provider neutral evidence", encoding="utf-8")
    ref = _capture_tool_evidence(engine, sid, evidence_file)

    # Same semantic history, different provider raw projection visibility.
    sess.messages.extend(
        [
            Message(
                role="user",
                content="VISIBLE_TO_MINIMAX_ONLY",
                source=MessageSource.USER,
                metadata={"cache_compacted_for": ["deepseek"]},
            ),
            Message(role="assistant", content="normal history", source=MessageSource.SYSTEM),
        ]
    )
    deepseek = engine._build_llm_messages(
        sess, [], max_chars=200000, planned_label="deepseek/model"
    )
    minimax = engine._build_llm_messages(sess, [], max_chars=200000, planned_label="minimax/model")
    deepseek_again = engine._build_llm_messages(
        sess, [], max_chars=200000, planned_label="deepseek/model"
    )

    # The hand-built provider-only marker is legacy/unscoped. Under a concrete
    # model+budget contract it is intentionally reopened rather than hidden forever.
    assert "VISIBLE_TO_MINIMAX_ONLY" in str(deepseek)
    assert "VISIBLE_TO_MINIMAX_ONLY" in str(minimax)
    assert _manifest(deepseek) == _manifest(minimax) == _manifest(deepseek_again) == ""
    md = engine.registry.evidence_recovery_manifest(limit=8)
    md2 = engine.registry.evidence_recovery_manifest(limit=8)
    assert md and md == md2 and ref in md
    listed = engine.registry.execute(
        ToolCall(id="list-provider-neutral", name="list_evidence", arguments={"limit": 8})
    )
    assert ref in listed.content
    assert deepseek[0]["role"] == "system"


def test_shadow_keeps_zero_prompt_schema_change_and_no_manifest(tmp_path):
    _, engine = _build_engine(tmp_path, mode="shadow")
    sid = engine.session.create()
    engine.registry.set_session_id(sid)
    path = tmp_path / "shadow.txt"
    path.write_text("shadow evidence", encoding="utf-8")
    engine.registry.execute(
        ToolCall(id="shadow-1", name="read_file", arguments={"path": str(path)})
    )
    sess = engine.session.load(sid)
    out = engine._build_llm_messages(sess, [], max_chars=200000, planned_label="deepseek/model")
    assert _manifest(out) == ""
    names = {row["name"] for row in engine.registry.schemas(lazy=False)}
    assert {"read_evidence", "search_evidence", "list_evidence"}.isdisjoint(names)


def test_physical_compaction_captures_history_and_old_tool_ref_survives(tmp_path, monkeypatch):
    monkeypatch.setenv("HEAD_KEEP_RATIO", "0")
    monkeypatch.setenv("HEAD_KEEP_FORCE_RATIO", "0")
    _, engine = _build_engine(tmp_path, manifest_limit=6)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    tool_path = tmp_path / "important.py"
    tool_path.write_text("IMPORTANT_FILE_EVIDENCE", encoding="utf-8")
    tool_ref = _capture_tool_evidence(engine, sid, tool_path)

    for i in range(18):
        marker = "EARLY_COMPRESSED_MARKER" if i == 0 else f"history-{i}"
        role = "user" if i % 2 == 0 else "assistant"
        source = MessageSource.USER if role == "user" else MessageSource.SYSTEM
        sess.messages.append(
            Message(role=role, content=f"{marker} " + (chr(65 + i % 20) * 900), source=source)
        )

    manifests: list[str] = []
    ledger = EvidenceLedgerStore(Path(engine.settings.evidence_dir) / "ledger")
    owner = OwnerScope(workspace_id=str(Path.cwd()), session_id=sid)
    counts: list[int] = []
    for _ in range(12):
        out = engine._build_llm_messages(sess, [], max_chars=3500, planned_label="deepseek/model")
        assert _manifest(out) == ""
        manifest = engine.registry.evidence_recovery_manifest(limit=6)
        assert manifest and tool_ref in manifest
        manifests.append(manifest)
        counts.append(ledger.count(owner))

    # Physical compaction may legitimately add new archived conversation records, but must
    # converge rather than re-archiving the same messages forever.
    assert counts == sorted(counts)
    assert counts[-1] <= len(sess.messages) + 1
    assert len(set(counts[-3:])) == 1
    assert manifests[-1] == manifests[-2]

    found = engine.registry.execute(
        ToolCall(
            id="search-compressed",
            name="search_evidence",
            arguments={"query": "EARLY_COMPRESSED_MARKER"},
        )
    )
    assert "EARLY_COMPRESSED_MARKER" in found.content
    compat = engine.registry.execute(
        ToolCall(
            id="search-legacy-name",
            name="search_archive",
            arguments={"query": "EARLY_COMPRESSED_MARKER", "with_summary": True},
        )
    )
    assert "search_archive→search_evidence" in compat.content
    assert "EARLY_COMPRESSED_MARKER" in compat.content


def test_provider_switch_does_not_duplicate_already_captured_compressed_history(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HEAD_KEEP_RATIO", "0")
    monkeypatch.setenv("HEAD_KEEP_FORCE_RATIO", "0")
    _, engine = _build_engine(tmp_path)
    sid = engine.session.create()
    engine.registry.set_session_id(sid)
    sess = engine.session.load(sid)
    for i in range(14):
        sess.messages.append(
            Message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"UNIQUE-{i}-" + ("Q" * 1000),
                source=MessageSource.USER if i % 2 == 0 else MessageSource.SYSTEM,
            )
        )
    ledger = EvidenceLedgerStore(Path(engine.settings.evidence_dir) / "ledger")
    owner = OwnerScope(workspace_id=str(Path.cwd()), session_id=sid)

    engine._build_llm_messages(sess, [], max_chars=3000, planned_label="deepseek/model")
    refs_after_deepseek = {r.evidence_ref.ref for r in ledger.list_recent(owner, limit=100)}
    assert refs_after_deepseek
    engine._build_llm_messages(sess, [], max_chars=3000, planned_label="minimax/model")
    refs_after_minimax = {r.evidence_ref.ref for r in ledger.list_recent(owner, limit=100)}
    # A provider may project different raw history, but logical capture IDs are provider-neutral;
    # switching provider must not create a second record for already-captured message content.
    assert refs_after_deepseek <= refs_after_minimax
    assert len(refs_after_minimax) <= len(sess.messages)


def test_manifest_is_bounded_and_prioritizes_tool_evidence_over_newer_conversation(tmp_path):
    root = tmp_path / "evidence"
    blobs = BlobStore(root / "blobs")
    ledger = EvidenceLedgerStore(root / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    owner = OwnerScope(workspace_id=str(tmp_path), session_id="s")

    def cap(stable_id: str, kind: SourceKind, acquired_at: datetime):
        return capture.capture(
            make_capture_request(
                owner=owner,
                stable_capture_id=stable_id,
                raw_observation=f"content {stable_id}",
                acquired_at=acquired_at,
                tool_name="read_file" if kind is SourceKind.FILE else "history_user",
                tool_call_id=stable_id if kind is SourceKind.FILE else None,
                source=SourceIdentity(
                    kind=kind,
                    locator=f"src/{stable_id}.txt"
                    if kind is SourceKind.FILE
                    else f"conversation:user:{stable_id}",
                    version_policy=(
                        SourceVersionPolicy.PROBEABLE
                        if kind is SourceKind.FILE
                        else SourceVersionPolicy.SNAPSHOT_ONLY
                    ),
                ),
                coverage=Coverage(
                    unit="observation", start=0, end_exclusive=None, source_complete=True
                ),
                provenance=Provenance(producer="phase5-test"),
            )
        )

    tool = cap("tool-old", SourceKind.FILE, datetime(2026, 8, 26, 8, 0, tzinfo=UTC))
    for i in range(12):
        cap(
            f"conv-{i}",
            SourceKind.CONVERSATION,
            datetime(2026, 8, 26, 8, i + 1, tzinfo=UTC),
        )
    manifest = ManifestProjector(ledger).build_recent(owner=owner, limit=3)
    text = render_recovery_manifest(manifest)
    assert len(manifest.entries) == 3
    assert manifest.truncated is True
    assert manifest.entries[0].evidence_ref == tool.evidence_ref
    assert tool.evidence_ref.ref in text
    assert len(text) < 3000


def test_canonical_root_cause_recovery_chain_reads_source_once(tmp_path, monkeypatch):
    """R0-1 canonical: compression/rebuild/provider switch must not force a source re-read."""
    monkeypatch.setenv("HEAD_KEEP_RATIO", "0")
    monkeypatch.setenv("HEAD_KEEP_FORCE_RATIO", "0")
    _, engine = _build_engine(tmp_path, manifest_limit=8)
    sid = engine.session.create()
    engine.registry.set_session_id(sid)
    sess = engine.session.load(sid)

    target = tmp_path / "canonical-large.txt"
    marker = "CANONICAL_HIDDEN_MIDDLE_314159265"
    target.write_text(
        "TARGET_HEAD\n" + ("A" * 6500) + marker + ("Z" * 6500) + "\nTARGET_TAIL", encoding="utf-8"
    )

    read_tool = engine.registry._tools["read_file"]
    original_execute = read_tool.execute
    calls = {"target": 0}

    def counted_execute(**kwargs):
        if str(kwargs.get("path", "")) == str(target):
            calls["target"] += 1
        return original_execute(**kwargs)

    monkeypatch.setattr(read_tool, "execute", counted_execute)
    call = ToolCall(id="canonical-read-1", name="read_file", arguments={"path": str(target)})
    result = engine.registry.execute(call)
    assert calls["target"] == 1
    assert result.evidence_ref
    ref = result.evidence_ref
    assert marker not in result.content  # immediate view is bounded; exact bytes are durable

    # Persist a real assistant declaration + tool result so compression later removes the
    # model-visible tool observation while the same EvidenceRef remains durable.
    sess.messages.append(
        Message(
            role="assistant",
            content="",
            source=MessageSource.SYSTEM,
            tool_calls=[
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
            ],
        )
    )
    sess.messages.append(result.to_message())

    # Unrelated completed tool round after the target evidence was acquired.
    class UnrelatedTool:
        name = "unrelated_probe"
        description = "deterministic unrelated probe"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **_kwargs):
            from llm_loop.core.message import ToolResult, ToolResultStatus

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="UNRELATED_OK",
                tool_call_id="",
                tool_name=self.name,
            )

    engine.registry.register(UnrelatedTool())
    unrelated_call = ToolCall(id="unrelated-1", name="unrelated_probe", arguments={})
    unrelated_result = engine.registry.execute(unrelated_call)
    sess.messages.append(
        Message(
            role="assistant",
            content="",
            source=MessageSource.SYSTEM,
            tool_calls=[
                {
                    "id": unrelated_call.id,
                    "type": "function",
                    "function": {"name": unrelated_call.name, "arguments": {}},
                }
            ],
        )
    )
    sess.messages.append(unrelated_result.to_message())

    for i in range(22):
        sess.messages.append(
            Message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"FILLER-{i}-" + (chr(65 + (i % 20)) * 1000),
                source=MessageSource.USER if i % 2 == 0 else MessageSource.SYSTEM,
            )
        )

    last = None
    providers = ["deepseek/model"] * 5 + ["minimax/model"] * 2 + ["deepseek/model"] * 3
    for provider in providers:  # exactly ten context rebuilds
        last = engine._build_llm_messages(sess, [], max_chars=3600, planned_label=provider)
        assert _manifest(last) == ""
        manifest = engine.registry.evidence_recovery_manifest(limit=8)
        assert manifest and ref in manifest
        assert calls["target"] == 1

    assert last is not None
    # The raw tool projection is gone; durable recovery remains out-of-band and
    # queryless-discoverable through the evidence control plane.
    assert "TARGET_HEAD" not in str(last)
    listed = engine.registry.execute(
        ToolCall(
            id="list-canonical",
            name="list_evidence",
            arguments={"scope": "recovery", "limit": 8},
        )
    )
    assert ref in listed.content

    hydrated = engine.registry.execute(
        ToolCall(
            id="hydrate-canonical",
            name="read_evidence",
            arguments={
                "evidence_ref": ref,
                "range_type": "text_char",
                "start": 5500,
                "limit": 3000,
            },
        )
    )
    assert marker in hydrated.content
    assert calls["target"] == 1


def test_compressed_tool_message_reuses_original_evidence_ref(tmp_path, monkeypatch):
    monkeypatch.setenv("HEAD_KEEP_RATIO", "0")
    monkeypatch.setenv("HEAD_KEEP_FORCE_RATIO", "0")
    _, engine = _build_engine(tmp_path)
    sid = engine.session.create()
    engine.registry.set_session_id(sid)
    sess = engine.session.load(sid)
    path = tmp_path / "reuse.txt"
    path.write_text("TOOL_REF_REUSE " + ("R" * 7000), encoding="utf-8")

    call = ToolCall(id="reuse-read-1", name="read_file", arguments={"path": str(path)})
    result = engine.registry.execute(call)
    assert result.evidence_ref
    original_ref = result.evidence_ref
    sess.messages.append(
        Message(
            role="assistant",
            content="",
            source=MessageSource.SYSTEM,
            tool_calls=[
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
            ],
        )
    )
    sess.messages.append(result.to_message())
    for i in range(12):
        sess.messages.append(
            Message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"REUSE-FILL-{i}-" + ("F" * 1000),
                source=MessageSource.USER if i % 2 == 0 else MessageSource.SYSTEM,
            )
        )

    ledger = EvidenceLedgerStore(Path(engine.settings.evidence_dir) / "ledger")
    owner = OwnerScope(workspace_id=str(Path.cwd()), session_id=sid)
    before = ledger.count(owner)
    engine._build_llm_messages(sess, [], max_chars=3000, planned_label="deepseek/model")
    records = ledger.list_recent(owner, limit=100)
    refs = {row.evidence_ref.ref for row in records}
    assert original_ref in refs
    # There must not be a second logical capture whose exact blob is the already-captured
    # tool projection under a history-msg:* id.
    original_record = ledger.require_authorized(owner, EvidenceRef(original_ref))
    duplicates = [
        row
        for row in records
        if row.blob_ref.ref == original_record.blob_ref.ref and row.evidence_ref.ref != original_ref
    ]
    assert duplicates == []
    assert ledger.count(owner) <= before + len(sess.messages)


def test_enforce_compression_fails_closed_when_history_evidence_capture_fails(
    tmp_path, monkeypatch
):
    import pytest

    monkeypatch.setenv("HEAD_KEEP_RATIO", "0")
    monkeypatch.setenv("HEAD_KEEP_FORCE_RATIO", "0")
    _, engine = _build_engine(tmp_path)
    sid = engine.session.create()
    engine.registry.set_session_id(sid)
    sess = engine.session.load(sid)
    for i in range(12):
        sess.messages.append(
            Message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"FAIL-CLOSED-{i}-" + ("X" * 1000),
                source=MessageSource.USER if i % 2 == 0 else MessageSource.SYSTEM,
            )
        )

    def broken_capture(_sid, _msg, _seq, _archive_id):
        raise OSError("simulated evidence store failure")

    engine.registry.set_evidence_history_capture_hook(broken_capture)
    before_meta = [dict(m.metadata) for m in sess.messages]
    with pytest.raises(OSError, match="simulated evidence store failure"):
        engine._build_llm_messages(sess, [], max_chars=2800, planned_label="deepseek/model")

    assert [dict(m.metadata) for m in sess.messages] == before_meta
    assert all("cache_compacted_for" not in m.metadata for m in sess.messages)


def test_context_compressed_event_carries_evidence_ref(tmp_path, monkeypatch):
    from llm_loop.event_log.store import EventStore

    monkeypatch.setenv("HEAD_KEEP_RATIO", "0")
    monkeypatch.setenv("HEAD_KEEP_FORCE_RATIO", "0")
    settings, engine = _build_engine(tmp_path)
    sid = engine.session.create()
    engine.registry.set_session_id(sid)
    sess = engine.session.load(sid)
    for i in range(14):
        sess.messages.append(
            Message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"EVENT-EVIDENCE-{i}-" + ("Y" * 1000),
                source=MessageSource.USER if i % 2 == 0 else MessageSource.SYSTEM,
            )
        )
    engine._build_llm_messages(sess, [], max_chars=3000, planned_label="deepseek/model")

    events = EventStore(settings.event_logs_dir).read(sid)
    compressed = [event for event in events if event.type == "context.compressed"]
    assert compressed
    assert all(event.payload.get("evidence_ref") for event in compressed)
    assert all(
        str(event.payload["evidence_ref"]).startswith("evidence://v1/") for event in compressed
    )


def test_manifest_render_failure_does_not_remove_recovery_tools(tmp_path):
    _, engine = _build_engine(tmp_path)
    sid = engine.session.create()
    engine.registry.set_session_id(sid)
    sess = engine.session.load(sid)

    def broken_manifest(_limit):
        raise RuntimeError("manifest render failed")

    engine.registry.set_evidence_manifest_provider(broken_manifest)
    out = engine._build_llm_messages(sess, [], max_chars=200000, planned_label="deepseek/model")
    assert _manifest(out) == ""
    names = {row["name"] for row in engine.registry.schemas(lazy=False)}
    assert {"read_evidence", "search_evidence", "list_evidence", "search_archive"} <= names


def test_empty_ledger_does_not_inject_empty_manifest(tmp_path):
    _, engine = _build_engine(tmp_path)
    sid = engine.session.create()
    engine.registry.set_session_id(sid)
    sess = engine.session.load(sid)
    out = engine._build_llm_messages(sess, [], max_chars=200000, planned_label="deepseek/model")
    assert _manifest(out) == ""


def test_evidence_ledger_change_does_not_change_prompt_projection(tmp_path):
    _, engine = _build_engine(tmp_path)
    sid = engine.session.create()
    engine.registry.set_session_id(sid)
    sess = engine.session.load(sid)
    engine._build_llm_messages(sess, [], max_chars=200000, planned_label="deepseek/model")
    assert engine._projection_guard_state == "miss"

    path = tmp_path / "projection-version.txt"
    path.write_text("projection version evidence", encoding="utf-8")
    ref = _capture_tool_evidence(engine, sid, path)
    second = engine._build_llm_messages(sess, [], max_chars=200000, planned_label="deepseek/model")
    assert engine._projection_guard_state == "ok"
    assert _manifest(second) == ""
    assert ref in engine.registry.evidence_recovery_manifest(limit=8)
    engine._build_llm_messages(sess, [], max_chars=200000, planned_label="deepseek/model")
    assert engine._projection_guard_state == "ok"


def test_enforce_has_single_new_search_archive_alias_while_off_keeps_legacy(tmp_path):
    _, enforce = _build_engine(tmp_path / "enforce", mode="enforce")
    _, off = _build_engine(tmp_path / "off", mode="off")
    enforce_names = [row["name"] for row in enforce.registry.schemas(lazy=False)]
    off_names = [row["name"] for row in off.registry.schemas(lazy=False)]
    assert enforce_names.count("search_archive") == 1
    assert off_names.count("search_archive") == 1
    enforce_tool = enforce.registry._tools["search_archive"]
    off_tool = off.registry._tools["search_archive"]
    assert type(enforce_tool).__name__ == "SearchArchiveCompatTool"
    assert type(off_tool).__name__ != "SearchArchiveCompatTool"


def test_identical_history_text_at_different_times_stays_distinct_without_msg_seq(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HEAD_KEEP_RATIO", "0")
    monkeypatch.setenv("HEAD_KEEP_FORCE_RATIO", "0")
    _, engine = _build_engine(tmp_path)
    sid = engine.session.create()
    engine.registry.set_session_id(sid)
    sess = engine.session.load(sid)
    first = Message(
        role="user", content="IDENTICAL-HISTORY " + ("I" * 900), source=MessageSource.USER
    )
    second = Message(role="user", content=first.content, source=MessageSource.USER)
    second.ts = first.ts + 1.0
    sess.messages.extend([first, second])
    for i in range(12):
        sess.messages.append(
            Message(
                role="assistant" if i % 2 else "user",
                content=f"IDENTITY-FILL-{i}-" + ("J" * 1000),
                source=MessageSource.SYSTEM if i % 2 else MessageSource.USER,
            )
        )

    engine._build_llm_messages(sess, [], max_chars=2600, planned_label="deepseek/model")
    ledger = EvidenceLedgerStore(Path(engine.settings.evidence_dir) / "ledger")
    owner = OwnerScope(workspace_id=str(Path.cwd()), session_id=sid)
    identical = [
        row
        for row in ledger.list_recent(owner, limit=100)
        if row.source.kind is SourceKind.CONVERSATION
        and row.blob_ref.size_chars == len(first.content)
    ]
    assert len(identical) == 2
    assert len({row.evidence_ref.ref for row in identical}) == 2
    assert len({row.acquired_at for row in identical}) == 2
