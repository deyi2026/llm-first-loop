from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.config import Settings
from llm_loop.core.history import validate_tool_call_pairing
from llm_loop.core.loop.engine import LoopEngine
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.recent_continuity import (
    RECENT_CONTINUITY_REF_KEY,
    apply_recent_continuity_suffix,
    attach_recent_continuity_anchor,
    latest_model_assistant_before_turn,
)
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMResponse
from llm_loop.memory.episode import EpisodeStore
from llm_loop.tools.registry import ToolRegistry


class _PreDispatchCrash(BaseException):
    """No provider output/finalizer receipt, as in a killed native process."""


class _Client:
    def __init__(self, *, crash: bool = False) -> None:
        self.crash = crash
        self.calls: list[list[dict]] = []

    def _response(self, messages: list[dict]) -> LLMResponse:
        self.calls.append([dict(message) for message in messages])
        if self.crash:
            raise _PreDispatchCrash
        return LLMResponse(
            content="Remembered code TEST-CODE and units [47, 71, 109]. READY",
            reasoning_content="HIDDEN-REASONING-MUST-NOT-REPLAY",
            tool_calls=[],
            provider="fake",
        )

    def chat(self, messages, tools, **kwargs):
        return self._response(messages)

    def chat_stream(self, messages, tools, **kwargs):
        yield from ()
        return self._response(messages)


def _engine(root: Path, client: _Client) -> tuple[LoopEngine, SessionStore]:
    events = EventStore(root / "events")
    sessions = SessionStore(root / "sessions", event_store=events)
    engine = LoopEngine(
        llm_client=client,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        memory=None,  # type: ignore[arg-type]
        session=sessions,
        settings=Settings(
            llm_api_key="test",
            llm_base_url="https://example.invalid/v1",
            llm_model="fake",
            data_dir=str(root / "data"),
            extract_enabled=False,
            summary_mode="off",
        ),
        episode_store=EpisodeStore(root / "episodes"),
        event_store=events,
    )
    return engine, sessions


@pytest.mark.parametrize("crashes", [1, 2])
def test_restart_after_durable_ingress_preserves_previous_visible_answer(
    tmp_path: Path, crashes: int
) -> None:
    first_client = _Client()
    first_engine, sessions = _engine(tmp_path, first_client)
    sid = sessions.create()
    first_engine.run(sid, "OLD-HUMAN-INSTRUCTION")
    first_engine.close()

    pending_texts = [f"Write the remembered result now. Attempt {i}." for i in range(crashes)]
    for text in pending_texts:
        crashing_client = _Client(crash=True)
        crashing_engine, _ = _engine(tmp_path, crashing_client)
        with pytest.raises(_PreDispatchCrash):
            crashing_engine.run(sid, text)
        crashing_engine.close()
        assert any("TEST-CODE" in str(m.get("content")) for m in crashing_client.calls[0])

    resumed_client = _Client()
    resumed_engine, reloaded = _engine(tmp_path, resumed_client)
    persisted = reloaded._load_from_event_log(sid)
    assert persisted is not None
    assert persisted.messages[-1].role == "user"
    assert persisted.messages[-1].content == pending_texts[-1]
    assert persisted.messages[-1].metadata.get(RECENT_CONTINUITY_REF_KEY)
    assert RECENT_CONTINUITY_REF_KEY not in persisted.messages[-1].to_llm_dict()
    prior = reloaded.load(sid).messages[1]
    assert isinstance(prior, Message)
    assert prior.metadata.get("resolved_episode_ref")
    resumed_engine.run(sid, "Continue, using the remembered facts.")
    resumed_engine.close()

    wire = resumed_client.calls[0]
    answers = [m for m in wire if m.get("role") == "assistant"]
    assert {"role": "assistant", "content": prior.content} in answers
    visible = "\n".join(str(m.get("content") or "") for m in wire)
    assert "TEST-CODE" in visible
    assert "[47, 71, 109]" in visible
    assert "OLD-HUMAN-INSTRUCTION" not in visible
    assert "HIDDEN-REASONING-MUST-NOT-REPLAY" not in visible
    assert all("reasoning_content" not in m for m in answers)
    assert [m["content"] for m in wire if m.get("role") == "user"] == pending_texts + [
        "Continue, using the remembered facts."
    ]


def _human(text: str) -> Message:
    return Message(
        role="user",
        content=text,
        source=MessageSource.USER,
        metadata={"origin_layer": "user_instruction", "program_origin": False},
    )


