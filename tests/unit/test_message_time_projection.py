from __future__ import annotations

from datetime import datetime

from llm_loop.core.history import _message_time_marker, build_history_messages
from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
from llm_loop.core.message import Message, MessageSource
from llm_loop.llm.client import LLMClient


def _human(text: str, ts: float) -> Message:
    return Message(
        role="user",
        content=text,
        source=MessageSource.USER,
        ts=ts,
        metadata=origin_metadata(InjectionLayer.USER_INSTRUCTION),
    )


def test_history_carries_persisted_time_without_changing_human_content() -> None:
    human = _human("TASK", 1_700_000_000.0)
    built = build_history_messages(
        [human],
        "SYS",
        max_chars=50_000,
        preserve_human_message=human,
        current_turn_ref=0,
    )

    user = next(item for item in built if item.get("role") == "user")
    assert user["content"] == "TASK"
    assert user["_message_time_ts"] == human.ts
    assert human.content == "TASK"


def test_program_user_and_legacy_zero_timestamp_get_no_time_marker() -> None:
    program = Message(
        role="user",
        content="status",
        source=MessageSource.USER,
        ts=1_700_000_000.0,
        metadata=origin_metadata(InjectionLayer.STATUS),
    )
    legacy = _human("legacy", 0.0)

    assert _message_time_marker(program) is None
    assert _message_time_marker(legacy) is None


def test_internal_marker_is_stable_when_turn_becomes_historical() -> None:
    first = _human("FIRST-TASK", 1_700_000_000.0)
    first_round = build_history_messages(
        [first],
        "SYS",
        max_chars=50_000,
        preserve_human_message=first,
        current_turn_ref=0,
    )
    first_wire = next(item for item in first_round if item.get("role") == "user")

    assistant = Message(role="assistant", content="done", source=MessageSource.SYSTEM)
    second = _human("SECOND-TASK", 1_700_000_100.0)
    second_round = build_history_messages(
        [first, assistant, second],
        "SYS",
        max_chars=50_000,
        preserve_human_message=second,
        current_turn_ref=2,
    )
    historical_first = next(
        item
        for item in second_round
        if item.get("role") == "user" and item.get("content") == "FIRST-TASK"
    )

    assert historical_first["content"] == first_wire["content"]
    assert historical_first["_message_time_ts"] == first_wire["_message_time_ts"]


def test_llm_client_projects_os_local_time_and_strips_internal_marker() -> None:
    ts = 1_700_000_000.0
    expected = datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")
    client = LLMClient(
        api_key="k",
        base_url="https://fake.local/v1",
        model="m",
        guard_enabled=False,
    )
    internal = [{"role": "user", "content": "TASK", "_message_time_ts": ts}]

    projected = client._project_provider_replay(internal)  # noqa: SLF001

    assert projected == [
        {"role": "user", "content": f"[message_time system_local={expected}]\nTASK"}
    ]
    assert "_message_time_ts" not in projected[0]
    assert internal[0]["content"] == "TASK"
    assert internal[0]["_message_time_ts"] == ts


def test_llm_client_invalid_time_marker_fails_closed_and_strips_field() -> None:
    client = LLMClient(
        api_key="k",
        base_url="https://fake.local/v1",
        model="m",
        guard_enabled=False,
    )
    projected = client._project_provider_replay(  # noqa: SLF001
        [{"role": "user", "content": "TASK", "_message_time_ts": "bad"}]
    )

    assert projected == [{"role": "user", "content": "TASK"}]
