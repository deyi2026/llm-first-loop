"""Sub-agent wire must not carry the engine-only active-ingress marker.

INC-20261020 (subagent_5fb2aef276c1): once a child transcript crossed its model
budget, ``_bounded_child_wire`` projected the transcript through the main history
builder with ``preserve_active_ingress_message``.  That builder stamps the
transport-internal ``_active_run_ingress_ref`` marker.  The child then calls
``LLMClient.chat`` with no ``GuardRequestContext``, so final provider-structure
validation saw markers with ``expected_ref == ""`` and rejected every attempt with
``active_run_ingress_unexpected_marker`` — three identical failures, then circuit
break.  The marker is engine bookkeeping and must not reach the child wire.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.llm.client import provider_structure_violations
from llm_loop.subagent.runner import SubAgentRunner


def _child_transcript() -> list[Message]:
    """Persisted child shape: program-origin delegated task + bulky tool results."""
    ingress = Message(
        role="user",
        content="[子代理任务] 调研并输出结论。" * 6,
        source=MessageSource.USER,
        metadata={"injection_kind": "subagent_task", "origin_layer": "program_recovery"},
    )
    messages = [ingress]
    for index in range(8):
        messages.append(
            Message(
                role="assistant",
                content="",
                source=MessageSource.USER,
                tool_calls=[
                    {
                        "id": f"call-{index}",
                        "type": "function",
                        "function": {"name": "web_fetch", "arguments": "{}"},
                    }
                ],
            )
        )
        messages.append(
            Message(
                role="tool",
                content="Y" * 2000,
                source=MessageSource.TOOL,
                tool_call_id=f"call-{index}",
                tool_name="web_fetch",
                status=ToolResultStatus.SUCCESS,
            )
        )
    return messages


def _runner_stub() -> SimpleNamespace:
    return SimpleNamespace(
        _context_limits_resolver=lambda _label: (2000, None, 2.0),
        _archive_store=SimpleNamespace(archive=lambda *a, **k: None),
    )


class _RawWireItem:
    """Minimal ``sess.messages`` entry replaying a pre-baked ``to_llm_dict`` value.

    D2 contract tests inject arbitrary wire items (including non-dict ones)
    through the same ``to_llm_dict`` seam the runner consumes.
    """

    def __init__(self, wire: object) -> None:
        self._wire = wire

    def to_llm_dict(self) -> object:
        return self._wire


def test_main_projector_stamps_marker_when_no_turn_ref_is_declared() -> None:
    """Precondition of the incident: the shared builder emits the transport marker."""
    messages = _child_transcript()
    projected = build_history_messages(
        messages,
        system_prompt="",
        max_chars=2500,
        session_id="child-precondition",
        preserve_active_ingress_message=messages[0],
    )
    assert any("_active_run_ingress_ref" in m for m in projected)
    assert provider_structure_violations(projected, expected_active_ingress_ref="") != []


def test_bounded_child_wire_strips_unvalidatable_ingress_marker() -> None:
    messages = _child_transcript()
    session = SimpleNamespace(messages=messages, session_id="child-wire")
    wire, failure = SubAgentRunner._bounded_child_wire(
        _runner_stub(),
        session,
        llm=SimpleNamespace(max_tokens=100),
        model_label="test/model",
        tools=[
            {
                "type": "function",
                "function": {"name": "search_archive", "parameters": {}},
            }
        ],
        archived_once=set(),
    )

    assert failure == ""
    assert wire, "compacted child wire must still be sendable"
    assert any(m.get("role") == "user" for m in wire)
    assert not any("_active_run_ingress_ref" in m for m in wire)
    assert provider_structure_violations(wire, expected_active_ingress_ref="") == []


def test_bounded_child_wire_rejects_non_dict_contract_violation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D2: any non-dict wire item rejects the whole wire — no send, no silent drop."""
    # repr 超 200 字符，验证 ERROR 日志的有界截断真实生效（而非平凡通过）。
    bad_item = "not-a-dict" + "x" * 500
    session = SimpleNamespace(
        messages=[
            _RawWireItem({"role": "user", "content": "ok"}),
            _RawWireItem(bad_item),
            _RawWireItem({"role": "assistant", "content": "x"}),
        ],
        session_id="child-wire-contract",
    )
    with caplog.at_level(logging.ERROR, logger="llm_loop.subagent.runner"):
        wire, failure = SubAgentRunner._bounded_child_wire(
            _runner_stub(),
            session,
            llm=SimpleNamespace(max_tokens=100),
            model_label="test/model",
            tools=[],
            archived_once=set(),
        )

    assert wire == []
    assert failure == "投影契约失败(第1项 type=str)"
    assert any(record.levelno == logging.ERROR for record in caplog.records)
    # 有界 repr：完整 500+ 字符 repr 不落日志，仅前 200 字符落日志。
    assert repr(bad_item) not in caplog.text
    assert repr(bad_item)[:200] in caplog.text
