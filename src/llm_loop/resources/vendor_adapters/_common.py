"""Shared mechanical builders for RG-3E vendor adapters."""

from __future__ import annotations

from llm_loop.resources.contracts import (
    DeclaredResourceProfile,
    FactProvenance,
    ObservedResourceState,
    PricingRule,
    PricingSchedule,
    QuotaSpec,
    QuotaUsage,
    ResourceKey,
    ResourceProductIdentity,
    RuntimeType,
)
from llm_loop.resources.ledger_projection import (
    AccountingWindow,
    FactValidity,
    ProviderResourceBinding,
)
from llm_loop.resources.vendor_facts import (
    ProviderAuthoritativeSnapshot,
    ProviderFactApplicability,
    ProviderGlobalCoverageProof,
)


def require_provider(provider_id: str, *objects: object) -> None:
    """Validate provider_id on typed objects that expose it."""

    for obj in objects:
        actual = getattr(obj, "provider_id", provider_id)
        if actual != provider_id:
            raise ValueError(f"expected provider_id={provider_id!r}, got {actual!r}")


def product_pricing_snapshot(
    *,
    provider_id: str,
    product: ResourceProductIdentity,
    key: ResourceKey,
    binding: ProviderResourceBinding,
    model_id: str,
    rules: tuple[PricingRule, ...],
    provenance: FactProvenance,
    validity: FactValidity,
) -> ProviderAuthoritativeSnapshot:
    """Materialize provider-documented pricing only after explicit product binding."""

    require_provider(provider_id, product, key, binding)
    if binding.model_id != model_id or not binding.includes(key) or binding.product != product:
        raise ValueError("pricing binding must match model/product/resource key")
    schedule = PricingSchedule(
        product=product,
        model_id=model_id,
        provenance=provenance,
        rules=rules,
    )
    return ProviderAuthoritativeSnapshot(
        provider_id=provider_id,
        applicability=ProviderFactApplicability.EXACT_PRODUCT,
        resource_key=key,
        product=product,
        provenance=provenance,
        validity=validity,
        bindings=(binding,),
        pricing_schedules=(schedule,),
    )


def product_quota_snapshot(
    *,
    provider_id: str,
    product: ResourceProductIdentity,
    key: ResourceKey,
    bindings: tuple[ProviderResourceBinding, ...],
    quota_limits: tuple[QuotaSpec, ...],
    quota_usage: tuple[QuotaUsage, ...],
    windows: tuple[AccountingWindow, ...],
    coverage_proofs: tuple[ProviderGlobalCoverageProof, ...],
    provenance: FactProvenance,
    validity: FactValidity,
) -> ProviderAuthoritativeSnapshot:
    """Build one exact product-level quota observation from control-plane facts."""

    require_provider(provider_id, product, key, *bindings)
    if not bindings:
        raise ValueError("exact product quota requires at least one explicit model binding")
    if any(not binding.includes(key) or binding.product != product for binding in bindings):
        raise ValueError("quota bindings must match product/resource key")
    declared = DeclaredResourceProfile(
        key=key,
        provenance=provenance,
        runtime_type=RuntimeType.CLOUD,
        quota_limits=quota_limits,
        product=product,
    )
    observed = ObservedResourceState(
        key=key,
        provenance=provenance,
        runtime_type=RuntimeType.CLOUD,
        quota_usage=quota_usage,
        product=product,
    )
    return ProviderAuthoritativeSnapshot(
        provider_id=provider_id,
        applicability=ProviderFactApplicability.EXACT_PRODUCT,
        resource_key=key,
        product=product,
        provenance=provenance,
        validity=validity,
        bindings=bindings,
        declared_profile=declared,
        observed_state=observed,
        accounting_windows=windows,
        coverage_proofs=coverage_proofs,
    )
