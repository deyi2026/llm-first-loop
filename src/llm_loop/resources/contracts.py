"""Pure data contracts for the provider-agnostic Resource Governor.

RG-0 intentionally contains no scheduler, queue, provider client, prompt code,
or task-semantic classifier.  It only defines mechanical facts that later
runtime phases may use for admission and accounting.

A crucial boundary is the separation between operator-declared facts and live
observations.  Neither side silently overwrites or infers the other; a later
Governor must reconcile them with explicit provenance and freshness rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Final


class ExecutionClass(StrEnum):
    """Why compute is running, without judging the task's semantic value."""

    FOREGROUND_TASK = "foreground_task"
    SUBAGENT = "subagent"
    DELIBERATION = "deliberation"
    BACKGROUND_LEARNING = "background_learning"
    QUALIFICATION = "qualification"
    META_LEARNING = "meta_learning"


class ServicePriority(IntEnum):
    """Resource service order only; lower numeric value receives earlier service."""

    P0_FOREGROUND = 0
    P1_ACTIVE_TASK_AUXILIARY = 10
    P2_BACKGROUND_DELIBERATION = 20
    P3_BACKGROUND_LEARNING = 30
    P4_QUALIFICATION = 40
    P5_META_LEARNING = 50


DEFAULT_SERVICE_PRIORITY: Final[Mapping[ExecutionClass, ServicePriority]] = MappingProxyType(
    {
        ExecutionClass.FOREGROUND_TASK: ServicePriority.P0_FOREGROUND,
        ExecutionClass.SUBAGENT: ServicePriority.P1_ACTIVE_TASK_AUXILIARY,
        ExecutionClass.DELIBERATION: ServicePriority.P1_ACTIVE_TASK_AUXILIARY,
        ExecutionClass.BACKGROUND_LEARNING: ServicePriority.P3_BACKGROUND_LEARNING,
        ExecutionClass.QUALIFICATION: ServicePriority.P4_QUALIFICATION,
        ExecutionClass.META_LEARNING: ServicePriority.P5_META_LEARNING,
    }
)


class RuntimeType(StrEnum):
    """Mechanically declared/observed execution runtime category."""

    UNKNOWN = "unknown"
    LOCAL = "local"
    CLOUD = "cloud"
    REMOTE_SELF_HOSTED = "remote_self_hosted"


class CapabilityState(StrEnum):
    """Tri-state capability fact; UNKNOWN is distinct from a negative fact."""

    UNKNOWN = "unknown"
    YES = "yes"
    NO = "no"


class FactSource(StrEnum):
    """Where a resource fact came from."""

    OPERATOR_CONFIG = "operator_config"
    RUNTIME_PROBE = "runtime_probe"
    PROVIDER_RESPONSE = "provider_response"
    PROVIDER_DOCUMENTATION = "provider_documentation"
    PROVIDER_CONTROL_PLANE = "provider_control_plane"
    USAGE_LEDGER = "usage_ledger"


class ResourceScopeKind(StrEnum):
    """Scope whose mechanical capacity/quota is consumed by a provider request."""

    RUNTIME = "runtime"
    PROVIDER = "provider"
    PRODUCT = "product"
    ACCOUNT = "account"
    PROJECT = "project"
    MODEL = "model"


class ResourceDimension(StrEnum):
    """Independent mechanical resource dimensions over the same scope key."""

    CONCURRENCY = "concurrency"
    RATE = "rate"
    QUOTA = "quota"
    COST = "cost"


class RateLimitMetric(StrEnum):
    """Provider-defined rolling rate unit; RPM/TPM are common 60s instances."""

    REQUESTS = "requests"
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    TOTAL_TOKENS = "total_tokens"


class QuotaMetric(StrEnum):
    """Provider quota unit; PROVIDER_UNITS keeps plan-specific units opaque."""

    REQUESTS = "requests"
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    TOTAL_TOKENS = "total_tokens"
    PROVIDER_UNITS = "provider_units"


