from __future__ import annotations

from dataclasses import fields
from decimal import Decimal
from pathlib import Path

import pytest

from llm_loop.resources.contracts import (
    FactProvenance,
    FactSource,
    MoneyAmount,
    QuotaMetric,
    ResourceKey,
    ResourceProductIdentity,
    ResourceScopeKind,
)
from llm_loop.resources.ledger_projection import (
    FactValidity,
    FactValidityKind,
    ProviderResourceBinding,
)
from llm_loop.resources.vendor_adapters.deepseek import DeepSeekResourceAdapter
from llm_loop.resources.vendor_adapters.minimax import MiniMaxResourceAdapter
from llm_loop.resources.vendor_facts import (
    ProviderAccountBalance,
    ProviderAdapterGap,
    ProviderFactApplicability,
)


def _prov(provider: str) -> FactProvenance:
    return FactProvenance(
        source=FactSource.PROVIDER_CONTROL_PLANE,
        source_ref=f"{provider}:control-plane:qualified",
        recorded_at=1_780_000_000.0,
    )


def _valid(provider: str) -> FactValidity:
    return FactValidity(
        FactValidityKind.BOUNDED,
        valid_from=1_780_000_000.0,
        valid_until=1_780_000_300.0,
        version_ref=f"{provider}:e4-schema:v1",
    )


def _bound(provider: str, model: str, product_id: str, *, region: str | None = None):
    product = ResourceProductIdentity(
        provider_id=provider,
        product_id=product_id,
        account_alias="primary",
        region=region,
        provenance=FactProvenance(
            source=FactSource.OPERATOR_CONFIG,
            source_ref=f"operator:{provider}:binding",
            recorded_at=1_780_000_000.0,
        ),
    )
    product_key = ResourceKey(provider, ResourceScopeKind.PRODUCT, f"primary:{product_id}")
    account_key = ResourceKey(provider, ResourceScopeKind.ACCOUNT, "primary:account")
    binding = ProviderResourceBinding(
        provider_id=provider,
        model_id=model,
        resource_keys=(product_key, account_key),
        provenance=product.provenance,
        validity=FactValidity(
            FactValidityKind.OPEN_ENDED,
            valid_from=1_780_000_000.0,
            version_ref=f"operator:{provider}:binding:v1",
        ),
        product=product,
    )
    return product, product_key, account_key, binding


def test_deepseek_balance_maps_to_independent_account_fact_not_cost_budget() -> None:
    product, _product_key, account_key, binding = _bound(
        "deepseek", "deepseek-flash", "standard-api"
    )
    result = DeepSeekResourceAdapter().map_account_balance_response(
        {
            "is_available": True,
            "balance_infos": [
                {
                    "currency": "CNY",
                    "total_balance": "12.3400",
                    "granted_balance": "2.0000",
                    "topped_up_balance": "10.3400",
                }
            ],
        },
        key=account_key,
        product=product,
        binding=binding,
        provenance=_prov("deepseek"),
        validity=_valid("deepseek"),
    )

    snapshot = result.authoritative[0]
    assert snapshot.applicability is ProviderFactApplicability.EXACT_ACCOUNT
    assert snapshot.account_balance is not None
    assert snapshot.account_balance.is_available is True
    balance = snapshot.account_balance.balances[0]
    assert balance.total == MoneyAmount(Decimal("12.3400"), "CNY")
    assert balance.granted == MoneyAmount(Decimal("2.0000"), "CNY")
    assert balance.topped_up == MoneyAmount(Decimal("10.3400"), "CNY")
    assert snapshot.declared_profile is None
    assert snapshot.observed_state is None
    assert {field.name for field in fields(ProviderAccountBalance)}.isdisjoint(
        {"cost_budget", "cost_usage", "raw_body", "raw_headers", "authorization"}
    )


def test_deepseek_balance_requires_live_control_plane_and_qualified_decimal_strings() -> None:
    product, _product_key, account_key, binding = _bound(
        "deepseek", "deepseek-flash", "standard-api"
    )
    raw = {
        "is_available": False,
        "balance_infos": [
            {
                "currency": "CNY",
                "total_balance": "0.00",
                "granted_balance": "0.00",
                "topped_up_balance": "0.00",
            }
        ],
    }
    with pytest.raises(ValueError, match="control-plane"):
        DeepSeekResourceAdapter().map_account_balance_response(
            raw,
            key=account_key,
            product=product,
            binding=binding,
            provenance=FactProvenance(
                source=FactSource.PROVIDER_DOCUMENTATION,
                source_ref="deepseek:docs",
                recorded_at=1_780_000_000.0,
            ),
            validity=_valid("deepseek"),
        )

    bad = dict(raw)
    bad["balance_infos"] = [
        {
            "currency": "CNY",
            "total_balance": "not-a-decimal",
            "granted_balance": "0.00",
            "topped_up_balance": "0.00",
        }
    ]
    with pytest.raises(ValueError, match="decimal"):
        DeepSeekResourceAdapter().map_account_balance_response(
            bad,
            key=account_key,
            product=product,
            binding=binding,
            provenance=_prov("deepseek"),
            validity=_valid("deepseek"),
        )


