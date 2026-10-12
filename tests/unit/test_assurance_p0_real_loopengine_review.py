"""Real LFL LoopEngine root session with FakeLLM; P0 only, not live Supervisor."""

from __future__ import annotations

import hashlib

import pytest

from llm_loop.assurance.review_contract import FrozenReviewRequest
from llm_loop.assurance.task_control_store import InvalidContractError
from llm_loop.assurance.task_owned_reviewer_probe import (
    FrozenCandidateReadTool,
    run_real_loopengine_review_probe,
)
from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse


def _request(candidate: bytes, reviewer_sid: str) -> FrozenReviewRequest:
    return FrozenReviewRequest(
        task_id="task_review", owner="principal_01",
        candidate_sha256=hashlib.sha256(candidate).hexdigest(),
        acceptance_sha256="a" * 64,
        author_session_id="previous_parent_session",
        reviewer_session_id=reviewer_sid,
    )


def _closed_engine(build_test_engine, responses: list) -> object:
    engine, _ = build_test_engine(responses)
    engine.registry.dispose()  # only test fixture's isolated engine is touched
    engine.registry.register(FrozenCandidateReadTool(b"candidate", hashlib.sha256(b"candidate").hexdigest()))
    return engine


def test_real_loopengine_separate_session_after_parent_run_terminal(build_test_engine) -> None:
    candidate = b"candidate"
    # Prior Executor Run already finalized in another engine/session. The new
    # root reviewer is NOT registered as its child.
    previous_engine, previous_fake = build_test_engine(
        [LLMResponse(content="executor finished candidate", tool_calls=[], provider="fake")]
    )
    previous_sid = previous_engine.session.create()
    assert previous_engine.run(previous_sid, "finish candidate").final_answer
    assert len(previous_fake.calls) == 1
    review_fake = [
        LLMResponse(
            content="", provider="fake",
            tool_calls=[ToolCall(
                id="read-candidate", name="review_frozen_candidate",
                arguments={"candidate_sha256": hashlib.sha256(candidate).hexdigest()},
            )],
        ),
        LLMResponse(
            content="bounded review: one source observed, no oracle verified",
            tool_calls=[], provider="fake",
        ),
    ]
    reviewer_engine = _closed_engine(build_test_engine, review_fake)
    trusted_reviewer_sid = reviewer_engine.session.create()
    res = run_real_loopengine_review_probe(
        review_request=_request(candidate, trusted_reviewer_sid), engine=reviewer_engine,
        frozen_bytes=candidate, accepted_stop_epoch=0, read_current_stop_epoch=lambda _: 0,
    )
    assert res.reviewer_session_id != previous_sid
    assert res.tool_names_attempted == ("review_frozen_candidate",)
    assert res.status == "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS"


def test_real_loopengine_rejects_unknown_write_tool_attempt(build_test_engine) -> None:
    candidate = b"candidate"
    reviewer = _closed_engine(build_test_engine, [
        LLMResponse(
            content="", tool_calls=[
                ToolCall(id="attempt-shell", name="execute_command", arguments={"command": "true"})
            ], provider="fake",
        ),
        LLMResponse(content="I claim PASS anyway", tool_calls=[], provider="fake"),
    ])
    trusted_reviewer_sid = reviewer.session.create()
    res = run_real_loopengine_review_probe(
        review_request=_request(candidate, trusted_reviewer_sid), engine=reviewer,
        frozen_bytes=candidate, accepted_stop_epoch=4,
        read_current_stop_epoch=lambda _: 4,
    )
    assert res.status == "UNQUALIFIED_UNSAFE_TOOL_ATTEMPT"
    assert "execute_command" not in reviewer.registry.names()


def test_full_factory_registry_denied_and_stop_epoch_blocks_dispatch(build_test_engine) -> None:
    candidate = b"candidate"
    full, _ = build_test_engine([])
    full_sid = full.session.create()
    with pytest.raises(InvalidContractError, match="closed read-only"):
        run_real_loopengine_review_probe(
            review_request=_request(candidate, full_sid), engine=full,
            frozen_bytes=candidate, accepted_stop_epoch=0,
            read_current_stop_epoch=lambda _: 0,
        )
    safe = _closed_engine(build_test_engine, [])
    safe_sid = safe.session.create()
    with pytest.raises(InvalidContractError, match="STOP"):
        run_real_loopengine_review_probe(
            review_request=_request(candidate, safe_sid), engine=safe,
            frozen_bytes=candidate, accepted_stop_epoch=1,
            read_current_stop_epoch=lambda _: 2,
        )


def test_candidate_content_drift_does_not_enter_loopengine(build_test_engine) -> None:
    reviewer = _closed_engine(build_test_engine, [])
    sid = reviewer.session.create()
    with pytest.raises(InvalidContractError, match="candidate bytes"):
        run_real_loopengine_review_probe(
            review_request=_request(b"candidate", sid), engine=reviewer,
            frozen_bytes=b"tampered",
            accepted_stop_epoch=0, read_current_stop_epoch=lambda _: 0,
        )


def test_stop_epoch_change_during_review_invalidates_terminal_result(build_test_engine) -> None:
    epoch = {"current": 10}

    def _late_stop(_calls) -> LLMResponse:
        epoch["current"] = 11
        return LLMResponse(
            content="reviewer completed after user STOP",
            tool_calls=[], provider="fake",
        )

    reviewer = _closed_engine(build_test_engine, [_late_stop])
    sid = reviewer.session.create()
    result = run_real_loopengine_review_probe(
        review_request=_request(b"candidate", sid), engine=reviewer,
        frozen_bytes=b"candidate", accepted_stop_epoch=10,
        read_current_stop_epoch=lambda _: epoch["current"],
    )
    assert result.status == "UNQUALIFIED_STOP_EPOCH_CHANGED"


def test_unallocated_reviewer_session_cannot_be_assumed_valid(build_test_engine) -> None:
    reviewer = _closed_engine(build_test_engine, [])
    with pytest.raises(InvalidContractError, match="not preallocated"):
        run_real_loopengine_review_probe(
            review_request=_request(b"candidate", "invented_reviewer_session"),
            engine=reviewer, frozen_bytes=b"candidate",
            accepted_stop_epoch=0, read_current_stop_epoch=lambda _: 0,
        )
