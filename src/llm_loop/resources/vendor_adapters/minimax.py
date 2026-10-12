"""MiniMax RG-3E resource fact normalization; no network I/O."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from math import isfinite

from llm_loop.resources.contracts import (
    FactProvenance,
    FactSource,
    PricingRule,
    QuotaMetric,
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


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be an array")
    return value


def _int(value: object, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must have integer numeric semantics")
    if isinstance(value, float) and (not isfinite(value) or not value.is_integer()):
        raise ValueError(f"{name} must have integer numeric semantics")
    parsed = int(value)
    if parsed < 0 or (positive and parsed == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be {qualifier}")
    return parsed


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _percent(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    parsed = float(value)
    if not isfinite(parsed) or not 0 <= parsed <= 100:
        raise ValueError(f"{name} must be within 0..100")
    return parsed


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

    def map_token_plan_remains_response(
        self,
        payload: Mapping[str, object],
        *,
        key: ResourceKey,
        product: ResourceProductIdentity,
        bindings: tuple[ProviderResourceBinding, ...],
        provenance: FactProvenance,
        validity: FactValidity,
    ) -> ProviderAdapterResult:
        """Map the qualified China Token Plan remains schema into provider-unit quota facts."""

        if key.scope_kind is not ResourceScopeKind.PRODUCT:
            raise ValueError("MiniMax Token Plan mapping requires a PRODUCT key")
        if product.provider_id != self.provider_id or key.provider_id != self.provider_id:
            raise ValueError("MiniMax Token Plan mapping requires matching provider identity")
        if product.product_id != "token-plan" or product.region != "cn":
            raise ValueError("MiniMax Token Plan E4 mapping requires explicit token-plan region=cn binding")
        if provenance.source is not FactSource.PROVIDER_CONTROL_PLANE:
            raise ValueError("MiniMax Token Plan mapping requires provider control-plane provenance")

        base = _mapping(payload.get("base_resp"), "base_resp")
        status_code = _int(base.get("status_code"), "base_resp.status_code")
        if status_code != 0:
            raise ValueError("MiniMax Token Plan mapping requires business status_code=0")
        _text(base.get("status_msg"), "base_resp.status_msg")
        rows = _sequence(payload.get("model_remains"), "model_remains")
        if not rows:
            raise ValueError("model_remains must be non-empty")

        quota_limits: list[QuotaSpec] = []
        quota_usage: list[QuotaUsage] = []
        windows: list[AccountingWindow] = []
        seen_buckets: set[str] = set()
        for index, raw_row in enumerate(rows):
            row = _mapping(raw_row, f"model_remains[{index}]")
            bucket = _text(row.get("model_name"), f"model_remains[{index}].model_name")
            if bucket in seen_buckets:
                raise ValueError(f"duplicate MiniMax quota bucket: {bucket}")
            seen_buckets.add(bucket)

            # These fields are schema-qualified but deliberately not normalized into quota math.
            _percent(
                row.get("current_interval_remaining_percent"),
                f"model_remains[{index}].current_interval_remaining_percent",
            )
            _int(row.get("current_interval_status"), f"model_remains[{index}].current_interval_status")
            _int(row.get("remains_time"), f"model_remains[{index}].remains_time")
            _percent(
                row.get("current_weekly_remaining_percent"),
                f"model_remains[{index}].current_weekly_remaining_percent",
            )
            _int(row.get("current_weekly_status"), f"model_remains[{index}].current_weekly_status")
            _int(row.get("weekly_remains_time"), f"model_remains[{index}].weekly_remains_time")

            for suffix, total_name, used_name, start_name, end_name in (
                (
                    "current",
                    "current_interval_total_count",
                    "current_interval_usage_count",
                    "start_time",
                    "end_time",
                ),
                (
                    "weekly",
                    "current_weekly_total_count",
                    "current_weekly_usage_count",
                    "weekly_start_time",
                    "weekly_end_time",
                ),
            ):
                total = _int(row.get(total_name), f"model_remains[{index}].{total_name}")
                used = _int(row.get(used_name), f"model_remains[{index}].{used_name}")
                if used > total:
                    raise ValueError("usage_count cannot exceed total_count")
                start_ms = _int(row.get(start_name), f"model_remains[{index}].{start_name}")
                end_ms = _int(row.get(end_name), f"model_remains[{index}].{end_name}")
                if end_ms <= start_ms:
                    raise ValueError("MiniMax quota window end must be after start")
                start_at = start_ms / 1000.0
                end_at = end_ms / 1000.0
                window_seconds = end_at - start_at
                unit = f"token_plan:{bucket}:{suffix}"
                quota_limits.append(
                    QuotaSpec(
                        metric=QuotaMetric.PROVIDER_UNITS,
                        limit=Decimal(total),
                        provenance=provenance,
                        window_seconds=window_seconds,
                        reset_at=end_at,
                        provider_unit=unit,
                    )
                )
                quota_usage.append(
                    QuotaUsage(
                        metric=QuotaMetric.PROVIDER_UNITS,
                        used=Decimal(used),
                        provenance=provenance,
                        window_seconds=window_seconds,
                        reset_at=end_at,
                        provider_unit=unit,
                    )
                )
                windows.append(
                    AccountingWindow(
                        window_ref=f"minimax:token-plan:{bucket}:{suffix}:{start_ms}:{end_ms}",
                        start_at=start_at,
                        end_at=end_at,
                    )
                )

        result = self.exact_token_plan_quota(
            key=key,
            product=product,
            bindings=bindings,
            quota_limits=tuple(quota_limits),
            quota_usage=tuple(quota_usage),
            windows=tuple(windows),
            provenance=provenance,
            validity=validity,
        )
        return ProviderAdapterResult(
            authoritative=result.authoritative,
            gaps=(
                ProviderAdapterGap.PROVIDER_STATUS_SEMANTICS_UNPROVEN,
                ProviderAdapterGap.REMAINING_PERCENT_SEMANTICS_UNPROVEN,
                ProviderAdapterGap.WINDOW_POLICY_SEMANTICS_UNPROVEN,
                ProviderAdapterGap.PROVIDER_GLOBAL_COVERAGE_UNPROVEN,
            ),
        )

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
