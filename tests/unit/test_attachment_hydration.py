from __future__ import annotations

from llm_loop.core.run_context import current_workspace_root
from llm_loop.tools.builtin.read_attachment import ReadAttachmentTool
from llm_loop.web.attachments import AttachmentStore, workspace_scope


def test_explicit_attachment_read_ignores_initial_excerpt_budget(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    scope = workspace_scope(workspace)
    store = AttachmentStore(tmp_path / "data")
    full = "HEAD-" + ("X" * 39_990) + "-TAIL"
    record = store.create(
        workspace_scope=scope,
        filename="long.txt",
        data=full.encode(),
        content_type="text",
        excerpt=full[:2_000],
        excerpt_kind="extracted_text",
        extracted_text=full,
        extraction_complete=True,
        extraction_kind="text_full",
    )
    assert len(record.excerpt) == 2_000
    token = current_workspace_root.set(scope)
    try:
        result = ReadAttachmentTool(store).execute(ref=record.ref)
    finally:
        current_workspace_root.reset(token)
    assert result.status.name == "SUCCESS"
    assert full in result.content
    assert "source_complete=true" in result.content and "page_complete=true" in result.content
    assert "next_offset=" not in result.content


def test_explicit_attachment_read_pages_monotonically_only_above_100k(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    scope = workspace_scope(workspace)
    store = AttachmentStore(tmp_path / "data")
    full = ("A" * 100_000) + ("B" * 80_000)
    record = store.create(
        workspace_scope=scope,
        filename="huge.txt",
        data=full.encode(),
        content_type="text",
        excerpt=full[:2_000],
        excerpt_kind="extracted_text",
        extracted_text=full,
        extraction_complete=True,
        extraction_kind="text_full",
    )
    tool = ReadAttachmentTool(store)
    token = current_workspace_root.set(scope)
    try:
        first = tool.execute(ref=record.ref)
        second = tool.execute(ref=record.ref, offset=100_000)
    finally:
        current_workspace_root.reset(token)
    assert first.status.name == "SUCCESS"
    assert "next_offset=100000" in first.content
    assert first.content.count("B") == 0
    assert second.status.name == "SUCCESS"
    assert ("B" * 80_000) in second.content
    assert ("A" * 100) not in second.content
    assert "source_complete=true" in second.content and "page_complete=true" in second.content


def test_legacy_attachment_lazy_hydrates_from_original_bytes(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    scope = workspace_scope(workspace)
    store = AttachmentStore(tmp_path / "data")
    full = "LEGACY-" + ("Z" * 20_000) + "-END"
    record = store.create(
        workspace_scope=scope,
        filename="legacy.txt",
        data=full.encode(),
        content_type="text",
        excerpt=full[:2_000],
        excerpt_kind="extracted_text",
    )
    assert record.extracted_chars == 0
    page = store.hydrate_text(record.ref, workspace_scope=scope)
    assert page["content"] == full
    assert page["complete"] is True
    resolved = store.resolve(record.ref, workspace_scope=scope)
    assert resolved.extraction_complete is True
    assert resolved.extracted_chars == len(full)


def test_incomplete_pdf_representation_is_replaced_by_full_lazy_extraction(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    scope = workspace_scope(workspace)
    store = AttachmentStore(tmp_path / "data")
    original = b"fake-pdf-source"
    record = store.create(
        workspace_scope=scope,
        filename="long.pdf",
        data=original,
        content_type="pdf",
        excerpt="PAGE-1-PREVIEW",
        excerpt_kind="extracted_text",
        extracted_text="INITIAL-FIRST-50-PAGES",
        extraction_complete=False,
        extraction_kind="pdf_extracted",
        page_count=80,
        pages_extracted=50,
    )

    calls: list[tuple[str, bytes]] = []

    def _full(filename: str, data: bytes):
        calls.append((filename, data))
        return "FULL-PDF-TEXT-ALL-80-PAGES", "pdf_text_full", 80, True

    monkeypatch.setattr("llm_loop.web.upload_handlers.extract_full_text", _full)
    page = store.hydrate_text(record.ref, workspace_scope=scope)
    assert calls == [("long.pdf", original)]
    assert page["content"] == "FULL-PDF-TEXT-ALL-80-PAGES"
    assert page["source_text_complete"] is True
    refreshed = store.resolve(record.ref, workspace_scope=scope)
    assert refreshed.extraction_complete is True
    assert refreshed.extraction_kind == "pdf_text_full"
    assert refreshed.pages_extracted == 80


def test_partial_pdf_vision_representation_never_claims_full_source_coverage(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    scope = workspace_scope(workspace)
    store = AttachmentStore(tmp_path / "data")
    original = b"fake-scanned-pdf"
    record = store.create(
        workspace_scope=scope,
        filename="scan.pdf",
        data=original,
        content_type="pdf",
        excerpt="VISION-FIRST-PAGE",
        excerpt_kind="vision_text",
    )

    monkeypatch.setattr(
        "llm_loop.web.upload_handlers.extract_full_text",
        lambda _filename, _data: ("VISION-FIRST-PAGE", "pdf_vision_partial", 12, False),
    )
    page = store.hydrate_text(record.ref, workspace_scope=scope)
    assert page["content"] == "VISION-FIRST-PAGE"
    assert page["complete"] is True  # this available representation fits one read page
    assert page["source_text_complete"] is False  # but it does not cover all 12 source pages
    refreshed = store.resolve(record.ref, workspace_scope=scope)
    assert refreshed.page_count == 12
    assert refreshed.pages_extracted == 1
