from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.memory.evidence import (
    BlobStore,
    EvidenceCapture,
    EvidenceFreshness,
    EvidenceLedgerStore,
    EvidenceSearch,
    OwnerScope,
    ProjectionEngine,
)
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.evidence_enforce import EvidenceEnforcer
from llm_loop.tools.evidence_source_resolver import EvidenceSourceResolver
from llm_loop.tools.evidence_tools import EvidenceSearchTool
from llm_loop.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data/audit/evidence_r9/r8_overlap_counterfactual_v1.json"
RUN_IDS = ("R8-006", "R8-011")


def replay(run_id: str) -> dict:
    source_row_path = ROOT / f"data/audit/evidence_r8/real_runs_v1/{run_id}.json"
    historical = json.loads(source_row_path.read_text())
    source_calls = [t for t in historical["trace"] if t["tool"] == "read_file"]
    search_calls = [t for t in historical["trace"] if t["tool"] == "search_evidence"]
    assert len(source_calls) == 2 and len(search_calls) == 1
    source_path = Path(source_calls[0]["arguments"]["path"])
    assert source_path.exists(), source_path

    run_dir = ROOT / f"data/audit/evidence_r9/r8_counterfactual/{run_id}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    blobs = BlobStore(run_dir / "blobs")
    ledger = EvidenceLedgerStore(run_dir / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    freshness = EvidenceFreshness(ledger)
    owner = OwnerScope(workspace_id=str(ROOT), session_id=f"r9-counterfactual-{run_id}")
    registry = ToolRegistry(
        summary_threshold=900, max_output_chars=100000, failure_guidance_enabled=False
    )
    registry.register(ReadFileTool())
    registry.set_evidence_enforcer(
        EvidenceEnforcer(
            capture,
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            projection_budget_chars=900,
        )
    )
    registry.set_evidence_source_resolver(
        EvidenceSourceResolver(ledger, freshness=freshness, owner_resolver=lambda: owner)
    )
    registry.register(
        EvidenceSearchTool(
            EvidenceSearch(blobs, ledger, snippet_chars=500),
            freshness=freshness,
            owner_resolver=lambda: owner,
        )
    )

    first = registry.execute(
        ToolCall(id=f"{run_id}-r1", name="read_file", arguments=source_calls[0]["arguments"])
    )
    assert first.status is ToolResultStatus.SUCCESS
    batch = registry.execute_many(
        [
            ToolCall(
                id=f"{run_id}-search",
                name="search_evidence",
                arguments=search_calls[0]["arguments"],
            ),
            ToolCall(
                id=f"{run_id}-fallback", name="read_file", arguments=source_calls[1]["arguments"]
            ),
        ]
    )
    search, fallback = batch
    return {
        "run_id": run_id,
        "input_row_sha256": hashlib.sha256(source_row_path.read_bytes()).hexdigest(),
        "provider": historical["provider"],
        "seed_id": historical["seed_id"],
        "historical_declared_read_file_count": historical["model_source_attempt_count"],
        "historical_physical_read_proxy": historical["model_source_execution_count"],
        "historical_overlap_count": historical["redundant_overlap_count"],
        "r9_first_mode": first.source_resolution_mode,
        "r9_search_status": search.status.value,
        "r9_search_target_hit": "CORAL-286" in search.content,
        "r9_fallback_status": fallback.status.value,
        "r9_fallback_mode": fallback.source_resolution_mode,
        "r9_fallback_source_execution": fallback.source_execution_performed,
        "r9_fallback_same_ref": fallback.evidence_ref == first.evidence_ref,
        "r9_physical_source_execution_count": int(first.source_execution_performed is True)
        + int(fallback.source_execution_performed is True),
        "r9_evidence_reuse_count": int(first.source_execution_performed is False)
        + int(fallback.source_execution_performed is False),
        "r9_ledger_count": ledger.count(owner),
    }


def main() -> int:
    rows = [replay(run_id) for run_id in RUN_IDS]
    payload = {
        "schema": "evidence-r9-r8-overlap-counterfactual-v1",
        "count": len(rows),
        "rows": rows,
        "pass": all(
            r["r9_search_target_hit"]
            and r["r9_fallback_mode"] == "evidence_reuse"
            and r["r9_fallback_source_execution"] is False
            and r["r9_fallback_same_ref"]
            and r["r9_physical_source_execution_count"] == 1
            and r["r9_evidence_reuse_count"] == 1
            and r["r9_ledger_count"] == 1
            for r in rows
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
