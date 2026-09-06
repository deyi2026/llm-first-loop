from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from llm_loop.config import Settings
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.memory.evidence import (
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceFreshness,
    EvidenceLedgerStore,
    EvidenceRef,
    EvidenceSearch,
    FreshnessState,
    OwnerScope,
    ProjectionEngine,
    Provenance,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
)
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.evidence_enforce import EvidenceEnforcer
from llm_loop.tools.evidence_tools import EvidenceListTool, EvidenceReadTool, EvidenceSearchTool
from llm_loop.tools.registry import ToolRegistry


def _owner(name: str = "A") -> OwnerScope:
    return OwnerScope(workspace_id=f"/workspace-{name}", session_id=f"session-{name}")


def _stores(tmp_path: Path):
    blobs = BlobStore(tmp_path / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "evidence" / "ledger")
    return blobs, ledger


def _capture(
    capture: EvidenceCapture,
    owner: OwnerScope,
    stable_id: str,
    content: str,
    *,
    source_kind: SourceKind = SourceKind.RUNTIME_SNAPSHOT,
    locator: str = "runtime:test",
    version_policy: SourceVersionPolicy = SourceVersionPolicy.VERSIONED,
    version_token: str | None = None,
):
    return capture.capture(
        make_capture_request(
            owner=owner,
            stable_capture_id=stable_id,
            raw_observation=content,
            acquired_at=datetime(2026, 8, 26, 8, 30, tzinfo=UTC),
            tool_name="fixture_tool",
            tool_call_id=stable_id,
            source=SourceIdentity(
                kind=source_kind,
                locator=locator,
                version_policy=version_policy,
                version_token=version_token,
            ),
            coverage=Coverage(unit="observation", start=0, end_exclusive=None, source_complete=True),
            provenance=Provenance(producer="phase4-test"),
        )
    )


def test_search_default_and_explicit_or_phrase_and_middle_visible(tmp_path):
    blobs, ledger = _stores(tmp_path)
    capture = EvidenceCapture(blobs, ledger)
    owner = _owner()
    r1 = _capture(capture, owner, "c1", "prefix " + "x" * 500 + " alpha beta omega")
    r2 = _capture(capture, owner, "c2", "alpha something gamma")
    _capture(capture, _owner("B"), "secret", "alpha beta gamma PRIVATE_B")
    search = EvidenceSearch(blobs, ledger, snippet_chars=180)

    and_hits = search.search(owner=owner, query="alpha beta", limit=10)
    assert [h.evidence_ref for h in and_hits.hits] == [r1.evidence_ref]
    assert "alpha" in and_hits.hits[0].snippet.lower()
    assert "beta" in and_hits.hits[0].snippet.lower()
    assert "prefix" not in and_hits.hits[0].snippet  # centered near the deep match

    or_hits = search.search(owner=owner, query="beta OR gamma", limit=10)
    assert {h.evidence_ref for h in or_hits.hits} == {r1.evidence_ref, r2.evidence_ref}

    phrase_hits = search.search(owner=owner, query='"alpha beta"', limit=10)
    assert [h.evidence_ref for h in phrase_hits.hits] == [r1.evidence_ref]
    assert "PRIVATE_B" not in str(or_hits)


def test_search_rejects_empty_query_and_is_owner_scoped(tmp_path):
    blobs, ledger = _stores(tmp_path)
    capture = EvidenceCapture(blobs, ledger)
    _capture(capture, _owner("B"), "b", "needle only in B")
    search = EvidenceSearch(blobs, ledger)
    with pytest.raises(ValueError, match="query"):
        search.search(owner=_owner(), query="   ", limit=10)
    assert search.search(owner=_owner(), query="needle", limit=10).hits == ()


