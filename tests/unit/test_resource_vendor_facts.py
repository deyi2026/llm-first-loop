from __future__ import annotations

from dataclasses import fields
from decimal import Decimal
from pathlib import Path

import pytest

from llm_loop.resources.contracts import (
    DeclaredResourceProfile,
    FactProvenance,
    FactSource,
    MoneyAmount,
    PricingBasis,
    PricingRule,
    PricingSchedule,
    ResourceKey,
    ResourceProductIdentity,
    ResourceScopeKind,
    RuntimeType,
)
from llm_loop.resources.ledger_projection import (
    AccountingWindow,
    CoverageState,
    FactValidity,
    FactValidityKind,
    ProviderResourceBinding,
)
from llm_loop.resources.vendor_facts import (
    ProviderAdapterGap,
    ProviderAdapterResult,
    ProviderAuthoritativeSnapshot,
    ProviderFactApplicability,
    ProviderGlobalCoverageProof,
    ProviderPublishedResourceProfile,
)


def _prov(source: FactSource) -> FactProvenance:
    return FactProvenance(source=source, source_ref=f"fixture:{source.value}", recorded_at=10.0)


def _valid() -> FactValidity:
    return FactValidity(FactValidityKind.BOUNDED, valid_from=10.0, valid_until=20.0, version_ref="v1")


def _product(provider: str = "minimax", *, project: str | None = None) -> ResourceProductIdentity:
    return ResourceProductIdentity(
        provider_id=provider,
        product_id="token-plan",
        account_alias="primary",
        project_alias=project,
        provenance=_prov(FactSource.OPERATOR_CONFIG),
    )


def test_product_is_a_first_class_resource_scope() -> None:
    key = ResourceKey("minimax", ResourceScopeKind.PRODUCT, "primary:token-plan")
    assert key.scope_kind is ResourceScopeKind.PRODUCT


def test_published_defaults_have_no_exact_resource_key_and_require_documentation_source() -> None:
    profile = ProviderPublishedResourceProfile(
        provider_id="deepseek",
        scope_kind=ResourceScopeKind.ACCOUNT,
        model_id="deepseek-v4-flash",
        max_concurrency=2500,
        override_possible=True,
        provenance=_prov(FactSource.PROVIDER_DOCUMENTATION),
        validity=_valid(),
    )
    assert "resource_key" not in {field.name for field in fields(profile)}
    assert profile.override_possible is True
    with pytest.raises(ValueError, match="PROVIDER_DOCUMENTATION"):
        ProviderPublishedResourceProfile(
            provider_id="deepseek",
            scope_kind=ResourceScopeKind.ACCOUNT,
            provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
            validity=_valid(),
        )


def test_published_default_cannot_be_constructed_as_exact_account_snapshot() -> None:
    key = ResourceKey("deepseek", ResourceScopeKind.ACCOUNT, "primary")
    product = ResourceProductIdentity(
        provider_id="deepseek",
        product_id="paygo",
        account_alias="primary",
        provenance=_prov(FactSource.OPERATOR_CONFIG),
    )
    profile = DeclaredResourceProfile(
        key=key,
        provenance=_prov(FactSource.PROVIDER_DOCUMENTATION),
        runtime_type=RuntimeType.CLOUD,
        max_concurrency=2500,
        product=product,
    )
    with pytest.raises(ValueError, match="live provider provenance"):
        ProviderAuthoritativeSnapshot(
            provider_id="deepseek",
            applicability=ProviderFactApplicability.EXACT_ACCOUNT,
            resource_key=key,
            product=product,
            provenance=_prov(FactSource.PROVIDER_DOCUMENTATION),
            validity=_valid(),
            declared_profile=profile,
        )


def test_exact_product_pricing_can_be_documentation_sourced_after_explicit_product_binding() -> None:
    key = ResourceKey("minimax", ResourceScopeKind.PRODUCT, "primary:paygo")
    product = ResourceProductIdentity(
        provider_id="minimax",
        product_id="paygo",
        account_alias="primary",
        provenance=_prov(FactSource.OPERATOR_CONFIG),
    )
    rule = PricingRule(
        rule_id="m3-short-input",
        basis=PricingBasis.INPUT_MILLION_TOKENS,
        price=MoneyAmount(Decimal("0.3"), "USD"),
        max_input_tokens=524288,
    )
    schedule = PricingSchedule(
        product=product,
        model_id="MiniMax-M3",
        provenance=_prov(FactSource.PROVIDER_DOCUMENTATION),
        rules=(rule,),
    )
    snapshot = ProviderAuthoritativeSnapshot(
        provider_id="minimax",
        applicability=ProviderFactApplicability.EXACT_PRODUCT,
        resource_key=key,
        product=product,
        provenance=_prov(FactSource.PROVIDER_DOCUMENTATION),
        validity=_valid(),
        pricing_schedules=(schedule,),
    )
    assert snapshot.pricing_schedules[0].rules[0].max_input_tokens == 524288


