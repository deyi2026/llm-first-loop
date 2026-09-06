"""Exact source-index provenance for message.cache_compacted observability."""

from __future__ import annotations

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt_build.stages.history_projection import (
    _map_compacted_source_indices,
)


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content, source=MessageSource.SYSTEM)


def test_duplicate_content_compaction_reports_distinct_exact_local_indices(monkeypatch):
    """Duplicate role+content messages must never collapse onto the first match."""
    monkeypatch.setenv("COMPRESS_TARGET_RATIO", "0.6")
    duplicate = "same-bytes-" + ("X" * 990)
    msgs = [_msg("assistant", duplicate) for _ in range(10)]
    msgs.append(Message(role="user", content="current task", source=MessageSource.USER))
    compacted_msgs: list[Message] = []
    compacted_indices: list[int] = []

    build_history_messages(
        msgs,
        "",
        max_chars=8_000,
        compact_ratio=0.85,
        session_id="s-dup-index",
        archive_sink=lambda _sid, _msg: None,
        cache_archive_provider="glm",
        cache_compacted_out=compacted_msgs,
        cache_compacted_index_out=compacted_indices,
    )

    assert len(compacted_msgs) >= 2
    assert compacted_indices == list(range(len(compacted_indices)))
    assert len(set(compacted_indices)) == len(compacted_indices)
    assert all(compacted_msgs[i] is msgs[idx] for i, idx in enumerate(compacted_indices))


def test_compacted_local_indices_map_through_prefix_and_filtered_session_indices():
    """Projection-local indices map exactly back to original Session message indices."""
    # base = 2 ephemeral prefix messages + filtered session messages at original indices
    # [1, 4, 7, 9]. Prefix indices are not Session facts and must be dropped.
    assert _map_compacted_source_indices(
        [0, 1, 2, 4, 5],
        prefix_len=2,
        filtered_indices=[1, 4, 7, 9],
    ) == [1, 7, 9]


def test_compacted_source_mapping_never_guesses_out_of_range_indices():
    assert _map_compacted_source_indices(
        [-1, 0, 2, 99],
        prefix_len=1,
        filtered_indices=[5, 8],
    ) == [8]



def test_eighty_eight_duplicate_compactions_keep_eighty_eight_exact_source_indices(monkeypatch):
    """Regression for the real 08:27 event shape: 88 marks must stay 88 distinct seqs."""
    monkeypatch.setenv("COMPRESS_TARGET_RATIO", "0.6")
    duplicate = "D" * 1000
    msgs = [_msg("assistant", duplicate) for _ in range(100)]
    msgs.append(Message(role="user", content="current000", source=MessageSource.USER))
    compacted_indices: list[int] = []

    build_history_messages(
        msgs,
        "",
        max_chars=21_000,
        compact_ratio=0.85,
        session_id="s-88-exact",
        archive_sink=lambda _sid, _msg: None,
        cache_archive_provider="glm",
        cache_compacted_index_out=compacted_indices,
    )

    assert compacted_indices == list(range(88))
    assert len(set(compacted_indices)) == 88

def test_postprocess_emits_explicit_source_seq_and_replay_marks_exact_messages():
    from types import SimpleNamespace

    from llm_loop.core.prompt_build.stages.history_postprocess import run_history_postprocess
    from llm_loop.event_log.model import Event
    from llm_loop.event_log.replay import replay_session

    class _Monitor:
        def note_build_result(self, **_kwargs):
            return None

    events: list[tuple[str, dict]] = []
    sess = SimpleNamespace(
        session_id="s-replay-exact",
        messages=[_msg("assistant", "dup") for _ in range(10)],
        history_anchors={},
    )
    run_history_postprocess(
        cache_compacted_source_box=[2, 5, 8],
        compacted_box=[True],
        compact_view_box=[],
        anchor_box=[],
        filtered_indices=list(range(10)),
        prefix_len=0,
        sess=sess,
        sess_anchor=0,
        provider_id="glm",
        resolved_label="glm/glm-5.3-flash",
        effective_budget=300_000,
        compact_event_seq=0,
        compact_event_was_compacted=False,
        cache_monitor=_Monitor(),
        event_append=lambda _sid, typ, payload: events.append((typ, payload)),
        provider_visible_chars=lambda *_args: 10,
    )
    compact_events = [payload for typ, payload in events if typ == "message.cache_compacted"]
    assert [e["msg_seq"] for e in compact_events] == [2, 5, 8]

    replay_events: list[Event] = [
        Event(
            event_id=f"m{i}", session_id=sess.session_id, seq=i + 1,
            type="message.appended", ts="2026-09-03T00:00:00Z",
            payload={"index": i, "role": "assistant", "content": "dup"},
        )
        for i in range(10)
    ]
    for j, payload in enumerate(compact_events, start=11):
        replay_events.append(
            Event(
                event_id=f"c{j}", session_id=sess.session_id, seq=j,
                type="message.cache_compacted", ts="2026-09-03T00:00:01Z", payload=payload,
            )
        )
    view = replay_session(replay_events)
    marked = [
        i for i, msg in enumerate(view["messages"])
        if "glm" in (msg.get("metadata") or {}).get("cache_compacted_for", [])
    ]
    assert marked == [2, 5, 8]