def test_file_freshness_current_then_stale_after_change(tmp_path):
    path = tmp_path / "fresh.txt"
    path.write_text("version one", encoding="utf-8")
    blobs, ledger = _stores(tmp_path)
    owner = OwnerScope(workspace_id=str(tmp_path), session_id="s1")
    capture = EvidenceCapture(blobs, ledger)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.set_evidence_enforcer(
        EvidenceEnforcer(
            capture,
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            projection_budget_chars=500,
        )
    )
    result = registry.execute(ToolCall(id="read-1", name="read_file", arguments={"path": str(path)}))
    ref = EvidenceRef(result.evidence_ref or "")
    freshness = EvidenceFreshness(ledger)

    assert freshness.refresh(owner=owner, evidence_ref=ref).freshness is FreshnessState.VERIFIED_CURRENT
    path.write_text("version two and changed size", encoding="utf-8")
    assert freshness.refresh(owner=owner, evidence_ref=ref).freshness is FreshnessState.STALE


def test_non_file_freshness_never_fabricates_current(tmp_path):
    blobs, ledger = _stores(tmp_path)
    capture = EvidenceCapture(blobs, ledger)
    owner = _owner()
    command = _capture(
        capture,
        owner,
        "cmd",
        "output",
        source_kind=SourceKind.COMMAND,
        locator="echo x",
        version_policy=SourceVersionPolicy.SNAPSHOT_ONLY,
    )
    web = _capture(
        capture,
        owner,
        "web",
        "web output",
        source_kind=SourceKind.WEB,
        locator="https://example.test/x",
        version_policy=SourceVersionPolicy.VOLATILE,
    )
    runtime = _capture(
        capture,
        owner,
        "runtime",
        "runtime output",
        source_kind=SourceKind.RUNTIME_SNAPSHOT,
        locator="runtime:state",
        version_policy=SourceVersionPolicy.VERSIONED,
    )
    freshness = EvidenceFreshness(ledger)
    assert freshness.refresh(owner=owner, evidence_ref=command.evidence_ref).freshness is FreshnessState.UNKNOWN
    assert freshness.refresh(owner=owner, evidence_ref=web.evidence_ref).freshness is FreshnessState.UNKNOWN
    assert freshness.refresh(owner=owner, evidence_ref=runtime.evidence_ref).freshness is FreshnessState.UNKNOWN


def test_evidence_control_tools_are_owner_injected_bounded_and_not_recaptured(tmp_path):
    blobs, ledger = _stores(tmp_path)
    owner = _owner()
    capture = EvidenceCapture(blobs, ledger)
    captured = _capture(capture, owner, "seed", "line1\nline2 alpha beta\nline3")
    freshness = EvidenceFreshness(ledger)
    search = EvidenceSearch(blobs, ledger)

    registry = ToolRegistry()
    registry.set_evidence_enforcer(
        EvidenceEnforcer(
            capture,
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            projection_budget_chars=500,
        )
    )
    registry.register(EvidenceReadTool(blobs, ledger, freshness=freshness, owner_resolver=lambda: owner))
    registry.register(EvidenceListTool(ledger, freshness=freshness, owner_resolver=lambda: owner))
    registry.register(EvidenceSearchTool(search, freshness=freshness, owner_resolver=lambda: owner))
    before = ledger.count(owner)

    listed = registry.execute(ToolCall(id="l1", name="list_evidence", arguments={"limit": 5}))
    assert listed.status is ToolResultStatus.SUCCESS
    assert captured.evidence_ref.ref in listed.content

    found = registry.execute(ToolCall(id="s1", name="search_evidence", arguments={"query": "alpha beta"}))
    assert found.status is ToolResultStatus.SUCCESS
    assert captured.evidence_ref.ref in found.content
    assert "alpha beta" in found.content.lower()

    read = registry.execute(
        ToolCall(
            id="r1",
            name="read_evidence",
            arguments={"evidence_ref": captured.evidence_ref.ref, "range_type": "line", "start": 1, "limit": 1},
        )
    )
    assert read.status is ToolResultStatus.SUCCESS
    assert "line2 alpha beta" in read.content
    assert ledger.count(owner) == before  # recovery operations do not recursively create Evidence


