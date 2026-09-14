"""P2 Missing-Context Authority regression tests."""

from types import SimpleNamespace

from llm_loop.core.message import ToolCall
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.evolution import EvolutionStore
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.tools_goal import run_create_goal
from llm_loop.memory.archive import ArchiveStore
from llm_loop.tools.registry import ToolRegistry


def test_registry_oversize_archive_does_not_borrow_explicit_last_session(tmp_path) -> None:
    """No execution ContextVar => archive mutation has no owner, even if last SID exists."""
    store = ArchiveStore(tmp_path / "archive")
    registry = ToolRegistry(archive_store=store)
    registry.set_session_id("stale-session-B")

    archived = registry._archive_oversize_output(  # noqa: SLF001 - authority regression
        ToolCall(id="tc-p2", name="read_file", arguments={}),
        "P2 OVERSIZE SECRET",
    )

    assert archived is False
    assert store.search("stale-session-B", "P2 OVERSIZE SECRET", limit=5) == []


def test_submit_evolution_missing_context_does_not_persist_to_stale_session(tmp_path) -> None:
    store = EvolutionStore(tmp_path / "audit")
    ctx = CorrectionContext(evolution_store=store, session_id="stale-session-B")

    result = CorrectionToolRegistry(ctx).execute(
        "submit_evolution",
        {"content": "P2 stale evolution", "impact_scope": "runtime"},
    )

    assert result.status.value == "failure"
    assert store.list() == []


def test_self_evaluate_missing_context_does_not_borrow_stale_session() -> None:
    calls: list[tuple[str, str]] = []

    class _Evaluator:
        def evaluate(self, *, session_id: str, trigger: str):
            calls.append((session_id, trigger))
            return SimpleNamespace(eval_id="SE-SHOULD-NOT-EXIST", metrics=[])

    ctx = CorrectionContext(evaluator=_Evaluator(), session_id="stale-session-B")
    result = CorrectionToolRegistry(ctx).execute("self_evaluate", {"trigger": "manual"})

    assert result.status.value == "failure"
    assert calls == []


def test_create_goal_missing_context_does_not_borrow_stale_session(tmp_path) -> None:
    host = SimpleNamespace(audit_dir=tmp_path)
    ctx = SimpleNamespace(session_id="stale-session-B")

    result = run_create_goal(ctx, host, {"objective": "P2 stale goal"})

    assert result.status.value == "failure"
    assert GoalStore(tmp_path).get() is None