def test_exact_account_snapshot_requires_matching_scope_provider_and_binding() -> None:
    key = ResourceKey("deepseek", ResourceScopeKind.ACCOUNT, "primary")
    product = ResourceProductIdentity(
        provider_id="deepseek",
        product_id="paygo",
        account_alias="primary",
        provenance=_prov(FactSource.OPERATOR_CONFIG),
    )
    binding = ProviderResourceBinding(
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        resource_keys=(key,),
        provenance=_prov(FactSource.OPERATOR_CONFIG),
        validity=_valid(),
        product=product,
    )
    profile = DeclaredResourceProfile(
        key=key,
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
        runtime_type=RuntimeType.CLOUD,
        max_concurrency=3000,
        product=product,
    )
    snapshot = ProviderAuthoritativeSnapshot(
        provider_id="deepseek",
        applicability=ProviderFactApplicability.EXACT_ACCOUNT,
        resource_key=key,
        product=product,
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
        validity=_valid(),
        bindings=(binding,),
        declared_profile=profile,
    )
    assert snapshot.declared_profile is not None
    assert snapshot.declared_profile.max_concurrency == 3000

    wrong_scope = ResourceKey("deepseek", ResourceScopeKind.PRODUCT, "primary:paygo")
    with pytest.raises(ValueError, match="scope"):
        ProviderAuthoritativeSnapshot(
            provider_id="deepseek",
            applicability=ProviderFactApplicability.EXACT_ACCOUNT,
            resource_key=wrong_scope,
            product=product,
            provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
            validity=_valid(),
            pricing_schedules=(
                PricingSchedule(
                    product=product,
                    provenance=_prov(FactSource.PROVIDER_DOCUMENTATION),
                    rules=(
                        PricingRule(
                            rule_id="x",
                            basis=PricingBasis.PROVIDER_UNIT,
                            price=MoneyAmount(Decimal("1"), "USD"),
                            provider_unit="unit",
                        ),
                    ),
                ),
            ),
        )


def test_provider_global_coverage_requires_control_plane_and_exact_validity() -> None:
    key = ResourceKey("minimax", ResourceScopeKind.PRODUCT, "primary:token-plan")
    window = AccountingWindow("token-plan:5h:1", 100.0, 18100.0)
    proof = ProviderGlobalCoverageProof(
        key=key,
        window=window,
        coverage=CoverageState.COMPLETE,
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
        validity=_valid(),
    )
    assert proof.coverage is CoverageState.COMPLETE
    with pytest.raises(ValueError, match="control-plane"):
        ProviderGlobalCoverageProof(
            key=key,
            window=window,
            coverage=CoverageState.COMPLETE,
            provenance=_prov(FactSource.PROVIDER_DOCUMENTATION),
            validity=_valid(),
        )
    with pytest.raises(ValueError, match="explicit validity"):
        ProviderGlobalCoverageProof(
            key=key,
            window=window,
            coverage=CoverageState.PARTIAL,
            provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
            validity=FactValidity(FactValidityKind.UNKNOWN),
        )


def test_adapter_result_is_observation_only_and_gap_set_is_closed() -> None:
    result = ProviderAdapterResult(
        gaps=(
            ProviderAdapterGap.DOCUMENTATION_ONLY,
            ProviderAdapterGap.PROVIDER_GLOBAL_COVERAGE_UNPROVEN,
        )
    )
    assert result.authoritative == ()
    with pytest.raises(ValueError, match="duplicates"):
        ProviderAdapterResult(gaps=(ProviderAdapterGap.PRODUCT_UNBOUND,) * 2)


def test_vendor_fact_contract_has_no_task_semantic_or_decision_fields() -> None:
    forbidden = {
        "task_text",
        "prompt",
        "messages",
        "quality",
        "complexity",
        "relevance",
        "importance",
        "completion",
        "should_run",
        "model_preference",
        "admission",
        "decision",
        "fallback",
    }
    for cls in (
        ProviderPublishedResourceProfile,
        ProviderGlobalCoverageProof,
        ProviderAuthoritativeSnapshot,
        ProviderAdapterResult,
    ):
        assert {field.name for field in fields(cls)}.isdisjoint(forbidden)


def test_generic_vendor_facts_module_has_no_vendor_names_and_no_governor_import() -> None:
    root = Path(__file__).parents[2]
    text = (root / "src/llm_loop/resources/vendor_facts.py").read_text().lower()
    for vendor in ("deepseek", "minimax", "glm"):
        assert vendor not in text
    assert "resources.governor" not in text
    assert "provider_calls" not in text
