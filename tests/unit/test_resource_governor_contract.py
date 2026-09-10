from __future__ import annotations

import ast
from dataclasses import fields
from decimal import Decimal
from pathlib import Path

import pytest

from llm_loop.resources.contracts import (
    DEFAULT_SERVICE_PRIORITY,
    AdmissionDecision,
    AdmissionOutcome,
    AdmissionReason,
    AdmissionRequest,
    CapabilityState,
    CostBudget,
    CostUsage,
    DeclaredResourceProfile,
    ExecutionClass,
    FactProvenance,
    FactSource,
    MoneyAmount,
    ObservedResourceState,
    RateLimitMetric,
    RateLimitSpec,
    RateUsage,
    ResourceKey,
    ResourceLease,
    ResourceScopeKind,
    RuntimeType,
    ServicePriority,
    TokenPricing,
    TrustConstraint,
)


def _prov(source: FactSource = FactSource.OPERATOR_CONFIG) -> FactProvenance:
    return FactProvenance(source=source, source_ref="test:resource-fact", recorded_at=1.0)


def _runtime_key() -> ResourceKey:
    return ResourceKey(
        provider_id="cognilocal",
        scope_kind=ResourceScopeKind.RUNTIME,
        scope_id="local-runtime-primary",
    )


def _account_key() -> ResourceKey:
    return ResourceKey(
        provider_id="glm",
        scope_kind=ResourceScopeKind.ACCOUNT,
        scope_id="account-primary",
    )


def test_execution_classes_and_default_service_order_are_closed() -> None:
    assert [item.value for item in ExecutionClass] == [
        "foreground_task",
        "subagent",
        "deliberation",
        "background_learning",
        "qualification",
        "meta_learning",
    ]
    assert DEFAULT_SERVICE_PRIORITY == {
        ExecutionClass.FOREGROUND_TASK: ServicePriority.P0_FOREGROUND,
        ExecutionClass.SUBAGENT: ServicePriority.P1_ACTIVE_TASK_AUXILIARY,
        ExecutionClass.DELIBERATION: ServicePriority.P1_ACTIVE_TASK_AUXILIARY,
        ExecutionClass.BACKGROUND_LEARNING: ServicePriority.P3_BACKGROUND_LEARNING,
        ExecutionClass.QUALIFICATION: ServicePriority.P4_QUALIFICATION,
        ExecutionClass.META_LEARNING: ServicePriority.P5_META_LEARNING,
    }
    assert ServicePriority.P0_FOREGROUND < ServicePriority.P1_ACTIVE_TASK_AUXILIARY
    assert ServicePriority.P1_ACTIVE_TASK_AUXILIARY < ServicePriority.P2_BACKGROUND_DELIBERATION
    assert ServicePriority.P2_BACKGROUND_DELIBERATION < ServicePriority.P3_BACKGROUND_LEARNING
    assert ServicePriority.P3_BACKGROUND_LEARNING < ServicePriority.P4_QUALIFICATION
    assert ServicePriority.P4_QUALIFICATION < ServicePriority.P5_META_LEARNING


def test_deliberation_priority_is_invocation_context_not_a_new_execution_class() -> None:
    req = AdmissionRequest(
        request_id="req-deliberation-background",
        owner_ref="deliberation:test",
        execution_class=ExecutionClass.DELIBERATION,
        service_priority=ServicePriority.P2_BACKGROUND_DELIBERATION,
        provider_id="glm",
        model_id="glm-5.3",
        resource_keys=(_account_key(),),
        submitted_at=2.0,
    )
    assert req.execution_class is ExecutionClass.DELIBERATION
    assert req.service_priority is ServicePriority.P2_BACKGROUND_DELIBERATION


def test_declared_and_observed_facts_are_separate_and_unknown_is_explicit() -> None:
    key = _runtime_key()
    declared = DeclaredResourceProfile(
        key=key,
        runtime_type=RuntimeType.UNKNOWN,
        supports_cancel=CapabilityState.UNKNOWN,
        supports_priority=CapabilityState.UNKNOWN,
        supports_parallelism=CapabilityState.UNKNOWN,
        provenance=_prov(),
    )
    observed = ObservedResourceState(
        key=key,
        runtime_type=RuntimeType.LOCAL,
        max_concurrency=1,
        in_flight=0,
        local_cache_slots_total=8,
        local_cache_slots_used=2,
        supports_parallelism=CapabilityState.YES,
        provenance=_prov(FactSource.RUNTIME_PROBE),
    )
    assert declared.runtime_type is RuntimeType.UNKNOWN
    assert declared.max_concurrency is None
    assert observed.runtime_type is RuntimeType.LOCAL
    assert observed.max_concurrency == 1
    assert observed.local_cache_slots_total == 8


def test_provider_name_never_infers_runtime_type() -> None:
    for provider_id in ("local", "cognilocal", "glm", "minimax", "deepseek"):
        profile = DeclaredResourceProfile(
            key=ResourceKey(
                provider_id=provider_id,
                scope_kind=ResourceScopeKind.PROVIDER,
                scope_id="default",
            ),
            runtime_type=RuntimeType.UNKNOWN,
            provenance=_prov(),
        )
        assert profile.runtime_type is RuntimeType.UNKNOWN


