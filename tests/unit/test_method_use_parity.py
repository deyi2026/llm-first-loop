"""Reading a method must not add a compulsory accounting round to a finished task."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.llm.client import LLMResponse
from llm_loop.methods.store import MethodStore
from llm_loop.web.routes import router


def test_exact_method_read_does_not_delay_final_answer(build_test_engine, tmp_path):
    from llm_loop.event_log.store import EventStore
    class HydrationTool:
        name = "search_records"
        description = "Read the requested method."
        parameters = {"type": "object", "properties": {
            "kind": {"type": "string"}, "query": {"type": "string"},
        }}

        def execute(self, **kwargs):
            return ToolResult(
                tool_call_id="", tool_name="search_records", status=ToolResultStatus.SUCCESS, content="method:parity status=candidate; use the exact source",
            )

    engine, fake = build_test_engine([
        LLMResponse(content="", tool_calls=[
            ToolCall(id="read-method", name="search_records",
                     arguments={"kind": "method", "query": "method:parity"}),
        ], provider="fake"),
        LLMResponse(content="Task complete using the exact source.", tool_calls=[], provider="fake"),
        LLMResponse(content="Unexpected accounting round.", tool_calls=[], provider="fake"),
    ])
    engine.registry.register(HydrationTool())
    engine._event_store = EventStore(tmp_path / "events", enabled=True)
    sid = engine.session.create()
    result = engine.run(sid, "Read the method, apply it, and finish.")
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["status"] == "success", result.tool_calls
    assert result.final_answer == "Task complete using the exact source."
    assert len(fake.calls) == 2
    assert not any(
        message.metadata.get("injection_kind") == "method_use_reminder"
        for message in engine.session.load(sid).messages
    )
    observations = [
        event for event in engine._event_store.read(sid)
        if event.type == "method.usage_observed"
    ]
    assert len(observations) == 1
    assert observations[0].payload["method_refs"] == ["method:parity"]
    assert observations[0].payload["application_proven"] is False


def test_store_and_knowledge_route_allow_status_labels_without_qualification(tmp_path):
    """Lifecycle labels are optional metadata; only destructive disposition keeps an evidence gate."""
    store = MethodStore(tmp_path / "methods")
    body = (
        "## Trigger\nmethod needs a status label\n\n## Discriminator\nstatus is not a use permit\n\n"
        "## Short path\nchoose a label directly\n\n## Stop conditions\nasset disposition is destructive\n\n"
        "## Verification\nread the stored status\n\n## Counterexamples\ninvalidated assets need evidence"
    )
    record = store.save_candidate(
        name="status label without qualification",
        description="Lifecycle labels do not control discovery or use.",
        body=body,
    )
    assert store.qualification_entries(record.method_ref) == []

    app = FastAPI()
    app.state.engine = SimpleNamespace(
        corrections=SimpleNamespace(_experience_store=None, _method_store=store)
    )
    app.include_router(router)
    client = TestClient(app)

    qualified = client.post(
        f"/api/v1/knowledge/methods/{record.method_id}/transition?transition=qualify"
    )
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["status"] == "qualified"
    active = client.post(
        f"/api/v1/knowledge/methods/{record.method_id}/transition?transition=activate"
    )
    assert active.status_code == 200, active.text
    assert active.json()["status"] == "active"
    assert store.qualification_entries(record.method_ref) == []
