"""Sub-agent length-exhaustion regression from real GLM-5.3 incidents."""
from __future__ import annotations

from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import LLMEmptyResponseError
from llm_loop.subagent.runner import SubAgentRunner


def test_reasoning_exhaustion_does_not_retry_unchanged_wire(build_test_engine):
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=6)

    def _length(_calls):
        raise LLMEmptyResponseError(
            "model used entire output budget without final text",
            provider="glm",
            finish_reason="length",
            prompt_tokens=18490,
            completion_tokens=16000,
            reasoning_tokens=15999,
            provider_truncated=True,
        )

    fake._responses = [_length, LLMResponse(content="unearned success", tool_calls=[], provider="fake")]
    result = runner.run(task="Reproduce output budget exhaustion", depth=0)
    assert result.outcome == "failed"
    assert result.rounds == 1
    assert len(fake.calls) == 1, "identical request must never spend 16K repeatedly"
    assert result.tokens_out == 16000, "failed provider attempt still incurred tokens"
    assert result.tokens_in == 18490, "failed stream usage must not disappear"
    assert "length" in result.final_answer
    assert "16000" in result.final_answer


def test_other_transient_provider_failure_still_allows_one_normal_retry(build_test_engine):
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=2)

    def _transient(_calls):
        raise RuntimeError("temporary")

    fake._responses = [_transient, LLMResponse(content="recovered", tool_calls=[], provider="fake")]
    result = runner.run(task="One transient failure", depth=0)
    assert result.outcome == "completed"
    assert result.final_answer == "recovered"
    assert len(fake.calls) == 2


def test_long_delegation_is_not_silently_truncated(build_test_engine):
    from llm_loop.tools.registry import ToolRegistry

    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake,
        registry=ToolRegistry(),
        session_store=engine.session,
        context_limits_resolver=lambda _model: (10000, 3000, 1.0),
    )
    exact_task = "DELEGATED-INSTRUCTION-" + "Z" * 6000
    result = runner.run(task=exact_task, depth=0)
    assert result.outcome == "failed"
    assert not fake.calls, "hard window must stop before a malformed provider request"
    assert "拒绝静默截断" in result.final_answer
    sessions = list(engine.session._dir.glob("subagent_*.json"))
    assert len(sessions) == 1
    saved = engine.session.load(sessions[0].stem)
    assert exact_task in saved.messages[0].content


def test_child_pressure_projects_with_exact_readable_archive(build_test_engine, tmp_path):
    from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
    from llm_loop.memory.archive import ArchiveStore
    from llm_loop.tools.registry import ToolRegistry

    class _ArchiveTool:
        name = "search_archive"
        description = "retrieve durable archive"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):  # noqa: ANN003, ANN201, ARG002
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="EXACT-ARCHIVE-MARKER-" + "T" * 6500,
                tool_call_id="", tool_name=self.name,
            )

    engine, fake = build_test_engine([])
    registry = ToolRegistry()
    registry.register(_ArchiveTool())  # type: ignore[arg-type]
    archive = ArchiveStore(tmp_path / "archives")
    runner = SubAgentRunner(
        llm=fake, registry=registry, session_store=engine.session,
        context_limits_resolver=lambda _model: (15000, 3000, 1.0),
        archive_store=archive,
    )
    fake._responses = [
        LLMResponse(content="", provider="fake", tool_calls=[ToolCall(id="fetch-1", name="search_archive", arguments={})]),
        LLMResponse(content="child-completed", provider="fake", tool_calls=[]),
    ]
    result = runner.run(task="Summarize archive retrieval", depth=0)
    assert result.outcome == "completed", result.final_answer
    assert len(fake.calls) == 2
    assert sum(len(str(m.get("content") or "")) for m in fake.calls[1]["messages"]) < 3000
    ids = list(engine.session._dir.glob("subagent_*.json"))
    saved = engine.session.load(ids[0].stem)
    assert any("EXACT-ARCHIVE-MARKER-" in m.content and len(m.content) > 6500 for m in saved.messages)
    matches = archive.search(saved.session_id, "EXACT-ARCHIVE-MARKER")
    assert matches, "retired content must be discoverable through the child archive"