def _minimax_success_body() -> dict:
    return {
        "base_resp": {"status_code": 0, "status_msg": "success"},
        "model_remains": [
            {
                "model_name": "general",
                "current_interval_total_count": 0,
                "current_interval_usage_count": 0,
                "current_interval_remaining_percent": 99.25,
                "current_interval_status": 1,
                "start_time": 1_780_000_000_000,
                "end_time": 1_780_014_400_000,
                "remains_time": 14_300_000,
                "current_weekly_total_count": 5000,
                "current_weekly_usage_count": 456,
                "current_weekly_remaining_percent": 88,
                "current_weekly_status": 3,
                "weekly_start_time": 1_779_494_400_000,
                "weekly_end_time": 1_780_099_200_000,
                "weekly_remains_time": 99_000_000,
            },
            {
                "model_name": "video",
                "current_interval_total_count": 20,
                "current_interval_usage_count": 2,
                "current_interval_remaining_percent": 90,
                "current_interval_status": 1,
                "start_time": 1_780_000_000_000,
                "end_time": 1_780_086_400_000,
                "remains_time": 86_300_000,
                "current_weekly_total_count": 100,
                "current_weekly_usage_count": 10,
                "current_weekly_remaining_percent": 90,
                "current_weekly_status": 1,
                "weekly_start_time": 1_779_494_400_000,
                "weekly_end_time": 1_780_099_200_000,
                "weekly_remains_time": 99_000_000,
            },
        ],
    }


def test_minimax_token_plan_maps_exact_provider_unit_quota_windows_and_reset() -> None:
    product, product_key, _account_key, binding = _bound(
        "minimax", "MiniMax-M3", "token-plan", region="cn"
    )
    result = MiniMaxResourceAdapter().map_token_plan_remains_response(
        _minimax_success_body(),
        key=product_key,
        product=product,
        bindings=(binding,),
        provenance=_prov("minimax"),
        validity=_valid("minimax"),
    )
    snapshot = result.authoritative[0]
    assert snapshot.applicability is ProviderFactApplicability.EXACT_PRODUCT
    assert snapshot.declared_profile is not None
    assert snapshot.observed_state is not None
    assert snapshot.coverage_proofs == ()
    assert len(snapshot.accounting_windows) == 4

    limits = {item.provider_unit: item for item in snapshot.declared_profile.quota_limits}
    usage = {item.provider_unit: item for item in snapshot.observed_state.quota_usage}
    assert set(limits) == {
        "token_plan:general:current",
        "token_plan:general:weekly",
        "token_plan:video:current",
        "token_plan:video:weekly",
    }
    general = limits["token_plan:general:current"]
    assert general.metric is QuotaMetric.PROVIDER_UNITS
    assert general.limit == Decimal("0")
    assert general.window_seconds == 14400.0
    assert general.reset_at == 1_780_014_400.0
    assert usage["token_plan:general:current"].used == Decimal("0")
    assert limits["token_plan:video:current"].window_seconds == 86400.0
    assert limits["token_plan:general:weekly"].window_seconds == 604800.0

    assert ProviderAdapterGap.PROVIDER_GLOBAL_COVERAGE_UNPROVEN in result.gaps
    assert ProviderAdapterGap.PROVIDER_STATUS_SEMANTICS_UNPROVEN in result.gaps
    assert ProviderAdapterGap.REMAINING_PERCENT_SEMANTICS_UNPROVEN in result.gaps
    assert ProviderAdapterGap.WINDOW_POLICY_SEMANTICS_UNPROVEN in result.gaps
    # A fractional provider percentage is accepted as an observed field but is not
    # converted into quota counts or a derived remaining value.
    assert general.limit == Decimal("0")


def test_minimax_mapper_rejects_business_error_and_usage_above_total() -> None:
    product, product_key, _account_key, binding = _bound(
        "minimax", "MiniMax-M3", "token-plan", region="cn"
    )
    raw = _minimax_success_body()
    raw["base_resp"] = {"status_code": 2049, "status_msg": "invalid api key"}
    with pytest.raises(ValueError, match="status_code=0"):
        MiniMaxResourceAdapter().map_token_plan_remains_response(
            raw,
            key=product_key,
            product=product,
            bindings=(binding,),
            provenance=_prov("minimax"),
            validity=_valid("minimax"),
        )

    raw = _minimax_success_body()
    raw["model_remains"][0]["current_interval_total_count"] = 1
    raw["model_remains"][0]["current_interval_usage_count"] = 2
    with pytest.raises(ValueError, match="usage_count cannot exceed total_count"):
        MiniMaxResourceAdapter().map_token_plan_remains_response(
            raw,
            key=product_key,
            product=product,
            bindings=(binding,),
            provenance=_prov("minimax"),
            validity=_valid("minimax"),
        )



def test_account_balance_cannot_be_attached_to_product_snapshot() -> None:
    from llm_loop.resources.vendor_facts import ProviderAuthoritativeSnapshot

    product, product_key, _account_key, binding = _bound(
        "deepseek", "deepseek-flash", "standard-api"
    )
    with pytest.raises(ValueError, match="account balance requires exact-account"):
        ProviderAuthoritativeSnapshot(
            provider_id="deepseek",
            applicability=ProviderFactApplicability.EXACT_PRODUCT,
            resource_key=product_key,
            product=product,
            provenance=_prov("deepseek"),
            validity=_valid("deepseek"),
            bindings=(binding,),
            account_balance=ProviderAccountBalance(is_available=True),
        )


def test_minimax_e4_source_has_no_fixed_window_policy_or_governor_dependency() -> None:
    root = Path(__file__).parents[2]
    source = (root / "src/llm_loop/resources/vendor_adapters/minimax.py").read_text().lower()
    assert "18000" not in source
    assert "14400" not in source
    assert "resources.governor" not in source
    assert "resourcegovernor" not in source

def test_e4_mapping_stays_observation_only_and_glm_is_untouched() -> None:
    assert not hasattr(DeepSeekResourceAdapter, "admit")
    assert not hasattr(MiniMaxResourceAdapter, "admit")

    from llm_loop.resources.vendor_adapters.glm import GlmResourceAdapter

    assert not hasattr(GlmResourceAdapter, "map_control_plane_response")
