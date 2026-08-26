from __future__ import annotations

from datetime import UTC, datetime

import pytest

from llm_loop.config import Settings
from llm_loop.core.message import RecoverabilityStatus, ToolCall, ToolResult, ToolResultStatus
from llm_loop.memory.evidence import (
    BlobStore,
    EvidenceCapture,
    EvidenceHydration,
    EvidenceLedgerStore,
    EvidenceRef,
    OwnerScope,
    ProjectionEngine,
    RangeType,
)
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.evidence_enforce import EvidenceEnforcer
from llm_loop.tools.registry import ToolRegistry


def _owner() -> OwnerScope:
    return OwnerScope(workspace_id="workspace-A", session_id="session-A")


def _enforcer(tmp_path, *, projection_budget_chars: int = 900):
    blobs = BlobStore(tmp_path / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "evidence" / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    enforcer = EvidenceEnforcer(
        capture,
        projection=ProjectionEngine(),
        owner_resolver=_owner,
        clock=lambda: datetime(2026, 8, 26, 8, 0, tzinfo=UTC),
        projection_budget_chars=projection_budget_chars,
    )
    return blobs, ledger, enforcer


def test_hot_large_evidence_is_excerpt_not_forced_full():
    engine = ProjectionEngine()
    raw = "HEAD\n" + ("x" * 4000) + "\nTAIL"
    out = engine.project(
        raw,
        evidence_ref=EvidenceRef("evidence://v1/" + "a" * 64),
        source_label="read_file:src/large.py",
        coverage_label="source_line:0-?/source_complete",
        budget_chars=500,
        temperature="hot",
    )

    assert out.metadata.representation == "excerpt"
    assert out.metadata.projection_complete is False
    assert len(out.content) <= 500
    assert "HEAD" in out.content and "TAIL" in out.content
    assert "[evidence]" in out.model_capsule
    assert "recover=read_evidence" in out.model_capsule


def test_enforce_read_file_captures_before_projection_and_hydrates_hidden_middle(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "legacy-data"))
    path = tmp_path / "large.txt"
    marker = "MIDDLE_ONLY_IN_EVIDENCE_314159"
    path.write_text("A" * 6000 + marker + "Z" * 6000, encoding="utf-8")

    blobs, ledger, enforcer = _enforcer(tmp_path, projection_budget_chars=700)
    registry = ToolRegistry(summary_threshold=12000, max_output_chars=20000)
    registry.register(ReadFileTool())
    registry.set_evidence_enforcer(enforcer)

    result = registry.execute(
        ToolCall(id="enforce-read-1", name="read_file", arguments={"path": str(path)})
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert result.recoverability_status is RecoverabilityStatus.RECORDED
    assert result.evidence_ref is not None
    assert result.evidence_representation == "excerpt"
    assert result.evidence_projection_complete is False
    assert marker not in result.content
    assert "[输出已截断]" not in result.content
    assert "search_archive" not in result.content
    assert "[evidence]" in result.content
    assert "recover=read_evidence" in result.content

    hydrated = EvidenceHydration(blobs, ledger, max_limit=20000).read(
        owner=_owner(),
        evidence_ref=EvidenceRef(result.evidence_ref),
        range_type=RangeType.TEXT_CHAR,
        start=0,
        limit=20000,
    )
    assert marker in hydrated.content
    assert hydrated.content.startswith(f"[read_file] {path}")
    assert ledger.count(_owner()) == 1


def test_enforce_capture_failure_preserves_side_effect_action_truth_and_does_not_rerun(tmp_path):
    calls = {"count": 0}

    class SideEffectTool:
        name = "side_effect_test"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **_kwargs):
            calls["count"] += 1
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="ACTION_SUCCEEDED\n" + ("Q" * 5000),
                tool_call_id="",
                tool_name=self.name,
            )

    class BrokenCapture:
        def capture(self, _request):
            raise OSError("evidence disk unavailable")

    enforcer = EvidenceEnforcer(
        BrokenCapture(),  # type: ignore[arg-type]
        projection=ProjectionEngine(),
        owner_resolver=_owner,
        projection_budget_chars=500,
    )
    registry = ToolRegistry(max_output_chars=1000)
    registry.register(SideEffectTool())
    registry.set_evidence_enforcer(enforcer)

    result = registry.execute(ToolCall(id="side-1", name=SideEffectTool.name, arguments={}))

    assert calls["count"] == 1
    assert result.status is ToolResultStatus.SUCCESS
    assert result.recoverability_status is RecoverabilityStatus.FAILED
    assert result.evidence_ref is None
    assert "ACTION ALREADY EXECUTED" in result.content
    assert "recoverability" in result.content.lower()
    assert len(result.content) < 1500