def test_read_evidence_cross_owner_does_not_reveal_existence(tmp_path):
    blobs, ledger = _stores(tmp_path)
    capture = EvidenceCapture(blobs, ledger)
    secret = _capture(capture, _owner("B"), "secret", "private")
    tool = EvidenceReadTool(blobs, ledger, freshness=EvidenceFreshness(ledger), owner_resolver=_owner)
    result = tool.execute(evidence_ref=secret.evidence_ref.ref, range_type="text_char", start=0, limit=10)
    assert result.status in {ToolResultStatus.FAILURE, ToolResultStatus.BLOCKED}
    assert "session-B" not in result.content
    assert "workspace-B" not in result.content
    assert "private" not in result.content


def test_factory_registers_recovery_tools_only_in_enforce_mode(tmp_path):
    from llm_loop.factory import build_engine

    base = dict(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        extract_enabled=False,
        tool_pipeline_enabled=False,
    )
    off = build_engine(Settings(**base, data_dir=str(tmp_path / "off"), evidence_mode="off"))
    shadow = build_engine(Settings(**base, data_dir=str(tmp_path / "shadow"), evidence_mode="shadow"))
    enforce = build_engine(Settings(**base, data_dir=str(tmp_path / "enforce"), evidence_mode="enforce"))

    def names(engine):
        return {row["name"] for row in engine.registry.schemas(lazy=False)}

    recovery = {"read_evidence", "search_evidence", "list_evidence"}
    assert recovery.isdisjoint(names(off))
    assert recovery.isdisjoint(names(shadow))  # preserve Phase2 promise: no prompt/schema change
    enforce_names = names(enforce)
    assert recovery <= enforce_names
    assert "search_archive" in enforce_names  # Phase5 compatibility alias, not legacy substring search



def test_search_gold_fixture_precision_recall_visible_matches(tmp_path):
    fixture_path = Path(__file__).parents[1] / "fixtures" / "evidence_search_r0_gold.json"
    gold = json.loads(fixture_path.read_text(encoding="utf-8"))
    blobs, ledger = _stores(tmp_path)
    capture = EvidenceCapture(blobs, ledger)
    refs_by_id = {}
    ids_by_ref = {}
    for doc in gold["documents"]:
        owner = _owner(doc["owner"])
        result = _capture(capture, owner, doc["id"], doc["content"])
        refs_by_id[doc["id"]] = result.evidence_ref
        ids_by_ref[result.evidence_ref] = doc["id"]

    search = EvidenceSearch(blobs, ledger, snippet_chars=160)
    for case in gold["queries"]:
        result = search.search(owner=_owner("A"), query=case["query"], limit=20)
        actual = {ids_by_ref[hit.evidence_ref] for hit in result.hits}
        assert actual == set(case["expected"]), case["query"]
        for hit in result.hits:
            snippet = hit.snippet.casefold()
            required = [str(term).casefold() for term in case.get("visible_terms", [])]
            any_terms = [str(term).casefold() for term in case.get("visible_any", [])]
            assert all(term in snippet for term in required), (case["query"], snippet)
            if any_terms:
                assert any(term in snippet for term in any_terms), (case["query"], snippet)
            assert "private owner evidence" not in snippet


def test_agent_read_evidence_limit_is_hard_bounded(tmp_path):
    blobs, ledger = _stores(tmp_path)
    owner = _owner()
    capture = EvidenceCapture(blobs, ledger)
    record = _capture(capture, owner, "large", "X" * 10000)
    tool = EvidenceReadTool(
        blobs,
        ledger,
        freshness=EvidenceFreshness(ledger),
        owner_resolver=lambda: owner,
        max_limit=4000,
    )
    result = tool.execute(
        evidence_ref=record.evidence_ref.ref,
        range_type="text_char",
        start=0,
        limit=4001,
    )
    assert result.status is ToolResultStatus.FAILURE
    assert "maximum 4000" in result.content


