from __future__ import annotations

from datetime import UTC, datetime

from llm_loop.llm.chatgpt_surface import ChatGPTSessionBindingStore
from llm_loop.runtime.chatgpt_binding_health import inspect_chatgpt_binding_health

PROJECT_REF = "g-p-health"


class _SessionPresence:
    def __init__(self, states: dict[str, str] | None = None) -> None:
        self.states = states or {}

    def global_presence_state(self, session_id: str) -> str:
        return self.states.get(session_id, "present")


def _exchange(
    store: ChatGPTSessionBindingStore,
    binding,
    *,
    conversation_id: str,
    request_chars: int,
):
    return store.record_exchange(
        binding,
        conversation_id=conversation_id,
        conversation_url=f"https://chatgpt.com/g/{PROJECT_REF}/c/{conversation_id}",
        request_chars=request_chars,
    )


def test_binding_health_reports_prompt_neutral_runtime_metrics(tmp_path):
    store = ChatGPTSessionBindingStore(tmp_path / "sessions")
    binding = store.get_or_create(session_id="s1", project_ref=PROJECT_REF)
    binding = _exchange(
        store,
        binding,
        conversation_id="conv-1",
        request_chars=100,
    )
    store.record_transport_event(binding, event="restore_succeeded")

    health = inspect_chatgpt_binding_health(
        store,
        _SessionPresence({"s1": "present"}),
        segment_max_chars=1_000,
        now=datetime.now(UTC),
    )

    assert health["status"] == "healthy"
    assert health["alerts"] == []
    metrics = health["metrics"]
    assert metrics["bindings_total"] == 1
    assert metrics["sessions_present"] == 1
    assert metrics["total_requests_committed"] == 1
    assert metrics["exchanges_24h"] == 1
    assert metrics["restore_attempts_24h"] == 1
    assert metrics["restore_success_rate_24h"] == 1.0
    assert metrics["segment_pressure_max_ratio"] == 0.1
    assert health["telemetry"]["coverage"] == "event_log_only"
    assert health["telemetry"]["event_count"] == 2


def test_binding_health_alerts_on_recent_restore_failures(tmp_path):
    store = ChatGPTSessionBindingStore(tmp_path / "sessions")
    binding = store.get_or_create(session_id="s1", project_ref=PROJECT_REF)
    binding = _exchange(
        store,
        binding,
        conversation_id="conv-1",
        request_chars=100,
    )
    for _ in range(3):
        store.record_transport_event(
            binding,
            event="restore_failed",
            error_type="BrowserSurfaceLeaseError",
        )

    health = inspect_chatgpt_binding_health(
        store,
        _SessionPresence({"s1": "present"}),
        segment_max_chars=1_000,
        now=datetime.now(UTC),
    )

    assert health["status"] == "critical"
    metrics = health["metrics"]
    assert metrics["restore_failures_24h"] == 3
    assert metrics["restore_success_rate_24h"] == 0.0
    alert = next(row for row in health["alerts"] if row["code"] == "restore_failures_recent")
    assert alert["severity"] == "critical"
    assert alert["count"] == 3


def test_binding_health_alerts_on_rollover_burst_and_segment_pressure(tmp_path):
    store = ChatGPTSessionBindingStore(tmp_path / "sessions")
    binding = store.get_or_create(session_id="s1", project_ref=PROJECT_REF)
    for index in range(4):
        binding = _exchange(
            store,
            binding,
            conversation_id=f"conv-{index}",
            request_chars=100,
        )
        binding = store.rollover(binding, reason="request_cap")
    binding = _exchange(
        store,
        binding,
        conversation_id="conv-pressure",
        request_chars=950,
    )

    health = inspect_chatgpt_binding_health(
        store,
        _SessionPresence({"s1": "present"}),
        segment_max_chars=1_000,
        now=datetime.now(UTC),
    )

    assert health["status"] == "warning"
    metrics = health["metrics"]
    assert metrics["rollovers_1h"] == 4
    assert metrics["max_rollovers_per_session_1h"] == 4
    assert metrics["segment_pressure_sessions"] == 1
    codes = {row["code"] for row in health["alerts"]}
    assert "rollover_burst" in codes
    assert "segment_pressure" in codes


def test_binding_health_keeps_missing_without_tombstone_as_metric_not_gc_fact(tmp_path):
    store = ChatGPTSessionBindingStore(tmp_path / "sessions")
    for index in range(2):
        store.get_or_create(session_id=f"synthetic-{index}", project_ref=PROJECT_REF)

    health = inspect_chatgpt_binding_health(
        store,
        _SessionPresence({"synthetic-0": "missing", "synthetic-1": "missing"}),
        segment_max_chars=1_000,
        now=datetime.now(UTC),
    )

    assert health["status"] == "healthy"
    assert health["metrics"]["sessions_missing_no_tombstone"] == 2
    assert health["metrics"]["gc_eligible_deleted_bindings"] == 0
    assert not any(row["code"] == "binding_identity_backlog" for row in health["alerts"])


def test_binding_health_surfaces_unreadable_session_telemetry(tmp_path):
    store = ChatGPTSessionBindingStore(tmp_path / "sessions")
    store.get_or_create(session_id="s1", project_ref=PROJECT_REF)
    event_path = tmp_path / "sessions" / "s1" / ChatGPTSessionBindingStore.EVENTS
    event_path.write_text("{not-json}\n", encoding="utf-8")

    health = inspect_chatgpt_binding_health(
        store,
        _SessionPresence({"s1": "present"}),
        segment_max_chars=1_000,
        now=datetime.now(UTC),
    )

    assert health["status"] == "critical"
    assert health["metrics"]["telemetry_unreadable_sessions"] == 1
    alert = next(row for row in health["alerts"] if row["code"] == "session_telemetry_unreadable")
    assert alert["severity"] == "critical"
