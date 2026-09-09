from __future__ import annotations

import hashlib

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import (
    current_model_label,
    current_session_id,
    current_workspace_root,
)
from llm_loop.memory.synopsis import MAX_SOURCE_READ_CHARS, SourceSnapshot, SynopsisStore
from llm_loop.tools.builtin.source_synopsis import SourceSynopsisTool


def _snapshot(
    ref: str, text: str, *, access_scope: str = "workspace", complete: bool = True
) -> SourceSnapshot:
    return SourceSnapshot(
        source_ref=ref,
        source_kind="test",
        text=text,
        source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        source_chars=len(text),
        source_complete=complete,
        representation="exact_test_text",
        access_scope=access_scope,  # type: ignore[arg-type]
    )


def _run_ctx(workspace, sid: str = "session-a", model: str = "provider/model"):
    return (
        current_workspace_root.set(str(workspace)),
        current_session_id.set(sid),
        current_model_label.set(model),
    )


def _reset_ctx(tokens) -> None:
    ws, sid, model = tokens
    current_model_label.reset(model)
    current_session_id.reset(sid)
    current_workspace_root.reset(ws)


def test_model_authored_summary_is_persisted_verbatim_and_bound_to_exact_source(tmp_path) -> None:
    text = "A" * 40_000
    source = _snapshot("attachment://" + "a" * 32, text)
    store = SynopsisStore(tmp_path / "data")
    tool = SourceSynopsisTool(store, lambda ref: source if ref == source.source_ref else None)  # type: ignore[arg-type]
    tokens = _run_ctx(tmp_path)
    try:
        summary = "模型自己写的摘要；程序不应改写，也不判断这句话是否正确。"
        result = tool.execute(action="save", source_ref=source.source_ref, summary=summary)
        assert result.status is ToolResultStatus.SUCCESS
        ref = __import__("json").loads(result.content)["synopsis_ref"]
        record = store.get(ref, workspace_scope=str(tmp_path), session_id="session-a")
        assert record is not None
        assert record.summary == summary
        assert record.source_sha256 == source.source_sha256
        assert record.range_sha256 == source.source_sha256
        assert record.summary_model == "provider/model"
        assert record.task_applicability == "not_evaluated"

        summary_read = tool.execute(action="read_summary", synopsis_ref=ref)
        assert summary_read.status is ToolResultStatus.SUCCESS
        assert __import__("json").loads(summary_read.content)["summary"] == summary

        read = tool.execute(action="read_source", synopsis_ref=ref)
        assert read.status is ToolResultStatus.SUCCESS
        assert read.content.endswith(text)
        assert '"complete": true' in read.content
    finally:
        _reset_ctx(tokens)


def test_explicit_source_read_pages_monotonically_without_repeating_prefix(tmp_path) -> None:
    text = "A" * MAX_SOURCE_READ_CHARS + "B" * 80_000
    source = _snapshot("artifact://v1/" + "b" * 32, text)
    store = SynopsisStore(tmp_path / "data")
    tool = SourceSynopsisTool(store, lambda _ref: source)
    tokens = _run_ctx(tmp_path)
    try:
        saved = tool.execute(action="save", source_ref=source.source_ref, summary="分段摘要")
        ref = __import__("json").loads(saved.content)["synopsis_ref"]
        first = store.read_source(ref, workspace_scope=str(tmp_path), session_id="session-a")
        assert first is not None
        assert first["content"] == "A" * MAX_SOURCE_READ_CHARS
        assert first["next_offset"] == MAX_SOURCE_READ_CHARS
        second = store.read_source(
            ref,
            workspace_scope=str(tmp_path),
            session_id="session-a",
            offset=first["next_offset"],
        )
        assert second is not None
        assert second["content"] == "B" * 80_000
        assert second["complete"] is True
        assert second["next_offset"] is None
    finally:
        _reset_ctx(tokens)