def test_list_evidence_safe_labels_hide_command_args_and_url_query(tmp_path):
    blobs, ledger = _stores(tmp_path)
    owner = _owner()
    capture = EvidenceCapture(blobs, ledger)
    _capture(
        capture,
        owner,
        "cmd-safe",
        "command result",
        source_kind=SourceKind.COMMAND,
        locator="curl -H Authorization:SECRET https://example.test",
        version_policy=SourceVersionPolicy.SNAPSHOT_ONLY,
    )
    _capture(
        capture,
        owner,
        "web-safe",
        "web result",
        source_kind=SourceKind.WEB,
        locator="https://example.test/path?token=SECRET_QUERY",
        version_policy=SourceVersionPolicy.VOLATILE,
    )
    tool = EvidenceListTool(
        ledger,
        freshness=EvidenceFreshness(ledger),
        owner_resolver=lambda: owner,
    )
    result = tool.execute(limit=10)
    assert result.status is ToolResultStatus.SUCCESS
    assert "SECRET" not in result.content
    assert "SECRET_QUERY" not in result.content
    assert "command#" in result.content
    assert "https://example.test/path" in result.content



def test_recovery_reads_do_not_churn_ledger_version_when_state_unchanged(tmp_path):
    blobs, ledger = _stores(tmp_path)
    owner = _owner()
    capture = EvidenceCapture(blobs, ledger)
    record = _capture(capture, owner, "stable", "stable observation")
    freshness = EvidenceFreshness(ledger)
    read_tool = EvidenceReadTool(blobs, ledger, freshness=freshness, owner_resolver=lambda: owner)
    list_tool = EvidenceListTool(ledger, freshness=freshness, owner_resolver=lambda: owner)
    search_tool = EvidenceSearchTool(
        EvidenceSearch(blobs, ledger), freshness=freshness, owner_resolver=lambda: owner
    )
    before = ledger.ledger_version(owner)
    assert read_tool.execute(evidence_ref=record.evidence_ref.ref).status is ToolResultStatus.SUCCESS
    assert list_tool.execute(limit=10).status is ToolResultStatus.SUCCESS
    assert search_tool.execute(query="stable").status is ToolResultStatus.SUCCESS
    assert ledger.ledger_version(owner) == before


def test_model_facing_read_rejects_blob_ref_as_capability(tmp_path):
    blobs, ledger = _stores(tmp_path)
    owner = _owner()
    record = _capture(EvidenceCapture(blobs, ledger), owner, "x", "secret")
    tool = EvidenceReadTool(
        blobs, ledger, freshness=EvidenceFreshness(ledger), owner_resolver=lambda: owner
    )
    result = tool.execute(evidence_ref=record.blob_ref.ref, range_type="text_char", start=0, limit=10)
    assert result.status is ToolResultStatus.FAILURE
    assert "blob://" not in result.content
    assert "secret" not in result.content


def test_recovery_tool_schemas_never_accept_owner_scope(tmp_path):
    blobs, ledger = _stores(tmp_path)
    owner = _owner()
    freshness = EvidenceFreshness(ledger)
    tools = [
        EvidenceReadTool(blobs, ledger, freshness=freshness, owner_resolver=lambda: owner),
        EvidenceListTool(ledger, freshness=freshness, owner_resolver=lambda: owner),
        EvidenceSearchTool(
            EvidenceSearch(blobs, ledger), freshness=freshness, owner_resolver=lambda: owner
        ),
    ]
    forbidden = {"owner", "workspace", "workspace_id", "session", "session_id"}
    for tool in tools:
        props = set(tool.parameters.get("properties", {}))
        assert forbidden.isdisjoint(props), (tool.name, props)
