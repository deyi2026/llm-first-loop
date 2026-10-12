"""method.record_use decision telemetry（subject-binding v3 reopen 前置①）.

Covers MethodLearningService._observe_method_use_decisions: one
``method.record_use`` event per successful natural record_use declaration,
no events for other actions/failed rows/empty traces, fail-open on
event-store errors. Registry/audit landings are out of scope here.
"""
from __future__ import annotations

from llm_loop.core.loop.method_learning import MethodLearningService


class _FakeEngine:
    def __init__(self, fail: bool = False) -> None:
        self.events: list[tuple[str, str, dict]] = []
        self.fail = fail

    def _event_append(self, session_id: str, event_type: str, payload: dict):
        if self.fail:
            raise RuntimeError("event store down")
        self.events.append((session_id, event_type, payload))
        return None


def _record_use(ref: str, decision: str, *, status: str = "success", **extra) -> dict:
    args = {
        "action": "record_use",
        "method_ref": ref,
        "episode_ref": extra.pop("episode_ref", "episode:s:1:abc"),
        "method_content_hash": extra.pop("method_content_hash", "deadbeef"),
        "decision": decision,
        **extra,
    }
    return {"name": "method_manage", "arguments": args, "status": status}


def test_one_event_per_successful_record_use() -> None:
    eng = _FakeEngine()
    svc = MethodLearningService(eng)
    svc.post_run(
        "sid-1",
        sess=None,
        rounds=3,
        tool_trace=[
            {"name": "search_records", "arguments": {"kind": "method", "query": "method:m1"}, "status": "success"},
            _record_use("method:m1", "applied"),
            _record_use("method:m2", "not_applicable"),
        ],
        run_end_reason="completed",
        final_answer="ok",
        model_used="prov/model-x",
    )
    evs = [e for e in eng.events if e[1] == "method.record_use"]
    assert [(e[2]["method_ref"], e[2]["decision"]) for e in evs] == [
        ("method:m1", "applied"),
        ("method:m2", "not_applicable"),
    ]
    for _, _, payload in evs:
        assert payload["reason"] == "completed"
        assert payload["rounds"] == 3
        assert payload["model_used"] == "prov/model-x"
        assert payload["episode_ref"] == "episode:s:1:abc"
        assert payload["method_content_hash"] == "deadbeef"


def test_non_record_use_and_failed_rows_emit_nothing() -> None:
    eng = _FakeEngine()
    svc = MethodLearningService(eng)
    svc.post_run(
        "sid-2",
        sess=None,
        rounds=1,
        tool_trace=[
            {"name": "method_manage", "arguments": {"action": "save_candidate", "method_ref": "method:m1"}, "status": "success"},
            _record_use("method:m1", "rejected", status="error"),
            _record_use("   ", "applied"),  # empty ref after strip -> skipped
            _record_use("method:m3", ""),  # empty decision -> skipped
        ],
        run_end_reason="completed",
        final_answer="",
        model_used="prov/model-x",
    )
    assert [e for e in eng.events if e[1] == "method.record_use"] == []


def test_empty_trace_and_decision_without_hydration() -> None:
    eng = _FakeEngine()
    svc = MethodLearningService(eng)
    svc.post_run("sid-3", sess=None, rounds=1, tool_trace=[], run_end_reason="completed", final_answer="", model_used="m")
    assert eng.events == []
    svc.post_run(
        "sid-4",
        sess=None,
        rounds=2,
        tool_trace=[_record_use("method:m9", "adapted")],
        run_end_reason="truncated",
        final_answer="",
        model_used="m",
    )
    evs = [e for e in eng.events if e[1] == "method.record_use"]
    assert len(evs) == 1 and evs[0][2]["reason"] == "truncated"


def test_fail_open_when_event_store_raises() -> None:
    eng = _FakeEngine(fail=True)
    svc = MethodLearningService(eng)
    svc.post_run(
        "sid-5",
        sess=None,
        rounds=1,
        tool_trace=[_record_use("method:m1", "applied")],
        run_end_reason="completed",
        final_answer="",
        model_used="m",
    )  # must not raise


def test_non_dict_arguments_row_is_ignored() -> None:
    eng = _FakeEngine()
    svc = MethodLearningService(eng)
    svc.post_run(
        "sid-6",
        sess=None,
        rounds=1,
        tool_trace=[{"name": "method_manage", "arguments": None, "status": "success"}],
        run_end_reason="completed",
        final_answer="",
        model_used="m",
    )
    assert eng.events == []