def test_snapshot_read_survives_current_source_version_changing(tmp_path) -> None:
    first = _snapshot("evidence://v1/" + "a" * 64, "FIRST" * 10_000, access_scope="session")
    current = {"value": first}
    store = SynopsisStore(tmp_path / "data")
    tool = SourceSynopsisTool(store, lambda _ref: current["value"])
    tokens = _run_ctx(tmp_path)
    try:
        saved = tool.execute(
            action="save",
            source_ref=first.source_ref,
            summary="基于 FIRST 的摘要",
            expected_source_sha256=first.source_sha256,
        )
        assert saved.status is ToolResultStatus.SUCCESS
        ref = __import__("json").loads(saved.content)["synopsis_ref"]
        current["value"] = _snapshot(first.source_ref, "SECOND" * 10_000, access_scope="session")
        read = tool.execute(action="read_source", synopsis_ref=ref)
        assert "FIRST" in read.content
        assert "SECOND" not in read.content
    finally:
        _reset_ctx(tokens)


def test_expected_source_sha_is_a_mechanical_version_precondition(tmp_path) -> None:
    source = _snapshot("truncated:123", "reasoning" * 1000, access_scope="session")
    tool = SourceSynopsisTool(SynopsisStore(tmp_path / "data"), lambda _ref: source)
    tokens = _run_ctx(tmp_path)
    try:
        result = tool.execute(
            action="save",
            source_ref=source.source_ref,
            summary="summary",
            expected_source_sha256="0" * 64,
        )
        assert result.status is ToolResultStatus.FAILURE
        assert "SHA" in result.content
    finally:
        _reset_ctx(tokens)


def test_session_scoped_synopsis_cannot_be_read_from_another_session(tmp_path) -> None:
    source = _snapshot("truncated:456", "private partial", access_scope="session")
    store = SynopsisStore(tmp_path / "data")
    tool = SourceSynopsisTool(store, lambda _ref: source)
    tokens = _run_ctx(tmp_path, sid="owner")
    try:
        saved = tool.execute(action="save", source_ref=source.source_ref, summary="owner summary")
        ref = __import__("json").loads(saved.content)["synopsis_ref"]
    finally:
        _reset_ctx(tokens)

    tokens = _run_ctx(tmp_path, sid="other")
    try:
        denied = tool.execute(action="read_source", synopsis_ref=ref)
        assert denied.status is ToolResultStatus.FAILURE
        assert "无此引用" in denied.content
    finally:
        _reset_ctx(tokens)


def test_invalid_declared_range_is_rejected_without_semantic_judgement(tmp_path) -> None:
    source = _snapshot("attachment://" + "c" * 32, "0123456789")
    tool = SourceSynopsisTool(SynopsisStore(tmp_path / "data"), lambda _ref: source)
    tokens = _run_ctx(tmp_path)
    try:
        bad = tool.execute(
            action="save",
            source_ref=source.source_ref,
            summary="this can say anything",
            source_start=8,
            source_end=3,
        )
        assert bad.status is ToolResultStatus.FAILURE
        good = tool.execute(
            action="save",
            source_ref=source.source_ref,
            summary="contradictory or odd summary is still model-owned text",
            source_start=2,
            source_end=8,
        )
        assert good.status is ToolResultStatus.SUCCESS
    finally:
        _reset_ctx(tokens)


def test_search_records_synopsis_is_index_first_and_exact_hydration_checks_version(
    tmp_path,
) -> None:
    from llm_loop.introspection.search import RecordSearcher
    from llm_loop.introspection.tools_status import run_search_records

    source = _snapshot("attachment://" + "d" * 32, "ORIGINAL" * 2000)
    store = SynopsisStore(tmp_path / "data")
    record = store.create(
        workspace_scope=str(tmp_path),
        session_id="session-a",
        source=source,
        summary="可检索的模型摘要",
        summary_model="p/m",
    )
    calls = {"n": 0}

    def current_resolver(_ref: str) -> SourceSnapshot:
        calls["n"] += 1
        return _snapshot(source.source_ref, "CHANGED" * 2000)

    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        synopsis_store=store,
        synopsis_source_resolver=current_resolver,
        workspace_scope_resolver=lambda: str(tmp_path),
    )
    cards = searcher.search(kind="synopsis", query="模型摘要", limit=10, session_id="session-a")
    assert len(cards) == 1
    assert cards[0]["id"] == record.ref
    assert cards[0]["projection_complete"] is False
    assert cards[0]["source_ref_state"] == "not_checked"
    assert cards[0]["task_applicability"] == "not_evaluated"
    assert calls["n"] == 0  # discovery never re-executes/re-extracts a source

    hydrated = searcher.search(kind="synopsis", query=record.ref, limit=10, session_id="session-a")
    assert hydrated[0]["projection_complete"] is False
    assert hydrated[0]["summary"] == "可检索的模型摘要"
    assert hydrated[0]["source_ref_state"] == "changed_representation"
    assert "source_synopsis(action=read_summary" in hydrated[0]["exact_summary_read"]
    assert hydrated[0]["task_applicability"] == "not_evaluated"
    assert calls["n"] == 1

    receipt = run_search_records(
        None,
        searcher.search,
        {"kind": "synopsis", "query": record.ref},
        lambda: "session-a",
    )
    assert receipt.status is ToolResultStatus.SUCCESS
    assert f"synopsis_ref={record.ref}" in receipt.content
    assert "source_sha256=" in receipt.content
    assert "task_applicability=not_evaluated" in receipt.content
    assert "synopsis=可检索的模型摘要" in receipt.content
    assert "source_synopsis(action=read_summary" in receipt.content


