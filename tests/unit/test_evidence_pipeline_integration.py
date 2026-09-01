from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.config import Settings
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.factory import build_engine
from llm_loop.tools.pipeline import PipelineConfig, ToolExecutionPipeline
from llm_loop.tools.registry import ToolRegistry


def _pipeline(*, enabled: bool = True, materialize: bool = True, guard: bool = False):
    return ToolExecutionPipeline(
        PipelineConfig(enabled=enabled, materialize=materialize, guard=guard)
    )


def test_enforce_accepts_materialize_pipeline_when_no_hooks() -> None:
    registry = ToolRegistry()
    registry.set_evidence_enforcer(object())
    pipeline = _pipeline()
    registry.set_pipeline(pipeline)
    assert registry._pipeline is pipeline


def test_assembly_order_pipeline_then_enforcer_is_also_supported() -> None:
    registry = ToolRegistry()
    pipeline = _pipeline()
    registry.set_pipeline(pipeline)
    registry.set_evidence_enforcer(object())
    assert registry._pipeline is pipeline
    assert registry.evidence_mode == "enforce"


def test_enforce_rejects_pipeline_with_existing_pre_or_post_hooks() -> None:
    for kind in ("pre", "post"):
        registry = ToolRegistry()
        registry.set_evidence_enforcer(object())
        pipeline = _pipeline()
        if kind == "pre":
            pipeline.add_pre_hook(lambda call: None)
        else:
            pipeline.add_post_hook(lambda result: None)
        with pytest.raises(RuntimeError, match="hook"):
            registry.set_pipeline(pipeline)


def test_evidence_compatible_pipeline_rejects_future_hooks_but_allows_guard_configuration() -> None:
    from llm_loop.tools.pipeline import MonotonicGuard

    registry = ToolRegistry()
    registry.set_evidence_enforcer(object())
    pipeline = _pipeline(guard=True)
    registry.set_pipeline(pipeline)
    pipeline.set_guard(MonotonicGuard())
    with pytest.raises(RuntimeError, match="Evidence"):
        pipeline.add_pre_hook(lambda call: None)
    with pytest.raises(RuntimeError, match="Evidence"):
        pipeline.add_post_hook(lambda result: None)


def test_factory_current_production_pipeline_subset_builds_with_enforce_and_preserves_capture(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LFL_EVIDENCE_CAPSULE", "on")  # R9-P0-01 批 1/3：on 态机制测试钉住前提
    data_dir = tmp_path / "data"
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(data_dir),
        evidence_mode="enforce",
        tool_pipeline_enabled=True,
        tool_materialize_enabled=True,
        tool_guard_enabled=False,
        extract_enabled=False,
    )
    engine = build_engine(settings)
    engine.registry.set_session_id("r12-factory-session")
    assert engine.registry.evidence_mode == "enforce"
    assert engine.registry._pipeline is not None
    assert engine.registry._pipeline.config.materialize is True

    path = tmp_path / "pipeline-evidence.txt"
    path.write_text("head\nR12-TARGET\ntail\n", encoding="utf-8")
    first = engine.registry.execute(
        ToolCall(id="r12-1", name="read_file", arguments={"path": str(path), "full": True})
    )
    assert first.status is ToolResultStatus.SUCCESS
    assert first.evidence_ref
    assert first.source_execution_performed is True
    assert "recover=read_evidence" in first.content

    second = engine.registry.execute(
        ToolCall(
            id="r12-2", name="read_file", arguments={"path": str(path), "offset": 0, "limit": 2}
        )
    )
    assert second.status is ToolResultStatus.SUCCESS
    assert second.source_resolution_mode == "evidence_reuse"
    assert second.source_execution_performed is False
    assert second.evidence_ref == first.evidence_ref
