"""DeepSeek RG-3E resource fact normalization; no network I/O."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from llm_loop.resources.contracts import (
    DeclaredResourceProfile,
    FactProvenance,
    FactSource,
    MoneyAmount,
    PricingRule,
    ResourceKey,
    ResourceProductIdentity,
    ResourceScopeKind,
    RuntimeType,
)
from llm_loop.resources.ledger_projection import FactValidity, ProviderResourceBinding
from llm_loop.resources.vendor_adapters._common import product_pricing_snapshot, require_provider
from llm_loop.resources.vendor_facts import (
    ProviderAccountBalance,
    ProviderAdapterGap,
    ProviderAdapterResult,
    ProviderAuthoritativeSnapshot,
    ProviderBalanceEntry,
    ProviderFactApplicability,
    ProviderPublishedResourceProfile,
)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be an array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _decimal_string(value: object, name: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal string") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{name} must be a non-negative finite decimal string")
    return parsed


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

    def map_account_balance_response(
        self,
        payload: Mapping[str, object],
        *,
        key: ResourceKey,
        product: ResourceProductIdentity,
        binding: ProviderResourceBinding,
        provenance: FactProvenance,
        validity: FactValidity,
    ) -> ProviderAdapterResult:
        """Map the independently qualified `/user/balance` schema into account facts."""

        require_provider(self.provider_id, key, product, binding)
        if key.scope_kind is not ResourceScopeKind.ACCOUNT:
            raise ValueError("DeepSeek balance requires an ACCOUNT key")
        if provenance.source is not FactSource.PROVIDER_CONTROL_PLANE:
            raise ValueError("DeepSeek balance mapping requires provider control-plane provenance")
        if binding.product != product or not binding.includes(key):
            raise ValueError("DeepSeek balance binding must include the exact account key/product")

        available = payload.get("is_available")
        if not isinstance(available, bool):
            raise ValueError("is_available must be bool")
        rows = _sequence(payload.get("balance_infos"), "balance_infos")
        balances: list[ProviderBalanceEntry] = []
        for index, raw_row in enumerate(rows):
            row = _mapping(raw_row, f"balance_infos[{index}]")
            currency = _text(row.get("currency"), f"balance_infos[{index}].currency")
            balances.append(
                ProviderBalanceEntry(
                    total=MoneyAmount(
                        _decimal_string(row.get("total_balance"), f"balance_infos[{index}].total_balance"),
                        currency,
                    ),
                    granted=MoneyAmount(
                        _decimal_string(
                            row.get("granted_balance"), f"balance_infos[{index}].granted_balance"
                        ),
                        currency,
                    ),
                    topped_up=MoneyAmount(
                        _decimal_string(
                            row.get("topped_up_balance"), f"balance_infos[{index}].topped_up_balance"
                        ),
                        currency,
                    ),
                )
            )
        snapshot = ProviderAuthoritativeSnapshot(
            provider_id=self.provider_id,
            applicability=ProviderFactApplicability.EXACT_ACCOUNT,
            resource_key=key,
            product=product,
            provenance=provenance,
            validity=validity,
            bindings=(binding,),
            account_balance=ProviderAccountBalance(
                is_available=available,
                balances=tuple(balances),
            ),
        )
        return ProviderAdapterResult(authoritative=(snapshot,))

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
