from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.memory.evidence import (
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceHydration,
    EvidenceLedgerStore,
    OwnerScope,
    Provenance,
    RangeType,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
)
from llm_loop.memory.evidence_legacy import EvidenceLifecycle, LegacySidecarMigrator


def _legacy_projected(
    data_dir: Path,
    full: str,
    *,
    kind: str = "tool",
    head: int = 50,
    tail: int = 50,
    source: str = "legacy",
) -> tuple[str, Path]:
    """Create a historical sidecar fixture without reviving a runtime producer."""
    subdir = "cmd_outputs" if kind == "command" else "tool_outputs"
    out_dir = data_dir / "audit" / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(full.encode()).hexdigest()[:16]
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in source)[:24] or "legacy"
    sidecar = out_dir / f"{digest}_{safe}.log"
    sidecar.write_text(full, encoding="utf-8")
    projected = (
        full[:head]
        + f"\n[输出已截断] 完整 {len(full)} 字符，仅首 {head} + 尾 {tail}（历史格式）。"
        + f"完整原文已落盘: {sidecar}；\n"
        + full[-tail:]
    )
    return projected, sidecar


def _stores(tmp_path: Path):
    root = tmp_path / "data" / "evidence"
    blobs = BlobStore(root / "blobs")
    ledger = EvidenceLedgerStore(root / "ledger")
    return blobs, ledger, EvidenceCapture(blobs, ledger)


def _session_with_tool(
    store: SessionStore, content: str, *, tool_name: str, tool_call_id: str
) -> str:
    sid = store.create()
    sess = store.load(sid)
    sess.messages.append(
        Message(
            role="tool",
            content=content,
            source=MessageSource.TOOL,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )
    )
    store.save(sess)
    return sid


def _migrator(tmp_path: Path, store: SessionStore):
    blobs, ledger, capture = _stores(tmp_path)
    migrator = LegacySidecarMigrator(
        data_dir=tmp_path / "data",
        sessions=store,
        capture=capture,
        ledger=ledger,
        workspace_id=str(tmp_path.resolve()),
    )
    return blobs, ledger, migrator


