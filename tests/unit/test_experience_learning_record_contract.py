from __future__ import annotations

from pathlib import Path

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.tools_experience import run_save_experience
from llm_loop.introspection.tools_status import run_search_records


def _doc(
    *,
    title: str,
    record_kind: str,
    verification_state: str,
) -> ExperienceDocument:
    return ExperienceDocument(
        title=title,
        scenario="same drift scenario",
        root_cause="fixture cause",
        solution="fixture handling",
        evidence="fixture:evidence" if verification_state != "unverified" else "",
        tags=["drift"],
        source={"kind": "fixture"},
        status="active",
        record_kind=record_kind,
        verification_state=verification_state,
    )


def test_legacy_document_is_readable_but_not_silently_verified() -> None:
    legacy = """---
title: legacy record
scenario: old
root_cause: old
solution: old
evidence: old
tags: [legacy]
source: {}
status: active
created_at: 2026-09-01T00:00:00+08:00
updated_at: 2026-09-01T00:00:00+08:00
---
legacy body
"""

    doc = ExperienceDocument.from_md(legacy)

    assert doc.record_kind == "experience"
    assert doc.verification_state == "legacy_unclassified"


def test_new_positive_experience_requires_verified_evidence(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path / "experiences")

    unverified = run_save_experience(
        store,
        title="not yet proven",
        scenario="scenario",
        solution="candidate solution",
        record_kind="experience",
        verification_state="unverified",
    )
    no_evidence = run_save_experience(
        store,
        title="claims verified without evidence",
        scenario="scenario",
        solution="candidate solution",
        record_kind="experience",
        verification_state="verified",
    )
    verified = run_save_experience(
        store,
        title="proven solution",
        scenario="scenario",
        solution="working solution",
        record_kind="experience",
        verification_state="verified",
        evidence="fixture:verified-run",
    )

    assert unverified.startswith("[参数错误]")
    assert "record_kind=lesson" in unverified
    assert no_evidence.startswith("[参数错误]")
    assert "evidence" in no_evidence
    assert verified.startswith("[save_experience]")
    assert "record_kind=experience verification_state=verified" in verified


def test_lesson_and_positive_experience_have_separate_discovery(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path / "experiences")
    exp_name = store.save(
        _doc(title="verified positive", record_kind="experience", verification_state="verified")
    )
    lesson_name = store.save(
        _doc(title="failed path lesson", record_kind="lesson", verification_state="disproven")
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)

    experiences = searcher.search(kind="experience", query="drift", limit=20)
    lessons = searcher.search(kind="lesson", query="drift", limit=20)

    assert {row["experience_ref"] for row in experiences} == {
        f"experience:{exp_name.removesuffix('.md')}"
    }
    assert experiences[0]["verification_state"] == "verified"
    assert {row["experience_ref"] for row in lessons} == {
        f"experience:{lesson_name.removesuffix('.md')}"
    }
    assert lessons[0]["record_kind"] == "lesson"
    assert lessons[0]["verification_state"] == "disproven"

    # Stable exact refs remain traceable even through the older experience retrieval entry.
    hydrated = searcher.search(
        kind="experience",
        query=f"experience:{lesson_name.removesuffix('.md')}",
        limit=1,
    )
    assert hydrated[0]["record_kind"] == "lesson"
    assert hydrated[0]["projection_complete"] is True


def test_model_visible_search_receipts_keep_record_type_boundary(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path / "experiences")
    store.save(
        _doc(title="visible lesson", record_kind="lesson", verification_state="disproven")
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)

    lesson_receipt = run_search_records(
        None,
        searcher.search,
        {"kind": "lesson", "query": "visible", "limit": 10},
        lambda: "visible-session",
    )

    assert lesson_receipt.status.value == "success"
    assert "record_kind=lesson" in lesson_receipt.content
    assert "verification_state=disproven" in lesson_receipt.content
