from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from llm_loop.core.message import RecoverabilityStatus, ToolCall, ToolResultStatus
from llm_loop.memory.evidence import (
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceFreshness,
    EvidenceLedgerStore,
    EvidenceRef,
    EvidenceSearch,
    ManifestProjector,
    OwnerScope,
    ProjectionEngine,
    Provenance,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
    render_recovery_manifest,
)
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.evidence_enforce import EvidenceEnforcer
from llm_loop.tools.evidence_tools import (
    EvidenceReadTool,
    EvidenceSearchTool,
    SearchArchiveCompatTool,
)
from llm_loop.tools.registry import ToolRegistry


def _stores(tmp_path: Path):
    blobs = BlobStore(tmp_path / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "evidence" / "ledger")
    return blobs, ledger


def _owner(tmp_path: Path) -> OwnerScope:
    return OwnerScope(workspace_id=str(tmp_path), session_id="r3-session")


def _capture_runtime(tmp_path: Path, content: str):
    blobs, ledger = _stores(tmp_path)
    owner = _owner(tmp_path)
    capture = EvidenceCapture(blobs, ledger)
    captured = capture.capture(
        make_capture_request(
            owner=owner,
            stable_capture_id="runtime-capture",
            raw_observation=content,
            acquired_at=datetime(2026, 8, 26, 11, 0, tzinfo=UTC),
            tool_name="runtime_snapshot",
            tool_call_id="runtime-capture",
            source=SourceIdentity(
                kind=SourceKind.RUNTIME_SNAPSHOT,
                locator="runtime:r3",
                version_policy=SourceVersionPolicy.VERSIONED,
            ),
            coverage=Coverage(unit="observation", start=0, end_exclusive=None, source_complete=True),
            provenance=Provenance(producer="r3-test"),
        )
    )
    return blobs, ledger, owner, captured.evidence_ref


def _capture_file(tmp_path: Path):
    path = tmp_path / "r3-file.txt"
    path.write_text("ORIGINAL-R3-CONTENT\n" + "x" * 300, encoding="utf-8")
    blobs, ledger = _stores(tmp_path)
    owner = _owner(tmp_path)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.set_evidence_enforcer(
        EvidenceEnforcer(
            EvidenceCapture(blobs, ledger),
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            projection_budget_chars=256,
        )
    )
    result = registry.execute(ToolCall(id="file-capture", name="read_file", arguments={"path": str(path)}))
    assert result.status is ToolResultStatus.SUCCESS
    return path, blobs, ledger, owner, EvidenceRef(result.evidence_ref or "")


def test_r3_read_evidence_structures_transport_content_and_completeness(tmp_path: Path) -> None:
    content = "A" * 500
    blobs, ledger, owner, ref = _capture_runtime(tmp_path, content)
    tool = EvidenceReadTool(
        blobs,
        ledger,
        freshness=EvidenceFreshness(ledger),
        owner_resolver=lambda: owner,
        max_limit=4000,
    )

    result = tool.execute(evidence_ref=ref.ref, range_type="text_char", start=0, limit=100)

    assert result.status is ToolResultStatus.SUCCESS
    payload = json.loads(result.content)
    assert payload["schema"] == "evidence_hydration_v2"
    assert payload["kind"] == "evidence_hydration"
    assert payload["transport"] == {
        "evidence_ref": ref.ref,
        "role": "recovery_handle",
        "is_domain_content": False,
    }
    assert payload["content"] == content[:100]
    assert payload["range"]["next_start"] == 100
    assert payload["range"]["complete"] is False
    assert payload["freshness"]["currentness"] == "unverified"
    assert payload["freshness"]["currentness_scope"] == "source_version_only"
    assert payload["freshness"]["task_applicability"] == "not_evaluated"
    assert payload["source"]["acquired_at"] == "2026-08-26T11:00:00+00:00"
    assert payload["source"]["version_policy"] == "versioned"
    assert payload["source"]["version_token"] is None
    assert payload["source"]["provenance"]["producer"] == "r3-test"
    assert result.recoverability_status is RecoverabilityStatus.RECORDED
    assert result.evidence_ref == ref.ref
    assert result.evidence_representation == "hydration_range"
    assert result.evidence_projection_complete is False
    assert result.source_resolution_mode == "evidence_hydration"
    assert result.source_execution_performed is False
    assert result.evidence_source_label
    assert result.evidence_origin_facts == {
        "acquired_at": "2026-08-26T11:00:00+00:00",
        "source_kind": "runtime_snapshot",
        "source_version_policy": "versioned",
        "source_version_token": None,
        "provenance": {"producer": "r3-test", "authority": "", "scope": ""},
    }
    assert "hydration=text_char:0+100/next=100" in (result.evidence_coverage_label or "")
    assert EvidenceReadTool.parameters["properties"]["allow_stale"]["type"] == "boolean"
    wire = result.to_message()
    assert wire.content.startswith("[状态: success] ")
    assert json.loads(wire.content.split("] ", 1)[1])["transport"]["role"] == "recovery_handle"