def test_enforce_structured_metadata_is_preserved_but_only_capsule_is_model_visible(tmp_path):
    _, _, enforcer = _enforcer(tmp_path, projection_budget_chars=500)

    class Tool:
        name = "meta_test"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **_kwargs):
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="VISIBLE OBSERVATION",
                tool_call_id="",
                tool_name=self.name,
            )

    registry = ToolRegistry()
    registry.register(Tool())
    registry.set_evidence_enforcer(enforcer)
    result = registry.execute(ToolCall(id="meta-1", name=Tool.name, arguments={}))
    message = result.to_message()
    wire = message.to_llm_dict()

    assert message.metadata["recoverability_status"] == "recorded"
    assert message.metadata["evidence_ref"] == result.evidence_ref
    assert "evidence_ref" not in wire
    assert result.evidence_ref in wire["content"]


def test_factory_enforce_is_offline_buildable_and_default_off_stays_legacy(tmp_path):
    from llm_loop.factory import build_engine

    base = dict(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
    )
    off_engine = build_engine(Settings(**base, evidence_mode="off"))
    assert off_engine.registry.evidence_mode == "off"

    enforce_engine = build_engine(Settings(**base, evidence_mode="enforce"))
    assert enforce_engine.registry.evidence_mode == "enforce"
    assert (tmp_path / "data" / "evidence").exists()


def test_shadow_and_enforce_are_mutually_exclusive(tmp_path):
    _, _, enforcer = _enforcer(tmp_path)
    registry = ToolRegistry()
    registry.set_evidence_enforcer(enforcer)

    with pytest.raises(RuntimeError, match="mutually exclusive"):
        registry.set_evidence_shadow_hook(lambda _call, _result: None)


def test_enforce_large_read_file_does_not_create_legacy_tool_sidecar(tmp_path, monkeypatch):
    data_dir = tmp_path / "legacy-data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    path = tmp_path / "large-sidecar-check.txt"
    path.write_text("A" * 12000, encoding="utf-8")

    _, _, enforcer = _enforcer(tmp_path, projection_budget_chars=600)
    registry = ToolRegistry(summary_threshold=12000)
    registry.register(ReadFileTool())
    registry.set_evidence_enforcer(enforcer)
    result = registry.execute(
        ToolCall(id="no-sidecar-read", name="read_file", arguments={"path": str(path)})
    )

    assert result.recoverability_status is RecoverabilityStatus.RECORDED
    sidecar_dir = data_dir / "audit" / "tool_outputs"
    assert not sidecar_dir.exists() or list(sidecar_dir.iterdir()) == []
    assert "data/audit/tool_outputs" not in result.content


def test_off_mode_large_read_file_still_uses_legacy_sidecar(tmp_path, monkeypatch):
    data_dir = tmp_path / "legacy-data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    path = tmp_path / "large-control.txt"
    path.write_text("B" * 12000, encoding="utf-8")

    registry = ToolRegistry(summary_threshold=12000)
    registry.register(ReadFileTool())
    result = registry.execute(
        ToolCall(id="legacy-read", name="read_file", arguments={"path": str(path)})
    )

    assert result.recoverability_status is RecoverabilityStatus.NOT_CONFIGURED
    assert "[输出已截断]" in result.content
    assert any((data_dir / "audit" / "tool_outputs").iterdir())