def test_factory_synopsis_can_bind_and_recover_exact_truncated_reasoning(tmp_path) -> None:
    from llm_loop.config import Settings
    from llm_loop.core.message import ToolCall
    from llm_loop.factory import build_engine

    engine = build_engine(
        Settings(
            llm_api_key="k",
            llm_base_url="https://x.invalid/v1",
            llm_model="m",
            data_dir=str(tmp_path / "data"),
            evidence_mode="off",
            summary_mode="off",
        )
    )
    sid = "synopsis-reasoning-session"
    reasoning = "THINK-HEAD\n" + ("推理中间段落\n" * 4000) + "THINK-TAIL"
    artifact_ref = engine.episode_store.capture_truncated_artifact(
        sid,
        reason="llm_error",
        round_no=3,
        provider="fake",
        model="fake-model",
        reasoning_full=reasoning,
    )
    assert artifact_ref
    assert engine.episode_store.index_truncated_run(
        sid,
        run_end_reason="llm_error",
        run_end_seq=777,
        last_round=3,
        reasoning_tail=reasoning[-800:],
        partial_chars=len(reasoning),
        artifact_ref=artifact_ref,
        ref="truncated:reasoning-fixture",
    )

    tokens = _run_ctx(tmp_path, sid=sid, model="fake/fake-model")
    try:
        saved = engine.registry.execute(
            ToolCall(
                id="syn-save",
                name="source_synopsis",
                arguments={
                    "action": "save",
                    "source_ref": "truncated:reasoning-fixture",
                    "summary": "这段长推理在截断前完成了若干分析，完整原文仍需按ref核验。",
                },
            )
        )
        assert saved.status is ToolResultStatus.SUCCESS, saved.content
        payload = __import__("json").loads(saved.content)
        synopsis_ref = payload["synopsis_ref"]
        assert payload["source_kind"] == "truncated"
        assert payload["source_complete"] is False  # underlying generation was interrupted
        assert payload["snapshot_complete"] is True  # captured partial itself is exact/complete
        assert payload["automatic_replay"] is False

        recovered = engine.registry.execute(
            ToolCall(
                id="syn-read",
                name="source_synopsis",
                arguments={"action": "read_source", "synopsis_ref": synopsis_ref},
            )
        )
        assert recovered.status is ToolResultStatus.SUCCESS
        assert "[assistant_reasoning]" in recovered.content
        assert "THINK-HEAD" in recovered.content
        assert "THINK-TAIL" in recovered.content
    finally:
        _reset_ctx(tokens)