def test_r3_verified_current_file_is_current_and_structured(tmp_path: Path) -> None:
    _, blobs, ledger, owner, ref = _capture_file(tmp_path)
    tool = EvidenceReadTool(blobs, ledger, freshness=EvidenceFreshness(ledger), owner_resolver=lambda: owner)

    result = tool.execute(evidence_ref=ref.ref, range_type="text_char", start=0, limit=100)

    assert result.status is ToolResultStatus.SUCCESS
    payload = json.loads(result.content)
    assert payload["freshness"]["state"] == "verified_current"
    assert payload["freshness"]["currentness"] == "current"
    # "current" is deliberately scoped to the physical source version. It must never
    # become a runtime claim that the file's assertions apply to the current task/build.
    assert payload["freshness"]["currentness_scope"] == "source_version_only"
    assert payload["freshness"]["task_applicability"] == "not_evaluated"
    assert payload["source"]["kind"] == "file"
    assert payload["source"]["version_policy"] == "probeable"
    assert str(payload["source"]["version_token"]).startswith("stat:")
    assert payload["source"]["provenance"] == {
        "producer": "tool_registry_enforce",
        "authority": "tool_observation",
        "scope": "success",
    }
    assert payload["transport"]["is_domain_content"] is False


def test_r3_stale_probeable_file_blocks_content_by_default_and_allows_explicit_history(tmp_path: Path) -> None:
    path, blobs, ledger, owner, ref = _capture_file(tmp_path)
    path.write_text("NEW-R3-CONTENT\n" + "y" * 500, encoding="utf-8")
    tool = EvidenceReadTool(blobs, ledger, freshness=EvidenceFreshness(ledger), owner_resolver=lambda: owner)

    blocked = tool.execute(evidence_ref=ref.ref, range_type="text_char", start=0, limit=4000)
    assert blocked.status is ToolResultStatus.FAILURE
    blocked_payload = json.loads(blocked.content)
    assert blocked_payload["kind"] == "evidence_hydration_blocked"
    assert blocked_payload["freshness"]["state"] == "stale"
    assert blocked_payload["freshness"]["currentness"] == "historical_only"
    assert blocked_payload["freshness"]["currentness_scope"] == "source_version_only"
    assert blocked_payload["freshness"]["task_applicability"] == "not_evaluated"
    assert blocked_payload["policy"]["refresh_required"] is True
    assert blocked_payload["policy"]["historical_read_requires"] == "allow_stale=true"
    assert "content" not in blocked_payload
    assert "ORIGINAL-R3-CONTENT" not in blocked.content
    blocked_wire = blocked.to_message()
    assert blocked_wire.content.startswith("[状态: failure] ")
    assert "ORIGINAL-R3-CONTENT" not in blocked_wire.content

    historical = tool.execute(
        evidence_ref=ref.ref,
        range_type="text_char",
        start=0,
        limit=4000,
        allow_stale=True,
    )
    assert historical.status is ToolResultStatus.SUCCESS
    historical_payload = json.loads(historical.content)
    assert historical_payload["freshness"]["state"] == "stale"
    assert historical_payload["freshness"]["currentness"] == "historical_only"
    assert "ORIGINAL-R3-CONTENT" in historical_payload["content"]


