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
    USAGE_LEDGER = "usage_ledger"


class ResourceScopeKind(StrEnum):
    """Scope whose mechanical capacity/quota is consumed by a provider request."""

    RUNTIME = "runtime"
    PROVIDER = "provider"
    ACCOUNT = "account"
    PROJECT = "project"
    MODEL = "model"


class RateLimitMetric(StrEnum):
    """Provider-defined rolling rate unit; RPM/TPM are common 60s instances."""

    REQUESTS = "requests"
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    TOTAL_TOKENS = "total_tokens"


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
class DeclaredResourceProfile:
    """Operator/provider-declared limits; never silently treated as live truth."""

    key: ResourceKey
    provenance: FactProvenance
    runtime_type: RuntimeType = RuntimeType.UNKNOWN
    max_concurrency: int | None = None
    rate_limits: tuple[RateLimitSpec, ...] = ()
    cost_budget: CostBudget | None = None
    trust_domain: str | None = None
    supports_cancel: CapabilityState = CapabilityState.UNKNOWN
    supports_priority: CapabilityState = CapabilityState.UNKNOWN
    supports_parallelism: CapabilityState = CapabilityState.UNKNOWN

    def __post_init__(self) -> None:
        _require_positive("max_concurrency", self.max_concurrency)
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
    cost_usage: CostUsage | None = None
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
