"""GLM 1310（周/月配额窗口）语义分类回归.

事实来源: 2026-11-16 午班 d91 实测——glm-5.3 / glm-5.3-flash 均返回
HTTP 429 + 业务码 1310（周/月上限，窗口 23:21:13 才重置），9 次重试全部
撞同一窗口。此前 1310 无专属分支，落进通用 HTTP 429 → kind=rate_limit，
引导同身份重试，与实际可恢复路径（等窗口 / 换同账户其他模型）不符。
"""

from __future__ import annotations

import json

import pytest

from llm_loop.llm.errors import LLMHTTPError, classify_llm_error


def _http_error(code: str | None, *, status: int = 429, provider: str = "glm-api") -> LLMHTTPError:
    body = json.dumps({"error": {"code": code, "message": "err"}}, ensure_ascii=False)
    return LLMHTTPError(
        f"HTTP {status}: err",
        status_code=status,
        body=body,
        provider=provider,
        provider_code=code,
    )


def test_1310_classified_as_period_quota_not_rate_limit():
    sem = classify_llm_error(_http_error("1310"))
    assert sem.kind == "period_quota"
    assert sem.provider_code == "1310"
    assert "1310" in sem.label
    assert "窗口" in sem.label


def test_1310_does_not_retry_same_identity_but_allows_sibling_model():
    """同模型等窗口才有意义；同账户其他模型有各自窗口，可降级一次."""
    sem = classify_llm_error(_http_error("1310"))
    assert sem.same_identity_retry is False
    assert sem.same_account_other_models is True
    assert sem.independent_provider is True
    assert sem.fallback_eligible is True


@pytest.mark.parametrize(
    "code,kind",
    [
        ("1302", "rate_limit"),          # 瞬时限流: 等待可恢复，行为不变
        ("1311", "model_permission"),    # 订阅未含所选模型: 行为不变
        ("1113", "account_billing"),     # 账户欠费: 行为不变
    ],
)
def test_neighbouring_glm_codes_unchanged(code, kind):
    assert classify_llm_error(_http_error(code)).kind == kind


def test_non_glm_provider_same_code_not_hijacked():
    """同码异义防劫持: 非 GLM 族的 1310 不获得 GLM 语义，仍按 HTTP 429 事实分类."""
    sem = classify_llm_error(_http_error("1310", provider="openai"))
    assert sem.kind == "rate_limit"
    assert sem.provider_code == "1310"


def test_429_without_provider_code_still_rate_limit():
    sem = classify_llm_error(_http_error(None))
    assert sem.kind == "rate_limit"
    assert sem.same_identity_retry is True
