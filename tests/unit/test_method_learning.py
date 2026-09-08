from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from llm_loop.introspection.registry_experience import execute as execute_experience_tool
from llm_loop.introspection.registry_experience import tool_defs as experience_tool_defs
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.tools_status import run_search_records
from llm_loop.methods.store import MethodStore


class _Host:
    def __init__(self, store: MethodStore) -> None:
        self.method_store = store
        self.experience_store = None
        self.audit_rows: list[tuple[str, dict, str]] = []

    def audit(self, tool_name: str, arguments: dict, result_status: str) -> None:
        self.audit_rows.append((tool_name, arguments, result_status))

    def current_session_id(self) -> str:
        return "method-test-session"


class _Ctx:
    pass


def _seed_method(root: Path, method_id: str, *, status: str = "candidate", body: str = "BODY") -> None:
    d = root / method_id
    d.mkdir(parents=True)
    (d / "METHOD.md").write_text(
        "---\n"
        f"method_id: {method_id}\n"
        f"name: {method_id}\n"
        f"description: diagnostic method {method_id}\n"
        f"status: {status}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )


def test_method_store_compact_discovery_and_exact_hydration(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    _seed_method(root, "root-cause", status="active", body="DISCRIMINATOR: first divergent fact")
    store = MethodStore(root)

    cards = store.list("diagnostic", 10)
    assert len(cards) == 1
    assert cards[0]["key"] == "method:root-cause"
    assert cards[0]["projection_complete"] is False
    assert "body" not in cards[0]
    assert cards[0]["task_applicability"] == "not_evaluated"

    exact = store.list("method:root-cause", 10)
    assert len(exact) == 1
    assert exact[0]["projection_complete"] is True
    assert "first divergent fact" in exact[0]["body"]


def test_candidate_is_immutable_and_cannot_jump_directly_active(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    first = store.save_candidate(name="hydrate trace", description="trace producer", body="counterexample: SSR page")
    second = store.save_candidate(name="hydrate trace", description="trace producer", body="counterexample: SSR page")
    assert first.method_ref == second.method_ref
    assert first.status == "candidate"

    try:
        store.update_status(first.method_ref, "active")
    except ValueError as exc:
        assert "qualify" in str(exc)
    else:
        raise AssertionError("candidate -> active must fail")


def test_qualification_then_qualified_then_active(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(name="api refresh", description="fresh callsites", body="verify current tree")

    try:
        store.update_status(record.method_ref, "qualified")
    except ValueError as exc:
        assert "promotion=pass" in str(exc)
    else:
        raise AssertionError("qualification evidence required")

    store.record_qualification(
        record.method_ref,
        task_ref="episode:unseen-1",
        verdict="pass",
        mechanism="pass",
        task_benefit="pass",
        promotion="pass",
        evidence_refs=["evidence:1"],
    )
    qualified = store.update_status(record.method_ref, "qualified")
    assert qualified.status == "qualified"
    active = store.update_status(record.method_ref, "active")
    assert active.status == "active"


def test_same_source_episode_cannot_supply_promotion_pass(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="source-bound",
        description="independent qualification required",
        body="counterexample included",
        source_episode_refs=["session:s1"],
    )
    try:
        store.record_qualification(
            record.method_ref,
            task_ref="session:s1",
            verdict="pass",
            mechanism="pass",
            task_benefit="pass",
            promotion="pass",
        )
    except ValueError as exc:
        assert "independent" in str(exc)
    else:
        raise AssertionError("same source episode must not authorize promotion")


def test_teacher_cannot_be_reclassified(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    _seed_method(root, "teacher-root", status="teacher")
    store = MethodStore(root)
    try:
        store.update_status("method:teacher-root", "candidate")
    except ValueError as exc:
        assert "teacher" in str(exc)
    else:
        raise AssertionError("teacher lifecycle should be immutable")


def test_record_searcher_method_kind_and_renderer_hydrate_exact(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    _seed_method(root, "root-cause", status="active", body="GENERAL_RULE: isolate the first divergent boundary")
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", method_store=MethodStore(root))

    card = searcher.search(kind="method", query="diagnostic", limit=10)
    assert card[0]["projection_complete"] is False
    exact = searcher.search(kind="method", query="method:root-cause", limit=10)
    assert exact[0]["projection_complete"] is True

    result = run_search_records(
        _Ctx(),
        lambda **kwargs: searcher.search(**kwargs),
        {"kind": "method", "query": "method:root-cause", "limit": 10},
        lambda: "",
    )
    assert "exact Method" in result.content
    assert "first divergent boundary" in result.content
    assert "status=active" in result.content


def test_method_tools_persist_candidate_qualification_and_lifecycle(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    host = _Host(store)
    tool_defs = {d["name"]: d for d in experience_tool_defs()}
    assert "method_manage" in tool_defs
    assert {"save_method_candidate", "record_method_qualification", "refine_method"}.isdisjoint(tool_defs)
    save_props = tool_defs["method_manage"]["parameters"]["properties"]
    assert "source_model" not in save_props
    assert "source_episode_refs" not in save_props
    assert "teacher_ref" not in save_props

    from llm_loop.core.run_context import current_model_label

    model_token = current_model_label.set("test-provider/test-model")
    try:
        saved = execute_experience_tool(
            "method_manage",
            {"action": "save_candidate", "name": "trace source", "description": "follow provenance", "body": "counterexample included"},
            cast(Any, host),
        )
    finally:
        current_model_label.reset(model_token)
    assert saved is not None and saved.status.value == "success"
    ref = saved.content.split()[1]
    persisted = store.get(ref)
    assert persisted is not None
    assert persisted.source_model == "test-provider/test-model"
    assert persisted.source_episode_refs == ("session:method-test-session",)

    blocked = execute_experience_tool(
        "method_manage", {"action": "refine", "method_ref": ref, "transition": "activate"}, cast(Any, host)
    )
    assert blocked is not None and blocked.status.value == "failure"

    qualified = execute_experience_tool(
        "method_manage",
        {
            "action": "record_qualification",
            "method_ref": ref,
            "task_ref": "episode:unseen",
            "verdict": "pass",
            "mechanism": "pass",
            "task_benefit": "pass",
            "promotion": "pass",
        },
        cast(Any, host),
    )
    assert qualified is not None and qualified.status.value == "success"
    moved = execute_experience_tool(
        "method_manage", {"action": "refine", "method_ref": ref, "transition": "qualify"}, cast(Any, host)
    )
    assert moved is not None and moved.status.value == "success"
    activated = execute_experience_tool(
        "method_manage", {"action": "refine", "method_ref": ref, "transition": "activate"}, cast(Any, host)
    )
    assert activated is not None and activated.status.value == "success"


def test_repository_seed_methods_are_complete() -> None:
    root = Path(__file__).resolve().parents[2] / "methods"
    store = MethodStore(root)
    cards = store.list("", 50)
    refs = {c["key"] for c in cards}
    expected = {
        "method:method-root-cause",
        "method:method-repo-api-discovery",
        "method:method-ab-experiment",
        "method:method-web-source-diagnosis",
        "method:method-self-distill",
        "method:method-self-distill-ab",
        "method:method-self-distill-repo-api",
        "method:method-self-distill-root-cause",
        "method:method-candidate-hydrate-trace",
        "method:method-candidate-ab-validity-trigger-confound",
        "method:method-candidate-current-callsite-refresh",
        "method:method-candidate-relative-clock-never-state",
    }
    assert expected <= refs
    by_ref = {c["key"]: c for c in cards}
    assert by_ref["method:method-web-source-diagnosis"]["status"] == "hold"
    assert by_ref["method:method-self-distill-root-cause"]["status"] == "teacher"
    assert by_ref["method:method-candidate-hydrate-trace"]["status"] == "candidate"


def test_reflection_below_threshold_does_not_call_model(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from llm_loop.methods.reflection import reflect_after_run

    root = tmp_path / "seed"
    _seed_method(root, "method-self-distill", status="active", body="self distill algorithm")
    store = MethodStore(tmp_path / "runtime", seed_dir=root)

    class NeverCall:
        def chat(self, **kwargs):
            raise AssertionError("must not call")

    out = reflect_after_run(
        mode="auto",
        llm_client=NeverCall(),
        store=store,
        session_id="s1",
        messages=[SimpleNamespace(role="user", content="tiny", reasoning_content="SECRET")],
        rounds=1,
        tool_trace=[],
        run_end_reason="completed",
        final_answer="ok",
        source_model="p/m",
        min_rounds=6,
        min_tools=6,
        min_failures=2,
    )
    assert out.attempted is False
    assert out.reason == "below_mechanical_friction_threshold"


def test_reflection_saves_candidate_without_reasoning_projection(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from llm_loop.methods.reflection import reflect_after_run

    root = tmp_path / "seed"
    _seed_method(root, "method-self-distill", status="active", body="FRICTION -> DISCRIMINATOR")
    store = MethodStore(tmp_path / "runtime", seed_dir=root)

    class FakeClient:
        model = "m"
        def __init__(self) -> None:
            self.calls = []
        def chat(self, **kwargs):
            self.calls.append(kwargs)
            from llm_loop.llm.client import LLMResponse
            return LLMResponse(
                content='{"decision":"candidate","name":"fresh callsite","description":"refresh current callsites","body":"trigger: signature changed\\ndiscriminator: current tree\\nshort_path: re-enumerate\\nstop_conditions: full gate green\\nverification: no missing args\\ncounterexamples: backwards compatible change"}',
                tool_calls=[],
                provider="fake",
            )

    client = FakeClient()
    out = reflect_after_run(
        mode="auto",
        llm_client=client,
        store=store,
        session_id="s1",
        messages=[
            SimpleNamespace(role="user", content="change API", reasoning_content="PRIVATE_REASONING"),
            SimpleNamespace(role="assistant", content="done", reasoning_content="MORE_PRIVATE_REASONING"),
        ],
        rounds=8,
        tool_trace=[{"name": "read_file", "arguments": {"path": "x"}, "status": "success"}] * 2,
        run_end_reason="completed",
        final_answer="done",
        source_model="p/m",
    )
    assert out.saved_ref.startswith("method:fresh-callsite-")
    assert len(client.calls) == 1
    wire = str(client.calls[0]["messages"])
    assert "PRIVATE_REASONING" not in wire
    assert "MORE_PRIVATE_REASONING" not in wire
    saved_record = store.get(out.saved_ref)
    assert saved_record is not None
    assert saved_record.status == "candidate"


def test_reflection_uses_one_teacher_fallback_on_invalid_structure(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from llm_loop.methods.reflection import reflect_after_run

    root = tmp_path / "seed"
    _seed_method(root, "method-self-distill", status="active", body="core algorithm")
    _seed_method(root, "teacher-one", status="teacher", body="teacher exemplar")
    store = MethodStore(tmp_path / "runtime", seed_dir=root)

    class FakeClient:
        def __init__(self) -> None:
            self.n = 0
        def chat(self, **kwargs):
            self.n += 1
            from llm_loop.llm.client import LLMResponse
            if self.n == 1:
                return LLMResponse(content="not-json", tool_calls=[], provider="fake")
            return LLMResponse(
                content='{"decision":"candidate","name":"bounded retry","description":"use evidence-changing retry","body":"trigger: repeated failure\\ndiscriminator: result class\\nshort_path: alter hypothesis\\nstop_conditions: no new evidence\\nverification: changed observation\\ncounterexamples: transient first failure"}',
                tool_calls=[],
                provider="fake",
            )

    client = FakeClient()
    out = reflect_after_run(
        mode="auto", llm_client=client, store=store, session_id="s2",
        messages=[SimpleNamespace(role="user", content="task")], rounds=7,
        tool_trace=[], run_end_reason="completed", final_answer="done", source_model="p/m",
    )
    assert out.saved_ref
    assert out.used_teacher_fallback is True
    assert client.n == 2
    saved = store.get(out.saved_ref)
    assert saved is not None
    assert saved.teacher_refs == ("method:teacher-one",)


def test_seed_lifecycle_is_copy_on_write_and_never_mutates_tracked_seed(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    runtime = tmp_path / "runtime"
    _seed_method(seed, "seed-candidate", status="candidate", body="seed bytes")
    seed_path = seed / "seed-candidate" / "METHOD.md"
    before = seed_path.read_bytes()
    store = MethodStore(runtime, seed_dir=seed)

    store.record_qualification(
        "method:seed-candidate",
        task_ref="episode:unseen",
        verdict="pass",
        mechanism="pass",
        task_benefit="pass",
        promotion="pass",
    )
    qualified = store.update_status("method:seed-candidate", "qualified")
    assert qualified.status == "qualified"
    assert seed_path.read_bytes() == before
    assert (runtime / "seed-candidate" / "METHOD.md").exists()
    assert (runtime / "seed-candidate" / "qualification.jsonl").exists()
