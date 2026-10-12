from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from llm_loop.memory.evidence import (
    AvailabilityState,
    BlobRef,
    BlobStore,
    Coverage,
    EvidenceAuthDeniedError,
    EvidenceCapture,
    EvidenceHydration,
    EvidenceLedgerStore,
    EvidenceRef,
    FreshnessState,
    ManifestProjector,
    OwnerScope,
    Provenance,
    RangeType,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
)


def _owner(name: str) -> OwnerScope:
    return OwnerScope(workspace_id="workspace-A", session_id=name)


def _source(locator: str = "src/foo.py") -> SourceIdentity:
    return SourceIdentity(
        kind=SourceKind.FILE,
        locator=locator,
        version_policy=SourceVersionPolicy.PROBEABLE,
        version_token="mtime=1:size=10",
    )


def _capture(
    capture: EvidenceCapture,
    owner: OwnerScope,
    stable_id: str,
    content: str,
    *,
    acquired_at: datetime | None = None,
):
    return capture.capture(
        make_capture_request(
            owner=owner,
            stable_capture_id=stable_id,
            raw_observation=content,
            acquired_at=acquired_at or datetime(2026, 8, 26, 7, 0, tzinfo=UTC),
            tool_name="read_file",
            tool_call_id=stable_id,
            source=_source(),
            coverage=Coverage(unit="line", start=0, end_exclusive=3, source_complete=True),
            provenance=Provenance(producer="tool", authority="workspace", scope="current"),
        )
    )


