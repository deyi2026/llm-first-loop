from __future__ import annotations

from datetime import UTC, datetime

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.memory.evidence import (
    BlobStore,
    EvidenceCapture,
    EvidenceHydration,
    EvidenceLedgerStore,
    ManifestProjector,
    OwnerScope,
    RangeType,
)
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.evidence_shadow import EvidenceShadowRecorder
from llm_loop.tools.registry import ToolRegistry


def _owner() -> OwnerScope:
    return OwnerScope(workspace_id="workspace-A", session_id="session-A")


def _stores(tmp_path):
    blobs = BlobStore(tmp_path / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "evidence" / "ledger")
    return blobs, ledger


def test_shadow_captures_pretrim_read_file_without_changing_visible_result(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "legacy-data"))
    path = tmp_path / "large.txt"
    middle_marker = "MIDDLE_EVIDENCE_MARKER_42"
    path.write_text("A" * 5000 + middle_marker + "Z" * 5000, encoding="utf-8")

    # Legacy result is our control: no shadow hook, no extra raw observation retained.
    control_registry = ToolRegistry()
    control_registry.register(ReadFileTool())
    control = control_registry.execute(
        ToolCall(id="control-call", name="read_file", arguments={"path": str(path)})
    )
    assert control.raw_observation is None
    assert middle_marker in control.content

    blobs, ledger = _stores(tmp_path)
    recorder = EvidenceShadowRecorder(
        EvidenceCapture(blobs, ledger),
        owner_resolver=_owner,
        clock=lambda: datetime(2026, 8, 26, 7, 0, tzinfo=UTC),
    )
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.set_evidence_shadow_hook(recorder)
    shadow = registry.execute(
        ToolCall(id="shadow-call", name="read_file", arguments={"path": str(path)})
    )

    # Shadow must not alter any model-visible legacy bytes.
    assert shadow.content == control.content
    assert middle_marker in shadow.content

    manifest = ManifestProjector(ledger).build_recent(owner=_owner(), limit=10)
    assert len(manifest.entries) == 1
    evidence_ref = manifest.entries[0].evidence_ref
    hydrated = EvidenceHydration(blobs, ledger, max_limit=20000).read(
        owner=_owner(),
        evidence_ref=evidence_ref,
        range_type=RangeType.TEXT_CHAR,
        start=0,
        limit=20000,
    )
    assert middle_marker in hydrated.content
    assert hydrated.content.startswith(f"[read_file] {path}")


def test_shadow_field_never_enters_tool_message_wire():
    result = ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="visible",
        raw_observation="PRIVATE_RAW_ONLY",
        tool_call_id="c1",
        tool_name="x",
    )
    message = result.to_message()
    wire = message.to_llm_dict()
    assert "PRIVATE_RAW_ONLY" not in str(wire)
    assert wire["content"] == "[状态: success] visible"


def test_shadow_hook_failure_preserves_action_truth_and_content():
    class Tool:
        name = "shadow_test_tool"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **_kwargs):
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="ACTION_ALREADY_SUCCEEDED",
                raw_observation="RAW",
                tool_call_id="",
                tool_name=self.name,
            )

    def broken_shadow(_call, _result):
        raise OSError("shadow disk unavailable")

    registry = ToolRegistry()
    registry.register(Tool())
    registry.set_evidence_shadow_hook(broken_shadow)
    result = registry.execute(ToolCall(id="c1", name=Tool.name, arguments={}))

    assert result.status is ToolResultStatus.SUCCESS
    assert result.content == "ACTION_ALREADY_SUCCEEDED"
    assert result.tool_call_id == "c1"


def test_removing_shadow_hook_restores_no_raw_retention(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "legacy-data"))
    path = tmp_path / "large.txt"
    path.write_text("X" * 8000, encoding="utf-8")
    blobs, ledger = _stores(tmp_path)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.set_evidence_shadow_hook(
        EvidenceShadowRecorder(
            EvidenceCapture(blobs, ledger),
            owner_resolver=_owner,
            clock=lambda: datetime(2026, 8, 26, 7, 0, tzinfo=UTC),
        )
    )
    first = registry.execute(ToolCall(id="c1", name="read_file", arguments={"path": str(path)}))
    assert first.raw_observation is not None

    registry.set_evidence_shadow_hook(None)
    second = registry.execute(ToolCall(id="c2", name="read_file", arguments={"path": str(path)}))
    assert second.raw_observation is None
    assert ledger.count(_owner()) == 1