def test_factory_synopsis_resolves_attachment_and_artifact_exact_sources(tmp_path) -> None:
    from llm_loop.config import Settings
    from llm_loop.core.message import ToolCall
    from llm_loop.factory import build_engine
    from llm_loop.web.attachments import AttachmentStore
    from llm_loop.workspace.artifacts import WorkspaceArtifactStore

    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = build_engine(
        Settings(
            llm_api_key="k",
            llm_base_url="https://x.invalid/v1",
            llm_model="m",
            data_dir=str(data_dir),
            evidence_mode="off",
            summary_mode="off",
        )
    )
    attachment_text = "ATTACHMENT-HEAD\n" + "x" * 40_000 + "\nATTACHMENT-TAIL"
    attachment = AttachmentStore(data_dir).create(
        workspace_scope=str(workspace.resolve()),
        filename="long.txt",
        data=attachment_text.encode(),
        content_type="text",
        excerpt=attachment_text[:2000],
        excerpt_kind="extracted_text",
        extracted_text=attachment_text,
        extraction_complete=True,
        extraction_kind="full_text",
    )
    target = workspace / "parent-context.jsonl"
    artifact_text = "ARTIFACT-HEAD\n" + "y" * 20_000 + "\nARTIFACT-TAIL"
    target.write_text(artifact_text, encoding="utf-8")
    artifact = WorkspaceArtifactStore(data_dir).create(
        workspace_scope=str(workspace.resolve()),
        canonical_path=str(target.resolve()),
        data=artifact_text.encode(),
        owner_session_id="sid",
        execution_id="exec",
        tool_call_id="tc",
        tool_name="test",
        effect_kind="parent_context_snapshot",
    )

    tokens = _run_ctx(workspace, sid="sid", model="fake/m")
    try:
        for source_ref, head, tail in (
            (attachment.ref, "ATTACHMENT-HEAD", "ATTACHMENT-TAIL"),
            (artifact.ref, "ARTIFACT-HEAD", "ARTIFACT-TAIL"),
        ):
            saved = engine.registry.execute(
                ToolCall(
                    id="save-" + head,
                    name="source_synopsis",
                    arguments={
                        "action": "save",
                        "source_ref": source_ref,
                        "summary": f"summary for {head}",
                    },
                )
            )
            assert saved.status is ToolResultStatus.SUCCESS, saved.content
            payload = __import__("json").loads(saved.content)
            assert payload["source_complete"] is True
            reread = engine.registry.execute(
                ToolCall(
                    id="read-" + head,
                    name="source_synopsis",
                    arguments={"action": "read_source", "synopsis_ref": payload["synopsis_ref"]},
                )
            )
            assert reread.status is ToolResultStatus.SUCCESS
            assert head in reread.content and tail in reread.content
    finally:
        _reset_ctx(tokens)


def test_evidence_source_synopsis_is_control_plane_and_does_not_recursively_capture(
    tmp_path,
) -> None:
    from llm_loop.config import Settings
    from llm_loop.core.message import ToolCall
    from llm_loop.factory import build_engine

    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source_file = workspace / "evidence.txt"
    source_text = "EVIDENCE-HEAD\n" + "z" * 40_000 + "\nEVIDENCE-TAIL"
    source_file.write_text(source_text, encoding="utf-8")
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(data_dir),
        evidence_mode="enforce",
        summary_mode="off",
    )
    engine = build_engine(settings)
    tokens = _run_ctx(workspace, sid="ev-sid", model="fake/m")
    try:
        observed = engine.registry.execute(
            ToolCall(id="rf", name="read_file", arguments={"path": str(source_file)})
        )
        assert observed.status is ToolResultStatus.SUCCESS
        assert observed.evidence_ref and observed.evidence_ref.startswith("evidence://v1/")
        ledger_root = settings.evidence_dir / "ledger"
        before = sorted(p.relative_to(ledger_root) for p in ledger_root.rglob("*.json"))

        saved = engine.registry.execute(
            ToolCall(
                id="syn-ev",
                name="source_synopsis",
                arguments={
                    "action": "save",
                    "source_ref": observed.evidence_ref,
                    "summary": "模型对已读取 Evidence 的摘要",
                },
            )
        )
        assert saved.status is ToolResultStatus.SUCCESS, saved.content
        assert saved.evidence_ref is None
        ref = __import__("json").loads(saved.content)["synopsis_ref"]
        summary_read = engine.registry.execute(
            ToolCall(
                id="syn-ev-summary",
                name="source_synopsis",
                arguments={"action": "read_summary", "synopsis_ref": ref},
            )
        )
        assert summary_read.status is ToolResultStatus.SUCCESS
        assert "模型对已读取 Evidence 的摘要" in summary_read.content
        reread = engine.registry.execute(
            ToolCall(
                id="syn-ev-read",
                name="source_synopsis",
                arguments={"action": "read_source", "synopsis_ref": ref},
            )
        )
        assert reread.status is ToolResultStatus.SUCCESS
        assert "EVIDENCE-HEAD" in reread.content and "EVIDENCE-TAIL" in reread.content
        after = sorted(p.relative_to(ledger_root) for p in ledger_root.rglob("*.json"))
        assert after == before  # derived-view save/read creates no recursive Evidence records
    finally:
        _reset_ctx(tokens)


