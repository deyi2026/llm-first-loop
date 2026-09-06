"""Rule-first tool-result boundary tests.

Exact tool bytes remain visible until the real per-result hard cap. Provider type does
not change that policy. At the hard cap, exact archival is attempted and truncation is
truthful; optional legacy guidance remains off by default.
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall
from llm_loop.tools.registry import ToolRegistry, ToolResult, ToolResultStatus


class _BigTool:
    name = "big_tool"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, content: str):
        self._content = content

    def execute(self, **_kwargs):
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=self._content,
            tool_call_id="",
            tool_name=self.name,
        )


class _ArchiveFake:
    def __init__(self):
        self.items = []

    def archive(self, session_id, **kwargs):
        self.items.append((session_id, kwargs))
        return object()


def _call() -> ToolCall:
    return ToolCall(id="c1", name="big_tool", arguments={})


def test_default_preserves_exact_output_below_hard_cap():
    body = "HEAD" + "x" * 20_000 + "TAIL"
    reg = ToolRegistry(max_output_chars=100_000)
    reg.register(_BigTool(body))
    result = reg.execute(_call())
    assert result.content == body
    assert "输出摘要" not in result.content


def test_local_and_cloud_have_identical_tool_result_projection_below_hard_cap():
    from llm_loop.core.run_context import current_model_label

    body = "FACT" + "x" * 20_000
    reg = ToolRegistry(max_output_chars=100_000)
    reg.register(_BigTool(body))
    outputs = []
    for label in ("local/qwen", "deepseek/v4"):
        token = current_model_label.set(label)
        try:
            outputs.append(reg.execute(_call()).content)
        finally:
            current_model_label.reset(token)
    assert outputs == [body, body]


def test_hard_cap_archives_exact_body_then_truncates_truthfully(monkeypatch):
    monkeypatch.setenv("LFL_TOOL_GUIDANCE", "off")
    body = "Z" * 5000
    archive = _ArchiveFake()
    reg = ToolRegistry(max_output_chars=2000, archive_store=archive)
    reg.set_session_id("s-hard")
    reg.register(_BigTool(body))

    result = reg.execute(_call())

    assert "已截断" in result.content
    assert "硬上限: 2000" in result.content
    assert "完整内容已另存" in result.content
    assert "行动指引" not in result.content
    assert archive.items[0][0] == "s-hard"
    assert archive.items[0][1]["content"] == body


def test_hard_cap_without_archive_never_invents_recovery(monkeypatch):
    monkeypatch.setenv("LFL_TOOL_GUIDANCE", "off")
    body = "Q" * 5000
    reg = ToolRegistry(max_output_chars=2000)
    reg.register(_BigTool(body))
    result = reg.execute(_call())
    assert "已截断" in result.content
    assert "没有 archive 恢复路径" in result.content
    assert "search_archive" not in result.content


def test_legacy_guidance_is_only_an_explicit_opt_in_at_real_truncation(monkeypatch):
    body = "G" * 5000
    archive = _ArchiveFake()
    reg = ToolRegistry(max_output_chars=2000, archive_store=archive)
    reg.set_session_id("s-guide")
    reg.register(_BigTool(body))

    monkeypatch.setenv("LFL_TOOL_GUIDANCE", "off")
    assert "行动指引" not in reg.execute(_call()).content

    monkeypatch.setenv("LFL_TOOL_GUIDANCE", "on")
    assert "行动指引" in reg.execute(_call()).content
