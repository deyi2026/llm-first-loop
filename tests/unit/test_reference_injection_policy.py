from __future__ import annotations

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.reference_injection import is_human_user_message


def _user(text: str, **metadata) -> Message:
    return Message(role="user", content=text, source=MessageSource.USER, metadata=metadata)


def test_exact_user_instruction_is_human_ingress() -> None:
    assert is_human_user_message(_user("继续", origin_layer="user_instruction", program_origin=False))


def test_program_or_delegated_user_shape_is_not_human_ingress() -> None:
    assert not is_human_user_message(_user("program", origin_layer="reference", program_origin=True))
    assert not is_human_user_message(_user("scheduled", ingress_delegated=True))
    assert not is_human_user_message(Message(role="assistant", content="x", source=MessageSource.SYSTEM))


def test_empty_user_is_not_human_ingress() -> None:
    assert not is_human_user_message(_user("   "))
