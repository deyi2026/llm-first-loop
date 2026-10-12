from __future__ import annotations

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.tools_status import run_search_records


def _saved_store(tmp_path):
    store = ExperienceStore(tmp_path / "experiences")
    filename = store.save(
        ExperienceDocument(
            title="fail-open callsite argument evaluation",
            scenario="observer 内部会吞异常，但调用点参数表达式可能先抛 ValueError",
            root_cause="Python 会在进入被调函数前先求值实参表达式",
            solution="args = tc.arguments if isinstance(tc.arguments, dict) else {}",
            evidence="测试桩把 tc.arguments 设为 str 时可复现 ValueError",
            tags=["fail-open", "observer"],
            source={"session": "fixture", "kind": "verified_test"},
            body="## 说明\n内部 try/except 接不到调用方实参求值异常。",
        )
    )
    return store, filename.removesuffix(".md")


def test_experience_discovery_returns_stable_ref_but_not_full_body(tmp_path):
    store, exp_id = _saved_store(tmp_path)

    results = store.list_active("callsite")

    assert len(results) == 1
    rec = results[0]
    assert rec["key"] == f"experience:{exp_id}"
    assert rec["experience_ref"] == f"experience:{exp_id}"
    assert rec["scenario"].startswith("observer 内部会吞异常")
    assert rec["task_applicability"] == "not_evaluated"
    assert "solution" not in rec
    assert "body" not in rec


def test_exact_experience_ref_hydrates_full_reusable_content(tmp_path):
    store, exp_id = _saved_store(tmp_path)
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)

    results = searcher.search(kind="experience", query=f"experience:{exp_id}")

    assert len(results) == 1
    rec = results[0]
    assert rec["experience_ref"] == f"experience:{exp_id}"
    assert rec["hydrated"] is True
    assert rec["representation"] == "full_record"
    assert rec["projection_complete"] is True
    assert rec["scenario"].startswith("observer 内部会吞异常")
    assert rec["root_cause"] == "Python 会在进入被调函数前先求值实参表达式"
    assert rec["solution"].startswith("args = tc.arguments")
    assert "ValueError" in rec["evidence"]
    assert "内部 try/except" in rec["body"]
    assert rec["source"] == {"session": "fixture", "kind": "verified_test"}
    assert rec["task_applicability"] == "not_evaluated"


def test_search_records_receipt_exposes_discovery_ref_then_exact_body(tmp_path):
    store, exp_id = _saved_store(tmp_path)
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)

    discovery = run_search_records(
        None,
        searcher.search,
        {"kind": "experience", "query": "callsite"},
        lambda: "session-fixture",
    )
    assert discovery.status.value == "success"
    assert f"experience:{exp_id}" in discovery.content
    assert "scenario=" in discovery.content
    assert "task_applicability=not_evaluated" in discovery.content
    assert "solution=" not in discovery.content

    hydrated = run_search_records(
        None,
        searcher.search,
        {"kind": "experience", "query": f"experience:{exp_id}"},
        lambda: "session-fixture",
    )
    assert hydrated.status.value == "success"
    assert f"experience:{exp_id}" in hydrated.content
    assert "root_cause=" in hydrated.content
    assert "Python 会在进入被调函数前先求值实参表达式" in hydrated.content
    assert "solution=" in hydrated.content
    assert "args = tc.arguments if isinstance(tc.arguments, dict) else {}" in hydrated.content
    assert "evidence=" in hydrated.content
    assert "body=" in hydrated.content
    assert "task_applicability=not_evaluated" in hydrated.content
    assert "representation=full_record" in hydrated.content
    assert "projection_complete=true" in hydrated.content
