from __future__ import annotations

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.search import RecordSearcher


def _doc(**overrides):
    base = dict(
        title="lifecycle fixture",
        scenario="历史经验场景",
        root_cause="历史根因",
        solution="历史解法",
        evidence="历史证据",
        tags=["lifecycle"],
        source={"kind": "fixture"},
        status="active",
        created_at="2026-09-01T00:00:00+08:00",
        updated_at="2026-09-01T00:00:00+08:00",
        body="正文",
    )
    base.update(overrides)
    return ExperienceDocument(**base)


def test_lifecycle_fields_round_trip_without_changing_applicability():
    doc = _doc(
        superseded_by="experience:EXPERIENCE-20260902-newer",
        promoted_to_rule="RULE-AI-22",
        last_verified_at="2026-09-05T12:00:00+08:00",
    )

    restored = ExperienceDocument.from_md(doc.to_md())

    assert restored.superseded_by == "experience:EXPERIENCE-20260902-newer"
    assert restored.promoted_to_rule == "RULE-AI-22"
    assert restored.last_verified_at == "2026-09-05T12:00:00+08:00"


def test_lifecycle_fields_default_empty_for_legacy_documents():
    legacy = _doc().to_md()
    restored = ExperienceDocument.from_md(legacy)

    assert restored.superseded_by == ""
    assert restored.promoted_to_rule == ""
    assert restored.last_verified_at == ""


def test_discovery_and_hydration_expose_lifecycle_facts(tmp_path):
    store = ExperienceStore(tmp_path / "experiences")
    filename = store.save(
        _doc(
            superseded_by="experience:EXPERIENCE-20260902-newer",
            promoted_to_rule="RULE-AI-22",
            last_verified_at="2026-09-05T12:00:00+08:00",
        )
    )
    exp_id = filename.removesuffix(".md")

    discovery = store.list_active("lifecycle")[0]
    assert discovery["superseded_by"] == "experience:EXPERIENCE-20260902-newer"
    assert discovery["promoted_to_rule"] == "RULE-AI-22"
    assert discovery["last_verified_at"] == "2026-09-05T12:00:00+08:00"
    assert discovery["task_applicability"] == "not_evaluated"

    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)
    hydrated = searcher.search(kind="experience", query=f"experience:{exp_id}")[0]
    assert hydrated["superseded_by"] == "experience:EXPERIENCE-20260902-newer"
    assert hydrated["promoted_to_rule"] == "RULE-AI-22"
    assert hydrated["last_verified_at"] == "2026-09-05T12:00:00+08:00"
    assert hydrated["projection_complete"] is True
    assert hydrated["task_applicability"] == "not_evaluated"


def test_archived_superseded_experience_leaves_discovery_but_exact_ref_still_hydrates(tmp_path):
    store = ExperienceStore(tmp_path / "experiences")
    active_name = store.save(_doc(title="current guidance", scenario="err1210 current"))
    archived = _doc(
        title="historical guidance",
        scenario="err1210 historical",
        status="archived",
        superseded_by=f"experience:{active_name.removesuffix('.md')}",
    )
    archived_path = tmp_path / "experiences" / "EXPERIENCE-20260901-historical-guidance.md"
    archived_path.write_text(archived.to_md(), encoding="utf-8")

    discovery = store.list_active("err1210", limit=20)
    refs = {row["experience_ref"] for row in discovery}
    old_ref = "experience:EXPERIENCE-20260901-historical-guidance"
    assert old_ref not in refs
    assert f"experience:{active_name.removesuffix('.md')}" in refs

    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)
    hydrated = searcher.search(kind="experience", query=old_ref)[0]
    assert hydrated["status"] == "archived"
    assert hydrated["superseded_by"] == f"experience:{active_name.removesuffix('.md')}"
    assert hydrated["projection_complete"] is True
    assert hydrated["task_applicability"] == "not_evaluated"
