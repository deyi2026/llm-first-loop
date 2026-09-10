"""DeepSeek RG-3E resource fact normalization; no network I/O."""

from __future__ import annotations

from llm_loop.resources.contracts import (
    DeclaredResourceProfile,
    FactProvenance,
    FactSource,
    PricingRule,
    ResourceKey,
    ResourceProductIdentity,
    ResourceScopeKind,
    RuntimeType,
)
from llm_loop.resources.ledger_projection import FactValidity, ProviderResourceBinding
from llm_loop.resources.vendor_adapters._common import product_pricing_snapshot, require_provider
from llm_loop.resources.vendor_facts import (
    ProviderAdapterGap,
    ProviderAdapterResult,
    ProviderAuthoritativeSnapshot,
    ProviderFactApplicability,
    ProviderPublishedResourceProfile,
)


class DeepSeekResourceAdapter:
    """Translate explicit DeepSeek documentation/control-plane facts into RG contracts."""

    provider_id = "deepseek"

    def model_mapping_gaps(
        self, model_id: str, *, documented_model_ids: tuple[str, ...]
    ) -> tuple[ProviderAdapterGap, ...]:
        """Require exact documented identity; aliases are never guessed."""

        return () if model_id in documented_model_ids else (ProviderAdapterGap.MODEL_MAPPING_UNPROVEN,)

    def published_account_concurrency(
        self,
        *,
        model_id: str,
        max_concurrency: int,
        provenance: FactProvenance,
        validity: FactValidity,
        account_override_possible: bool,
    ) -> ProviderAdapterResult:
        """Record provider-published account default without binding an actual account."""

        profile = ProviderPublishedResourceProfile(
            provider_id=self.provider_id,
            scope_kind=ResourceScopeKind.ACCOUNT,
            model_id=model_id,
            max_concurrency=max_concurrency,
            override_possible=account_override_possible,
            provenance=provenance,
            validity=validity,
        )
        gaps = (ProviderAdapterGap.DOCUMENTATION_ONLY,)
        return ProviderAdapterResult(published=(profile,), gaps=gaps)

    def exact_account_concurrency(
        self,
        *,
        key: ResourceKey,
        product: ResourceProductIdentity,
        binding: ProviderResourceBinding,
        max_concurrency: int,
        provenance: FactProvenance,
        validity: FactValidity,
    ) -> ProviderAdapterResult:
        """Materialize an exact account limit only from live provider provenance."""

        require_provider(self.provider_id, key, product, binding)
        if key.scope_kind is not ResourceScopeKind.ACCOUNT:
            raise ValueError("DeepSeek account concurrency requires an ACCOUNT key")
        if provenance.source not in {FactSource.PROVIDER_CONTROL_PLANE, FactSource.PROVIDER_RESPONSE}:
            raise ValueError("exact account concurrency requires live provider provenance")
        profile = DeclaredResourceProfile(
            key=key,
            provenance=provenance,
            runtime_type=RuntimeType.CLOUD,
            max_concurrency=max_concurrency,
            product=product,
        )
        snapshot = ProviderAuthoritativeSnapshot(
            provider_id=self.provider_id,
            applicability=ProviderFactApplicability.EXACT_ACCOUNT,
            resource_key=key,
            product=product,
            provenance=provenance,
            validity=validity,
            bindings=(binding,),
            declared_profile=profile,
        )
        return ProviderAdapterResult(
            authoritative=(snapshot,),
            gaps=(ProviderAdapterGap.PROVIDER_GLOBAL_COVERAGE_UNPROVEN,),
        )

    def product_pricing(
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
        """Bind published pricing to an explicitly declared DeepSeek product only."""

        if key.scope_kind is not ResourceScopeKind.PRODUCT:
            raise ValueError("DeepSeek pricing requires a PRODUCT key")
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
