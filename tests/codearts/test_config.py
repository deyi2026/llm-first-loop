"""CodeArtsSettings 配置单元测试（design.md §2.1.2）."""

from __future__ import annotations

from llm_loop.codearts.config import CodeArtsSettings


def test_defaults_fail_open():
    s = CodeArtsSettings()
    assert s.enabled is False
    assert s.has_credential() is False
    assert s.credential_kind() == "none"


def test_ak_sk_credential():
    s = CodeArtsSettings(ak="AK123", sk="SK456")
    assert s.has_credential() is True
    assert s.credential_kind() == "ak_sk"


def test_iam_token_credential():
    s = CodeArtsSettings(iam_token="token123")
    assert s.has_credential() is True
    assert s.credential_kind() == "iam_token"


def test_frozen():
    s = CodeArtsSettings()
    try:
        s.enabled = True  # type: ignore[misc]
        raise AssertionError("应抛 FrozenInstanceError")
    except AttributeError:
        pass