def _completed() -> Message:
    return Message(
        role="assistant",
        content="VISIBLE-FACT",
        source=MessageSource.USER,
        metadata={
            "answer_origin": "model",
            "run_end_reason": "completed",
            "episode_resolution_candidate": True,
            "resolved_episode_ref": "episode:s:0:anchor",
        },
    )


@pytest.mark.parametrize("ref", [None, "", 7, "not-an-episode", "episode:s:0:wrong"])
def test_missing_or_mismatched_anchor_does_not_cross_human_boundary(ref: object) -> None:
    pending = _human("unresolved task")
    pending.metadata[RECENT_CONTINUITY_REF_KEY] = ref
    messages = [_human("old task"), _completed(), pending, _human("current task")]
    assert latest_model_assistant_before_turn(messages, 3) is None


@pytest.mark.parametrize(
    "output",
    [
        Message(
            role="assistant",
            content="PARTIAL",
            source=MessageSource.USER,
            metadata={"llm_interrupted": True},
        ),
        Message(
            role="assistant",
            content="PROGRAM",
            source=MessageSource.SYSTEM,
            metadata={"answer_origin": "program"},
        ),
        Message(role="tool", content="RECEIPT", source=MessageSource.TOOL, tool_call_id="tc"),
        Message(role="assistant", content="", source=MessageSource.USER, tool_calls=[{"id": "tc"}]),
    ],
)
def test_output_after_anchored_ingress_blocks_older_answer_recovery(output: Message) -> None:
    messages = [_human("old"), _completed(), _human("pending")]
    attach_recent_continuity_anchor(messages, 2)
    messages.extend([output, _human("current")])
    assert latest_model_assistant_before_turn(messages, 4) is None


@pytest.mark.parametrize(
    "change",
    [
        {"run_end_reason": "cancelled"},
        {"episode_resolution_candidate": False},
        {"answer_origin": "program"},
        {"llm_interrupted": True},
        {"delegated_span_state": "closed", "delegated_span_ref": "delegated:s:0:closed"},
    ],
)
def test_anchor_never_restores_unproven_or_ineligible_answer(change: dict) -> None:
    answer = _completed()
    answer.metadata.update(change)
    pending = _human("pending")
    pending.metadata[RECENT_CONTINUITY_REF_KEY] = "episode:s:0:anchor"
    messages = [_human("old"), answer, pending, _human("current")]
    assert latest_model_assistant_before_turn(messages, 3) is None


def test_anchor_requires_completed_episode_and_genuine_ingress() -> None:
    answer = _completed()
    answer.metadata.pop("resolved_episode_ref")
    pending = _human("pending")
    messages = [_human("old"), answer, pending]
    attach_recent_continuity_anchor(messages, 2)
    assert RECENT_CONTINUITY_REF_KEY not in pending.metadata
    answer.metadata["resolved_episode_ref"] = "episode:s:0:anchor"
    pending.metadata["ingress_delegated"] = True
    attach_recent_continuity_anchor(messages, 2)
    assert RECENT_CONTINUITY_REF_KEY not in pending.metadata


def test_different_anchors_in_unanswered_chain_do_not_search_older_history() -> None:
    messages = [_human("old"), _completed(), _human("pending"), _human("pending again")]
    attach_recent_continuity_anchor(messages, 2)
    messages[3].metadata[RECENT_CONTINUITY_REF_KEY] = "episode:s:0:different"
    messages.append(_human("current"))
    assert latest_model_assistant_before_turn(messages, 4) is None


def test_recovered_answer_stays_before_current_turn_tool_protocol() -> None:
    messages = [_human("old"), _completed(), _human("pending")]
    messages[0].metadata["resolved_episode_ref"] = "episode:s:0:anchor"
    attach_recent_continuity_anchor(messages, 2)
    current = _human("inspect")
    declaration = Message(
        role="assistant",
        content="",
        source=MessageSource.USER,
        tool_calls=[
            {"id": "tc", "type": "function", "function": {"name": "read", "arguments": "{}"}}
        ],
    )
    receipt = Message(role="tool", content="OK", source=MessageSource.TOOL, tool_call_id="tc")
    messages.extend([current, declaration, receipt])
    built = [
        {"role": "system", "content": "SYS"},
        current.to_llm_dict(),
        declaration.to_llm_dict(),
        receipt.to_llm_dict(),
    ]
    out, info = apply_recent_continuity_suffix(built, session_messages=messages, current_turn_ref=3)
    assert info["source"] == "recent_assistant_sticky"
    assert out[1] == {"role": "assistant", "content": "VISIBLE-FACT"}
    assert out[2:] == built[1:]
    assert validate_tool_call_pairing(out) == []