def test_workspace_source_synopsis_does_not_widen_summary_to_other_sessions(tmp_path) -> None:
    source = _snapshot("attachment://" + "e" * 32, "workspace source", access_scope="workspace")
    store = SynopsisStore(tmp_path / "data")
    record = store.create(
        workspace_scope=str(tmp_path),
        session_id="author-session",
        source=source,
        summary="summary may contain current-session context",
    )
    assert record.access_scope == "session"
    assert record.source_access_scope == "workspace"
    assert (
        store.get(record.ref, workspace_scope=str(tmp_path), session_id="author-session")
        is not None
    )
    assert store.get(record.ref, workspace_scope=str(tmp_path), session_id="other-session") is None


def test_delete_session_removes_owned_synopses_and_only_unreferenced_blobs(tmp_path) -> None:
    store = SynopsisStore(tmp_path / "data")
    shared = _snapshot("artifact://v1/" + "f" * 32, "same exact bytes")
    a = store.create(
        workspace_scope=str(tmp_path), session_id="a", source=shared, summary="A summary"
    )
    b = store.create(
        workspace_scope=str(tmp_path), session_id="b", source=shared, summary="B summary"
    )
    blob = store.blobs_root / shared.source_sha256[:2] / f"{shared.source_sha256}.txt"
    assert blob.is_file()
    assert store.delete_session("a") == 1
    assert store.get(a.ref, workspace_scope=str(tmp_path), session_id="a") is None
    assert store.get(b.ref, workspace_scope=str(tmp_path), session_id="b") is not None
    assert blob.is_file()  # still referenced by session b
    assert store.delete_session("b") == 1
    assert not blob.exists()


def test_factory_session_delete_removes_session_owned_synopsis_sidecar(tmp_path) -> None:
    from llm_loop.config import Settings
    from llm_loop.core.message import ToolCall
    from llm_loop.factory import build_engine

    data_dir = tmp_path / "data"
    engine = build_engine(
        Settings(
            llm_api_key="k",
            llm_base_url="https://x.invalid/v1",
            llm_model="m",
            data_dir=str(data_dir),
            evidence_mode="off",
            summary_mode="off",
        )
    )
    sid = engine.session.create()
    reasoning = "DELETE-ME-REASONING" * 1000
    artifact_ref = engine.episode_store.capture_truncated_artifact(
        sid,
        reason="cancelled",
        round_no=1,
        provider="fake",
        model="fake",
        reasoning_full=reasoning,
    )
    engine.episode_store.index_truncated_run(
        sid,
        run_end_reason="cancelled",
        run_end_seq=900,
        reasoning_tail=reasoning[-800:],
        artifact_ref=artifact_ref,
        ref="truncated:delete-fixture",
    )
    tokens = _run_ctx(tmp_path, sid=sid, model="fake/m")
    try:
        saved = engine.registry.execute(
            ToolCall(
                id="save-delete",
                name="source_synopsis",
                arguments={
                    "action": "save",
                    "source_ref": "truncated:delete-fixture",
                    "summary": "temporary summary",
                },
            )
        )
        assert saved.status is ToolResultStatus.SUCCESS
    finally:
        _reset_ctx(tokens)
    records = list((data_dir / "synopses" / "records").rglob("*.json"))
    assert len(records) == 1
    blobs = list((data_dir / "synopses" / "blobs").rglob("*.txt"))
    assert len(blobs) == 1

    assert engine.session.delete(sid) is True
    assert list((data_dir / "synopses" / "records").rglob("*.json")) == []
    assert list((data_dir / "synopses" / "blobs").rglob("*.txt")) == []
