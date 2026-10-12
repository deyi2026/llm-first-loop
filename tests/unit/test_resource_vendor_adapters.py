from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from llm_loop.resources.contracts import (
    FactProvenance,
    FactSource,
    MoneyAmount,
    PricingBasis,
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
    CoverageState,
    FactValidity,
    FactValidityKind,
    ProviderResourceBinding,
)
from llm_loop.resources.vendor_adapters.deepseek import DeepSeekResourceAdapter
from llm_loop.resources.vendor_adapters.glm import GlmResourceAdapter
from llm_loop.resources.vendor_adapters.minimax import MiniMaxResourceAdapter
from llm_loop.resources.vendor_facts import ProviderAdapterGap, ProviderGlobalCoverageProof


def _prov(source: FactSource, ref: str = "fixture") -> FactProvenance:
    return FactProvenance(source=source, source_ref=ref, recorded_at=100.0)


def _valid(ref: str = "snapshot:v1") -> FactValidity:
    return FactValidity(
        FactValidityKind.BOUNDED,
        valid_from=100.0,
        valid_until=200.0,
        version_ref=ref,
    )


def _product(provider: str, product_id: str) -> ResourceProductIdentity:
    return ResourceProductIdentity(
        provider_id=provider,
        product_id=product_id,
        account_alias="primary",
        provenance=_prov(FactSource.OPERATOR_CONFIG, f"binding:{provider}:{product_id}"),
    )


def _binding(provider: str, model: str, key: ResourceKey, product: ResourceProductIdentity):
    return ProviderResourceBinding(
        provider_id=provider,
        model_id=model,
        resource_keys=(key,),
        product=product,
        provenance=_prov(FactSource.OPERATOR_CONFIG, f"binding:{provider}:{model}"),
        validity=_valid("binding:v1"),
    )


def test_deepseek_documented_concurrency_stays_published_default() -> None:
    adapter = DeepSeekResourceAdapter()
    result = adapter.published_account_concurrency(
        model_id="deepseek-v4-flash",
        max_concurrency=2500,
        account_override_possible=True,
        provenance=_prov(FactSource.PROVIDER_DOCUMENTATION, "deepseek:rate-limit-doc"),
        validity=_valid("deepseek-doc:v1"),
    )
    assert result.authoritative == ()
    assert result.published[0].max_concurrency == 2500
    assert result.published[0].override_possible is True
    assert result.gaps == (ProviderAdapterGap.DOCUMENTATION_ONLY,)


def test_deepseek_never_aliases_local_bare_model_to_current_documented_model() -> None:
    adapter = DeepSeekResourceAdapter()
    documented = ("deepseek-v4-flash", "deepseek-v4-pro")
    assert adapter.model_mapping_gaps("deepseek-v4-flash", documented_model_ids=documented) == ()
    assert adapter.model_mapping_gaps("deepseek-flash", documented_model_ids=documented) == (
        ProviderAdapterGap.MODEL_MAPPING_UNPROVEN,
    )


def test_deepseek_exact_account_limit_requires_live_provider_fact() -> None:
    adapter = DeepSeekResourceAdapter()
    product = _product("deepseek", "paygo")
    key = ResourceKey("deepseek", ResourceScopeKind.ACCOUNT, "primary")
    binding = _binding("deepseek", "deepseek-v4-flash", key, product)
    result = adapter.exact_account_concurrency(
        key=key,
        product=product,
        binding=binding,
        max_concurrency=3000,
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE, "account:limits:v1"),
        validity=_valid("account:limits:v1"),
    )
    snapshot = result.authoritative[0]
    assert snapshot.declared_profile is not None
    assert snapshot.declared_profile.max_concurrency == 3000
    assert ProviderAdapterGap.PROVIDER_GLOBAL_COVERAGE_UNPROVEN in result.gaps

    with pytest.raises(ValueError, match="live provider provenance"):
        adapter.exact_account_concurrency(
            key=key,
            product=product,
            binding=binding,
            max_concurrency=2500,
            provenance=_prov(FactSource.PROVIDER_DOCUMENTATION),
            validity=_valid(),
        )