class PricingBasis(StrEnum):
    """Mechanical billing basis; rules may vary by time, length, or service tier."""

    INPUT_MILLION_TOKENS = "input_million_tokens"
    CACHED_INPUT_MILLION_TOKENS = "cached_input_million_tokens"
    OUTPUT_MILLION_TOKENS = "output_million_tokens"
    PROVIDER_UNIT = "provider_unit"
    SUBSCRIPTION_PERIOD = "subscription_period"


class AdmissionOutcome(StrEnum):
    """Mechanical Resource Governor response."""

    ADMITTED = "admitted"
    DEFERRED = "deferred"
    HARD_REJECTED = "hard_rejected"


class AdmissionReason(StrEnum):
    """Closed mechanical reason codes; none encode task quality or relevance."""

    AVAILABLE = "available"
    CONCURRENCY_FULL = "concurrency_full"
    HIGHER_PRIORITY_ACTIVE = "higher_priority_active"
    HIGHER_PRIORITY_WAITING = "higher_priority_waiting"
    REQUEST_RATE_LIMIT = "request_rate_limit"
    TOKEN_RATE_LIMIT = "token_rate_limit"
    COST_BUDGET_EXHAUSTED = "cost_budget_exhausted"
    TRUST_DOMAIN_FORBIDDEN = "trust_domain_forbidden"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    REQUIRED_FACT_UNKNOWN = "required_fact_unknown"
    FACT_CONFLICT = "fact_conflict"
    CANCELLED_BEFORE_START = "cancelled_before_start"


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


def _require_non_negative(name: str, value: int | float | None) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{name} must be >= 0")


def _require_positive(name: str, value: int | float | None) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be > 0")