def test_blob_identity_is_physical_but_evidence_identity_is_owner_scoped(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    capture = EvidenceCapture(blobs, ledger)

    a = _capture(capture, _owner("A"), "call-1", "same bytes")
    b = _capture(capture, _owner("B"), "call-1", "same bytes")
    c = _capture(capture, _owner("A"), "call-2", "same bytes")

    assert a.blob_ref == b.blob_ref == c.blob_ref
    assert a.evidence_ref != b.evidence_ref
    assert a.evidence_ref != c.evidence_ref
    assert a.evidence_ref.ref.startswith("evidence://v1/")
    assert a.blob_ref.ref.startswith("blob://sha256/")


def test_same_capture_replay_is_idempotent(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    owner = _owner("A")

    first = _capture(capture, owner, "call-1", "alpha")
    second = _capture(capture, owner, "call-1", "alpha")

    assert first == second
    assert len(ledger.list_recent(owner, limit=10)) == 1


def test_owner_authorization_blocks_cross_session_hydration_and_listing(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    hydrate = EvidenceHydration(blobs, ledger, max_limit=50)

    owner_a = _owner("A")
    owner_b = _owner("B")
    result_b = _capture(capture, owner_b, "call-b", "secret-B")

    with pytest.raises(EvidenceAuthDeniedError):
        hydrate.read(
            owner=owner_a,
            evidence_ref=result_b.evidence_ref,
            range_type=RangeType.TEXT_CHAR,
            start=0,
            limit=10,
        )
    assert ledger.list_recent(owner_a, limit=10) == []
    assert [r.evidence_ref for r in ledger.list_recent(owner_b, limit=10)] == [
        result_b.evidence_ref
    ]


def test_blob_ref_is_not_accepted_as_model_facing_evidence_ref(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    hydrate = EvidenceHydration(blobs, ledger)
    blob = blobs.put_text("secret")

    with pytest.raises(TypeError):
        hydrate.read(
            owner=_owner("A"),
            evidence_ref=blob,  # type: ignore[arg-type]
            range_type=RangeType.TEXT_CHAR,
            start=0,
            limit=5,
        )


def test_unicode_text_char_and_line_hydration_are_exact_and_bounded(tmp_path):
    content = "A你🙂Z\n第二行\nlast"
    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    hydrate = EvidenceHydration(blobs, ledger, max_limit=5)
    result = _capture(capture, _owner("A"), "call-1", content)

    chars = hydrate.read(
        owner=_owner("A"),
        evidence_ref=result.evidence_ref,
        range_type=RangeType.TEXT_CHAR,
        start=1,
        limit=3,
    )
    assert chars.content == "你🙂Z"
    assert chars.count == 3
    assert chars.next_start == 4
    assert chars.blob_sha256 == result.blob_ref.sha256
    assert chars.range_sha256

    lines = hydrate.read(
        owner=_owner("A"),
        evidence_ref=result.evidence_ref,
        range_type=RangeType.LINE,
        start=1,
        limit=1,
    )
    assert lines.content == "第二行\n"
    assert lines.count == 1
    assert lines.next_start == 2

    with pytest.raises(ValueError, match="limit"):
        hydrate.read(
            owner=_owner("A"),
            evidence_ref=result.evidence_ref,
            range_type=RangeType.TEXT_CHAR,
            start=0,
            limit=6,
        )


def test_recent_manifest_is_bounded_queryless_and_durable_across_reopen(tmp_path):
    root = tmp_path / "evidence"
    blobs = BlobStore(root / "blobs")
    ledger = EvidenceLedgerStore(root / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    owner = _owner("A")
    for idx in range(4):
        _capture(
            capture,
            owner,
            f"call-{idx}",
            f"observation-{idx}",
            acquired_at=datetime(2026, 8, 26, 7, 0, tzinfo=UTC) + timedelta(seconds=idx),
        )

    reopened = EvidenceLedgerStore(root / "ledger")
    manifest = ManifestProjector(reopened).build_recent(owner=owner, limit=2)

    assert len(manifest.entries) == 2
    assert manifest.truncated is True
    assert [entry.stable_capture_id for entry in manifest.entries] == ["call-3", "call-2"]
    assert all(entry.evidence_ref.ref.startswith("evidence://v1/") for entry in manifest.entries)
    assert all(entry.source_label == "read_file:src/foo.py" for entry in manifest.entries)


def test_evidence_state_is_separate_from_immutable_record(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    owner = _owner("A")
    result = _capture(capture, owner, "call-1", "alpha")
    record_before = ledger.get_record(owner, result.evidence_ref)
    state = ledger.get_state(owner, result.evidence_ref)
    assert record_before is not None and state is not None
    assert state.freshness is FreshnessState.VERIFIED_CURRENT
    assert state.availability is AvailabilityState.AVAILABLE

    ledger.update_state(
        owner,
        state.with_freshness(FreshnessState.STALE, updated_at="2026-08-26T08:00:00+00:00"),
    )
    assert ledger.get_record(owner, result.evidence_ref) == record_before
    assert ledger.get_state(owner, result.evidence_ref).freshness is FreshnessState.STALE  # type: ignore[union-attr]


def test_blob_and_ledger_survive_process_style_reopen(tmp_path):
    root = tmp_path / "evidence"
    blobs = BlobStore(root / "blobs")
    ledger = EvidenceLedgerStore(root / "ledger")
    result = _capture(EvidenceCapture(blobs, ledger), _owner("A"), "call-1", "persist me")

    blobs2 = BlobStore(root / "blobs")
    ledger2 = EvidenceLedgerStore(root / "ledger")
    record = ledger2.get_record(_owner("A"), result.evidence_ref)
    assert record is not None
    assert blobs2.read_text_chars(record.blob_ref, start=0, limit=100) == "persist me"
    assert blobs2.verify(record.blob_ref)


def test_refs_are_strongly_typed(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    blob = blobs.put_text("x")
    assert isinstance(blob, BlobRef)
    assert not isinstance(blob, EvidenceRef)


def test_shared_blob_refcount_survives_first_owner_delete(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    a = _capture(capture, _owner("A"), "call-a", "shared")
    b = _capture(capture, _owner("B"), "call-b", "shared")

    assert a.blob_ref == b.blob_ref
    assert ledger.blob_refcount(a.blob_ref) == 2

    removed_a = ledger.remove_owner(_owner("A"))
    assert removed_a == [a.blob_ref]
    assert ledger.blob_refcount(a.blob_ref) == 1
    assert blobs.verify(a.blob_ref)

    ledger.remove_owner(_owner("B"))
    assert ledger.blob_refcount(a.blob_ref) == 0
    assert blobs.delete(a.blob_ref) is True
    assert blobs.verify(a.blob_ref) is False


def test_same_session_id_in_different_workspace_is_different_owner(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    owner_a = OwnerScope(workspace_id="workspace-A", session_id="same")
    owner_b = OwnerScope(workspace_id="workspace-B", session_id="same")
    a = _capture(capture, owner_a, "call", "same bytes")
    b = _capture(capture, owner_b, "call", "same bytes")
    assert a.blob_ref == b.blob_ref
    assert a.evidence_ref != b.evidence_ref
    with pytest.raises(EvidenceAuthDeniedError):
        EvidenceHydration(blobs, ledger).read(
            owner=owner_a,
            evidence_ref=b.evidence_ref,
            range_type=RangeType.TEXT_CHAR,
            start=0,
            limit=5,
        )


def test_blob_corruption_is_detected(tmp_path):
    from llm_loop.memory.evidence import EvidenceCorruptedError

    blobs = BlobStore(tmp_path / "blobs")
    ref = blobs.put_text("immutable")
    blob_path = blobs.root / "sha256" / ref.sha256[:2] / f"{ref.sha256}.blob"
    blob_path.write_text("tampered", encoding="utf-8")
    assert blobs.verify(ref) is False
    with pytest.raises(EvidenceCorruptedError):
        blobs.read_text(ref)


def test_deterministic_ref_collision_with_changed_metadata_fails_closed(tmp_path):
    from llm_loop.memory.evidence import EvidenceLedgerCommitError

    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    owner = _owner("A")
    first = _capture(capture, owner, "stable", "same")
    record = ledger.get_record(owner, first.evidence_ref)
    state = ledger.get_state(owner, first.evidence_ref)
    assert record is not None and state is not None

    changed = type(record)(
        evidence_ref=record.evidence_ref,
        owner=record.owner,
        blob_ref=record.blob_ref,
        stable_capture_id=record.stable_capture_id,
        acquired_at=record.acquired_at,
        tool_name=record.tool_name,
        tool_call_id=record.tool_call_id,
        source=_source("src/other.py"),
        coverage=record.coverage,
        provenance=record.provenance,
    )
    with pytest.raises(EvidenceLedgerCommitError):
        ledger.append_record(changed, state)


def test_concurrent_same_capture_is_idempotent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    owner = _owner("A")

    def one(_idx: int):
        return _capture(capture, owner, "same-call", "same observation")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, range(32)))

    assert len({r.evidence_ref.ref for r in results}) == 1
    assert len({r.blob_ref.ref for r in results}) == 1
    assert ledger.count(owner) == 1


def test_manifest_masks_command_and_web_query_locator(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    owner = _owner("A")
    ts = datetime(2026, 8, 26, 7, 0, tzinfo=UTC)

    capture.capture(
        make_capture_request(
            owner=owner,
            stable_capture_id="cmd-1",
            raw_observation="ok",
            acquired_at=ts,
            tool_name="execute_command",
            tool_call_id="cmd-1",
            source=SourceIdentity(
                kind=SourceKind.COMMAND,
                locator="deploy --token TOP_SECRET",
                version_policy=SourceVersionPolicy.SNAPSHOT_ONLY,
            ),
            coverage=Coverage(unit="observation", start=0, end_exclusive=1, source_complete=True),
            provenance=Provenance(producer="tool"),
        )
    )
    capture.capture(
        make_capture_request(
            owner=owner,
            stable_capture_id="web-1",
            raw_observation="result",
            acquired_at=ts + timedelta(seconds=1),
            tool_name="web_search",
            tool_call_id="web-1",
            source=SourceIdentity(
                kind=SourceKind.WEB,
                locator="https://example.com/path?secret=TOP_SECRET#fragment",
                version_policy=SourceVersionPolicy.VOLATILE,
            ),
            coverage=Coverage(unit="result", start=0, end_exclusive=1, source_complete=True),
            provenance=Provenance(producer="tool"),
        )
    )

    labels = [entry.source_label for entry in ManifestProjector(ledger).build_recent(owner=owner, limit=10).entries]
    joined = "\n".join(labels)
    assert "TOP_SECRET" not in joined
    assert "deploy --token" not in joined
    assert "?secret=" not in joined
    assert "https://example.com/path" in joined
    assert any("command#" in label for label in labels)


def test_ledger_version_changes_when_state_changes_but_record_does_not(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    owner = _owner("A")
    result = _capture(capture, owner, "call-1", "alpha")
    record = ledger.get_record(owner, result.evidence_ref)
    state = ledger.get_state(owner, result.evidence_ref)
    assert record is not None and state is not None
    version_before = ledger.ledger_version(owner)

    ledger.update_state(
        owner,
        state.with_freshness(FreshnessState.STALE, updated_at="2026-08-26T09:00:00+00:00"),
    )
    version_after = ledger.ledger_version(owner)
    assert version_after != version_before
    assert ledger.get_record(owner, result.evidence_ref) == record