def test_glm_current_local_alias_is_not_mapped_to_different_documented_model() -> None:
    adapter = GlmResourceAdapter()
    documented = ("GLM-5.2", "GLM-5-Turbo", "GLM-4.7")
    assert adapter.model_mapping_gaps("glm-5.3", documented_model_ids=documented) == (
        ProviderAdapterGap.MODEL_MAPPING_UNPROVEN,
    )


def test_glm_approximate_published_prompt_limits_are_not_typed_as_exact_quota() -> None:
    adapter = GlmResourceAdapter()
    result = adapter.published_coding_plan(
        product_id="coding-plan-pro",
        model_id="GLM-5.2",
        provenance=_prov(FactSource.PROVIDER_DOCUMENTATION, "glm:coding-plan:overview"),
        validity=_valid("glm-doc:v1"),
        published_limits_are_approximate=True,
    )
    profile = result.published[0]
    assert profile.quota_limits == ()
    assert profile.max_concurrency is None
    assert result.gaps == (
        ProviderAdapterGap.DOCUMENTATION_ONLY,
        ProviderAdapterGap.APPROXIMATE_VALUE_NOT_NORMALIZED,
    )


def test_glm_exact_coding_plan_quota_requires_control_plane_and_product_scope() -> None:
    adapter = GlmResourceAdapter()
    product = _product("glm", "coding-plan-pro")
    key = ResourceKey("glm", ResourceScopeKind.PRODUCT, "primary:coding-plan-pro")
    binding = _binding("glm", "GLM-5.2", key, product)
    window = AccountingWindow("glm:5h:100", 100.0, 18100.0)
    quota = QuotaSpec(
        metric=QuotaMetric.PROVIDER_UNITS,
        limit=Decimal("400"),
        window_seconds=18000.0,
        provider_unit="coding_prompt",
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
    )
    usage = QuotaUsage(
        metric=QuotaMetric.PROVIDER_UNITS,
        used=Decimal("25"),
        window_seconds=18000.0,
        provider_unit="coding_prompt",
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
    )
    result = adapter.exact_coding_plan_quota(
        key=key,
        product=product,
        bindings=(binding,),
        quota_limits=(quota,),
        quota_usage=(usage,),
        windows=(window,),
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE, "glm:usage-snapshot"),
        validity=_valid("glm:usage-snapshot:v1"),
    )
    snapshot = result.authoritative[0]
    assert snapshot.observed_state is not None
    assert snapshot.observed_state.quota_usage[0].used == Decimal("25")
    assert result.gaps == (ProviderAdapterGap.PROVIDER_GLOBAL_COVERAGE_UNPROVEN,)


def test_minimax_token_plan_marketing_agent_count_is_not_concurrency_limit() -> None:
    adapter = MiniMaxResourceAdapter()
    result = adapter.published_token_plan(
        product_id="token-plan-plus",
        model_id="MiniMax-M3",
        provenance=_prov(FactSource.PROVIDER_DOCUMENTATION, "minimax:token-plan"),
        validity=_valid("minimax-doc:v1"),
        published_agent_concurrency_is_approximate=True,
    )
    assert result.published[0].max_concurrency is None
    assert ProviderAdapterGap.APPROXIMATE_VALUE_NOT_NORMALIZED in result.gaps


