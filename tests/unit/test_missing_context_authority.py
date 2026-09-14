"""P2 Missing-Context Authority regression tests."""

from types import SimpleNamespace

from llm_loop.core.message import ToolCall
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.evolution import EvolutionStore
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.tools_goal import run_create_goal
from llm_loop.memory.archive import ArchiveStore
from llm_loop.tools.registry import ToolRegistry
from llm_loop.web.routes import _evolution_store_from


def test_registry_oversize_archive_requires_execution_context(tmp_path) -> None:
    """No execution ContextVar => archive mutation has no owner."""
    store = ArchiveStore(tmp_path / "archive")
    registry = ToolRegistry(archive_store=store)

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


def test_legacy_engine_evolution_store_cannot_become_write_authority(tmp_path) -> None:
    """P6: production EvolutionStore SoT is correction_ctx only."""
    legacy_store = EvolutionStore(tmp_path / "legacy-audit")
    engine = SimpleNamespace(
        correction_ctx=SimpleNamespace(evolution_store=None),
        evolution_store=legacy_store,
    )

    assert _evolution_store_from(engine) is None


def test_tool_registry_has_no_shared_last_session_fallback() -> None:
    """P6: tool mutation ownership must come from execution ContextVar, never last writer."""
    registry = ToolRegistry()

    assert not hasattr(registry, "_session_id_explicit")
    assert not hasattr(type(registry), "_session_id")
    assert not hasattr(registry, "set_session_id")


def test_correction_context_has_no_shared_model_override_authority_fields() -> None:
    """P6: model ownership is exact/local; shared dataclass fields are retired."""
    fields = CorrectionContext.__dataclass_fields__
    assert "session_model_override" not in fields
    assert "session_set_override" not in fields


def test_active_run_does_not_refresh_shared_model_override_fields(build_test_engine) -> None:
    """P6: synthetic stale attrs must not become active-run model authority."""
    engine, _fake = build_test_engine([{"content": "ok"}])
    assert engine.correction_ctx is not None
    stale_writes: list[str | None] = []
    stale_setter = stale_writes.append
    vars(engine.correction_ctx)["session_model_override"] = "stale-session-B/model"
    vars(engine.correction_ctx)["session_set_override"] = stale_setter
    sid = engine.session.create(model_override="current-session/model")

    result = engine.run(sid, "hello")

    assert result.final_answer == "ok"
    assert vars(engine.correction_ctx)["session_model_override"] == "stale-session-B/model"
    assert vars(engine.correction_ctx)["session_set_override"] is stale_setter
    assert stale_writes == []


def test_exact_session_override_setter_does_not_write_shared_model_fallback(
    build_test_engine,
) -> None:
    """P6: exact session setter mutates only the bound Session object."""
    engine, _fake = build_test_engine([])
    assert engine.correction_ctx is not None
    vars(engine.correction_ctx)["session_model_override"] = "stale-session-B/model"
    sid = engine.session.create()
    sess = engine.session.load(sid)

    engine._set_session_override(sess, "current-session/model")  # noqa: SLF001

    assert sess.model_override == "current-session/model"
    assert vars(engine.correction_ctx)["session_model_override"] == "stale-session-B/model"
