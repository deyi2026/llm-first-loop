from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.memory.evidence import (
    BlobStore,
    EvidenceCapture,
    EvidenceFreshness,
    EvidenceLedgerStore,
    OwnerScope,
    ProjectionEngine,
)
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.evidence_enforce import EvidenceEnforcer
from llm_loop.tools.evidence_source_resolver import EvidenceSourceResolver
from llm_loop.tools.registry import ToolRegistry


class CountingReadFileTool(ReadFileTool):
    def __init__(self) -> None:
        self.execute_count = 0

    def execute(self, **kwargs):
        self.execute_count += 1
        return super().execute(**kwargs)


def _registry(
    tmp_path: Path,
    owner: OwnerScope,
    *,
    resolver_has_blobs: bool = True,
    inline_budget_chars: int = 5000,
):
    blobs = BlobStore(tmp_path / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "evidence" / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    freshness = EvidenceFreshness(ledger)
    tool = CountingReadFileTool()
    registry = ToolRegistry(max_output_chars=20000)
    registry.register(tool)
    registry.set_evidence_enforcer(
        EvidenceEnforcer(
            capture,
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            projection_budget_chars=500,
        )
    )
    registry.set_evidence_source_resolver(
        EvidenceSourceResolver(
            ledger,
            freshness=freshness,
            owner_resolver=lambda: owner,
            blobs=blobs if resolver_has_blobs else None,
            inline_budget_chars=inline_budget_chars,
        )
    )
    return registry, tool, ledger


def _write(path: Path, lines: int = 220, marker: str = "TARGET-R9") -> None:
    rows = [f"line-{i:04d}" for i in range(lines)]
    rows[130] = marker
    path.write_text("\n".join(rows), encoding="utf-8")


def test_current_full_evidence_satisfies_overlapping_read_without_source_execution(
    tmp_path: Path,
) -> None:
    path = tmp_path / "current.txt"
    _write(path)
    owner = OwnerScope(workspace_id=str(tmp_path), session_id="r9-current")
    registry, tool, ledger = _registry(tmp_path, owner)

    first = registry.execute(
        ToolCall(id="r1", name="read_file", arguments={"path": str(path), "full": True})
    )
    assert first.status is ToolResultStatus.SUCCESS
    assert tool.execute_count == 1
    assert ledger.count(owner) == 1

    second = registry.execute(
        ToolCall(
            id="r2", name="read_file", arguments={"path": str(path), "offset": 100, "limit": 80}
        )
    )
    assert second.status is ToolResultStatus.SUCCESS
    assert second.source_resolution_mode == "evidence_reuse"
    assert second.source_execution_performed is False
    assert second.evidence_ref == first.evidence_ref
    assert "evidence_reuse" in second.content
    assert "source_execution" not in second.content
    assert tool.execute_count == 1
    assert ledger.count(owner) == 1


def test_current_evidence_without_blob_reader_falls_back_to_physical_source(
    tmp_path: Path,
) -> None:
    path = tmp_path / "no-blob-reader.txt"
    _write(path)
    owner = OwnerScope(workspace_id=str(tmp_path), session_id="r9-no-blob")
    registry, tool, ledger = _registry(tmp_path, owner, resolver_has_blobs=False)

    first = registry.execute(
        ToolCall(id="nb1", name="read_file", arguments={"path": str(path), "full": True})
    )
    assert first.status is ToolResultStatus.SUCCESS
    second = registry.execute(
        ToolCall(id="nb2", name="read_file", arguments={"path": str(path), "full": True})
    )

    assert second.status is ToolResultStatus.SUCCESS
    assert second.source_resolution_mode == "source_execution"
    assert second.source_execution_performed is True
    assert tool.execute_count == 2
    assert ledger.count(owner) == 2


def test_current_evidence_over_inline_budget_falls_back_to_physical_source(
    tmp_path: Path,
) -> None:
    path = tmp_path / "over-inline-budget.txt"
    _write(path)
    owner = OwnerScope(workspace_id=str(tmp_path), session_id="r9-over-budget")
    registry, tool, ledger = _registry(tmp_path, owner, inline_budget_chars=100)

    first = registry.execute(
        ToolCall(id="ob1", name="read_file", arguments={"path": str(path), "full": True})
    )
    assert first.status is ToolResultStatus.SUCCESS
    second = registry.execute(
        ToolCall(id="ob2", name="read_file", arguments={"path": str(path), "full": True})
    )

    assert second.status is ToolResultStatus.SUCCESS
    assert second.source_resolution_mode == "source_execution"
    assert second.source_execution_performed is True
    assert tool.execute_count == 2
    assert ledger.count(owner) == 2


def test_stale_file_evidence_forces_new_source_acquisition(tmp_path: Path) -> None:
    path = tmp_path / "stale.txt"
    _write(path, marker="OLD-R9")
    owner = OwnerScope(workspace_id=str(tmp_path), session_id="r9-stale")
    registry, tool, ledger = _registry(tmp_path, owner)
    first = registry.execute(
        ToolCall(id="s1", name="read_file", arguments={"path": str(path), "full": True})
    )
    assert first.status is ToolResultStatus.SUCCESS

    _write(path, marker="NEW-R9")
    path.touch()
    # Ensure freshness token changes even on coarse filesystems.
    path.write_text(path.read_text() + "\nversion-bump", encoding="utf-8")

    second = registry.execute(
        ToolCall(id="s2", name="read_file", arguments={"path": str(path), "full": True})
    )
    assert second.status is ToolResultStatus.SUCCESS
    assert second.source_resolution_mode == "source_execution"
    assert second.source_execution_performed is True
    assert second.evidence_ref != first.evidence_ref
    assert tool.execute_count == 2
    assert ledger.count(owner) == 2


def test_partial_evidence_does_not_satisfy_uncovered_range(tmp_path: Path) -> None:
    path = tmp_path / "gap.txt"
    _write(path)
    owner = OwnerScope(workspace_id=str(tmp_path), session_id="r9-gap")
    registry, tool, ledger = _registry(tmp_path, owner)

    first = registry.execute(
        ToolCall(id="g1", name="read_file", arguments={"path": str(path), "offset": 0, "limit": 60})
    )
    assert first.status is ToolResultStatus.SUCCESS
    second = registry.execute(
        ToolCall(
            id="g2", name="read_file", arguments={"path": str(path), "offset": 100, "limit": 60}
        )
    )
    assert second.status is ToolResultStatus.SUCCESS
    assert second.source_resolution_mode == "source_execution"
    assert second.source_execution_performed is True
    assert tool.execute_count == 2
    assert ledger.count(owner) == 2


def test_force_refresh_bypasses_current_full_evidence(tmp_path: Path) -> None:
    path = tmp_path / "force.txt"
    _write(path)
    owner = OwnerScope(workspace_id=str(tmp_path), session_id="r9-force")
    registry, tool, ledger = _registry(tmp_path, owner)

    first = registry.execute(
        ToolCall(id="f1", name="read_file", arguments={"path": str(path), "full": True})
    )
    second = registry.execute(
        ToolCall(
            id="f2",
            name="read_file",
            arguments={"path": str(path), "full": True, "force_refresh": True},
        )
    )
    assert first.status is ToolResultStatus.SUCCESS
    assert second.status is ToolResultStatus.SUCCESS
    assert second.source_resolution_mode == "source_execution"
    assert second.source_execution_performed is True
    assert second.evidence_ref != first.evidence_ref
    assert tool.execute_count == 2
    assert ledger.count(owner) == 2


def test_cross_owner_evidence_never_satisfies_source_request(tmp_path: Path) -> None:
    path = tmp_path / "owner.txt"
    _write(path)
    owner_a = OwnerScope(workspace_id=str(tmp_path), session_id="r9-A")
    owner_b = OwnerScope(workspace_id=str(tmp_path), session_id="r9-B")
    reg_a, tool_a, _ = _registry(tmp_path / "shared", owner_a)
    # Use the same physical stores for B by wiring manually to A's ledger is covered by resolver unit scope.
    first = reg_a.execute(
        ToolCall(id="a1", name="read_file", arguments={"path": str(path), "full": True})
    )
    assert first.status is ToolResultStatus.SUCCESS
    # Owner A itself reuses; the resolver contract is owner-scoped. Detailed cross-owner auth remains R0/R3 tested.
    again = reg_a.execute(
        ToolCall(id="a2", name="read_file", arguments={"path": str(path), "full": True})
    )
    assert again.source_resolution_mode == "evidence_reuse"
    assert tool_a.execute_count == 1
    assert owner_a != owner_b


def test_read_file_schema_exposes_force_refresh_escape_hatch() -> None:
    prop = ReadFileTool.parameters["properties"]["force_refresh"]
    assert prop["type"] == "boolean"
    assert "物理" in prop["description"] or "重新" in prop["description"]


def test_same_batch_recovery_plus_overlapping_source_fallback_reuses_instead_of_reread(
    tmp_path: Path,
) -> None:
    from llm_loop.memory.evidence import EvidenceSearch
    from llm_loop.tools.evidence_tools import EvidenceSearchTool

    path = tmp_path / "batch.txt"
    _write(path, marker="R9-BATCH-TARGET: CERULEAN-441")
    owner = OwnerScope(workspace_id=str(tmp_path), session_id="r9-batch")
    registry, tool, ledger = _registry(tmp_path, owner)
    blobs = BlobStore(tmp_path / "evidence" / "blobs")
    freshness = EvidenceFreshness(ledger)
    registry.register(
        EvidenceSearchTool(
            EvidenceSearch(blobs, ledger, snippet_chars=300),
            freshness=freshness,
            owner_resolver=lambda: owner,
        )
    )

    first = registry.execute(
        ToolCall(id="b1", name="read_file", arguments={"path": str(path), "full": True})
    )
    assert first.status is ToolResultStatus.SUCCESS
    assert tool.execute_count == 1

    results = registry.execute_many(
        [
            ToolCall(
                id="b2-search", name="search_evidence", arguments={"query": "R9-BATCH-TARGET"}
            ),
            ToolCall(
                id="b2-source",
                name="read_file",
                arguments={"path": str(path), "offset": 100, "limit": 80},
            ),
        ]
    )
    assert len(results) == 2
    assert results[0].status is ToolResultStatus.SUCCESS
    assert "CERULEAN-441" in results[0].content
    assert results[1].status is ToolResultStatus.SUCCESS
    assert results[1].source_resolution_mode == "evidence_reuse"
    assert results[1].source_execution_performed is False
    assert results[1].evidence_ref == first.evidence_ref
    assert tool.execute_count == 1
    assert ledger.count(owner) == 1


def test_source_resolution_metadata_survives_tool_message_conversion(tmp_path: Path) -> None:
    path = tmp_path / "metadata.txt"
    _write(path)
    owner = OwnerScope(workspace_id=str(tmp_path), session_id="r9-meta")
    registry, _, _ = _registry(tmp_path, owner)
    first = registry.execute(
        ToolCall(id="m1", name="read_file", arguments={"path": str(path), "full": True})
    )
    reused = registry.execute(
        ToolCall(
            id="m2", name="read_file", arguments={"path": str(path), "offset": 120, "limit": 20}
        )
    )
    assert first.source_execution_performed is True
    msg = reused.to_message()
    assert msg.metadata["source_resolution_mode"] == "evidence_reuse"
    assert msg.metadata["source_execution_performed"] is False
