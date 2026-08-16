"""凭证提供者单元测试（design.md §2.2.2.2）."""

from __future__ import annotations

import pytest

from llm_loop.codearts.config import CodeArtsSettings
from llm_loop.codearts.credential import (
    CredentialError,
    CredentialRefreshError,
    EnvCredentialProvider,
)
from llm_loop.codearts.models import CredentialKind


def test_get_ak_sk():
    config = CodeArtsSettings(ak="AK123", sk="SK456", region="cn-north-4")
    provider = EnvCredentialProvider(config)
    cred = provider.get("cn-north-4")
    assert cred.kind == CredentialKind.AK_SK
    assert cred.ak == "AK123"
    assert cred.sk == "SK456"


def test_get_iam_token():
    config = CodeArtsSettings(iam_token="token123", region="cn-north-4")
    provider = EnvCredentialProvider(config)
    cred = provider.get("cn-north-4")
    assert cred.kind == CredentialKind.IAM_TOKEN
    assert cred.token == "token123"


def test_missing_credential_raises():
    config = CodeArtsSettings(region="cn-north-4")
    provider = EnvCredentialProvider(config)
    with pytest.raises(CredentialError):
        provider.get("cn-north-4")


def test_refresh_ak_sk():
    config = CodeArtsSettings(ak="AK123", sk="SK456", region="cn-north-4")
    provider = EnvCredentialProvider(config)
    provider.get("cn-north-4")
    new_cred = provider.refresh("cn-north-4")
    assert new_cred.kind == CredentialKind.AK_SK


def test_refresh_iam_token_raises():
    config = CodeArtsSettings(iam_token="token123", region="cn-north-4")
    provider = EnvCredentialProvider(config)
    provider.get("cn-north-4")
    with pytest.raises(CredentialRefreshError):
        provider.refresh("cn-north-4")


def test_validate_ak_sk():
    config = CodeArtsSettings(ak="AK123", sk="SK456", region="cn-north-4")
    provider = EnvCredentialProvider(config)
    assert provider.validate("cn-north-4") is True


def test_validate_missing():
    config = CodeArtsSettings(region="cn-north-4")
    provider = EnvCredentialProvider(config)
    assert provider.validate("cn-north-4") is False


def test_credential_cached_in_memory():
    config = CodeArtsSettings(ak="AK123", sk="SK456", region="cn-north-4")
    provider = EnvCredentialProvider(config)
    cred1 = provider.get("cn-north-4")
    cred2 = provider.get("cn-north-4")
    assert cred1 is cred2