def test_r3_manifest_marks_stale_as_historical_only(tmp_path: Path) -> None:
    path, _, ledger, owner, ref = _capture_file(tmp_path)
    path.write_text("CHANGED-R3", encoding="utf-8")
    freshness = EvidenceFreshness(ledger)
    assert freshness.refresh(owner=owner, evidence_ref=ref).freshness.value == "stale"

    rendered = render_recovery_manifest(ManifestProjector(ledger).build_recent(owner=owner, limit=5))

    assert "freshness=stale" in rendered
    assert "currentness=historical_only" in rendered
    assert "currentness_scope=source_version_only" in rendered
    assert "task_applicability=not_evaluated" in rendered
    assert "acquired_at=" in rendered


def test_r3_search_stale_probeable_file_hides_snippet_by_default_and_allows_explicit_history(tmp_path: Path) -> None:
    path, blobs, ledger, owner, _ = _capture_file(tmp_path)
    path.write_text("NEW-R3-CONTENT\n" + "z" * 500, encoding="utf-8")
    tool = EvidenceSearchTool(
        EvidenceSearch(blobs, ledger, snippet_chars=180),
        freshness=EvidenceFreshness(ledger),
        owner_resolver=lambda: owner,
    )

    blocked = tool.execute(query="ORIGINAL-R3-CONTENT", limit=5)
    assert blocked.status is ToolResultStatus.SUCCESS
    assert "freshness=stale" in blocked.content
    assert "currentness=historical_only" in blocked.content
    assert "currentness_scope=source_version_only" in blocked.content
    assert "task_applicability=not_evaluated" in blocked.content
    assert "acquired_at=" in blocked.content
    assert "historical_search_requires=allow_stale=true" in blocked.content
    assert "ORIGINAL-R3-CONTENT" not in blocked.content
    assert EvidenceSearchTool.parameters["properties"]["allow_stale"]["type"] == "boolean"

    historical = tool.execute(query="ORIGINAL-R3-CONTENT", limit=5, allow_stale=True)
    assert historical.status is ToolResultStatus.SUCCESS
    assert "freshness=stale" in historical.content
    assert "currentness=historical_only" in historical.content
    assert "ORIGINAL-R3-CONTENT" in historical.content

    compat = SearchArchiveCompatTool(
        EvidenceSearch(blobs, ledger, snippet_chars=180),
        freshness=EvidenceFreshness(ledger),
        owner_resolver=lambda: owner,
    )
    compat_blocked = compat.execute(query="ORIGINAL-R3-CONTENT", limit=5)
    assert "ORIGINAL-R3-CONTENT" not in compat_blocked.content
    assert "currentness=historical_only" in compat_blocked.content
    assert SearchArchiveCompatTool.parameters["properties"]["allow_stale"]["type"] == "boolean"


def test_origin_enrichment_program_error_is_visible_without_rewriting_source_success(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "origin-error.txt"
    path.write_text("SOURCE-ACTION-TRUTH", encoding="utf-8")
    blobs, ledger = _stores(tmp_path)
    owner = _owner(tmp_path)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.set_evidence_enforcer(
        EvidenceEnforcer(
            EvidenceCapture(blobs, ledger),
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            projection_budget_chars=512,
        )
    )

    original_get_record = ledger.get_record
    call_count = 0

    def _fail_only_origin_lookup(owner_arg, ref):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("origin-observability-bug")
        return original_get_record(owner_arg, ref)

    monkeypatch.setattr(ledger, "get_record", _fail_only_origin_lookup)

    result = registry.execute(
        ToolCall(id="origin-error", name="read_file", arguments={"path": str(path)})
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert "SOURCE-ACTION-TRUTH" in result.content
    assert "[程序异常] Evidence origin facts enrichment failed" in result.content
    assert "error_type=RuntimeError" in result.content
    assert "source_action_status=success" in result.content
    assert "source action result remains valid" in result.content
