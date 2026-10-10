from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest

from llm_loop.introspection.registry_experience import execute as execute_experience_tool
from llm_loop.introspection.registry_experience import tool_defs as experience_tool_defs
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.tools_status import run_search_records
from llm_loop.memory.retriever import SemanticRetriever
from llm_loop.methods.store import MethodStore


class _Host:
    def __init__(self, store: MethodStore) -> None:
        self.method_store = store
        self.experience_store = None
        self.audit_rows: list[tuple[str, dict, str]] = []
        self.episode_ref = "episode:method-test-session:1:feedface"

    def audit(self, tool_name: str, arguments: dict, result_status: str) -> None:
        self.audit_rows.append((tool_name, arguments, result_status))

    def current_session_id(self) -> str:
        return "method-test-session"

    def current_episode_ref(self) -> str:
        return self.episode_ref

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


# EVO-20260929-5283ab1b P2: save_candidate now enforces the six-section Card
# Contract at the persistence boundary, so every fixture body that flows through
# save_candidate (not _seed_method, which writes files directly) must comply.
_CONTRACT_BODY = (
    "## Trigger\n"
    "need the known-good path\n\n"
    "## Discriminator\n"
    "task matches the recorded scenario\n\n"
    "## Short path\n"
    "read -> apply -> verify\n\n"
    "## Stop conditions\n"
    "verification fails or evidence missing\n\n"
    "## Verification\n"
    "pytest green\n\n"
    "## Counterexamples\n"
    "SSR page\n"
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


def test_method_discovery_v2_matches_id_fragments_and_partial_terms(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    _seed_method(
        root,
        "poc-a-b-6dd78baba7e8",
        body="冻结件 PoC 验证法：预写边界、判定器、A/B、审计链",
    )
    _seed_method(
        root,
        "lfl-mirror-qualified-worktree-33ba78f2f2e7",
        status="active",
        body="restart mirror worktree 服务上线，推进 deployment 代次并验收",
    )
    store = MethodStore(root)

    by_id_fragment = store.list("poc-a-b", 5)
    assert by_id_fragment[0]["key"] == "method:poc-a-b-6dd78baba7e8"

    # Discovery no longer requires every mixed-language term to match.  A query may
    # include broader task words while the relevant card wins on coverage + field weight.
    deploy = store.list("restart deploy mirror worktree 服务上线 部署 代次", 5)
    assert deploy[0]["key"] == "method:lfl-mirror-qualified-worktree-33ba78f2f2e7"
    assert deploy[0]["task_applicability"] == "not_evaluated"

    _seed_method(root, "semantic-operation", status="active", body="browser navigate semantic execution")
    _seed_method(root, "incidental-navigation-note", body="diagnostic note", status="candidate")
    incidental = root / "incidental-navigation-note" / "METHOD.md"
    incidental.write_text(
        incidental.read_text(encoding="utf-8").replace(
            "description: diagnostic method incidental-navigation-note",
            "description: navigate was mentioned incidentally",
        ),
        encoding="utf-8",
    )
    navigate = MethodStore(root).list("navigate", 5)
    assert navigate[0]["key"] == "method:semantic-operation"


def test_method_freshness_reports_contract_change_without_judging_applicability(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    seed = workspace / "methods"
    runtime = workspace / "data" / "methods"
    contract = workspace / "docs" / "contract.md"
    contract.parent.mkdir(parents=True)
    contract.write_text("v1 contract\n", encoding="utf-8")
    method_dir = seed / "deploy-method"
    method_dir.mkdir(parents=True)
    (method_dir / "METHOD.md").write_text(
        "---\n"
        "method_id: deploy-method\n"
        "name: deploy method\n"
        "description: deployment workflow\n"
        "status: candidate\n"
        "freshness_refs: docs/contract.md\n"
        "---\n"
        "## Trigger\ndeploy\n",
        encoding="utf-8",
    )
    store = MethodStore(runtime, seed_dir=seed)

    store.record_qualification(
        "method:deploy-method",
        task_ref="episode:freshness:2:bb",
        verdict="pass",
        mechanism="pass",
        task_benefit="pass",
        promotion="not_evaluated",
    )
    current = store.list("method:deploy-method", 1)[0]
    assert current["freshness"]["state"] == "current"
    assert current["task_applicability"] == "not_evaluated"

    contract.write_text("v2 changed contract\n", encoding="utf-8")
    changed = store.list("method:deploy-method", 1)[0]
    assert changed["freshness"]["state"] == "changed"
    assert changed["freshness"]["changed_refs"] == ["docs/contract.md"]
    # A contract delta is only a mechanical fact; the program still does not decide
    # whether the Method remains semantically applicable.
    assert changed["task_applicability"] == "not_evaluated"

    searcher = RecordSearcher(audit_dir=workspace / "audit", method_store=store)
    rendered = run_search_records(
        _Ctx(),
        lambda **kwargs: searcher.search(**kwargs),
        {"kind": "method", "query": "method:deploy-method", "limit": 1},
        lambda: "",
    )
    assert "freshness=changed" in rendered.content
    assert "docs/contract.md" in rendered.content


def test_method_discovery_v2_semantic_channel_recovers_nonlexical_match(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    _seed_method(root, "deploy-flow", status="active", body="publish generation then restart services")
    _seed_method(root, "unrelated", body="inspect parser diagnostics")
    store = MethodStore(root)
    assert store.list("release", 5) == []

    class FakeSemanticEmbedder:
        provider = "fake"
        vector_version = "fake-method-v1"

        def embed(self, text: str) -> list[float]:
            raw = text.lower()
            if "release" in raw or "publish generation" in raw or "deploy-flow" in raw:
                return [1.0, 0.0]
            return [0.0, 1.0]

    retriever = SemanticRetriever(FakeSemanticEmbedder(), threshold=0.8)
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        method_store=store,
        semantic_retriever=retriever,
    )
    rows = searcher.search(kind="method", query="release", limit=5)
    assert rows[0]["key"] == "method:deploy-flow"
    assert rows[0]["task_applicability"] == "not_evaluated"


def test_semantic_method_receipt_budget_keeps_top_two_model_visible() -> None:
    rows = [
        {
            "kind": "method",
            "summary": f"method-{idx}",
            "key": f"method:m-{idx}",
            "status": "candidate",
            "description": f"description-{idx}-" + ("x" * 600),
            "task_applicability": "not_evaluated",
            "_method_semantic_discovery": True,
        }
        for idx in range(5)
    ]
    rendered = run_search_records(
        _Ctx(),
        lambda **kwargs: rows[: kwargs["limit"]],
        {"kind": "method", "query": "abstract task", "limit": 5},
        lambda: "",
    )

    assert "method:m-0" in rendered.content
    assert "method:m-1" in rendered.content
    assert "method:m-2" not in rendered.content
    assert "内部保留 5 条召回" in rendered.content
    assert "top1 compact card + rank2 alternate ref" in rendered.content
    assert "task_applicability=not_evaluated" in rendered.content
    assert "x" * 250 not in rendered.content
    assert "description-1" not in rendered.content
    assert len(rendered.content) < 900


def test_lexical_method_receipt_is_not_subject_to_semantic_budget() -> None:
    rows = [
        {
            "kind": "method",
            "summary": f"method-{idx}",
            "key": f"method:m-{idx}",
            "status": "candidate",
            "description": f"description-{idx}",
            "task_applicability": "not_evaluated",
        }
        for idx in range(5)
    ]
    rendered = run_search_records(
        _Ctx(),
        lambda **kwargs: rows[: kwargs["limit"]],
        {"kind": "method", "query": "literal keyword", "limit": 5},
        lambda: "",
    )

    assert "method:m-4" in rendered.content
    assert "Method semantic 候选预算" not in rendered.content


def test_candidate_is_immutable_and_cannot_jump_directly_active(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    first = store.save_candidate(name="hydrate trace", description="trace producer", body=_CONTRACT_BODY)
    second = store.save_candidate(name="hydrate trace", description="trace producer", body=_CONTRACT_BODY)
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
    record = store.save_candidate(name="api refresh", description="fresh callsites", body=_CONTRACT_BODY)

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
        task_type="code-edit",
    )
    qualified = store.update_status(record.method_ref, "qualified")
    assert qualified.status == "qualified"

    # EVO-20261010-994e30f4: single-domain pass evidence cannot activate yet.
    try:
        store.update_status(record.method_ref, "active")
    except ValueError as exc:
        assert "task_type" in str(exc)
    else:
        raise AssertionError("single-domain activation must be blocked")

    store.record_qualification(
        record.method_ref,
        task_ref="episode:unseen-2",
        verdict="pass",
        mechanism="pass",
        task_benefit="pass",
        evidence_refs=["evidence:2"],
        task_type=" Browser ",
    )
    entries = store.qualification_entries(record.method_ref)
    assert [e["task_type"] for e in entries] == ["code-edit", "browser"]
    active = store.update_status(record.method_ref, "active")
    assert active.status == "active"
    # Idempotent re-assert of active stays available (grandfather clause:
    # the gate only applies to transitions into active).
    still = store.update_status(record.method_ref, "active")
    assert still.status == "active"


def test_same_source_episode_cannot_supply_promotion_pass(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="source-bound",
        description="independent qualification required",
        body=_CONTRACT_BODY,
        source_episode_refs=["episode:s1:1:aa"],
    )
    try:
        store.record_qualification(
            record.method_ref,
            task_ref="episode:s1:1:aa",
            verdict="pass",
            mechanism="pass",
            task_benefit="pass",
            promotion="pass",
        )
    except ValueError as exc:
        assert "independent" in str(exc)
    else:
        raise AssertionError("same source episode must not authorize promotion")

    # An independent later episode may legitimately authorize promotion.
    independent = store.record_qualification(
        record.method_ref,
        task_ref="episode:s1:9:bb",
        verdict="pass",
        mechanism="pass",
        task_benefit="pass",
        promotion="pass",
    )
    assert independent["promotion"] == "pass"


def test_activation_task_type_gate_counts_and_grandfather_semantics(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(name="gate probe", description="type gate", body=_CONTRACT_BODY)

    # Only verdict=pass entries with a declared task_type count toward diversity.
    store.record_qualification(record.method_ref, task_ref="episode:x1", verdict="fail", task_type="browser")
    store.record_qualification(record.method_ref, task_ref="episode:x2", verdict="mixed", task_type="writing")
    store.record_qualification(record.method_ref, task_ref="episode:x3", verdict="not_evaluated", task_type="diagnosis")
    store.record_qualification(record.method_ref, task_ref="episode:x4", verdict="pass", task_type="")
    store.record_qualification(
        record.method_ref, task_ref="episode:x5", verdict="pass", mechanism="pass",
        task_benefit="pass", promotion="pass", task_type="code-edit",
    )
    store.update_status(record.method_ref, "qualified")
    try:
        store.update_status(record.method_ref, "active")
    except ValueError as exc:
        assert "task_type" in str(exc)
    else:
        raise AssertionError("non-pass/unknown declarations must not satisfy the gate")

    # Case/format variants collapse to one type and must not fake diversity.
    store.record_qualification(record.method_ref, task_ref="episode:x6", verdict="pass", task_type="CODE_EDIT")
    try:
        store.update_status(record.method_ref, "active")
    except ValueError as exc:
        assert "task_type" in str(exc)
    else:
        raise AssertionError("variant spellings must collapse to a single task_type")

    store.record_qualification(record.method_ref, task_ref="episode:x7", verdict="pass", task_type="browser")
    assert store.update_status(record.method_ref, "active").status == "active"

    # Grandfather: a legacy card that was already active re-asserts fine, but
    # leaving and re-entering active re-applies the gate.
    legacy = store.save_candidate(name="legacy active", description="predates gate", body=_CONTRACT_BODY)
    legacy_path = Path(legacy.path)
    legacy_path.write_text(
        legacy_path.read_text(encoding="utf-8").replace("status: candidate", "status: active"),
        encoding="utf-8",
    )
    store2 = MethodStore(tmp_path / "methods")
    reloaded = store2.get(legacy.method_ref)
    assert reloaded is not None and reloaded.status == "active"
    assert store2.update_status(legacy.method_ref, "active").status == "active"
    assert store2.update_status(legacy.method_ref, "hold").status == "hold"
    try:
        store2.update_status(legacy.method_ref, "active")
    except ValueError as exc:
        assert "task_type" in str(exc)
    else:
        raise AssertionError("re-entering active must pass the cross-task-type gate")


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


def test_method_exact_miss_teaches_discovery_without_silent_fallback(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    _seed_method(root, "semantic-operation", status="active", body="browser navigate method")
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", method_store=MethodStore(root))

    exact_miss = run_search_records(
        _Ctx(),
        lambda **kwargs: searcher.search(**kwargs),
        {"kind": "method", "query": "method:navigate", "limit": 10},
        lambda: "",
    )
    assert "未找到匹配 'method:navigate'" in exact_miss.content
    assert "method: 仅用于已返回的 stable ref" in exact_miss.content
    assert 'query="navigate"' in exact_miss.content
    assert "method:semantic-operation" not in exact_miss.content

    discovery = run_search_records(
        _Ctx(),
        lambda **kwargs: searcher.search(**kwargs),
        {"kind": "method", "query": "navigate", "limit": 10},
        lambda: "",
    )
    assert "method:semantic-operation" in discovery.content
    assert "projection_complete=False" not in discovery.content


def test_method_use_receipt_is_append_only_observation_not_lifecycle_transition(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    runtime = tmp_path / "runtime"
    _seed_method(seed, "root-cause", status="active", body="find first divergent fact")
    store = MethodStore(runtime, seed_dir=seed)

    entry = store.record_use(
        "method:root-cause",
        episode_ref="episode:use-test:2:bead",
        decision="adapted",
        model="glm/glm-5.3",
        note="Used discriminator but adapted verification to current repo.",
        evidence_refs=["evidence://v1/use"],
    )

    assert entry["decision"] == "adapted"
    assert entry["application_proven"] is True
    assert entry["task_benefit"] == "not_evaluated"
    assert entry["promotion"] == "not_evaluated"
    assert entry["method_status"] == "active"
    assert entry["method_content_hash"] == store.get("method:root-cause").content_hash
    assert store.get("method:root-cause").status == "active"
    # Recording use of a tracked seed must not create a mutable Method overlay.
    assert not (runtime / "root-cause" / "METHOD.md").exists()
    assert store.usage_entries("method:root-cause") == [entry]


def test_method_manage_record_use_derives_episode_and_model_and_never_promotes(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(name="bounded lookup", description="reuse known path", body=_CONTRACT_BODY)
    host = _Host(store)
    host.episode_ref = "episode:method-test-session:77:use"

    from llm_loop.core.run_context import current_model_label

    token = current_model_label.set("glm/glm-5.3")
    try:
        result = execute_experience_tool(
            "method_manage",
            {
                "action": "record_use",
                "method_ref": record.method_ref,
                "use_decision": "applied",
                "note": "Applied the bounded lookup path.",
                "evidence_refs": ["evidence://v1/applied"],
            },
            cast(Any, host),
        )
    finally:
        current_model_label.reset(token)

    assert result is not None and result.status.value == "success"
    entry = store.usage_entries(record.method_ref)[-1]
    assert entry["episode_ref"] == "episode:method-test-session:77:use"
    assert entry["model"] == "glm/glm-5.3"
    assert entry["decision"] == "applied"
    assert entry["application_proven"] is True
    assert store.get(record.method_ref).status == "candidate"
    assert store.qualification_entries(record.method_ref) == []
    assert host.audit_rows[-1][0] == "record_method_use"


def test_method_manage_annotate_freshness_routes_and_reports_state(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(name="annotated card", description="legacy without refs", body=_CONTRACT_BODY)
    host = _Host(store)

    ok = execute_experience_tool(
        "method_manage",
        {"action": "annotate_freshness", "method_ref": record.method_ref, "freshness_refs": ["src/x.py"]},
        cast(Any, host),
    )
    assert ok is not None and ok.status.value == "success"
    assert "unbaselined" in ok.content
    assert store.get(record.method_ref).freshness_refs == ("src/x.py",)

    bad_ref = execute_experience_tool(
        "method_manage",
        {"action": "annotate_freshness", "method_ref": "not-a-method-ref", "freshness_refs": ["src/x.py"]},
        cast(Any, host),
    )
    assert bad_ref is not None and bad_ref.status.value == "failure"

    unsafe = execute_experience_tool(
        "method_manage",
        {"action": "annotate_freshness", "method_ref": record.method_ref, "freshness_refs": ["../escape.txt"]},
        cast(Any, host),
    )
    assert unsafe is not None and unsafe.status.value == "failure"
    assert store.get(record.method_ref).freshness_refs == ("src/x.py",)  # unchanged after rejected attempts


def test_method_tools_persist_candidate_qualification_and_lifecycle(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    host = _Host(store)
    tool_defs = {d["name"]: d for d in experience_tool_defs()}
    assert "method_manage" in tool_defs
    assert {"save_method_candidate", "record_method_qualification", "refine_method"}.isdisjoint(tool_defs)
    save_props = tool_defs["method_manage"]["parameters"]["properties"]
    assert "record_use" in tool_defs["method_manage"]["parameters"]["properties"]["action"]["enum"]
    assert save_props["use_decision"]["enum"] == ["applied", "adapted", "not_applicable", "rejected"]
    assert "source_model" not in save_props
    assert "source_episode_refs" not in save_props
    assert "teacher_ref" not in save_props
    assert "task_ref" not in save_props

    from llm_loop.core.run_context import current_model_label

    model_token = current_model_label.set("test-provider/test-model")
    try:
        saved = execute_experience_tool(
            "method_manage",
            {"action": "save_candidate", "name": "trace source", "description": "follow provenance（当前性验证：先 grep -n provenance src/ 确认）", "body": _CONTRACT_BODY},
            cast(Any, host),
        )
    finally:
        current_model_label.reset(model_token)
    assert saved is not None and saved.status.value == "success"
    ref = saved.content.split()[1]
    persisted = store.get(ref)
    assert persisted is not None
    assert persisted.source_model == "test-provider/test-model"
    assert persisted.source_episode_refs == ("episode:method-test-session:1:feedface",)

    blocked = execute_experience_tool(
        "method_manage", {"action": "refine", "method_ref": ref, "transition": "activate"}, cast(Any, host)
    )
    assert blocked is not None and blocked.status.value == "failure"

    # Qualification identity must come from the runtime current Episode.  The
    # legacy/spoofed caller task_ref is ignored and cannot manufacture independence.
    host.episode_ref = "episode:method-test-session:9:qualification"
    qualified = execute_experience_tool(
        "method_manage",
        {
            "action": "record_qualification",
            "method_ref": ref,
            "task_ref": "episode:spoofed-caller-ref",
            "verdict": "pass",
            "mechanism": "pass",
            "task_benefit": "pass",
            "promotion": "pass",
            "task_type": "Code Edit",
        },
        cast(Any, host),
    )
    assert qualified is not None and qualified.status.value == "success"
    entry = store.qualification_entries(ref)[-1]
    assert entry["qualification_episode_ref"] == "episode:method-test-session:9:qualification"
    assert entry["task_ref"] == "episode:method-test-session:9:qualification"
    assert entry["task_ref"] != "episode:spoofed-caller-ref"
    assert entry["task_type"] == "code-edit"
    moved = execute_experience_tool(
        "method_manage", {"action": "refine", "method_ref": ref, "transition": "qualify"}, cast(Any, host)
    )
    assert moved is not None and moved.status.value == "success"

    # EVO-20261010-994e30f4: single-domain evidence cannot activate via the tool layer.
    blocked_activate = execute_experience_tool(
        "method_manage", {"action": "refine", "method_ref": ref, "transition": "activate"}, cast(Any, host)
    )
    assert blocked_activate is not None and blocked_activate.status.value == "failure"
    assert "task_type" in blocked_activate.content

    host.episode_ref = "episode:method-test-session:10:cross-domain"
    cross_domain = execute_experience_tool(
        "method_manage",
        {
            "action": "record_qualification",
            "method_ref": ref,
            "verdict": "pass",
            "mechanism": "pass",
            "task_benefit": "pass",
            "task_type": "browser",
        },
        cast(Any, host),
    )
    assert cross_domain is not None and cross_domain.status.value == "success"
    assert "task_type=browser" in cross_domain.content
    activated = execute_experience_tool(
        "method_manage", {"action": "refine", "method_ref": ref, "transition": "activate"}, cast(Any, host)
    )
    assert activated is not None and activated.status.value == "success"


def test_model_facing_method_writes_require_runtime_episode_provenance(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    host = _Host(store)
    host.episode_ref = ""

    saved = execute_experience_tool(
        "method_manage",
        {"action": "save_candidate", "name": "no source", "description": "must reject（当前性验证：先 grep 确认）", "body": _CONTRACT_BODY},
        cast(Any, host),
    )
    assert saved is not None and saved.status.value == "failure"
    assert "provenance" in saved.content

    record = store.save_candidate(name="existing", description="programmatic seed", body=_CONTRACT_BODY)
    qualified = execute_experience_tool(
        "method_manage",
        {
            "action": "record_qualification",
            "method_ref": record.method_ref,
            "task_ref": "episode:model-invented",
            "promotion": "pass",
        },
        cast(Any, host),
    )
    assert qualified is not None and qualified.status.value == "failure"
    assert "provenance" in qualified.content

    use = execute_experience_tool(
        "method_manage",
        {
            "action": "record_use",
            "method_ref": record.method_ref,
            "use_decision": "applied",
        },
        cast(Any, host),
    )
    assert use is not None and use.status.value == "failure"
    assert "provenance" in use.content


def test_repository_seed_methods_are_complete() -> None:
    root = Path(__file__).resolve().parents[2] / "methods"
    store = MethodStore(root)
    cards = store.list("", 50)
    refs = {c["key"] for c in cards}
    expected = {
        "method:method-semantic-operation",
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
                content='{"decision":"candidate","name":"fresh callsite","description":"refresh current callsites","body":"## Trigger\\nsignature changed\\n\\n## Discriminator\\ncurrent tree\\n\\n## Short path\\nre-enumerate\\n\\n## Stop conditions\\nfull gate green\\n\\n## Verification\\nno missing args\\n\\n## Counterexamples\\nbackwards compatible change"}',
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
                content='{"decision":"candidate","name":"bounded retry","description":"use evidence-changing retry","body":"## Trigger\\nrepeated failure\\n\\n## Discriminator\\nresult class\\n\\n## Short path\\nalter hypothesis\\n\\n## Stop conditions\\nno new evidence\\n\\n## Verification\\nchanged observation\\n\\n## Counterexamples\\ntransient first failure"}',
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


# ── EVO-20260929-5283ab1b P1/P2/P3: journal, disposition basis, card contract, freshness_refs ──


def test_blocked_qualification_lands_in_journal_not_vaporized(tmp_path: Path) -> None:
    """R4-as-journal: a failed qualify must leave a durable, retrievable trace."""
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(name="journal probe", description="blocked transition", body=_CONTRACT_BODY)

    import pytest

    with pytest.raises(ValueError):
        store.update_status(record.method_ref, "qualified")  # no promotion=pass yet

    assert store.get(record.method_ref).status == "candidate"  # lifecycle untouched
    attempts = store.attempt_entries(record.method_ref)
    assert len(attempts) == 1
    entry = attempts[0]
    assert entry["event"] == "lifecycle_transition_attempt"
    assert entry["requested"] == "qualified"
    assert entry["result"] == "blocked"
    assert entry["missing_fact"] == "promotion_pass"
    assert entry["method_status"] == "candidate"
    assert entry["journal_persisted"] is True


def test_refine_failure_reports_journaled_attempt(tmp_path: Path) -> None:
    """Model-facing refine failure carries the journal receipt, not a silent no."""
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(name="tool journal", description="refine path", body=_CONTRACT_BODY)
    host = _Host(store)
    host.episode_ref = "episode:method-test-session:9:qualification"

    result = execute_experience_tool(
        "method_manage",
        {"action": "refine", "method_ref": record.method_ref, "transition": "qualify"},
        cast(Any, host),
    )
    assert result is not None and result.status.value == "failure"
    assert "已落账 lifecycle_transition_attempt" in result.content
    assert "missing_fact=promotion_pass" in result.content
    assert store.attempt_entries(record.method_ref)[0]["episode_ref"].startswith("episode:")


def test_destructive_disposition_requires_independent_basis(tmp_path: Path) -> None:
    """R3: a lone session cannot convict a Method on its own self-judgment."""
    import pytest

    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(name="conviction", description="needs independent basis", body=_CONTRACT_BODY)

    # No basis at all -> blocked, journaled, status untouched.
    with pytest.raises(ValueError) as info:
        store.update_status(record.method_ref, "invalidated")
    assert "independent factual basis" in str(info.value)
    assert store.attempt_entries(record.method_ref)[-1]["missing_fact"] == "independent_disposition_evidence"
    assert store.get(record.method_ref).status == "candidate"

    # One rejected use from a single episode is still not a basis.
    store.record_use(record.method_ref, episode_ref="episode:s1:1:aa", decision="rejected")
    with pytest.raises(ValueError):
        store.update_status(record.method_ref, "invalidated")

    # >=2 distinct episodes rejecting IS a mechanical basis (model still decided).
    store.record_use(record.method_ref, episode_ref="episode:s2:2:bb", decision="rejected")
    invalidated = store.update_status(record.method_ref, "invalidated")
    assert invalidated.status == "invalidated"

    # reopen stays permanently available; nothing was deleted.
    reopened = store.update_status(record.method_ref, "candidate")
    assert reopened.status == "candidate"


def test_disposition_via_independent_qualification_fail(tmp_path: Path) -> None:
    """A qualification verdict=fail is also a mechanical basis for disposition."""

    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(name="fail verdict", description="fail path", body=_CONTRACT_BODY)

    store.record_qualification(
        record.method_ref,
        task_ref="episode:s9:9:zz",
        verdict="fail",
        mechanism="fail",
        task_benefit="mixed",
        promotion="fail",
    )
    retired = store.update_status(record.method_ref, "retired")
    assert retired.status == "retired"


def test_card_contract_rejects_incomplete_bodies(tmp_path: Path) -> None:
    """R5: structure is checked mechanically at the persistence boundary."""
    import pytest

    store = MethodStore(tmp_path / "methods")

    with pytest.raises(ValueError) as info:
        store.save_candidate(name="no sections", description="plain prose", body="just prose, no structure")
    assert "Trigger" in str(info.value)

    placeholder_body = _CONTRACT_BODY.replace("SSR page", "(none)")
    with pytest.raises(ValueError) as info:
        store.save_candidate(name="placeholder", description="empty section", body=placeholder_body)
    assert "Counterexamples" in str(info.value)  # placeholder counts as missing

    ok = store.save_candidate(name="compliant", description="six sections", body=_CONTRACT_BODY)
    assert ok.status == "candidate"


def test_freshness_refs_persist_and_validate(tmp_path: Path) -> None:
    """P3: model-declared refs are persisted; non-relative paths are rejected."""
    import pytest

    store = MethodStore(tmp_path / "methods", workspace_root=tmp_path)

    record = store.save_candidate(
        name="fresh bound",
        description="declares dependencies",
        body=_CONTRACT_BODY,
        freshness_refs=["src/llm_loop/methods/store.py", "docs/DESIGN-20260926-model-variance-containment.md"],
    )
    assert record.freshness_refs == (
        "src/llm_loop/methods/store.py",
        "docs/DESIGN-20260926-model-variance-containment.md",
    )
    # reloaded from disk, not just in-memory
    reloaded = MethodStore(tmp_path / "methods", workspace_root=tmp_path).get(record.method_ref)
    assert reloaded is not None and reloaded.freshness_refs == record.freshness_refs

    with pytest.raises(ValueError):
        store.save_candidate(name="abs path", description="must reject", body=_CONTRACT_BODY, freshness_refs=["/etc/passwd"])
    with pytest.raises(ValueError):
        store.save_candidate(name="traversal", description="must reject", body=_CONTRACT_BODY, freshness_refs=["../outside.txt"])


# ── EVO-20260929-5283ab1b P5-B follow-up: annotate_freshness channel ──
def test_annotate_freshness_updates_only_that_key(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    store = MethodStore(root)
    record = store.save_candidate(name="legacy card", description="no refs declared", body=_CONTRACT_BODY)
    card_path = root / record.method_ref.removeprefix("method:") / "METHOD.md"
    before = card_path.read_text(encoding="utf-8")
    assert "freshness_refs" not in before

    updated = store.annotate_freshness(record.method_ref, ["src/a.py", "docs/b.md"])

    after = card_path.read_text(encoding="utf-8")
    assert updated.freshness_refs == ("src/a.py", "docs/b.md")
    # card body and every other frontmatter field stay byte-identical
    assert after.split("## Trigger", 1)[1] == before.split("## Trigger", 1)[1]
    for key in ("method_id", "name", "description", "status", "created_at"):
        assert re.search(rf"^{key}:.*$", after, re.MULTILINE).group(0) == re.search(rf"^{key}:.*$", before, re.MULTILINE).group(0)
    # no qualification yet → unbaselined until the next qualification
    assert store.freshness(record.method_ref)["state"] == "unbaselined"
    # append-only journal carries old→new
    journal = (root / "annotations.jsonl").read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(journal[-1])
    assert entry["event"] == "annotate_freshness" and entry["old"] == "" and entry["new"] == ["src/a.py", "docs/b.md"]


def test_annotate_freshness_rejects_unsafe_paths_and_keeps_card_intact(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    store = MethodStore(root)
    record = store.save_candidate(name="guard card", description="path safety", body=_CONTRACT_BODY)
    card_path = root / record.method_ref.removeprefix("method:") / "METHOD.md"
    before = card_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        store.annotate_freshness(record.method_ref, ["/etc/passwd"])
    with pytest.raises(ValueError):
        store.annotate_freshness(record.method_ref, ["../outside.txt"])
    assert card_path.read_text(encoding="utf-8") == before

    with pytest.raises(ValueError):
        store.annotate_freshness("method:does-not-exist", ["src/a.py"])


# --- EVO-20260930-429f7c12: zero-signal candidate ranking decay ---


def _seed_timed_method(
    root: Path,
    method_id: str,
    *,
    status: str = "candidate",
    body: str = "timeout retry network diagnostic",
    created_days_ago: float = 0,
) -> None:
    from datetime import timedelta

    from llm_loop.timekeeping import system_local_now

    d = root / method_id
    d.mkdir(parents=True)
    created = (system_local_now() - timedelta(days=created_days_ago)).isoformat()
    (d / "METHOD.md").write_text(
        "---\n"
        f"method_id: {method_id}\n"
        f"name: {method_id}\n"
        f"description: timeout retry network diagnostic {method_id}\n"
        f"status: {status}\n"
        f"created_at: {created}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )


def test_zero_signal_candidate_decays_and_sinks(tmp_path):
    root = tmp_path / "methods"
    _seed_timed_method(root, "stale-card", created_days_ago=40)
    _seed_timed_method(root, "fresh-card", created_days_ago=2)
    _seed_timed_method(root, "live-card", status="active", created_days_ago=90)

    cards = MethodStore(root).list("timeout retry", 10)
    order = [c["key"] for c in cards]
    # Same lexical score; active(+35) > fresh candidate(0, inside grace window)
    # > stale candidate(decayed by (40-7)*2 = 66, capped at 80).
    assert order[0] == "method:live-card"
    assert order[1] == "method:fresh-card"
    assert order[2] == "method:stale-card"
    stale = cards[2]
    assert stale["last_signal_age_days"] is None  # zero signals ever
    assert cards[0]["last_signal_age_days"] is None  # active card never qualified either


def test_signal_restores_candidate_ranking(tmp_path):
    root = tmp_path / "methods"
    _seed_timed_method(root, "signaled-card", created_days_ago=40)

    store = MethodStore(root)
    store.record_qualification("method:signaled-card", task_ref="task:probe", verdict="not_evaluated")

    cards = MethodStore(root).list("timeout retry", 10)
    assert len(cards) == 1
    # Any interaction signal removes the idle-age decay entirely and is projected.
    assert cards[0]["last_signal_age_days"] == 0


def test_hydrated_projection_includes_last_signal_age(tmp_path):
    root = tmp_path / "methods"
    _seed_timed_method(root, "probe-card", created_days_ago=30)
    store = MethodStore(root)
    cards = store.list("method:probe-card", 5)
    assert len(cards) == 1
    assert "last_signal_age_days" in cards[0]
    assert cards[0]["last_signal_age_days"] is None