def _require_decimal(name: str, value: Decimal, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if positive and value <= 0:
        raise ValueError(f"{name} must be > 0")
    if not positive and value < 0:
        raise ValueError(f"{name} must be >= 0")


@dataclass(frozen=True)
class FactProvenance:
    """Non-secret origin + acquisition time for a mechanical resource fact."""

    source: FactSource
    source_ref: str
    recorded_at: float

    def __post_init__(self) -> None:
        _require_text("source_ref", self.source_ref)
        _require_non_negative("recorded_at", self.recorded_at)


@dataclass(frozen=True)
class ResourceKey:
    """Stable non-secret alias for one capacity/quota scope."""

    provider_id: str
    scope_kind: ResourceScopeKind
    scope_id: str

    def __post_init__(self) -> None:
        _require_text("provider_id", self.provider_id)
        _require_text("scope_id", self.scope_id)


@dataclass(frozen=True)
class ResourceProductIdentity:
    """Explicit non-secret cloud product/account identity; never inferred from provider name."""

    provider_id: str
    product_id: str
    account_alias: str
    provenance: FactProvenance
    api_family: str | None = None
    region: str | None = None
    project_alias: str | None = None

    def __post_init__(self) -> None:
        _require_text("provider_id", self.provider_id)
        _require_text("product_id", self.product_id)
        _require_text("account_alias", self.account_alias)
        for name in ("api_family", "region", "project_alias"):
            value = getattr(self, name)
            if value is not None:
                _require_text(name, value)


@dataclass(frozen=True)
class ResourceRequirement:
    """One resource scope/dimension pair; no dimension implies another."""

    key: ResourceKey
    dimension: ResourceDimension


@dataclass(frozen=True)
class RateLimitSpec:
    """Declared rate limit over an exact window."""

    metric: RateLimitMetric
    limit: int
    window_seconds: float

    def __post_init__(self) -> None:
        _require_positive("limit", self.limit)
        _require_positive("window_seconds", self.window_seconds)


@dataclass(frozen=True)
class RateUsage:
    """Observed usage for the same metric/window vocabulary as RateLimitSpec."""

    metric: RateLimitMetric
    used: int
    window_seconds: float

    def __post_init__(self) -> None:
        _require_non_negative("used", self.used)
        _require_positive("window_seconds", self.window_seconds)


@dataclass(frozen=True)
class RateLimitResetFacts:
    """Normalized safe rate-limit/reset facts; raw response headers are never retained."""

    metric: RateLimitMetric
    limit: int | None = None
    remaining: int | None = None
    window_seconds: float | None = None
    reset_at: float | None = None
    reset_after_seconds: float | None = None

    def __post_init__(self) -> None:
        _require_non_negative("limit", self.limit)
        _require_non_negative("remaining", self.remaining)
        _require_positive("window_seconds", self.window_seconds)
        _require_non_negative("reset_at", self.reset_at)
        _require_non_negative("reset_after_seconds", self.reset_after_seconds)
        if self.limit is not None and self.remaining is not None and self.remaining > self.limit:
            raise ValueError("remaining cannot exceed limit")
        if all(
            value is None
            for value in (
                self.limit,
                self.remaining,
                self.window_seconds,
                self.reset_at,
                self.reset_after_seconds,
            )
        ):
            raise ValueError("rate-limit reset facts must contain at least one observed value")


@dataclass(frozen=True)
class QuotaSpec:
    """Declared quota ceiling; time window/reset may be fixed, calendar based, or unknown."""

    metric: QuotaMetric
    limit: Decimal
    provenance: FactProvenance
    window_seconds: float | None = None
    reset_at: float | None = None
    provider_unit: str | None = None

    def __post_init__(self) -> None:
        _require_decimal("limit", self.limit)
        _require_positive("window_seconds", self.window_seconds)
        _require_non_negative("reset_at", self.reset_at)
        if self.metric is QuotaMetric.PROVIDER_UNITS:
            if self.provider_unit is None:
                raise ValueError("provider_unit is required for PROVIDER_UNITS quota")
            _require_text("provider_unit", self.provider_unit)
        elif self.provider_unit is not None:
            _require_text("provider_unit", self.provider_unit)


@dataclass(frozen=True)
class QuotaUsage:
    """Observed quota consumption; Decimal supports weighted provider-defined units."""

    metric: QuotaMetric
    used: Decimal
    provenance: FactProvenance
    window_seconds: float | None = None
    reset_at: float | None = None
    provider_unit: str | None = None

    def __post_init__(self) -> None:
        _require_decimal("used", self.used)
        _require_positive("window_seconds", self.window_seconds)
        _require_non_negative("reset_at", self.reset_at)
        if self.metric is QuotaMetric.PROVIDER_UNITS:
            if self.provider_unit is None:
                raise ValueError("provider_unit is required for PROVIDER_UNITS quota usage")
            _require_text("provider_unit", self.provider_unit)
        elif self.provider_unit is not None:
            _require_text("provider_unit", self.provider_unit)


@dataclass(frozen=True)
class MoneyAmount:
    """Currency-safe amount; Decimal avoids binary floating point billing drift."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("amount must be Decimal")
        if self.amount < 0:
            raise ValueError("amount must be >= 0")
        _require_text("currency", self.currency)


@dataclass(frozen=True)
class TokenPricing:
    """Operator/provider-sourced token prices; absent prices remain unknown."""

    provider_id: str
    model_id: str
    input_per_million: Decimal | None
    cached_input_per_million: Decimal | None
    output_per_million: Decimal | None
    currency: str
    provenance: FactProvenance

    def __post_init__(self) -> None:
        _require_text("provider_id", self.provider_id)
        _require_text("model_id", self.model_id)
        _require_text("currency", self.currency)
        for name in ("input_per_million", "cached_input_per_million", "output_per_million"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, Decimal):
                    raise TypeError(f"{name} must be Decimal or None")
                if value < 0:
                    raise ValueError(f"{name} must be >= 0")


@dataclass(frozen=True)
class PricingRule:
    """One normalized price rule with only mechanical selectors."""

    rule_id: str
    basis: PricingBasis
    price: MoneyAmount
    min_input_tokens: int | None = None
    max_input_tokens: int | None = None
    service_tier: str | None = None
    effective_from: float | None = None
    effective_until: float | None = None
    provider_unit: str | None = None
    period_seconds: float | None = None

    def __post_init__(self) -> None:
        _require_text("rule_id", self.rule_id)
        _require_non_negative("min_input_tokens", self.min_input_tokens)
        _require_non_negative("max_input_tokens", self.max_input_tokens)
        _require_non_negative("effective_from", self.effective_from)
        _require_non_negative("effective_until", self.effective_until)
        _require_positive("period_seconds", self.period_seconds)
        if (
            self.min_input_tokens is not None
            and self.max_input_tokens is not None
            and self.min_input_tokens > self.max_input_tokens
        ):
            raise ValueError("min_input_tokens cannot exceed max_input_tokens")
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_from >= self.effective_until
        ):
            raise ValueError("effective_from must be earlier than effective_until")
        if self.service_tier is not None:
            _require_text("service_tier", self.service_tier)
        if self.basis is PricingBasis.PROVIDER_UNIT:
            if self.provider_unit is None:
                raise ValueError("provider_unit is required for PROVIDER_UNIT pricing")
            _require_text("provider_unit", self.provider_unit)
        elif self.provider_unit is not None:
            _require_text("provider_unit", self.provider_unit)
        if self.basis is PricingBasis.SUBSCRIPTION_PERIOD and self.period_seconds is None:
            raise ValueError("period_seconds is required for SUBSCRIPTION_PERIOD pricing")


@dataclass(frozen=True)
class PricingSchedule:
    """Authoritative normalized pricing rules for one explicit resource product."""

    product: ResourceProductIdentity
    provenance: FactProvenance
    rules: tuple[PricingRule, ...]
    model_id: str | None = None

    def __post_init__(self) -> None:
        if not self.rules:
            raise ValueError("pricing schedule must contain at least one rule")
        if self.model_id is not None:
            _require_text("model_id", self.model_id)
        currencies = {rule.price.currency for rule in self.rules}
        if len(currencies) != 1:
            raise ValueError("pricing schedule rules must use one currency")


@dataclass(frozen=True)
class CostBudget:
    """Mechanical monetary ceiling for a resource scope and exact time window."""

    limit: MoneyAmount
    window_seconds: float
    provenance: FactProvenance

    def __post_init__(self) -> None:
        _require_positive("window_seconds", self.window_seconds)


@dataclass(frozen=True)
class CostUsage:
    """Observed monetary usage over one exact accounting window."""

    used: MoneyAmount
    window_seconds: float

    def __post_init__(self) -> None:
        _require_positive("window_seconds", self.window_seconds)


@dataclass(frozen=True)
class ProviderUsageFacts:
    """Per-call provider usage facts; None means unreported and is distinct from zero."""

    provider_id: str
    model_id: str
    provenance: FactProvenance
    product: ResourceProductIdentity | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    provider_units: Decimal | None = None
    provider_unit: str | None = None

    def __post_init__(self) -> None:
        _require_text("provider_id", self.provider_id)
        _require_text("model_id", self.model_id)
        for name in (
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            _require_non_negative(name, getattr(self, name))
        if (
            self.input_tokens is not None
            and self.cached_input_tokens is not None
            and self.cached_input_tokens > self.input_tokens
        ):
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        if self.provider_units is not None:
            _require_decimal("provider_units", self.provider_units)
            if self.provider_unit is None:
                raise ValueError("provider_unit is required when provider_units are reported")
        if self.provider_unit is not None:
            _require_text("provider_unit", self.provider_unit)
        if self.product is not None and self.product.provider_id != self.provider_id:
            raise ValueError("product provider_id must match usage provider_id")


@dataclass(frozen=True)
class ProviderResponseFacts:
    """Safe normalized HTTP response facts; raw headers are never retained."""

    provider_id: str
    model_id: str
    provenance: FactProvenance
    status_code: int
    product: ResourceProductIdentity | None = None
    retry_after_seconds: float | None = None
    rate_limits: tuple[RateLimitResetFacts, ...] = ()

    def __post_init__(self) -> None:
        _require_text("provider_id", self.provider_id)
        _require_text("model_id", self.model_id)
        if not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be a valid HTTP status")
        _require_non_negative("retry_after_seconds", self.retry_after_seconds)
        if self.product is not None and self.product.provider_id != self.provider_id:
            raise ValueError("product provider_id must match response provider_id")


@dataclass(frozen=True)
class ProviderErrorFacts:
    """Safe normalized provider failure facts; excludes body, raw headers, prompt, and credentials."""

    provider_id: str
    model_id: str
    provenance: FactProvenance
    product: ResourceProductIdentity | None = None
    status_code: int | None = None
    provider_code: str | None = None
    retry_after_seconds: float | None = None
    rate_limits: tuple[RateLimitResetFacts, ...] = ()

    def __post_init__(self) -> None:
        _require_text("provider_id", self.provider_id)
        _require_text("model_id", self.model_id)
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be a valid HTTP status")
        if self.provider_code is not None:
            _require_text("provider_code", self.provider_code)
        _require_non_negative("retry_after_seconds", self.retry_after_seconds)
        if self.product is not None and self.product.provider_id != self.provider_id:
            raise ValueError("product provider_id must match error provider_id")


@dataclass(frozen=True)
class DeclaredResourceProfile:
    """Operator/provider-declared limits; never silently treated as live truth."""

    key: ResourceKey
    provenance: FactProvenance
    runtime_type: RuntimeType = RuntimeType.UNKNOWN
    max_concurrency: int | None = None
    rate_limits: tuple[RateLimitSpec, ...] = ()
    quota_limits: tuple[QuotaSpec, ...] = ()
    cost_budget: CostBudget | None = None
    product: ResourceProductIdentity | None = None
    trust_domain: str | None = None
    supports_cancel: CapabilityState = CapabilityState.UNKNOWN
    supports_priority: CapabilityState = CapabilityState.UNKNOWN
    supports_parallelism: CapabilityState = CapabilityState.UNKNOWN

    def __post_init__(self) -> None:
        _require_positive("max_concurrency", self.max_concurrency)
        if self.product is not None and self.product.provider_id != self.key.provider_id:
            raise ValueError("product provider_id must match resource key provider_id")
        if self.trust_domain is not None:
            _require_text("trust_domain", self.trust_domain)


@dataclass(frozen=True)
class ObservedResourceState:
    """Point-in-time runtime facts; UNKNOWN/None means not observed, never guessed."""

    key: ResourceKey
    provenance: FactProvenance
    runtime_type: RuntimeType = RuntimeType.UNKNOWN
    runtime_model_id: str | None = None
    runtime_max_output_tokens: int | None = None
    max_concurrency: int | None = None
    in_flight: int | None = None
    rate_usage: tuple[RateUsage, ...] = ()
    quota_usage: tuple[QuotaUsage, ...] = ()
    cost_usage: CostUsage | None = None
    product: ResourceProductIdentity | None = None
    local_memory_pressure: float | None = None
    local_cache_slots_total: int | None = None
    local_cache_slots_used: int | None = None
    supports_cancel: CapabilityState = CapabilityState.UNKNOWN
    supports_priority: CapabilityState = CapabilityState.UNKNOWN
    supports_parallelism: CapabilityState = CapabilityState.UNKNOWN

    def __post_init__(self) -> None:
        if self.runtime_model_id is not None:
            _require_text("runtime_model_id", self.runtime_model_id)
        _require_positive("runtime_max_output_tokens", self.runtime_max_output_tokens)
        _require_positive("max_concurrency", self.max_concurrency)
        _require_non_negative("in_flight", self.in_flight)
        _require_non_negative("local_cache_slots_total", self.local_cache_slots_total)
        _require_non_negative("local_cache_slots_used", self.local_cache_slots_used)
        if self.product is not None and self.product.provider_id != self.key.provider_id:
            raise ValueError("product provider_id must match resource key provider_id")
        if self.local_memory_pressure is not None and not 0 <= self.local_memory_pressure <= 1:
            raise ValueError("local_memory_pressure must be within [0, 1]")
        if (
            self.local_cache_slots_total is not None
            and self.local_cache_slots_used is not None
            and self.local_cache_slots_used > self.local_cache_slots_total
        ):
            raise ValueError("local_cache_slots_used cannot exceed local_cache_slots_total")


@dataclass(frozen=True)
class TrustConstraint:
    """Mechanical allow relation supplied by a separate TrustDomainPolicy."""

    material_domain: str
    allowed_execution_domains: tuple[str, ...]
    provenance: FactProvenance

    def __post_init__(self) -> None:
        _require_text("material_domain", self.material_domain)
        if not self.allowed_execution_domains:
            raise ValueError("allowed_execution_domains must be non-empty")
        for domain in self.allowed_execution_domains:
            _require_text("allowed_execution_domains item", domain)
        if len(set(self.allowed_execution_domains)) != len(self.allowed_execution_domains):
            raise ValueError("allowed_execution_domains contains duplicate values")


@dataclass(frozen=True)
class AdmissionRequest:
    """One provider call's resource request; contains no prompt or task semantics."""

    request_id: str
    owner_ref: str
    execution_class: ExecutionClass
    service_priority: ServicePriority
    provider_id: str
    model_id: str
    resource_keys: tuple[ResourceKey, ...]
    submitted_at: float
    estimated_input_tokens: int | None = None
    reserved_output_tokens: int | None = None
    estimated_cost: MoneyAmount | None = None
    trust_constraint: TrustConstraint | None = None

    def __post_init__(self) -> None:
        _require_text("request_id", self.request_id)
        _require_text("owner_ref", self.owner_ref)
        _require_text("provider_id", self.provider_id)
        _require_text("model_id", self.model_id)
        _require_non_negative("submitted_at", self.submitted_at)
        _require_non_negative("estimated_input_tokens", self.estimated_input_tokens)
        _require_non_negative("reserved_output_tokens", self.reserved_output_tokens)
        if not self.resource_keys:
            raise ValueError("resource_keys must be non-empty")
        if len(set(self.resource_keys)) != len(self.resource_keys):
            raise ValueError("resource_keys contains duplicate values")
        if any(key.provider_id != self.provider_id for key in self.resource_keys):
            raise ValueError("resource key provider_id must match request provider_id")


@dataclass(frozen=True)
class ResourceLease:
    """Mechanical ownership fact returned only after successful admission."""

    lease_id: str
    request_id: str
    owner_ref: str
    execution_class: ExecutionClass
    service_priority: ServicePriority
    provider_id: str
    model_id: str
    resource_keys: tuple[ResourceKey, ...]
    admitted_at: float

    def __post_init__(self) -> None:
        _require_text("lease_id", self.lease_id)
        _require_text("request_id", self.request_id)
        _require_text("owner_ref", self.owner_ref)
        _require_text("provider_id", self.provider_id)
        _require_text("model_id", self.model_id)
        _require_non_negative("admitted_at", self.admitted_at)
        if not self.resource_keys:
            raise ValueError("resource_keys must be non-empty")
        if any(key.provider_id != self.provider_id for key in self.resource_keys):
            raise ValueError("resource key provider_id must match lease provider_id")


@dataclass(frozen=True)
class AdmissionDecision:
    """Closed admission result. Free-form semantic rationale is intentionally absent."""

    request_id: str
    outcome: AdmissionOutcome
    reason: AdmissionReason
    decided_at: float
    lease: ResourceLease | None = None
    blocked_keys: tuple[ResourceKey, ...] = ()
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        _require_text("request_id", self.request_id)
        _require_non_negative("decided_at", self.decided_at)
        _require_non_negative("retry_after_seconds", self.retry_after_seconds)
        if self.outcome is AdmissionOutcome.ADMITTED:
            if self.lease is None:
                raise ValueError("ADMITTED decision requires a lease")
            if self.reason is not AdmissionReason.AVAILABLE:
                raise ValueError("ADMITTED decision requires AVAILABLE reason")
            if self.lease.request_id != self.request_id:
                raise ValueError("lease request_id must match decision request_id")
        else:
            if self.lease is not None:
                raise ValueError("non-ADMITTED decision cannot carry a lease")
            if self.reason is AdmissionReason.AVAILABLE:
                raise ValueError("AVAILABLE reason is valid only for ADMITTED decisions")