def test_minimax_exact_token_plan_quota_can_carry_control_plane_coverage_proof() -> None:
    adapter = MiniMaxResourceAdapter()
    product = _product("minimax", "token-plan-plus")
    key = ResourceKey("minimax", ResourceScopeKind.PRODUCT, "primary:token-plan-plus")
    binding = _binding("minimax", "MiniMax-M3", key, product)
    window = AccountingWindow("minimax:5h:100", 100.0, 18100.0)
    quota = QuotaSpec(
        metric=QuotaMetric.PROVIDER_UNITS,
        limit=Decimal("1000"),
        window_seconds=18000.0,
        provider_unit="token_plan_request",
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
    )
    usage = QuotaUsage(
        metric=QuotaMetric.PROVIDER_UNITS,
        used=Decimal("100"),
        window_seconds=18000.0,
        provider_unit="token_plan_request",
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE),
    )
    proof = ProviderGlobalCoverageProof(
        key=key,
        window=window,
        coverage=CoverageState.COMPLETE,
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE, "minimax:token-plan-remains"),
        validity=_valid("minimax:remains:v1"),
    )
    result = adapter.exact_token_plan_quota(
        key=key,
        product=product,
        bindings=(binding,),
        quota_limits=(quota,),
        quota_usage=(usage,),
        windows=(window,),
        coverage_proofs=(proof,),
        provenance=_prov(FactSource.PROVIDER_CONTROL_PLANE, "minimax:token-plan-remains"),
        validity=_valid("minimax:remains:v1"),
    )
    assert result.gaps == ()
    snapshot = result.authoritative[0]
    assert snapshot.coverage_proofs == (proof,)


def test_minimax_paygo_pricing_requires_explicit_product_scope() -> None:
    adapter = MiniMaxResourceAdapter()
    product = _product("minimax", "paygo")
    key = ResourceKey("minimax", ResourceScopeKind.PRODUCT, "primary:paygo")
    rules = (
        PricingRule(
            rule_id="m3-input-up-to-512k",
            basis=PricingBasis.INPUT_MILLION_TOKENS,
            price=MoneyAmount(Decimal("0.3"), "USD"),
            max_input_tokens=524288,
        ),
        PricingRule(
            rule_id="m3-output-up-to-512k",
            basis=PricingBasis.OUTPUT_MILLION_TOKENS,
            price=MoneyAmount(Decimal("1.2"), "USD"),
            max_input_tokens=524288,
        ),
    )
    binding = _binding("minimax", "MiniMax-M3", key, product)
    result = adapter.paygo_pricing(
        key=key,
        product=product,
        binding=binding,
        model_id="MiniMax-M3",
        rules=rules,
        provenance=_prov(FactSource.PROVIDER_DOCUMENTATION, "minimax:pricing"),
        validity=_valid("minimax:pricing:v1"),
    )
    schedule = result.authoritative[0].pricing_schedules[0]
    assert schedule.product.product_id == "paygo"
    assert len(schedule.rules) == 2


def test_vendor_adapters_do_no_network_io_and_are_not_consumed_by_governor() -> None:
    root = Path(__file__).parents[2]
    adapter_root = root / "src/llm_loop/resources/vendor_adapters"
    combined = "\n".join(path.read_text().lower() for path in adapter_root.glob("*.py"))
    assert "import httpx" not in combined
    assert "import requests" not in combined
    assert "urllib.request" not in combined
    assert "resources.governor" not in combined

    for rel in (
        "src/llm_loop/resources/governor.py",
        "src/llm_loop/resources/provider_calls.py",
        "src/llm_loop/core/loop/engine.py",
        "src/llm_loop/factory.py",
    ):
        text = (root / rel).read_text()
        assert "vendor_adapters" not in text
        assert "ProviderAuthoritativeSnapshot" not in text


def test_rg3e_design_pointer_keeps_observation_only_boundary() -> None:
    root = Path(__file__).parents[2]
    architecture = (
        root / "docs/DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md"
    ).read_text()
    design = (root / "docs/DESIGN-20260910-resource-governor-rg3e-authoritative-adapters.md").read_text()
    assert "DESIGN-20260910-resource-governor-rg3e-authoritative-adapters.md" in architecture
    assert "contract/observation-first implementation candidate" in architecture
    assert "RG-3E does not yet calculate or enforce a cost budget" in design
    assert "no model-visible tool" in design
    assert "RG-3F" in design and "RG-3G" in design