def test_rate_limits_support_provider_specific_metrics_and_windows() -> None:
    profile = DeclaredResourceProfile(
        key=_account_key(),
        runtime_type=RuntimeType.CLOUD,
        rate_limits=(
            RateLimitSpec(metric=RateLimitMetric.REQUESTS, limit=60, window_seconds=60.0),
            RateLimitSpec(metric=RateLimitMetric.INPUT_TOKENS, limit=200_000, window_seconds=60.0),
        ),
        provenance=_prov(),
    )
    state = ObservedResourceState(
        key=_account_key(),
        rate_usage=(
            RateUsage(metric=RateLimitMetric.REQUESTS, used=4, window_seconds=60.0),
            RateUsage(metric=RateLimitMetric.INPUT_TOKENS, used=12_000, window_seconds=60.0),
        ),
        provenance=_prov(FactSource.USAGE_LEDGER),
    )
    assert profile.rate_limits[1].metric is RateLimitMetric.INPUT_TOKENS
    assert state.rate_usage[0].used == 4


def test_pricing_and_budget_are_optional_facts_not_cost_tier_inference() -> None:
    pricing = TokenPricing(
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        input_per_million=Decimal("1.25"),
        cached_input_per_million=Decimal("0.25"),
        output_per_million=Decimal("5.00"),
        currency="USD",
        provenance=_prov(),
    )
    budget = CostBudget(
        limit=MoneyAmount(amount=Decimal("10.00"), currency="USD"),
        window_seconds=86_400.0,
        provenance=_prov(),
    )
    usage = CostUsage(
        used=MoneyAmount(amount=Decimal("2.25"), currency="USD"),
        window_seconds=86_400.0,
    )
    profile = DeclaredResourceProfile(
        key=ResourceKey("deepseek", ResourceScopeKind.ACCOUNT, "primary"),
        runtime_type=RuntimeType.CLOUD,
        cost_budget=budget,
        provenance=_prov(),
    )
    state = ObservedResourceState(
        key=profile.key,
        cost_usage=usage,
        provenance=_prov(FactSource.USAGE_LEDGER),
    )
    assert pricing.provider_id == profile.key.provider_id
    assert profile.cost_budget == budget
    assert state.cost_usage == usage


def test_admission_request_can_consume_multiple_resource_scopes_atomically() -> None:
    keys = (
        ResourceKey("glm", ResourceScopeKind.ACCOUNT, "account-primary"),
        ResourceKey("glm", ResourceScopeKind.PROJECT, "project-default"),
        ResourceKey("glm", ResourceScopeKind.MODEL, "glm-5.3"),
    )
    request = AdmissionRequest(
        request_id="req-1",
        owner_ref="run:1",
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        provider_id="glm",
        model_id="glm-5.3",
        resource_keys=keys,
        estimated_input_tokens=10_000,
        reserved_output_tokens=2_000,
        estimated_cost=MoneyAmount(Decimal("0.08"), "USD"),
        submitted_at=3.0,
    )
    assert request.resource_keys == keys
    assert request.estimated_input_tokens == 10_000


def test_admission_request_rejects_cross_provider_resource_key_and_duplicates() -> None:
    with pytest.raises(ValueError, match="provider_id"):
        AdmissionRequest(
            request_id="req-cross-provider",
            owner_ref="run:2",
            execution_class=ExecutionClass.FOREGROUND_TASK,
            service_priority=ServicePriority.P0_FOREGROUND,
            provider_id="glm",
            model_id="glm-5.3",
            resource_keys=(ResourceKey("deepseek", ResourceScopeKind.ACCOUNT, "primary"),),
            submitted_at=4.0,
        )

    duplicate = ResourceKey("glm", ResourceScopeKind.ACCOUNT, "primary")
    with pytest.raises(ValueError, match="duplicate"):
        AdmissionRequest(
            request_id="req-duplicate",
            owner_ref="run:3",
            execution_class=ExecutionClass.FOREGROUND_TASK,
            service_priority=ServicePriority.P0_FOREGROUND,
            provider_id="glm",
            model_id="glm-5.3",
            resource_keys=(duplicate, duplicate),
            submitted_at=4.0,
        )


def test_trust_constraint_is_mechanical_allow_relation_with_provenance() -> None:
    trust = TrustConstraint(
        material_domain="workspace:private",
        allowed_execution_domains=("local:owner", "cloud:approved"),
        provenance=_prov(),
    )
    request = AdmissionRequest(
        request_id="req-trust",
        owner_ref="learning:1",
        execution_class=ExecutionClass.BACKGROUND_LEARNING,
        service_priority=ServicePriority.P3_BACKGROUND_LEARNING,
        provider_id="glm",
        model_id="glm-5.3",
        resource_keys=(_account_key(),),
        trust_constraint=trust,
        submitted_at=5.0,
    )
    assert request.trust_constraint == trust
    assert "cloud:approved" in trust.allowed_execution_domains


