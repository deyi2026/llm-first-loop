"""GLM/BigModel RG-3E resource fact normalization; no network I/O."""

from __future__ import annotations

from llm_loop.resources.contracts import (
    FactProvenance,
    FactSource,
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
from llm_loop.resources.vendor_adapters._common import product_quota_snapshot
from llm_loop.resources.vendor_facts import (
    ProviderAdapterGap,
    ProviderAdapterResult,
    ProviderGlobalCoverageProof,
    ProviderPublishedResourceProfile,
)


class GlmResourceAdapter:
    """Normalize exact GLM facts while preserving Coding Plan approximation boundaries."""

    provider_id = "glm"

    def model_mapping_gaps(
        self, model_id: str, *, documented_model_ids: tuple[str, ...]
    ) -> tuple[ProviderAdapterGap, ...]:
        return () if model_id in documented_model_ids else (ProviderAdapterGap.MODEL_MAPPING_UNPROVEN,)

    def published_coding_plan(
        self,
        *,
        product_id: str,
        model_id: str | None,
        provenance: FactProvenance,
        validity: FactValidity,
        published_limits_are_approximate: bool,
    ) -> ProviderAdapterResult:
        """Represent plan existence/window vocabulary without converting approximate prompts to quota."""

        profile = ProviderPublishedResourceProfile(
            provider_id=self.provider_id,
            scope_kind=ResourceScopeKind.PRODUCT,
            product_id=product_id,
            model_id=model_id,
            provenance=provenance,
            validity=validity,
        )
        gaps = [ProviderAdapterGap.DOCUMENTATION_ONLY]
        if published_limits_are_approximate:
            gaps.append(ProviderAdapterGap.APPROXIMATE_VALUE_NOT_NORMALIZED)
        return ProviderAdapterResult(published=(profile,), gaps=tuple(gaps))

    def exact_coding_plan_quota(
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
        """Normalize exact Coding Plan usage only from provider control-plane facts."""

        if key.scope_kind is not ResourceScopeKind.PRODUCT:
            raise ValueError("GLM Coding Plan quota requires a PRODUCT key")
        if provenance.source is not FactSource.PROVIDER_CONTROL_PLANE:
            raise ValueError("GLM exact quota requires provider control-plane provenance")
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
