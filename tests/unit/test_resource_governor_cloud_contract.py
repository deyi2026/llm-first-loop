from __future__ import annotations

from dataclasses import fields
from decimal import Decimal
from pathlib import Path

import pytest

from llm_loop.resources.contracts import (
    CostBudget,
    DeclaredResourceProfile,
    FactProvenance,
    FactSource,
    MoneyAmount,
    ObservedResourceState,
    PricingBasis,
    PricingRule,
    PricingSchedule,
    ProviderErrorFacts,
    ProviderUsageFacts,
    QuotaMetric,
    QuotaSpec,
    QuotaUsage,
    RateLimitMetric,
    RateLimitResetFacts,
    RateLimitSpec,
    ResourceDimension,
    ResourceKey,
    ResourceProductIdentity,
    ResourceRequirement,
    ResourceScopeKind,
    RuntimeType,
)


def _prov(source: FactSource = FactSource.OPERATOR_CONFIG) -> FactProvenance:
    return FactProvenance(source=source, source_ref="test:cloud-resource-fact", recorded_at=10.0)


def _product(provider_id: str = "glm", product_id: str = "coding-plan") -> ResourceProductIdentity:
    return ResourceProductIdentity(
        provider_id=provider_id,
        product_id=product_id,
        account_alias="primary",
        api_family="openai-compatible",
        region="global",
        provenance=_prov(),
    )


def test_resource_product_identity_is_explicit_and_non_secret_alias_based() -> None:
    product = _product()
    assert product.provider_id == "glm"
    assert product.product_id == "coding-plan"
    assert product.account_alias == "primary"
    assert product.api_family == "openai-compatible"
    assert product.region == "global"


def test_provider_usage_distinguishes_unreported_from_real_zero() -> None:
    unknown = ProviderUsageFacts(
        provider_id="deepseek",
        model_id="model-a",
        product=_product("deepseek", "payg"),
        provenance=_prov(FactSource.PROVIDER_RESPONSE),
    )
    zero = ProviderUsageFacts(
        provider_id="deepseek",
        model_id="model-a",
        product=_product("deepseek", "payg"),
        input_tokens=0,
        output_tokens=0,
        cached_input_tokens=0,
        total_tokens=0,
        provenance=_prov(FactSource.PROVIDER_RESPONSE),
    )
    assert unknown.input_tokens is None
    assert zero.input_tokens == 0
    assert unknown != zero


def test_provider_usage_supports_opaque_plan_units_without_turning_them_into_tokens() -> None:
    usage = ProviderUsageFacts(
        provider_id="glm",
        model_id="model-a",
        product=_product(),
        provider_units=Decimal("0.25"),
        provider_unit="plan_unit",
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
    )
    assert usage.provider_units == Decimal("0.25")
    assert usage.input_tokens is None
    with pytest.raises(ValueError, match="provider_unit"):
        ProviderUsageFacts(
            provider_id="glm",
            model_id="model-a",
            provider_units=Decimal("1"),
            provenance=_prov(),
        )


def test_provider_error_facts_normalize_only_safe_reset_fields() -> None:
    reset = RateLimitResetFacts(
        metric=RateLimitMetric.REQUESTS,
        limit=100,
        remaining=0,
        window_seconds=60.0,
        reset_after_seconds=4.5,
    )
    facts = ProviderErrorFacts(
        provider_id="minimax",
        model_id="model-a",
        product=_product("minimax", "token-plan"),
        status_code=429,
        provider_code="rate_limit",
        retry_after_seconds=4.5,
        rate_limits=(reset,),
        provenance=_prov(FactSource.PROVIDER_RESPONSE),
    )
    assert facts.status_code == 429
    assert facts.rate_limits[0].remaining == 0
    names = {field.name for field in fields(ProviderErrorFacts)}
    assert names.isdisjoint({"body", "headers", "raw_headers", "prompt", "messages", "api_key"})


def test_quota_contract_handles_token_and_provider_defined_units() -> None:
    token_quota = QuotaSpec(
        metric=QuotaMetric.TOTAL_TOKENS,
        limit=Decimal("1000000"),
        window_seconds=604800.0,
        provenance=_prov(FactSource.PROVIDER_DOCUMENTATION),
    )
    plan_quota = QuotaSpec(
        metric=QuotaMetric.PROVIDER_UNITS,
        limit=Decimal("5"),
        window_seconds=604800.0,
        provider_unit="plan_hour_equivalent",
        provenance=_prov(FactSource.PROVIDER_DOCUMENTATION),
    )
    usage = QuotaUsage(
        metric=QuotaMetric.PROVIDER_UNITS,
        used=Decimal("1.5"),
        window_seconds=604800.0,
        provider_unit="plan_hour_equivalent",
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
    )
    assert token_quota.metric is QuotaMetric.TOTAL_TOKENS
    assert plan_quota.provider_unit == usage.provider_unit
    with pytest.raises(ValueError, match="provider_unit"):
        QuotaSpec(
            metric=QuotaMetric.PROVIDER_UNITS,
            limit=Decimal("1"),
            provenance=_prov(),
        )