def test_enforce_full_true_is_still_bounded_and_recoverable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "legacy-data"))
    path = tmp_path / "full-large.txt"
    marker = "FULL_MODE_HIDDEN_MIDDLE"
    path.write_text("L" * 5000 + marker + "R" * 5000, encoding="utf-8")

    blobs, ledger, enforcer = _enforcer(tmp_path, projection_budget_chars=650)
    registry = ToolRegistry(summary_threshold=650, max_output_chars=20000)
    registry.register(ReadFileTool())
    registry.set_evidence_enforcer(enforcer)
    result = registry.execute(
        ToolCall(
            id="full-bounded",
            name="read_file",
            arguments={"path": str(path), "full": True},
        )
    )

    assert result.evidence_representation == "excerpt"
    assert marker not in result.content
    assert len(result.content) < 1200
    hydrated = EvidenceHydration(blobs, ledger, max_limit=20000).read(
        owner=_owner(),
        evidence_ref=EvidenceRef(result.evidence_ref or ""),
        range_type=RangeType.TEXT_CHAR,
        start=0,
        limit=20000,
    )
    assert marker in hydrated.content


def test_enforce_large_execute_command_does_not_create_legacy_command_sidecar(
    tmp_path, monkeypatch
):
    import shlex
    import sys

    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

    data_dir = tmp_path / "legacy-data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    _, _, enforcer = _enforcer(tmp_path, projection_budget_chars=700)
    registry = ToolRegistry(summary_threshold=12000, tool_timeout_s=10)
    registry.register(ExecuteCommandTool(timeout_s=10))
    registry.set_evidence_enforcer(enforcer)
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote('print(chr(67) * 7000)')}"

    result = registry.execute(
        ToolCall(id="command-no-sidecar", name="execute_command", arguments={"command": command})
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert result.recoverability_status is RecoverabilityStatus.RECORDED
    cmd_dir = data_dir / "audit" / "cmd_outputs"
    assert not cmd_dir.exists() or list(cmd_dir.iterdir()) == []
    assert "recover=read_evidence" in result.content


def test_enforce_local_projection_budget_uses_local_head_tail_window(tmp_path):
    from llm_loop.core.run_context import current_model_label

    _, _, enforcer = _enforcer(tmp_path, projection_budget_chars=5000)

    class Tool:
        name = "local_budget_tool"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **_kwargs):
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="X" * 10000,
                tool_call_id="",
                tool_name=self.name,
            )

    registry = ToolRegistry(
        summary_threshold=12000,
        summary_local_threshold=4000,
        summary_local_head_chars=300,
        summary_local_tail_chars=300,
    )
    registry.register(Tool())
    registry.set_evidence_enforcer(enforcer)
    token = current_model_label.set("local/model")
    try:
        result = registry.execute(ToolCall(id="local-budget", name=Tool.name, arguments={}))
    finally:
        current_model_label.reset(token)

    # 600 raw projection chars + a small deterministic capsule; HOT never forces full.
    assert result.evidence_representation == "excerpt"
    assert len(result.content) < 1000


def test_enforce_accepts_hookless_pipeline_and_locks_future_post_hooks(tmp_path):
    from llm_loop.tools.pipeline import PipelineConfig, ToolExecutionPipeline

    _, _, enforcer = _enforcer(tmp_path)
    registry = ToolRegistry()
    registry.set_evidence_enforcer(enforcer)
    pipeline = ToolExecutionPipeline(PipelineConfig(enabled=True))
    registry.set_pipeline(pipeline)

    assert registry._pipeline is pipeline
    with pytest.raises(RuntimeError, match="Evidence"):
        pipeline.add_post_hook(lambda result: None)


def test_enforce_order_is_tool_then_capture_then_projection(tmp_path):
    events: list[str] = []
    blobs = BlobStore(tmp_path / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "evidence" / "ledger")
    real_capture = EvidenceCapture(blobs, ledger)

    class RecordingCapture:
        def capture(self, request):
            events.append("capture")
            return real_capture.capture(request)

    class RecordingProjection(ProjectionEngine):
        def project(self, *args, **kwargs):
            events.append("projection")
            return super().project(*args, **kwargs)

    class Tool:
        name = "ordering_tool"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **_kwargs):
            events.append("tool")
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="observation" * 1000,
                tool_call_id="",
                tool_name=self.name,
            )

    registry = ToolRegistry(summary_threshold=500)
    registry.register(Tool())
    registry.set_evidence_enforcer(
        EvidenceEnforcer(
            RecordingCapture(),  # type: ignore[arg-type]
            projection=RecordingProjection(),
            owner_resolver=_owner,
            projection_budget_chars=500,
        )
    )
    registry.execute(ToolCall(id="ordering-1", name=Tool.name, arguments={}))

    assert events == ["tool", "capture", "projection"]


