"""MiniMax RG-3E resource fact normalization; no network I/O."""

from __future__ import annotations

from llm_loop.resources.contracts import (
    FactProvenance,
    FactSource,
    PricingRule,
    QuotaSpec,
    QuotaUsage,
    ResourceKey,
    ResourceProductIdentity,
    ResourceScopeKind,
)
from llm_loop.resources.ledger_projection import (
    AccountingWindow,
    FactValidity,
    ProviderResourceBinding,
)
from llm_loop.resources.vendor_adapters._common import (
    product_pricing_snapshot,
    product_quota_snapshot,
)
from llm_loop.resources.vendor_facts import (
    ProviderAdapterGap,
    ProviderAdapterResult,
    ProviderGlobalCoverageProof,
    ProviderPublishedResourceProfile,
)


class MiniMaxResourceAdapter:
    """Normalize explicit MiniMax paygo/Token Plan facts without guessing key product type."""

    provider_id = "minimax"

    def model_mapping_gaps(
        self, model_id: str, *, documented_model_ids: tuple[str, ...]
    ) -> tuple[ProviderAdapterGap, ...]:
        return () if model_id in documented_model_ids else (ProviderAdapterGap.MODEL_MAPPING_UNPROVEN,)

    def published_token_plan(
        self,
        *,
        product_id: str,
        model_id: str | None,
        provenance: FactProvenance,
        validity: FactValidity,
        published_agent_concurrency_is_approximate: bool,
    ) -> ProviderAdapterResult:
        """Do not turn approximate 'N agents' marketing guidance into concurrency capacity."""

        profile = ProviderPublishedResourceProfile(
            provider_id=self.provider_id,
            scope_kind=ResourceScopeKind.PRODUCT,
            product_id=product_id,
            model_id=model_id,
            provenance=provenance,
            validity=validity,
        )
        gaps = [ProviderAdapterGap.DOCUMENTATION_ONLY]
        if published_agent_concurrency_is_approximate:
            gaps.append(ProviderAdapterGap.APPROXIMATE_VALUE_NOT_NORMALIZED)
        return ProviderAdapterResult(published=(profile,), gaps=tuple(gaps))

    def exact_token_plan_quota(
        self,
        *,
        key: ResourceKey,
        product: ResourceProductIdentity,
        bindings: tuple[ProviderResourceBinding, ...],
        quota_limits: tuple[QuotaSpec, ...],
        quota_usage: tuple[QuotaUsage, ...],
        windows: tuple[AccountingWindow, ...],
        provenance: FactProvenance,
        validity: FactValidity,
        coverage_proofs: tuple[ProviderGlobalCoverageProof, ...] = (),
    ) -> ProviderAdapterResult:
        """Normalize Token Plan remains only after product binding and schema qualification."""

        if key.scope_kind is not ResourceScopeKind.PRODUCT:
            raise ValueError("MiniMax Token Plan quota requires a PRODUCT key")
        if provenance.source is not FactSource.PROVIDER_CONTROL_PLANE:
            raise ValueError("MiniMax exact quota requires provider control-plane provenance")
        snapshot = product_quota_snapshot(
            provider_id=self.provider_id,
            product=product,
            key=key,
            bindings=bindings,
            quota_limits=quota_limits,
            quota_usage=quota_usage,
            windows=windows,
            coverage_proofs=coverage_proofs,
            provenance=provenance,
            validity=validity,
        )
        gaps = () if coverage_proofs else (ProviderAdapterGap.PROVIDER_GLOBAL_COVERAGE_UNPROVEN,)
        return ProviderAdapterResult(authoritative=(snapshot,), gaps=gaps)

    def paygo_pricing(
        self,
        *,
        key: ResourceKey,
        product: ResourceProductIdentity,
        binding: ProviderResourceBinding,
        model_id: str,
        rules: tuple[PricingRule, ...],
        provenance: FactProvenance,
        validity: FactValidity,
    ) -> ProviderAdapterResult:
        """Materialize paygo pricing only after an explicit MiniMax product binding."""

        if key.scope_kind is not ResourceScopeKind.PRODUCT:
            raise ValueError("MiniMax pricing requires a PRODUCT key")
        if provenance.source is not FactSource.PROVIDER_DOCUMENTATION:
            raise ValueError("published pricing requires provider documentation provenance")
        snapshot = product_pricing_snapshot(
            provider_id=self.provider_id,
            product=product,
            key=key,
            binding=binding,
            model_id=model_id,
            rules=rules,
            provenance=provenance,
            validity=validity,
        )
        return ProviderAdapterResult(authoritative=(snapshot,))