def test_owned_tool_output_sidecar_migrates_with_exact_proof(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    full = "HEAD-" + ("A" * 180) + "-MIDDLE-314159-" + ("Z" * 180) + "-TAIL"
    projected, _sidecar = _legacy_projected(data_dir, full, source="owned.txt")
    store = SessionStore(tmp_path / "sessions")
    sid = _session_with_tool(store, projected, tool_name="read_file", tool_call_id="call-owned")
    blobs, ledger, migrator = _migrator(tmp_path, store)

    report = migrator.migrate_all()

    owner = OwnerScope(workspace_id=str(tmp_path.resolve()), session_id=sid)
    records = ledger.list_recent(owner, limit=10)
    assert report.migrated_records == 1
    assert report.quarantined_files == 0
    assert len(records) == 1
    record = records[0]
    assert record.tool_call_id == "call-owned"
    assert record.provenance.producer == "legacy_sidecar_migration"
    hydrated = EvidenceHydration(blobs, ledger, max_limit=1000).read(
        owner=owner,
        evidence_ref=record.evidence_ref,
        range_type=RangeType.TEXT_CHAR,
        start=0,
        limit=1000,
    )
    assert hydrated.content == full


def test_command_sidecar_migrates_and_is_idempotent(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    full = "CMD_HEAD" + ("x" * 260) + "CMD_TAIL"
    projected, _sidecar = _legacy_projected(
        data_dir, full, kind="command", head=40, tail=40, source="printf_legacy"
    )
    store = SessionStore(tmp_path / "sessions")
    sid = _session_with_tool(store, projected, tool_name="execute_command", tool_call_id="cmd-1")
    _, ledger, migrator = _migrator(tmp_path, store)

    first = migrator.migrate_all()
    refs_first = [
        r.evidence_ref.ref
        for r in ledger.list_recent(
            OwnerScope(workspace_id=str(tmp_path.resolve()), session_id=sid), limit=10
        )
    ]
    second = migrator.migrate_all()
    refs_second = [
        r.evidence_ref.ref
        for r in ledger.list_recent(
            OwnerScope(workspace_id=str(tmp_path.resolve()), session_id=sid), limit=10
        )
    ]

    assert first.migrated_records == 1
    assert second.migrated_records == 0
    assert second.reused_records == 1
    assert refs_second == refs_first


def test_tampered_sidecar_is_quarantined_not_migrated(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    full = "T" * 400
    projected, sidecar = _legacy_projected(data_dir, full, head=40, tail=40, source="tampered.txt")
    sidecar.write_text(full + "CORRUPTED", encoding="utf-8")
    store = SessionStore(tmp_path / "sessions")
    sid = _session_with_tool(store, projected, tool_name="read_file", tool_call_id="tampered-1")
    _, ledger, migrator = _migrator(tmp_path, store)

    report = migrator.migrate_all()

    owner = OwnerScope(workspace_id=str(tmp_path.resolve()), session_id=sid)
    assert ledger.count(owner) == 0
    assert report.migrated_records == 0
    assert report.quarantined_files == 1
    inventory = (tmp_path / "data" / "evidence" / "quarantine" / "legacy_sidecars.json").read_text(
        encoding="utf-8"
    )
    assert "proof_failed" in inventory
    assert sidecar.name in inventory


def test_orphan_sidecar_inventory_only_never_enters_ledger(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    _legacy_projected(data_dir, "ORPHAN" * 100, head=40, tail=40, source="orphan.txt")
    store = SessionStore(tmp_path / "sessions")
    _, ledger, migrator = _migrator(tmp_path, store)

    report = migrator.migrate_all()

    assert report.migrated_records == 0
    assert report.quarantined_files == 1
    assert not (tmp_path / "data" / "evidence" / "ledger" / "owners").exists()
    inventory = (tmp_path / "data" / "evidence" / "quarantine" / "legacy_sidecars.json").read_text(
        encoding="utf-8"
    )
    assert "unreferenced" in inventory


def test_symlink_sidecar_is_never_accepted_as_owned(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    out_dir = data_dir / "audit" / "tool_outputs"
    out_dir.mkdir(parents=True)
    full = "SAFE" * 100
    digest = hashlib.sha256(full.encode()).hexdigest()[:16]
    external = tmp_path / "external.log"
    external.write_text(full, encoding="utf-8")
    sidecar = out_dir / f"{digest}_link.log"
    sidecar.symlink_to(external)
    projected = (
        full[:40]
        + "\n[输出已截断] 完整 400 字符，仅首 40 + 尾 40（阈值 100）。截断确定性: 重跑得同结果勿重跑。"
        + f"取全文: full=true 重调 / read_file 读取落盘全文 {sidecar}。\n"
        + full[-40:]
    )
    store = SessionStore(tmp_path / "sessions")
    sid = _session_with_tool(store, projected, tool_name="read_file", tool_call_id="link-1")
    _, ledger, migrator = _migrator(tmp_path, store)

    report = migrator.migrate_all()

    assert ledger.count(OwnerScope(workspace_id=str(tmp_path.resolve()), session_id=sid)) == 0
    assert report.quarantined_files == 1
    inventory = (tmp_path / "data" / "evidence" / "quarantine" / "legacy_sidecars.json").read_text(
        encoding="utf-8"
    )
    assert "symlink" in inventory


def _capture(capture: EvidenceCapture, owner: OwnerScope, stable_id: str, text: str):
    return capture.capture(
        make_capture_request(
            owner=owner,
            stable_capture_id=stable_id,
            raw_observation=text,
            acquired_at=datetime.now(UTC),
            tool_name="unit",
            tool_call_id=stable_id,
            source=SourceIdentity(
                kind=SourceKind.CONVERSATION,
                locator=f"unit:{stable_id}",
                version_policy=SourceVersionPolicy.SNAPSHOT_ONLY,
            ),
            coverage=Coverage(unit="text", start=0, end_exclusive=None, source_complete=True),
            provenance=Provenance(producer="phase6_test"),
        )
    )


def test_shared_blob_gc_waits_for_last_owner(tmp_path):
    blobs, ledger, capture = _stores(tmp_path)
    owner_a = OwnerScope(workspace_id="ws", session_id="a")
    owner_b = OwnerScope(workspace_id="ws", session_id="b")
    a = _capture(capture, owner_a, "a1", "SHARED-BYTES")
    b = _capture(capture, owner_b, "b1", "SHARED-BYTES")
    assert a.blob_ref.ref == b.blob_ref.ref
    lifecycle = EvidenceLifecycle(blobs, ledger)

    first = lifecycle.delete_owner(owner_a)
    assert first.records_removed == 1
    assert first.blobs_deleted == 0
    assert first.blobs_retained == 1
    assert blobs.verify(b.blob_ref)
    assert ledger.count(owner_b) == 1

    second = lifecycle.delete_owner(owner_b)
    assert second.records_removed == 1
    assert second.blobs_deleted == 1
    assert second.blobs_retained == 0
    assert not blobs.verify(b.blob_ref)


def test_lifecycle_delete_unknown_owner_is_idempotent(tmp_path):
    blobs, ledger, _ = _stores(tmp_path)
    lifecycle = EvidenceLifecycle(blobs, ledger)
    owner = OwnerScope(workspace_id="ws", session_id="missing")
    first = lifecycle.delete_owner(owner)
    second = lifecycle.delete_owner(owner)
    assert first.records_removed == second.records_removed == 0
    assert first.blobs_deleted == second.blobs_deleted == 0


def _factory_settings(data_dir: Path, *, mode: str):
    from llm_loop.config import Settings

    return Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(data_dir),
        extract_enabled=False,
        evidence_mode=mode,
        tool_pipeline_enabled=False,
        history_max_chars=200000,
    )


def test_factory_enforce_auto_migrates_and_compression_reuses_full_legacy_evidence(
    tmp_path, monkeypatch
):
    from llm_loop.factory import build_engine

    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("HEAD_KEEP_RATIO", "0")
    monkeypatch.setenv("HEAD_KEEP_FORCE_RATIO", "0")
    full = "LEGACY_HEAD" + ("M" * 420) + "HIDDEN_FULL_BYTES" + ("N" * 420) + "LEGACY_TAIL"
    projected, _sidecar = _legacy_projected(data_dir, full, source="legacy-factory.txt")

    # Create the session through the real legacy/off factory first, so workspace partition
    # and global session identity match production behavior before enforce is introduced.
    legacy_engine = build_engine(_factory_settings(data_dir, mode="off"))
    sid = legacy_engine.session.create()
    sess = legacy_engine.session.load(sid)
    call_id = "legacy-factory-call"
    sess.messages.append(
        Message(
            role="assistant",
            content="",
            source=MessageSource.SYSTEM,
            tool_calls=[
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "read_file", "arguments": {"path": "legacy-factory.txt"}},
                }
            ],
        )
    )
    sess.messages.append(
        Message(
            role="tool",
            content=projected,
            source=MessageSource.TOOL,
            tool_name="read_file",
            tool_call_id=call_id,
        )
    )
    for i in range(18):
        sess.messages.append(
            Message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"FILLER-{i}-" + ("Q" * 900),
                source=MessageSource.USER if i % 2 == 0 else MessageSource.SYSTEM,
            )
        )
    legacy_engine.session.save(sess)

    settings = _factory_settings(data_dir, mode="enforce")
    engine = build_engine(settings)
    ledger = EvidenceLedgerStore(settings.evidence_dir / "ledger")
    owners = ledger.owners_for_session(sid)
    assert len(owners) == 1
    owner = owners[0]
    migrated = ledger.find_by_tool_call_id(owner, call_id)
    assert len(migrated) == 1
    assert migrated[0].provenance.producer == "legacy_sidecar_migration"
    assert BlobStore(settings.evidence_dir / "blobs").read_text(migrated[0].blob_ref) == full

    loaded = engine.session.load(sid)
    engine._build_llm_messages(loaded, [], max_chars=3200, planned_label="deepseek/model")
    after = ledger.find_by_tool_call_id(owner, call_id)
    assert len(after) == 1
    assert after[0].evidence_ref == migrated[0].evidence_ref
    assert BlobStore(settings.evidence_dir / "blobs").read_text(after[0].blob_ref) == full


def test_off_mode_session_delete_cleans_prior_evidence_with_shared_blob_refcount(tmp_path):
    from llm_loop.factory import build_engine

    data_dir = tmp_path / "data"
    engine = build_engine(_factory_settings(data_dir, mode="off"))
    sid_a = engine.session.create()
    sid_b = engine.session.create()

    blobs = BlobStore(data_dir / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(data_dir / "evidence" / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    owner_a = OwnerScope(workspace_id="workspace-a", session_id=sid_a)
    owner_b = OwnerScope(workspace_id="workspace-b", session_id=sid_b)
    a = _capture(capture, owner_a, "delete-a", "DELETE-SHARED-BLOB")
    b = _capture(capture, owner_b, "delete-b", "DELETE-SHARED-BLOB")
    assert a.blob_ref == b.blob_ref

    assert engine.session.delete(sid_a) is True
    assert ledger.count(owner_a) == 0
    assert ledger.count(owner_b) == 1
    assert blobs.verify(b.blob_ref)

    assert engine.session.delete(sid_b) is True
    assert ledger.count(owner_b) == 0
    assert not blobs.verify(b.blob_ref)


def test_owners_for_session_ignores_corrupt_owner_metadata(tmp_path):
    _, ledger, capture = _stores(tmp_path)
    owner = OwnerScope(workspace_id="workspace", session_id="target")
    _capture(capture, owner, "owner-good", "GOOD")
    corrupt = ledger.root / "owners" / ("f" * 64) / "owner.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{broken", encoding="utf-8")
    assert ledger.owners_for_session("target") == [owner]


def test_capture_racing_zero_ref_gc_never_leaves_dangling_record(tmp_path, monkeypatch):
    import threading

    blobs, ledger, capture = _stores(tmp_path)
    owner_a = OwnerScope(workspace_id="ws", session_id="race-a")
    owner_b = OwnerScope(workspace_id="ws", session_id="race-b")
    initial = _capture(capture, owner_a, "race-a", "RACE-SHARED")
    lifecycle = EvidenceLifecycle(blobs, ledger)

    at_zero = threading.Event()
    release_delete = threading.Event()
    original_refcount = ledger.blob_refcount

    def gated_refcount(ref):
        count = original_refcount(ref)
        if count == 0:
            at_zero.set()
            assert release_delete.wait(timeout=5)
        return count

    monkeypatch.setattr(ledger, "blob_refcount", gated_refcount)
    delete_thread = threading.Thread(target=lambda: lifecycle.delete_owner(owner_a), daemon=True)
    delete_thread.start()
    assert at_zero.wait(timeout=5)

    capture_done = threading.Event()

    def capture_b():
        _capture(capture, owner_b, "race-b", "RACE-SHARED")
        capture_done.set()

    capture_thread = threading.Thread(target=capture_b, daemon=True)
    capture_thread.start()
    # Capture must serialize behind the GC lock while delete is paused after refcount=0.
    assert not capture_done.wait(timeout=0.05)
    release_delete.set()
    delete_thread.join(timeout=5)
    capture_thread.join(timeout=5)
    assert capture_done.is_set()
    records = ledger.list_recent(owner_b, limit=10)
    assert len(records) == 1
    assert records[0].blob_ref.ref == initial.blob_ref.ref
    assert blobs.verify(records[0].blob_ref)
