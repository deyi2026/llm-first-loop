from __future__ import annotations

from llm_loop.core.run_context import current_model_label, current_session_id
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner


def test_subagent_defaults_to_parent_current_model(build_test_engine) -> None:
    engine, default = build_test_engine([])
    _engine2, child = build_test_engine([])
    child._responses = [LLMResponse(content="child-via-minimax", tool_calls=[], provider="minimax")]
    seen: list[str | None] = []

    def resolve(model_ref: str | None):
        seen.append(model_ref)
        assert model_ref == "minimax/MiniMax-M3"
        return child

    runner = SubAgentRunner(
        llm=default,
        registry=engine.registry,
        session_store=engine.session,
        llm_resolver=resolve,
    )
    sid_tok = current_session_id.set("parent-route-inherit")
    model_tok = current_model_label.set("minimax/MiniMax-M3")
    try:
        result = runner.run(task="route me")
    finally:
        current_model_label.reset(model_tok)
        current_session_id.reset(sid_tok)
    assert result.final_answer == "child-via-minimax"
    assert seen == ["minimax/MiniMax-M3"]
    assert child.calls and not default.calls


def test_subagent_explicit_model_overrides_parent_without_program_selection(build_test_engine) -> None:
    engine, default = build_test_engine([])
    _engine2, child = build_test_engine([])
    child._responses = [LLMResponse(content="child-via-deepseek", tool_calls=[], provider="deepseek")]
    seen: list[str | None] = []

    def resolve(model_ref: str | None):
        seen.append(model_ref)
        if model_ref != "deepseek/deepseek-v4-flash":
            raise ValueError("unexpected model")
        return child

    runner = SubAgentRunner(
        llm=default,
        registry=engine.registry,
        session_store=engine.session,
        llm_resolver=resolve,
    )
    sid_tok = current_session_id.set("parent-route-explicit")
    model_tok = current_model_label.set("glm/glm-5.3")
    try:
        result = runner.run(task="route me", model="deepseek/deepseek-v4-flash")
    finally:
        current_model_label.reset(model_tok)
        current_session_id.reset(sid_tok)
    assert result.final_answer == "child-via-deepseek"
    assert seen == ["deepseek/deepseek-v4-flash"]
    assert child.calls and not default.calls


def test_subagent_invalid_explicit_model_refuses_before_child_execution(build_test_engine) -> None:
    engine, default = build_test_engine([])

    def reject(_model_ref: str | None):
        raise ValueError("unknown model")

    runner = SubAgentRunner(
        llm=default,
        registry=engine.registry,
        session_store=engine.session,
        llm_resolver=reject,
    )
    sid_tok = current_session_id.set("parent-route-invalid")
    model_tok = current_model_label.set("glm/glm-5.3")
    try:
        result = runner.run(task="do not start", model="nope/missing")
    finally:
        current_model_label.reset(model_tok)
        current_session_id.reset(sid_tok)
    assert result.outcome == "refused"
    assert default.calls == []
    assert runner.active_children("parent-route-invalid") == []
