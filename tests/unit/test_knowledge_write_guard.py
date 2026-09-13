import pytest

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.methods.store import MethodStore


def _doc() -> ExperienceDocument:
    return ExperienceDocument(
        title="guarded",
        scenario="s",
        root_cause="r",
        solution="x",
        evidence="e",
        tags=[],
        source={},
    )


def test_experience_store_quarantine_blocks_mutation(tmp_path):
    store = ExperienceStore(tmp_path / "experiences", write_guard=lambda: False)
    with pytest.raises(PermissionError, match="quarantined"):
        store.save(_doc())
    assert not (tmp_path / "experiences").exists()


def test_method_store_quarantine_blocks_candidate_write(tmp_path):
    store = MethodStore(tmp_path / "methods", write_guard=lambda: False)
    with pytest.raises(PermissionError, match="quarantined"):
        store.save_candidate(name="candidate", description="d", body="body")
    assert not (tmp_path / "methods").exists()


def test_write_guard_is_evaluated_at_write_time(tmp_path):
    state = {"safe": True}
    store = MethodStore(tmp_path / "methods", write_guard=lambda: state["safe"])
    record = store.save_candidate(name="first", description="d", body="body-1")
    assert record.method_ref.startswith("method:")
    state["safe"] = False
    with pytest.raises(PermissionError, match="quarantined"):
        store.save_candidate(name="second", description="d", body="body-2")
