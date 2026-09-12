"""SMC-CONTRACT-v0.1 observational conformance probes.

These probes deliberately do NOT modify the SMX implementation to make the matrix green.
`PASS` means the current implementation satisfies the probed contract behavior.
`GAP` means the contract requires a capability/wire fact that the current pre-contract
implementation does not yet expose.  The pytest suite itself should stay green while it
truthfully locks the current PASS/GAP matrix.

R1: P0-P8 — SMX Domain-0 implementation probes.
R2: L1-L5 — existing LFL file/Evidence mechanisms used only as cross-domain precedents.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.core.run_context import (
    current_model_label,
    current_session_id,
    current_workspace_root,
)
from llm_loop.memory.evidence import (
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceFreshness,
    EvidenceLedgerStore,
    OwnerScope,
    ProjectionEngine,
    Provenance,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
)
from llm_loop.memory.synopsis import SourceSnapshot, SynopsisStore
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.builtin.smx_perceive import SmxPerceiveTool
from llm_loop.tools.builtin.source_synopsis import SourceSynopsisTool
from llm_loop.tools.evidence_enforce import EvidenceEnforcer
from llm_loop.tools.evidence_tools import EvidenceReadTool
from llm_loop.tools.registry import ToolRegistry
from llm_loop.workspace.artifacts import WorkspaceArtifactStore
from llm_loop.workspace.file_effects import FileArtifactProvenance
from llm_loop.workspace.file_service import FileService, FileServiceError

ROOT = Path(__file__).resolve().parents[2]
SMX_PATH = ROOT / "tools" / "smx" / "smx.py"


@dataclass(frozen=True)
class ProbeResult:
    probe_id: str
    status: str
    summary: str
    facts: dict[str, object]


EXPECTED_MATRIX = {
    "P0": "GAP",
    "P1": "PASS",
    "P2": "GAP",
    "P3": "PASS",
    "P4": "GAP",
    "P5": "GAP",
    "P6": "PASS",
    "P7": "GAP",
    "P8": "GAP",
    "L1": "PASS",
    "L2": "PASS",
    "L3": "PASS",
    "L4": "PASS",
    "L5": "PASS",
}


def _json_result(result) -> dict:
    assert result.status is ToolResultStatus.SUCCESS, result.content
    return json.loads(result.content)


def _smx_tool(tmp_path: Path) -> SmxPerceiveTool:
    return SmxPerceiveTool(
        smx_path=str(SMX_PATH),
        data_dir=str(tmp_path / "smx-data"),
        max_wait_s=3.0,
    )


def _snapshot(tool: SmxPerceiveTool, root: Path, *, budget: int = 5000) -> dict:
    return _json_result(
        tool.execute(action="snapshot", roots=[str(root)], depth=2, budget=budget)
    )


def _all_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys |= _all_keys(child)
    elif isinstance(value, list):
        for child in value:
            keys |= _all_keys(child)
    return keys


def probe_p0(tmp_path: Path) -> ProbeResult:
    tool = _smx_tool(tmp_path)
    work = tmp_path / "p0"
    work.mkdir()
    payload = _snapshot(tool, work)

    provider_keys = _all_keys(tool.parameters)
    banned_strategy_keys = {
        "recommended_action",
        "best_candidate",
        "priority",
        "completion",
        "command",
        "cmd",
        "exec",
    }
    assert provider_keys.isdisjoint(banned_strategy_keys)
    assert set(tool.parameters["properties"]["action"]["enum"]) == {
        "wait",
        "snapshot",
        "diff",
        "receipt",
    }

    canonical_snapshot_wire = (
        payload.get("schema") == "smc.world_snapshot.v0.1"
        and payload.get("domain") == "shell"
        and "scope" in payload
        and "completeness" in payload
        and "grounding_version" in payload
    )
    assert canonical_snapshot_wire is False
    return ProbeResult(
        "P0",
        "GAP",
        "Provider surface has no hidden command/strategy channel, but current output is pre-SMC wire.",
        {
            "structural_lint": "PASS",
            "actions": ["wait", "snapshot", "diff", "receipt"],
            "canonical_snapshot_wire": False,
        },
    )


def probe_p1(tmp_path: Path) -> ProbeResult:
    tool = _smx_tool(tmp_path)
    work = tmp_path / "p1"
    work.mkdir()
    delete_me = work / "delete.txt"
    change_me = work / "change.txt"
    delete_me.write_text("delete", encoding="utf-8")
    change_me.write_text("old", encoding="utf-8")
    before = _snapshot(tool, work)

    delete_me.unlink()
    change_me.write_text("new-longer-value", encoding="utf-8")
    (work / "created.txt").write_text("new", encoding="utf-8")
    after = _snapshot(tool, work)
    diff = _json_result(
        tool.execute(
            action="diff",
            since=before["snapshot_id"],
            current=after["snapshot_id"],
        )
    )

    rows = diff["display_rows"]
    assert diff["diff_complete"] is True
    assert diff["created"] >= 1
    assert diff["deleted"] >= 1
    assert diff["modified"] >= 1
    assert any(row.startswith("+") and "created.txt" in row for row in rows)
    assert any(row.startswith("-") and "delete.txt" in row for row in rows)
    assert any(row.startswith("~") and "change.txt" in row for row in rows)
    return ProbeResult(
        "P1",
        "PASS",
        "Complete comparable snapshots preserve positive create/delete/change facts.",
        {"diff_complete": True, "create_delete_modify_observed": True},
    )


def probe_p2(tmp_path: Path) -> ProbeResult:
    tool = _smx_tool(tmp_path)
    work = tmp_path / "p2"
    work.mkdir()
    for idx in range(110):
        (work / f"f{idx:03d}.txt").write_text("x", encoding="utf-8")
    full = _snapshot(tool, work, budget=5000)
    truncated = _snapshot(tool, work, budget=100)
    diff = _json_result(
        tool.execute(
            action="diff",
            since=full["snapshot_id"],
            current=truncated["snapshot_id"],
        )
    )

    assert diff["diff_complete"] is False
    assert diff["created"] is None
    assert diff["deleted"] is None
    assert diff["total_changes"] is None
    assert not any(str(row).startswith(("+", "-")) for row in diff["display_rows"])
    assert isinstance(diff["modified"], int)
    assert "field_completeness" not in diff
    return ProbeResult(
        "P2",
        "GAP",
        "False +/- facts are suppressed, but modified is an unlabeled lower-bound count.",
        {
            "created_deleted_unknown": True,
            "false_plus_minus_suppressed": True,
            "modified_has_field_completeness": False,
        },
    )


def probe_p3(tmp_path: Path) -> ProbeResult:
    tool = _smx_tool(tmp_path)

    missing = _snapshot(tool, tmp_path / "does-not-exist")
    missing_meta = missing["roots_meta"][0]
    assert missing_meta["note"] == "not_found"

    crowded = tmp_path / "p3-crowded"
    crowded.mkdir()
    for idx in range(110):
        (crowded / f"f{idx:03d}").write_text("x", encoding="utf-8")
    crowded_snap = _snapshot(tool, crowded, budget=100)
    assert any(row.get("truncated") for row in crowded_snap["roots_meta"])

    denied = tmp_path / "p3-denied"
    denied.mkdir()
    (denied / "child").write_text("x", encoding="utf-8")
    mod = tool._load_smx()  # noqa: SLF001 - conformance probe inspects frozen sensor behavior
    original_scandir = mod.os.scandir

    def denied_scandir(path):
        if os.fspath(path) == str(denied):
            raise PermissionError(13, "permission denied", str(denied))
        return original_scandir(path)

    mod.os.scandir = denied_scandir
    try:
        denied_snap = _snapshot(tool, denied)
    finally:
        mod.os.scandir = original_scandir
    denied_meta = denied_snap["roots_meta"][0]
    assert denied_meta.get("walk_errors")

    return ProbeResult(
        "P3",
        "PASS",
        "Missing roots, budget truncation and traversal errors are surfaced instead of silent empty sets.",
        {
            "not_found_visible": True,
            "truncation_visible": True,
            "walk_error_visible": True,
        },
    )


def probe_p4(tmp_path: Path) -> ProbeResult:
    tool = _smx_tool(tmp_path)
    existing = tmp_path / "exists.flag"
    existing.write_text("ok", encoding="utf-8")
    satisfied = _json_result(
        tool.execute(action="wait", file_exists=str(existing), timeout=0.5, interval=0.1)
    )
    assert satisfied["satisfied"] is True

    timeout_result = _json_result(
        tool.execute(
            action="wait",
            file_exists=str(tmp_path / "never.flag"),
            timeout=0.5,
            interval=0.1,
        )
    )
    assert timeout_result["satisfied"] is False

    denied = tool.execute(action="wait", port_open=80, host="example.com", timeout=0.5)
    assert denied.status is ToolResultStatus.FAILURE

    # Observer error is currently folded into ordinary false/timeout.
    directory = tmp_path / "not-a-file"
    directory.mkdir()
    observer_error = _json_result(
        tool.execute(
            action="wait",
            file_contains=[str(directory), "needle"],
            timeout=0.5,
            interval=0.1,
        )
    )
    assert observer_error["satisfied"] is False
    assert "读取失败" in observer_error["detail"]

    # Partial coverage is also currently folded into false: needle is beyond FC_CAP.
    cap = int(tool._load_smx().FC_CAP)  # noqa: SLF001
    capped_file = tmp_path / "capped.bin"
    with capped_file.open("wb") as fh:
        fh.write(b"A" * cap)
        fh.write(b"NEEDLE_AFTER_CAP")
    capped = _json_result(
        tool.execute(
            action="wait",
            file_contains=[str(capped_file), "NEEDLE_AFTER_CAP"],
            timeout=0.5,
            interval=0.1,
        )
    )
    assert capped["satisfied"] is False
    assert "capped" in capped["detail"]

    sampling_keys = {"evaluation_mode", "interval", "sample_count", "observer_error_count"}
    assert sampling_keys.isdisjoint(timeout_result)
    return ProbeResult(
        "P4",
        "GAP",
        "Wait works mechanically, but tri-state observer errors, capped-negative honesty and sampling facts are missing.",
        {
            "satisfied_path": True,
            "timeout_is_observation": True,
            "nonloopback_rejected": True,
            "observer_error_is_indeterminate": False,
            "partial_negative_is_indeterminate": False,
            "sampling_facts_visible": False,
        },
    )


def probe_p5(tmp_path: Path) -> ProbeResult:
    tool = _smx_tool(tmp_path)
    work = tmp_path / "p5"
    work.mkdir()
    snap = _snapshot(tool, work)
    stored = Path(snap["store_path"])
    assert stored.is_file()
    loaded = json.loads(stored.read_text(encoding="utf-8"))
    assert loaded["snapshot_id"] == snap["snapshot_id"]
    assert tool._load_snap(snap["snapshot_id"])["snapshot_id"] == snap["snapshot_id"]  # noqa: SLF001

    integrity_keys = {"content_sha256", "snapshot_sha256", "blob_sha256", "grounding_version"}
    has_integrity_token = bool(integrity_keys & set(snap)) or bool(integrity_keys & set(loaded))
    assert has_integrity_token is False
    return ProbeResult(
        "P5",
        "GAP",
        "Snapshot IDs hydrate to stored observations, but the model-facing snapshot has no independent content-integrity token.",
        {"hydration_reachable": True, "content_integrity_token": False},
    )


def _run_smx_cli(*args: str, cwd: Path | None = None) -> dict:
    cp = subprocess.run(
        [sys.executable, str(SMX_PATH), *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert cp.stdout.strip(), (cp.returncode, cp.stderr)
    return json.loads(cp.stdout)


def probe_p6(tmp_path: Path) -> ProbeResult:
    root = tmp_path / "p6"
    root.mkdir()
    launched = _run_smx_cli("bg", "sleep 1.2", "--root", str(root), "--json")
    run_id = launched["run_id"]
    running = _run_smx_cli("collect", run_id, "--root", str(root), "--json")
    assert running["running"] is True
    assert "diff" not in running
    assert "未取 diff" in running["note"]
    # Allow the short-lived child to exit so the probe leaves no long-running process behind.
    time.sleep(1.3)
    return ProbeResult(
        "P6",
        "PASS",
        "CLI collect does not present a running background operation as terminal diff/completion.",
        {"running_explicit": True, "terminal_diff_absent": True},
    )


def probe_p7(tmp_path: Path) -> ProbeResult:
    tool = _smx_tool(tmp_path)
    left = tmp_path / "p7-left"
    right = tmp_path / "p7-right"
    left.mkdir()
    right.mkdir()
    (left / "left.txt").write_text("left", encoding="utf-8")
    (right / "right.txt").write_text("right", encoding="utf-8")
    s_left = _snapshot(tool, left)
    s_right = _snapshot(tool, right)
    diff = _json_result(
        tool.execute(
            action="diff",
            since=s_left["snapshot_id"],
            current=s_right["snapshot_id"],
        )
    )
    assert diff["diff_complete"] is True
    assert diff["created"] >= 1 and diff["deleted"] >= 1
    assert "comparable" not in diff and "scope_relation" not in diff
    return ProbeResult(
        "P7",
        "GAP",
        "Diff accepts snapshots from different roots without a comparability/scope-relation guard.",
        {"scope_comparability_visible": False, "different_roots_diffed_as_changes": True},
    )


def probe_p8(tmp_path: Path) -> ProbeResult:
    root = tmp_path / "p8"
    root.mkdir()
    for idx in range(110):
        (root / f"f{idx:03d}.txt").write_text("x", encoding="utf-8")
    raw = _run_smx_cli(
        "exec",
        "true",
        "--root",
        str(root),
        "--budget",
        "100",
        "--json",
    )
    assert raw["scope"]["truncated_any"] is True
    assert isinstance(raw["diff"]["counts"]["created"], int)
    assert isinstance(raw["diff"]["counts"]["deleted"], int)

    tool = _smx_tool(tmp_path)
    hydrated = _json_result(
        tool.execute(action="receipt", run_id=raw["run_id"], root=str(root), full=True)
    )
    assert hydrated["scope"]["truncated_any"] is True
    assert "canonical" not in hydrated["diff"]
    assert isinstance(hydrated["diff"]["counts"]["created"], int)
    return ProbeResult(
        "P8",
        "GAP",
        "full=true hydrates raw CLI diff/counts without canonical=false separation under truncation.",
        {"raw_hydration_reachable": True, "canonical_false_marker": False},
    )


def _evidence_owner(tmp_path: Path) -> OwnerScope:
    return OwnerScope(workspace_id=str(tmp_path), session_id="smc-session")


def _capture_runtime_evidence(tmp_path: Path, content: str):
    blobs = BlobStore(tmp_path / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "evidence" / "ledger")
    owner = _evidence_owner(tmp_path)
    captured = EvidenceCapture(blobs, ledger).capture(
        make_capture_request(
            owner=owner,
            stable_capture_id="smc-runtime-capture",
            raw_observation=content,
            acquired_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
            tool_name="runtime_snapshot",
            tool_call_id="smc-runtime-capture",
            source=SourceIdentity(
                kind=SourceKind.RUNTIME_SNAPSHOT,
                locator="runtime:smc",
                version_policy=SourceVersionPolicy.VERSIONED,
            ),
            coverage=Coverage(
                unit="observation", start=0, end_exclusive=None, source_complete=True
            ),
            provenance=Provenance(producer="smc-conformance"),
        )
    )
    return blobs, ledger, owner, captured.evidence_ref


def probe_l1(tmp_path: Path) -> ProbeResult:
    content = "abcdef" * 100
    blobs, ledger, owner, ref = _capture_runtime_evidence(tmp_path, content)
    tool = EvidenceReadTool(
        blobs,
        ledger,
        freshness=EvidenceFreshness(ledger),
        owner_resolver=lambda: owner,
    )
    result = tool.execute(evidence_ref=ref.ref, range_type="text_char", start=10, limit=50)
    assert result.status is ToolResultStatus.SUCCESS
    payload = json.loads(result.content)
    assert payload["content"] == content[10:60]
    assert payload["range"]["complete"] is False
    assert payload["range"]["next_start"] == 60
    assert payload["integrity"]["blob_sha256"]
    assert payload["integrity"]["range_sha256"] == hashlib.sha256(
        content[10:60].encode("utf-8")
    ).hexdigest()
    return ProbeResult(
        "L1",
        "PASS",
        "EvidenceRef hydration is range-exact, paginated and integrity-addressed.",
        {"hydration": True, "blob_sha256": True, "range_sha256": True},
    )


def _file_service(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = WorkspaceArtifactStore(tmp_path / "file-data")
    service = FileService(artifact_store=store, lock_root=tmp_path / "file-data" / "locks")
    return service, store, workspace


def _file_provenance(workspace: Path) -> FileArtifactProvenance:
    return FileArtifactProvenance(
        workspace_scope=str(workspace),
        owner_session_id="smc-session",
        operation_id="smc-observe",
        tool_call_id="smc-observe",
        tool_name="read_file",
        effect_kind="file_observation",
    )


def probe_l2(tmp_path: Path) -> ProbeResult:
    service, _store, workspace = _file_service(tmp_path)
    path = workspace / "a.txt"
    path.write_bytes(b"AAAA\n")
    observed = service.observe(
        path=path,
        workspace_scope=str(workspace),
        provenance=_file_provenance(workspace),
    )
    stat = path.stat()
    path.write_bytes(b"BBBB\n")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    error_type = ""
    try:
        service.edit(
            path=path,
            old_string="AAAA",
            new_string="CCCC",
            workspace_scope=str(workspace),
            expected_snapshot_ref=observed.snapshot_ref,
        )
    except FileServiceError as exc:
        error_type = exc.error_type
    assert error_type == "VersionConflict"
    assert path.read_bytes() == b"BBBB\n"
    return ProbeResult(
        "L2",
        "PASS",
        "Immutable file snapshot preconditions reject stale full-byte state before write.",
        {"stale_rejected": True, "error_type": "VersionConflict", "no_overwrite": True},
    )


def _source_snapshot(ref: str, text: str) -> SourceSnapshot:
    return SourceSnapshot(
        source_ref=ref,
        source_kind="test",
        text=text,
        source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        source_chars=len(text),
        source_complete=True,
        representation="exact_test_text",
        access_scope="workspace",  # type: ignore[arg-type]
    )


def probe_l3(tmp_path: Path) -> ProbeResult:
    text = "source-line\n" * 200
    source = _source_snapshot("attachment://" + "a" * 32, text)
    store = SynopsisStore(tmp_path / "synopsis-data")
    tool = SourceSynopsisTool(store, lambda ref: source if ref == source.source_ref else None)  # type: ignore[arg-type]
    ws_token = current_workspace_root.set(str(tmp_path))
    sid_token = current_session_id.set("smc-session")
    model_token = current_model_label.set("provider/model")
    try:
        summary = "模型自己写的摘要；程序只保存，不判断其任务语义。"
        saved = tool.execute(action="save", source_ref=source.source_ref, summary=summary)
        assert saved.status is ToolResultStatus.SUCCESS
        payload = json.loads(saved.content)
        record = store.get(
            payload["synopsis_ref"],
            workspace_scope=str(tmp_path),
            session_id="smc-session",
        )
        assert record is not None
        assert record.summary == summary
        assert record.source_sha256 == source.source_sha256
        assert record.range_sha256 == source.source_sha256
        assert record.task_applicability == "not_evaluated"
    finally:
        current_model_label.reset(model_token)
        current_session_id.reset(sid_token)
        current_workspace_root.reset(ws_token)
    return ProbeResult(
        "L3",
        "PASS",
        "source_synopsis preserves model-authored summary verbatim and binds it to exact source SHA/range.",
        {"model_authored_verbatim": True, "source_bound": True, "task_applicability": "not_evaluated"},
    )


def _capture_file_evidence(tmp_path: Path):
    path = tmp_path / "l4-file.txt"
    path.write_text("ORIGINAL\n" + "x" * 200, encoding="utf-8")
    blobs = BlobStore(tmp_path / "l4-evidence" / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "l4-evidence" / "ledger")
    owner = _evidence_owner(tmp_path)
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
    result = registry.execute(
        ToolCall(id="smc-file-capture", name="read_file", arguments={"path": str(path)})
    )
    assert result.status is ToolResultStatus.SUCCESS
    assert result.evidence_ref
    return path, blobs, ledger, owner, result.evidence_ref


def probe_l4(tmp_path: Path) -> ProbeResult:
    path, blobs, ledger, owner, ref = _capture_file_evidence(tmp_path)
    path.write_text("CHANGED\n" + "y" * 200, encoding="utf-8")
    tool = EvidenceReadTool(
        blobs,
        ledger,
        freshness=EvidenceFreshness(ledger),
        owner_resolver=lambda: owner,
    )
    blocked = tool.execute(evidence_ref=ref, range_type="text_char", start=0, limit=4000)
    assert blocked.status is ToolResultStatus.FAILURE
    blocked_payload = json.loads(blocked.content)
    assert blocked_payload["freshness"]["state"] == "stale"
    assert blocked_payload["freshness"]["currentness"] == "historical_only"
    assert blocked_payload["freshness"]["task_applicability"] == "not_evaluated"
    assert blocked_payload["policy"]["historical_read_requires"] == "allow_stale=true"

    historical = tool.execute(
        evidence_ref=ref,
        range_type="text_char",
        start=0,
        limit=4000,
        allow_stale=True,
    )
    assert historical.status is ToolResultStatus.SUCCESS
    assert "ORIGINAL" in json.loads(historical.content)["content"]
    return ProbeResult(
        "L4",
        "PASS",
        "Evidence currentness is source-version scoped; stale history requires explicit allow_stale and task applicability stays model-owned.",
        {"stale_visible": True, "historical_opt_in": True, "task_applicability": "not_evaluated"},
    )


def probe_l5(tmp_path: Path) -> ProbeResult:
    content = "0123456789" * 100
    blobs, ledger, owner, ref = _capture_runtime_evidence(tmp_path, content)
    tool = EvidenceReadTool(
        blobs,
        ledger,
        freshness=EvidenceFreshness(ledger),
        owner_resolver=lambda: owner,
    )
    partial = tool.execute(evidence_ref=ref.ref, range_type="text_char", start=0, limit=37)
    assert partial.status is ToolResultStatus.SUCCESS
    partial_payload = json.loads(partial.content)
    assert partial_payload["range"]["complete"] is False
    assert partial_payload["range"]["next_start"] == 37

    unavailable = tool.execute(
        evidence_ref="evidence://v1/" + "f" * 64,
        range_type="text_char",
        start=0,
        limit=37,
    )
    assert unavailable.status is ToolResultStatus.FAILURE
    assert "Evidence 不可用" in unavailable.content
    return ProbeResult(
        "L5",
        "PASS",
        "Hydration truncation has an explicit continuation cursor and unavailable refs fail explicitly.",
        {"partial_visible": True, "next_start": 37, "unavailable_explicit": True},
    )


PROBES = {
    "P0": probe_p0,
    "P1": probe_p1,
    "P2": probe_p2,
    "P3": probe_p3,
    "P4": probe_p4,
    "P5": probe_p5,
    "P6": probe_p6,
    "P7": probe_p7,
    "P8": probe_p8,
    "L1": probe_l1,
    "L2": probe_l2,
    "L3": probe_l3,
    "L4": probe_l4,
    "L5": probe_l5,
}


@pytest.mark.parametrize("probe_id", list(EXPECTED_MATRIX))
def test_smc_contract_v01_current_conformance(probe_id: str, tmp_path: Path) -> None:
    probe_root = tmp_path / probe_id.lower()
    probe_root.mkdir(parents=True, exist_ok=True)
    result = PROBES[probe_id](probe_root)
    assert result.probe_id == probe_id
    assert result.status == EXPECTED_MATRIX[probe_id], asdict(result)


def test_smc_contract_v01_matrix_is_complete(tmp_path: Path, capsys) -> None:
    results = []
    for probe_id, probe in PROBES.items():
        probe_root = tmp_path / f"matrix-{probe_id.lower()}"
        probe_root.mkdir(parents=True, exist_ok=True)
        result = probe(probe_root)
        assert result.status == EXPECTED_MATRIX[probe_id], asdict(result)
        results.append(asdict(result))
    print(json.dumps({"schema": "smc_conformance_probe_v0.1", "results": results}, ensure_ascii=False, sort_keys=True))
    captured = capsys.readouterr()
    assert '"P8"' in captured.out and '"L5"' in captured.out
