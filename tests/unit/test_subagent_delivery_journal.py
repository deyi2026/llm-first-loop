from __future__ import annotations

from llm_loop.core.subagent_delivery import SubAgentDeliveryJournal
from llm_loop.event_log.store import EventStore


def test_delivery_journal_keeps_exact_generation_scoped_transport_facts(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    journal = SubAgentDeliveryJournal(events)
    child = "subagent_delivery_journal"
    parent = "parent-delivery-journal"

    queued = journal.queue_mailbox(
        child_id=child,
        parent_id=parent,
        generation="g1",
        sender_id=parent,
        content="STEER-EXACT",
    )
    report = journal.queue_report(
        child_id=child,
        parent_id=parent,
        generation="g1",
        content="REPORT-EXACT",
    )
    result = journal.result_available(
        child_id=child,
        parent_id=parent,
        generation="g1",
        result={
            "final_answer": "FINAL-EXACT",
            "outcome": "completed",
            "rounds": 2,
            "tool_calls": [{"name": "read_file", "status": "success"}],
            "reports": ["REPORT-EXACT"],
            "truncated": False,
            "refused": False,
            "depth": 0,
            "tokens_in": 10,
            "tokens_out": 5,
        },
        report_ids=[report.report_id],
    )
    cancel = journal.cancel_requested(
        child_id=child,
        parent_id=parent,
        generation="g1",
        reason="parent_lifecycle_cancel",
    )

    assert queued is not None and queued.message_id
    assert report is not None and report.report_id
    assert result is not None and result.result_id
    assert cancel is not None
    assert [row.content for row in journal.pending_mailbox(child, "g1", delivered_ids=set())] == [
        "STEER-EXACT"
    ]
    assert [row.content for row in journal.reports(child, "g1")] == ["REPORT-EXACT"]
    loaded = journal.result(child, "g1")
    assert loaded is not None
    assert loaded.payload["final_answer"] == "FINAL-EXACT"
    assert loaded.payload["tool_calls"] == [{"name": "read_file", "status": "success"}]
    assert loaded.report_ids == (report.report_id,)
    assert journal.cancel_state(child, "g1") is not None

    assert journal.pending_mailbox(child, "g2", delivered_ids=set()) == []
    assert journal.reports(child, "g2") == []
    assert journal.result(child, "g2") is None
    assert journal.cancel_state(child, "g2") is None


def test_pending_mailbox_excludes_ids_already_durable_in_child_transcript(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    journal = SubAgentDeliveryJournal(events)
    queued = journal.queue_mailbox(
        child_id="subagent_delivery_ids",
        parent_id="parent-delivery-ids",
        generation="g1",
        sender_id="parent-delivery-ids",
        content="ONCE",
    )
    assert queued is not None
    assert (
        journal.pending_mailbox("subagent_delivery_ids", "g1", delivered_ids={queued.message_id})
        == []
    )


def test_delivery_journal_disabled_mode_is_explicitly_process_local(tmp_path) -> None:
    events = EventStore(tmp_path / "events-disabled", enabled=False)
    journal = SubAgentDeliveryJournal(events)
    queued = journal.queue_mailbox(
        child_id="subagent-disabled",
        parent_id="parent-disabled",
        generation="g1",
        sender_id="parent-disabled",
        content="legacy-local",
    )
    assert queued is not None
    assert queued.durable is False
    assert journal.pending_mailbox("subagent-disabled", "g1", delivered_ids=set()) == []
