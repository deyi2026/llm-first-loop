"""RG-3E authority-safe provider/product fact envelopes.

This module is provider-agnostic. It keeps provider documentation defaults separate
from exact product/account/project facts so a public table can never silently become
live account truth. Vendor adapters may normalize external observations into these
contracts, but neither this module nor an adapter owns admission, routing, fallback,
or task semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from llm_loop.resources.contracts import (
    DeclaredResourceProfile,
    FactProvenance,
    FactSource,
    MoneyAmount,
    ObservedResourceState,
    PricingRule,
    PricingSchedule,
    QuotaSpec,
    RateLimitSpec,
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


class ProviderFactApplicability(StrEnum):
    """Mechanical scope to which an adapter can prove a fact applies."""

    PUBLISHED_DEFAULT = "published_default"
    EXACT_PRODUCT = "exact_product"
    EXACT_ACCOUNT = "exact_account"
    EXACT_PROJECT = "exact_project"


class ProviderAdapterGap(StrEnum):
    """Closed observation gaps; none are admission decisions."""

    PRODUCT_UNBOUND = "product_unbound"
    ACCOUNT_SCOPE_UNBOUND = "account_scope_unbound"
    PROJECT_SCOPE_UNBOUND = "project_scope_unbound"
    MODEL_MAPPING_UNPROVEN = "model_mapping_unproven"
    DOCUMENTATION_ONLY = "documentation_only"
    APPROXIMATE_VALUE_NOT_NORMALIZED = "approximate_value_not_normalized"
    CONTROL_PLANE_SCHEMA_UNPROVEN = "control_plane_schema_unproven"
    PROVIDER_GLOBAL_COVERAGE_UNPROVEN = "provider_global_coverage_unproven"
    FACT_NOT_CURRENT = "fact_not_current"
    PROVIDER_STATUS_SEMANTICS_UNPROVEN = "provider_status_semantics_unproven"
    REMAINING_PERCENT_SEMANTICS_UNPROVEN = "remaining_percent_semantics_unproven"
    WINDOW_POLICY_SEMANTICS_UNPROVEN = "window_policy_semantics_unproven"


@dataclass(frozen=True)
class ProviderPublishedResourceProfile:
    """Provider-published default/plan facts with deliberately no ResourceKey.

    Public documentation can be authoritative about what the provider publishes,
    while still not proving an exact account/project's current entitlement. The lack
    of ``scope_id`` is intentional and prevents accidental account binding.
    """

    provider_id: str
    scope_kind: ResourceScopeKind
    provenance: FactProvenance
    validity: FactValidity
    model_id: str | None = None
    product_id: str | None = None
    max_concurrency: int | None = None
    rate_limits: tuple[RateLimitSpec, ...] = ()
    quota_limits: tuple[QuotaSpec, ...] = ()
    pricing_rules: tuple[PricingRule, ...] = ()
    override_possible: bool = False

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id must be non-empty")
        if self.provenance.source is not FactSource.PROVIDER_DOCUMENTATION:
            raise ValueError("published profile requires PROVIDER_DOCUMENTATION provenance")
        if self.model_id is not None and not self.model_id.strip():
            raise ValueError("model_id must be non-empty when supplied")
        if self.product_id is not None and not self.product_id.strip():
            raise ValueError("product_id must be non-empty when supplied")
        if self.max_concurrency is not None and self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be > 0")


@dataclass(frozen=True)
class ProviderBalanceEntry:
    """One provider-reported monetary balance row; it is not a budget or spend limit."""

    total: MoneyAmount
    granted: MoneyAmount
    topped_up: MoneyAmount

    def __post_init__(self) -> None:
        currencies = {self.total.currency, self.granted.currency, self.topped_up.currency}
        if len(currencies) != 1:
            raise ValueError("balance row money amounts must use one currency")


@dataclass(frozen=True)
class ProviderAccountBalance:
    """Exact account balance/availability observation with no budget semantics."""

    is_available: bool
    balances: tuple[ProviderBalanceEntry, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.is_available, bool):
            raise TypeError("is_available must be bool")


@dataclass(frozen=True)
class ProviderGlobalCoverageProof:
    """Exact provider-side coverage assertion for one bound scope/window."""

    key: ResourceKey
    window: AccountingWindow
    coverage: CoverageState
    provenance: FactProvenance
    validity: FactValidity

    def __post_init__(self) -> None:
        if self.coverage is CoverageState.UNKNOWN:
            raise ValueError("coverage proof cannot claim UNKNOWN")
        if self.provenance.source is not FactSource.PROVIDER_CONTROL_PLANE:
            raise ValueError("provider-global coverage proof requires control-plane provenance")
        if self.validity.kind is FactValidityKind.UNKNOWN:
            raise ValueError("provider-global coverage proof requires explicit validity")


_EXACT_SCOPE = {
    ProviderFactApplicability.EXACT_PRODUCT: ResourceScopeKind.PRODUCT,
    ProviderFactApplicability.EXACT_ACCOUNT: ResourceScopeKind.ACCOUNT,
    ProviderFactApplicability.EXACT_PROJECT: ResourceScopeKind.PROJECT,
}


@dataclass(frozen=True)
class ProviderAuthoritativeSnapshot:
    """Normalized exact provider facts for one explicit product/resource scope.

    This is an observation envelope only. A future shadow-admission phase may compare
    these facts with RG-3D ledger projections, but RG-3E does not feed them into the
    ResourceGovernor.
    """

    provider_id: str
    applicability: ProviderFactApplicability
    resource_key: ResourceKey
    product: ResourceProductIdentity
    provenance: FactProvenance
    validity: FactValidity
    bindings: tuple[ProviderResourceBinding, ...] = ()
    declared_profile: DeclaredResourceProfile | None = None
    observed_state: ObservedResourceState | None = None
    pricing_schedules: tuple[PricingSchedule, ...] = ()
    accounting_windows: tuple[AccountingWindow, ...] = ()
    coverage_proofs: tuple[ProviderGlobalCoverageProof, ...] = ()
    account_balance: ProviderAccountBalance | None = None

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id must be non-empty")
        if self.applicability is ProviderFactApplicability.PUBLISHED_DEFAULT:
            raise ValueError("published defaults must use ProviderPublishedResourceProfile")
        expected_scope = _EXACT_SCOPE[self.applicability]
        if self.resource_key.scope_kind is not expected_scope:
            raise ValueError("resource_key scope does not match fact applicability")
        if self.resource_key.provider_id != self.provider_id:
            raise ValueError("resource_key provider_id must match snapshot provider_id")
        if self.product.provider_id != self.provider_id:
            raise ValueError("product provider_id must match snapshot provider_id")
        if self.applicability in {
            ProviderFactApplicability.EXACT_ACCOUNT,
            ProviderFactApplicability.EXACT_PROJECT,
        } and self.provenance.source not in {
            FactSource.PROVIDER_CONTROL_PLANE,
            FactSource.PROVIDER_RESPONSE,
        }:
            raise ValueError("exact account/project facts require live provider provenance")
        if self.applicability is ProviderFactApplicability.EXACT_PROJECT and not self.product.project_alias:
            raise ValueError("exact project facts require product.project_alias")
        if self.validity.kind is FactValidityKind.UNKNOWN:
            raise ValueError("authoritative exact snapshot requires explicit validity")
        if not any(
            (
                self.bindings,
                self.declared_profile is not None,
                self.observed_state is not None,
                self.pricing_schedules,
                self.accounting_windows,
                self.coverage_proofs,
                self.account_balance is not None,
            )
        ):
            raise ValueError("authoritative snapshot must contain at least one normalized fact")
        for binding in self.bindings:
            if binding.provider_id != self.provider_id or not binding.includes(self.resource_key):
                raise ValueError("binding must include snapshot resource_key for the same provider")
        for profile in (self.declared_profile, self.observed_state):
            if profile is not None and profile.key != self.resource_key:
                raise ValueError("profile key must equal snapshot resource_key")
        for schedule in self.pricing_schedules:
            if schedule.product != self.product:
                raise ValueError("pricing schedule product must equal snapshot product")
        for proof in self.coverage_proofs:
            if proof.key != self.resource_key:
                raise ValueError("coverage proof key must equal snapshot resource_key")
        if self.account_balance is not None and self.applicability is not ProviderFactApplicability.EXACT_ACCOUNT:
            raise ValueError("account balance requires exact-account applicability")


@dataclass(frozen=True)
class ProviderAdapterResult:
    """Observation-only result returned by a vendor adapter."""

    published: tuple[ProviderPublishedResourceProfile, ...] = ()
    authoritative: tuple[ProviderAuthoritativeSnapshot, ...] = ()
    gaps: tuple[ProviderAdapterGap, ...] = ()

    def __post_init__(self) -> None:
        if len(set(self.gaps)) != len(self.gaps):
            raise ValueError("adapter gaps contain duplicates")