def test_lease_and_decision_encode_only_mechanical_admission_outcome() -> None:
    key = _runtime_key()
    lease = ResourceLease(
        lease_id="lease-1",
        request_id="req-local",
        owner_ref="learning:2",
        execution_class=ExecutionClass.BACKGROUND_LEARNING,
        service_priority=ServicePriority.P3_BACKGROUND_LEARNING,
        provider_id="cognilocal",
        model_id="ornith-1.5-35b-a3b-mlx",
        resource_keys=(key,),
        admitted_at=6.0,
    )
    admitted = AdmissionDecision(
        request_id="req-local",
        outcome=AdmissionOutcome.ADMITTED,
        reason=AdmissionReason.AVAILABLE,
        decided_at=6.0,
        lease=lease,
    )
    deferred = AdmissionDecision(
        request_id="req-cloud",
        outcome=AdmissionOutcome.DEFERRED,
        reason=AdmissionReason.CONCURRENCY_FULL,
        decided_at=7.0,
        blocked_keys=(_account_key(),),
        retry_after_seconds=1.5,
    )
    assert admitted.lease == lease
    assert deferred.lease is None
    assert deferred.retry_after_seconds == 1.5


def test_decision_invariants_reject_fake_lease_or_available_reason() -> None:
    with pytest.raises(ValueError, match="lease"):
        AdmissionDecision(
            request_id="req-bad",
            outcome=AdmissionOutcome.ADMITTED,
            reason=AdmissionReason.AVAILABLE,
            decided_at=1.0,
        )
    with pytest.raises(ValueError, match="AVAILABLE"):
        AdmissionDecision(
            request_id="req-bad-2",
            outcome=AdmissionOutcome.DEFERRED,
            reason=AdmissionReason.AVAILABLE,
            decided_at=1.0,
        )


def test_contract_rejects_negative_mechanical_quantities() -> None:
    with pytest.raises(ValueError):
        RateLimitSpec(metric=RateLimitMetric.REQUESTS, limit=0, window_seconds=60.0)
    with pytest.raises(ValueError):
        ObservedResourceState(
            key=_runtime_key(),
            in_flight=-1,
            provenance=_prov(FactSource.RUNTIME_PROBE),
        )
    with pytest.raises(ValueError):
        MoneyAmount(Decimal("-0.01"), "USD")


def test_contract_has_no_task_semantic_or_prompt_payload_fields() -> None:
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
    }
    dataclasses = (
        DeclaredResourceProfile,
        ObservedResourceState,
        AdmissionRequest,
        AdmissionDecision,
        ResourceLease,
    )
    for cls in dataclasses:
        names = {item.name for item in fields(cls)}
        assert names.isdisjoint(forbidden), f"{cls.__name__}: {names & forbidden}"


def test_contract_module_is_pure_and_does_not_import_runtime_decision_planes() -> None:
    path = Path(__file__).parents[2] / "src/llm_loop/resources/contracts.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name.startswith("llm_loop.") for name in imported)


def test_rg1_wiring_is_narrow_and_task_subagent_provider_pool_remain_unwired() -> None:
    root = Path(__file__).parents[2]
    allowed = {
        root / "src/llm_loop/factory.py",
        root / "src/llm_loop/methods/learning_plane.py",
    }
    forbidden = {
        root / "src/llm_loop/subagent/runner.py",
        root / "src/llm_loop/llm/pool.py",
    }
    for path in allowed:
        text = path.read_text(encoding="utf-8")
        assert "llm_loop.resources" in text, path
    for path in forbidden:
        text = path.read_text(encoding="utf-8")
        assert "llm_loop.resources" not in text, path
        assert "ResourceGovernor" not in text, path

    engine_text = (root / "src/llm_loop/core/loop/engine.py").read_text(encoding="utf-8")
    assert "resource_governor: Any | None = None" in engine_text
    assert "try_acquire(" not in engine_text
    assert "acquire(" not in engine_text


def test_architecture_sot_points_to_rg0_contract_without_runtime_claim() -> None:
    root = Path(__file__).parents[2]
    text = (
        root / "docs/DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md"
    ).read_text(encoding="utf-8")
    assert "docs/DESIGN-20260910-resource-governor-rg0.md" in text
    assert "RG-0 仅冻结 contract，不接管任何 runtime path" in text


def test_fact_conflict_has_a_closed_mechanical_reason_code() -> None:
    assert AdmissionReason.FACT_CONFLICT.value == "fact_conflict"


def test_token_pricing_is_target_fact_not_embedded_in_resource_scope_profile() -> None:
    profile_fields = {item.name for item in fields(DeclaredResourceProfile)}
    assert "pricing" not in profile_fields
    pricing_fields = {item.name for item in fields(TokenPricing)}
    assert {"provider_id", "model_id", "provenance"} <= pricing_fields