def test_factory_enforce_accepts_enabled_hookless_tool_pipeline(tmp_path):
    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        evidence_mode="enforce",
        tool_pipeline_enabled=True,
    )
    engine = build_engine(settings)
    assert engine.registry.evidence_mode == "enforce"
    assert engine.registry._pipeline is not None
    assert engine.registry._pipeline.config.enabled is True


def test_enforce_edit_file_captures_full_diff_beyond_legacy_preview(tmp_path):
    from llm_loop.tools.builtin.edit_file import EditFileTool

    path = tmp_path / "many-lines.txt"
    path.write_text("".join(f"OLD line {i:03d}\n" for i in range(140)), encoding="utf-8")
    blobs, ledger, enforcer = _enforcer(tmp_path, projection_budget_chars=700)
    registry = ToolRegistry(summary_threshold=700)
    registry.register(EditFileTool())
    registry.set_evidence_enforcer(enforcer)

    result = registry.execute(
        ToolCall(
            id="edit-full-diff",
            name="edit_file",
            arguments={
                "path": str(path),
                "old_string": "OLD",
                "new_string": "NEW",
                "replace_all": True,
            },
        )
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert path.read_text(encoding="utf-8").count("NEW") == 140
    hydrated = EvidenceHydration(blobs, ledger, max_limit=30000).read(
        owner=_owner(),
        evidence_ref=EvidenceRef(result.evidence_ref or ""),
        range_type=RangeType.TEXT_CHAR,
        start=0,
        limit=30000,
    )
    assert "+NEW line 139" in hydrated.content
    assert "diff 过长已截断" not in hydrated.content


def test_enforce_web_fetch_captures_full_default_body_before_max_chars_projection(
    tmp_path, monkeypatch
):
    import httpx

    from llm_loop.tools.builtin.web_fetch import WebFetchTool

    marker = "WEB_FETCH_DEEP_MARKER_271828"
    html = (
        "<html><body><article>" + ("A" * 3000) + marker + ("Z" * 3000) + "</article></body></html>"
    )
    tool = WebFetchTool()

    def fake_request(url):
        return httpx.Response(200, text=html, request=httpx.Request("GET", url))

    monkeypatch.setattr(tool, "_request", fake_request)
    blobs, ledger, enforcer = _enforcer(tmp_path, projection_budget_chars=700)
    registry = ToolRegistry(summary_threshold=700)
    registry.register(tool)
    registry.set_evidence_enforcer(enforcer)

    result = registry.execute(
        ToolCall(
            id="web-full-default",
            name="web_fetch",
            arguments={"url": "https://example.test/article", "max_chars": 300},
        )
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert "[内容超长" not in result.content
    assert marker not in result.content
    hydrated = EvidenceHydration(blobs, ledger, max_limit=20000).read(
        owner=_owner(),
        evidence_ref=EvidenceRef(result.evidence_ref or ""),
        range_type=RangeType.TEXT_CHAR,
        start=0,
        limit=20000,
    )
    assert marker in hydrated.content
    record = ledger.get_record(_owner(), EvidenceRef(result.evidence_ref or ""))
    assert record is not None and record.source.kind.value == "web"


def test_enforce_web_fetch_explicit_start_remains_partial_acquisition(tmp_path, monkeypatch):
    import httpx

    from llm_loop.tools.builtin.web_fetch import WebFetchTool

    body = "0123456789" * 300
    tool = WebFetchTool()

    def fake_request(url):
        return httpx.Response(
            200,
            text=f"<html><body><article>{body}</article></body></html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(tool, "_request", fake_request)
    blobs, ledger, enforcer = _enforcer(tmp_path, projection_budget_chars=700)
    registry = ToolRegistry(summary_threshold=700)
    registry.register(tool)
    registry.set_evidence_enforcer(enforcer)

    result = registry.execute(
        ToolCall(
            id="web-partial",
            name="web_fetch",
            arguments={
                "url": "https://example.test/article",
                "start": 500,
                "count": 200,
                "max_chars": 200,
            },
        )
    )

    record = ledger.get_record(_owner(), EvidenceRef(result.evidence_ref or ""))
    assert record is not None
    assert record.coverage.start == 500
    assert record.coverage.source_complete is False
    hydrated = EvidenceHydration(blobs, ledger, max_limit=1000).read(
        owner=_owner(),
        evidence_ref=EvidenceRef(result.evidence_ref or ""),
        range_type=RangeType.TEXT_CHAR,
        start=0,
        limit=1000,
    )
    assert len(hydrated.content) < 1000
    assert "[分页" in hydrated.content


def test_dsh_clippers_defer_only_under_enforce_context():
    from llm_loop.core.run_context import current_evidence_enforce_enabled
    from llm_loop.tools.builtin.dsh_session_read import DshSessionReadTool
    from llm_loop.tools.builtin.dsh_task import DshTaskTool

    long_text = "D" * 35000
    assert "已截断" in DshTaskTool._clip(long_text)

    event = {
        "type": "assistant/message",
        "data": {"message": {"content": [{"type": "text", "text": long_text}]}},
    }
    assert "摘要截断" in DshSessionReadTool._digest([event], "", 200)

    token = current_evidence_enforce_enabled.set(True)
    try:
        assert DshTaskTool._clip(long_text) == long_text
        digest = DshSessionReadTool._digest([event], "", 200)
        assert "摘要截断" not in digest
        assert len(digest) > 30000
    finally:
        current_evidence_enforce_enabled.reset(token)


def test_enforce_architecture_status_captures_full_snapshot_before_8000_char_view(tmp_path):
    from llm_loop.introspection.tools_status import run_status

    marker = "ARCH_STATUS_DEEP_MARKER_161803"

    class Provider:
        def snapshot(self, dimensions=None):
            return {"payload": ("A" * 9000) + marker + ("Z" * 2000)}

    class Tool:
        name = "architecture_status"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            return run_status(None, Provider(), kwargs)

    blobs, ledger, enforcer = _enforcer(tmp_path, projection_budget_chars=700)
    registry = ToolRegistry(summary_threshold=700)
    registry.register(Tool())
    registry.set_evidence_enforcer(enforcer)
    result = registry.execute(ToolCall(id="status-full", name=Tool.name, arguments={}))

    assert "[快照截断]" not in result.content
    assert marker not in result.content
    hydrated = EvidenceHydration(blobs, ledger, max_limit=20000).read(
        owner=_owner(),
        evidence_ref=EvidenceRef(result.evidence_ref or ""),
        range_type=RangeType.TEXT_CHAR,
        start=0,
        limit=20000,
    )
    assert marker in hydrated.content


def test_enforce_search_records_captures_all_limited_hits_not_only_six(tmp_path):
    from llm_loop.introspection.tools_status import run_search_records

    rows = [
        {"ts": f"t{i}", "kind": "memory", "summary": f"row-{i}-" + ("X" * 400)} for i in range(10)
    ]

    class Tool:
        name = "search_records"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            return run_search_records(None, lambda **_kw: rows, kwargs, lambda: "session-A")

    blobs, ledger, enforcer = _enforcer(tmp_path, projection_budget_chars=700)
    registry = ToolRegistry(summary_threshold=700)
    registry.register(Tool())
    registry.set_evidence_enforcer(enforcer)
    result = registry.execute(
        ToolCall(
            id="records-full",
            name=Tool.name,
            arguments={"kind": "all", "query": "row", "limit": 10},
        )
    )
    hydrated = EvidenceHydration(blobs, ledger, max_limit=10000).read(
        owner=_owner(),
        evidence_ref=EvidenceRef(result.evidence_ref or ""),
        range_type=RangeType.TEXT_CHAR,
        start=0,
        limit=10000,
    )
    assert "row-9-" in hydrated.content
    assert hydrated.content.count("row-") == 10