def test_pricing_schedule_supports_time_length_tier_and_subscription_rules() -> None:
    product = _product("minimax", "payg")
    token_schedule = PricingSchedule(
        product=product,
        model_id="model-a",
        provenance=_prov(FactSource.PROVIDER_DOCUMENTATION),
        rules=(
            PricingRule(
                rule_id="short-input",
                basis=PricingBasis.INPUT_MILLION_TOKENS,
                price=MoneyAmount(Decimal("1.25"), "USD"),
                max_input_tokens=32768,
                service_tier="standard",
            ),
            PricingRule(
                rule_id="long-input-window",
                basis=PricingBasis.INPUT_MILLION_TOKENS,
                price=MoneyAmount(Decimal("2.50"), "USD"),
                min_input_tokens=32769,
                service_tier="standard",
                effective_from=1000.0,
                effective_until=2000.0,
            ),
        ),
    )
    subscription = PricingSchedule(
        product=_product("glm", "coding-plan"),
        provenance=_prov(FactSource.OPERATOR_CONFIG),
        rules=(
            PricingRule(
                rule_id="subscription-period",
                basis=PricingBasis.SUBSCRIPTION_PERIOD,
                price=MoneyAmount(Decimal("10.00"), "USD"),
                period_seconds=2592000.0,
            ),
        ),
    )
    assert len(token_schedule.rules) == 2
    assert subscription.model_id is None
    assert subscription.rules[0].period_seconds == 2592000.0


def test_resource_dimensions_do_not_imply_concurrency() -> None:
    key = ResourceKey("glm", ResourceScopeKind.ACCOUNT, "primary")
    product = _product()
    profile = DeclaredResourceProfile(
        key=key,
        runtime_type=RuntimeType.CLOUD,
        max_concurrency=None,
        rate_limits=(
            RateLimitSpec(metric=RateLimitMetric.REQUESTS, limit=100, window_seconds=60.0),
        ),
        quota_limits=(
            QuotaSpec(
                metric=QuotaMetric.PROVIDER_UNITS,
                limit=Decimal("5"),
                window_seconds=604800.0,
                provider_unit="plan_hour_equivalent",
                provenance=_prov(),
            ),
        ),
        cost_budget=CostBudget(
            limit=MoneyAmount(Decimal("25"), "USD"),
            window_seconds=2592000.0,
            provenance=_prov(),
        ),
        product=product,
        provenance=_prov(),
    )
    requirements = (
        ResourceRequirement(key, ResourceDimension.RATE),
        ResourceRequirement(key, ResourceDimension.QUOTA),
        ResourceRequirement(key, ResourceDimension.COST),
    )
    assert profile.max_concurrency is None
    assert {row.dimension for row in requirements} == {
        ResourceDimension.RATE,
        ResourceDimension.QUOTA,
        ResourceDimension.COST,
    }
    assert ResourceDimension.CONCURRENCY not in {row.dimension for row in requirements}


def test_observed_cloud_profile_keeps_quota_and_concurrency_independent() -> None:
    key = ResourceKey("glm", ResourceScopeKind.ACCOUNT, "primary")
    state = ObservedResourceState(
        key=key,
        runtime_type=RuntimeType.CLOUD,
        max_concurrency=None,
        quota_usage=(
            QuotaUsage(
                metric=QuotaMetric.PROVIDER_UNITS,
                used=Decimal("0"),
                provider_unit="plan_unit",
                provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
            ),
        ),
        product=_product(),
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
    )
    assert state.max_concurrency is None
    assert state.quota_usage[0].used == Decimal("0")


def test_rg3a_contract_has_no_vendor_specific_policy_or_runtime_wiring() -> None:
    root = Path(__file__).parents[2]
    contract = (root / "src/llm_loop/resources/contracts.py").read_text(encoding="utf-8").lower()
    assert "deepseek" not in contract
    assert "minimax" not in contract
    assert "glm" not in contract

    for rel in (
        "src/llm_loop/resources/governor.py",
        "src/llm_loop/resources/provider_calls.py",
        "src/llm_loop/llm/client.py",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        assert "ResourceProductIdentity" not in text
        assert "ProviderUsageFacts" not in text
        assert "ProviderErrorFacts" not in text
        assert "PricingSchedule" not in text


def test_rg3a_contract_adds_no_task_semantic_authority_fields() -> None:
    forbidden = {
        "task_text",
        "prompt",
        "messages",
        "quality",
        "quality_score",
        "complexity",
        "relevance",
        "importance",
        "completion",
        "should_run",
        "method_applicability",
        "model_preference",
    }
    dataclasses = (
        ResourceProductIdentity,
        ResourceRequirement,
        ProviderUsageFacts,
        ProviderErrorFacts,
        QuotaSpec,
        QuotaUsage,
        PricingRule,
        PricingSchedule,
    )
    for cls in dataclasses:
        names = {field.name for field in fields(cls)}
        assert names.isdisjoint(forbidden), f"{cls.__name__}: {names & forbidden}"


def test_rg3a_design_pointer_declares_contract_only_no_enforcement() -> None:
    root = Path(__file__).parents[2]
    text = (
        root / "docs/DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md"
    ).read_text(encoding="utf-8")
    assert "docs/DESIGN-20260910-resource-governor-rg3a-cloud-facts.md" in text
    assert "RG-3A 仅冻结 cloud resource facts contract" in text
    assert "不接 cloud enforcement" in text
