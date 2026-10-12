"""P1-B regression: capability requirements are facts, not selectors."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus


def test_capability_selection_module_is_retired():
    root = Path(__file__).resolve().parents[2]
    assert not (root / "src/llm_loop/tools/capability_requirements.py").exists()
    assert importlib.util.find_spec("llm_loop.tools.capability_requirements") is None


def test_tool_result_preserves_capability_fact_metadata():
    result = ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="fact producer",
        tool_call_id="c1",
        tool_name="producer",
        capability_requirements=("job_output", "read_evidence"),
    )
    msg = result.to_message()
    assert msg.metadata["capability_requirements"] == ["job_output", "read_evidence"]
    assert "capability_requirements" not in msg.content
