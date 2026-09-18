"""Provider-call lease coordination for RG-2.

RG-2 applies ResourceGovernor only when a runtime adapter can prove a concrete
local concurrency scope. Remote/cloud calls remain behavior-identical until the
later cloud concurrency/rate phase has explicit provider facts.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from llm_loop.resources.contracts import (
    AdmissionOutcome,
    AdmissionRequest,
    ExecutionClass,
    ObservedResourceState,
    ResourceLease,
    ServicePriority,
)
from llm_loop.resources.governor import ResourceGovernor
from llm_loop.resources.lfrt_runtime import LocalRuntimeTargetState
from llm_loop.resources.local_runtime import LocalRuntimeConcurrencyAdapter
from llm_loop.resources.provider_settlement import (
    ProviderAttemptKind,
    ProviderCallIdentity,
    ProviderCallOutcome,
    ProviderCallPurpose,
    ProviderCallSettlementJournal,
    ProviderCallSite,
    bind_provider_call_site,
)


class ResourceAdmissionError(RuntimeError):
    """Mechanical provider-call admission failed despite a qualified resource."""


class ProviderCallCoordinator:
    """Map a real provider client to qualified resources and hold leases per call."""

    def __init__(
        self,
        governor: ResourceGovernor,
        *,
        local_runtime: LocalRuntimeConcurrencyAdapter | Any,
        settlement_journal: ProviderCallSettlementJournal | None = None,
        admission_authority: str = "legacy",
        lfrt_runtime: Any | None = None,
        clock=time.time,
    ) -> None:
        self._governor = governor
        self._local_runtime = local_runtime
        authority = str(admission_authority or "legacy").strip().lower()
        if authority not in {"legacy", "lfrt"}:
            raise ValueError("admission_authority must be legacy or lfrt")
        self._settlement_journal = settlement_journal
        self._admission_authority = authority
        self._lfrt_runtime = lfrt_runtime
        self._clock = clock

    @property
    def governor(self) -> ResourceGovernor:
        return self._governor

    @staticmethod
    def _target(
        client: object,
        *,
        provider_id: str | None,
        model_id: str | None,
    ) -> tuple[str, str]:
        provider = str(provider_id or getattr(client, "provider", "") or "").strip()
        model = str(model_id or getattr(client, "model", "") or "").strip()
        return provider, model

    @property
    def settlement_journal(self) -> ProviderCallSettlementJournal | None:
        return self._settlement_journal

    def open_shadow_call_for_client(
        self,
        client: object,
        *,
        session_id: str,
        idempotency_key: str,
        owner_ref: str,
        execution_class: ExecutionClass,
        service_priority: ServicePriority,
        purpose: ProviderCallPurpose,
    ) -> ProviderCallIdentity | None:
        """Open RG-3C logical identity only when the real transport shares its journal."""

        journal = self._settlement_journal
        observer = getattr(client, "transport_observer", None)
        if (
            journal is None
            or observer is None
            or getattr(observer, "settlement_journal", None) is not journal
        ):
            return None
        try:
            return journal.open_call(
                session_id=session_id,
                idempotency_key=idempotency_key,
                owner_ref=owner_ref,
                execution_class=execution_class,
                service_priority=service_priority,
                purpose=purpose,
            )
        except Exception:
            return None

    @contextmanager
    def bind_shadow_call_site(
        self,
        call: ProviderCallIdentity | None,
        client: object,
        *,
        attempt_kind: ProviderAttemptKind,
        site_index: int,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> Iterator[None]:
        """Bind RG-3C correlation without changing admission or provider execution."""

        if call is None:
            yield
            return
        provider, model = self._target(
            client, provider_id=provider_id, model_id=model_id
        )
        if not provider or not model:
            yield
            return
        site = ProviderCallSite(
            call=call,
            attempt_kind=attempt_kind,
            site_index=int(site_index),
            provider_id=provider,
            model_id=model,
        )
        with bind_provider_call_site(site):
            yield

    def settle_shadow_call(
        self, call: ProviderCallIdentity | None, outcome: ProviderCallOutcome
    ) -> None:
        journal = self._settlement_journal
        if journal is None or call is None:
            return
        try:
            journal.settle_call(call, outcome)
        except Exception:
            return

    def _legacy_shadow_conflicts(
        self,
        client: object,
        *,
        provider: str,
        model: str,
        state: ObservedResourceState,
        generation: str | None,
    ) -> bool:
        """Return only a mechanical contradiction; shadow absence is neutral."""
        try:
            legacy_state = self._local_runtime.observe(
                client, provider_id=provider, model_id=model
            )
        except Exception:  # noqa: BLE001 - unavailable shadow is not authority
            return False
        if legacy_state is None:
            return False
        return bool(
            legacy_state.key != state.key
            or legacy_state.runtime_type is not state.runtime_type
            or legacy_state.max_concurrency != state.max_concurrency
            or generation is None
            or not legacy_state.provenance.source_ref.endswith(generation)
        )

    def revalidate_request_for_client(
        self,
        client: object,
        request: AdmissionRequest,
        *,
        expected_generation: str | None,
    ) -> None:
        """Recheck LFRT immediately before a delayed transport without renewing its lease."""
        if self._admission_authority != "lfrt":
            return
        if len(request.resource_keys) != 1:
            raise ResourceAdmissionError(
                "provider resource admission failed: fact_conflict"
            )
        expected_key = request.resource_keys[0]
        adapter = self._lfrt_runtime
        if adapter is None:
            self._governor.invalidate_concurrency_limit(expected_key)
            raise ResourceAdmissionError(
                "provider resource admission failed: required_fact_unknown"
            )
        try:
            target = adapter.observe_target(
                client, provider_id=request.provider_id, model_id=request.model_id
            )
        except Exception as exc:  # noqa: BLE001 - authority failure is terminal
            self._governor.invalidate_concurrency_limit(expected_key)
            raise ResourceAdmissionError(
                "provider resource admission failed: required_fact_unknown"
            ) from exc
        if target.state is LocalRuntimeTargetState.NOT_APPLICABLE:
            # Non-managed target (e.g. cloud provider, non-loopback base_url): LFRT
            # has no authority fact here, mirroring build_request_for_client's
            # NOT_APPLICABLE -> None -> RG-1 fallback. The RG-1 lease stands and
            # this is not a conflict. (Root cause of the 6350/6350 learning
            # requeue starvation observed 2026-09-17 on cloud-model deployments.)
            return
        if target.state is LocalRuntimeTargetState.MANAGED_BUT_UNKNOWN:
            self._governor.invalidate_concurrency_limit(expected_key)
            raise ResourceAdmissionError(
                "provider resource admission failed: required_fact_unknown"
            )
        if target.state is not LocalRuntimeTargetState.OBSERVED or target.resource is None:
            self._governor.invalidate_concurrency_limit(expected_key)
            raise ResourceAdmissionError(
                "provider resource admission failed: fact_conflict"
            )
        state = target.resource
        installed_limit = self._governor.concurrency_limit(expected_key)
        installed_generation = self._governor.concurrency_limit_generation(expected_key)
        if (
            state.key != expected_key
            or expected_generation is None
            or target.generation != expected_generation
            or installed_generation != expected_generation
            or state.max_concurrency != installed_limit
            or self._legacy_shadow_conflicts(
                client,
                provider=request.provider_id,
                model=request.model_id,
                state=state,
                generation=target.generation,
            )
        ):
            self._governor.invalidate_concurrency_limit(expected_key)
            raise ResourceAdmissionError(
                "provider resource admission failed: fact_conflict"
            )

    def build_request_for_client(
        self,
        client: object,
        *,
        execution_class: ExecutionClass,
        service_priority: ServicePriority,
        owner_ref: str,
        provider_id: str | None = None,
        model_id: str | None = None,
        request_id: str | None = None,
    ) -> AdmissionRequest | None:
        """Build an admission request only for a mechanically qualified RG-2 scope."""
        provider, model = self._target(
            client, provider_id=provider_id, model_id=model_id
        )
        if not provider or not model:
            return None
        generation = None
        if self._admission_authority == "lfrt":
            adapter = self._lfrt_runtime
            if adapter is None:
                raise ResourceAdmissionError(
                    "provider resource admission failed: required_fact_unknown"
                )
            try:
                target = adapter.observe_target(
                    client, provider_id=provider, model_id=model
                )
            except Exception as exc:  # noqa: BLE001 - authority failure is terminal
                raise ResourceAdmissionError(
                    "provider resource admission failed: required_fact_unknown"
                ) from exc
            if target.state is LocalRuntimeTargetState.NOT_APPLICABLE:
                return None
            if target.state is not LocalRuntimeTargetState.OBSERVED or target.resource is None:
                if target.key is not None:
                    self._governor.invalidate_concurrency_limit(target.key)
                raise ResourceAdmissionError(
                    "provider resource admission failed: required_fact_unknown"
                )
            state = target.resource
            generation = target.generation
            # LFRT is the only positive authority. Legacy is a shadow veto only.
            if self._legacy_shadow_conflicts(
                client,
                provider=provider,
                model=model,
                state=state,
                generation=generation,
            ):
                self._governor.invalidate_concurrency_limit(state.key)
                raise ResourceAdmissionError(
                    "provider resource admission failed: fact_conflict"
                )
        else:
            try:
                state = self._local_runtime.observe(
                    client,
                    provider_id=provider,
                    model_id=model,
                )
            except Exception:  # noqa: BLE001 - legacy adapter failures preserve old behavior
                state = None
            if state is None or state.max_concurrency is None:
                return None
        if state.max_concurrency is None:
            if self._admission_authority == "lfrt":
                self._governor.invalidate_concurrency_limit(state.key)
                raise ResourceAdmissionError(
                    "provider resource admission failed: required_fact_unknown"
                )
            return None
        if state.key.provider_id != provider:
            raise ValueError("runtime resource provider_id does not match provider target")
        self._governor.set_concurrency_limit(
            state.key,
            state.max_concurrency,
            source_ref=(state.provenance.source_ref if self._admission_authority == "lfrt" else None),
            generation=generation,
        )
        return AdmissionRequest(
            request_id=request_id or f"provider:{uuid.uuid4().hex}",
            owner_ref=str(owner_ref),
            execution_class=execution_class,
            service_priority=service_priority,
            provider_id=provider,
            model_id=model,
            resource_keys=(state.key,),
            submitted_at=float(self._clock()),
        )

    @contextmanager
    def lease_for_client(
        self,
        client: object,
        *,
        execution_class: ExecutionClass,
        service_priority: ServicePriority,
        owner_ref: str,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> Iterator[ResourceLease | None]:
        """Hold a qualified local-runtime lease across exactly one provider call.

        ``None`` means the target is mechanically not applicable to the selected
        local authority (notably cloud). Under LFRT authority, a managed local
        target with unknown facts raises before transport instead of bypassing RG-2.
        Cloud resource enforcement is intentionally later.
        """
        request = self.build_request_for_client(
            client,
            execution_class=execution_class,
            service_priority=service_priority,
            owner_ref=owner_ref,
            provider_id=provider_id,
            model_id=model_id,
        )
        if request is None:
            yield None
            return
        decision = self._governor.acquire(request)
        if decision.outcome is not AdmissionOutcome.ADMITTED or decision.lease is None:
            raise ResourceAdmissionError(
                f"provider resource admission failed: {decision.reason.value}"
            )
        lease = decision.lease
        try:
            yield lease
        finally:
            self._governor.release(lease)


@contextmanager
def provider_call_lease(
    owner: object,
    client: object,
    *,
    execution_class: ExecutionClass,
    service_priority: ServicePriority,
    owner_ref: str,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> Iterator[ResourceLease | None]:
    """Compatibility helper: no coordinator installed means exact legacy behavior."""
    coordinator = getattr(owner, "provider_call_coordinator", None)
    if coordinator is None:
        yield None
        return
    with coordinator.lease_for_client(
        client,
        execution_class=execution_class,
        service_priority=service_priority,
        owner_ref=owner_ref,
        provider_id=provider_id,
        model_id=model_id,
    ) as lease:
        yield lease


@contextmanager
def foreground_task_provider_call_lease(
    owner: object,
    client: object,
    *,
    owner_ref: str,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> Iterator[ResourceLease | None]:
    """RG-2 fixed service class for user Task provider attempts."""
    with provider_call_lease(
        owner,
        client,
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        owner_ref=owner_ref,
        provider_id=provider_id,
        model_id=model_id,
    ) as lease:
        yield lease


@contextmanager
def subagent_provider_call_lease(
    owner: object,
    client: object,
    *,
    owner_ref: str,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> Iterator[ResourceLease | None]:
    """RG-2 fixed service class for active-task SubAgent provider attempts."""
    with provider_call_lease(
        owner,
        client,
        execution_class=ExecutionClass.SUBAGENT,
        service_priority=ServicePriority.P1_ACTIVE_TASK_AUXILIARY,
        owner_ref=owner_ref,
        provider_id=provider_id,
        model_id=model_id,
    ) as lease:
        yield lease


def foreground_task_provider_chat(
    owner: object,
    client: object,
    call: Callable[..., Any],
    kwargs: dict[str, Any],
    *,
    owner_ref: str,
    provider_id: str | None = None,
    model_id: str | None = None,
    before_call: Callable[[], None] | None = None,
    provider_call: ProviderCallIdentity | None = None,
    attempt_kind: ProviderAttemptKind = ProviderAttemptKind.PRIMARY,
    site_index: int = 0,
) -> Any:
    """Execute one foreground Task sync provider call under its qualified lease."""
    coordinator = getattr(owner, "provider_call_coordinator", None)
    site_scope = (
        coordinator.bind_shadow_call_site(
            provider_call,
            client,
            attempt_kind=attempt_kind,
            site_index=site_index,
            provider_id=provider_id,
            model_id=model_id,
        )
        if coordinator is not None
        else nullcontext()
    )
    with foreground_task_provider_call_lease(
        owner,
        client,
        owner_ref=owner_ref,
        provider_id=provider_id,
        model_id=model_id,
    ), site_scope:
        if before_call is not None:
            before_call()
        return call(**kwargs)


def foreground_task_provider_stream(
    owner: object,
    client: object,
    call: Callable[..., Any],
    kwargs: dict[str, Any],
    *,
    owner_ref: str,
    provider_id: str | None = None,
    model_id: str | None = None,
    before_call: Callable[[], None] | None = None,
    provider_call: ProviderCallIdentity | None = None,
    attempt_kind: ProviderAttemptKind = ProviderAttemptKind.PRIMARY,
    site_index: int = 0,
) -> Iterator[Any]:
    """Wrap one foreground Task stream; lease lives until stream terminal/close."""
    coordinator = getattr(owner, "provider_call_coordinator", None)
    site_scope = (
        coordinator.bind_shadow_call_site(
            provider_call,
            client,
            attempt_kind=attempt_kind,
            site_index=site_index,
            provider_id=provider_id,
            model_id=model_id,
        )
        if coordinator is not None
        else nullcontext()
    )
    with foreground_task_provider_call_lease(
        owner,
        client,
        owner_ref=owner_ref,
        provider_id=provider_id,
        model_id=model_id,
    ), site_scope:
        if before_call is not None:
            before_call()
        inner = call(**kwargs)
        return (yield from inner)


def subagent_provider_chat(
    owner: object,
    client: object,
    call: Callable[..., Any],
    kwargs: dict[str, Any],
    *,
    owner_ref: str,
    provider_id: str | None = None,
    model_id: str | None = None,
    provider_call: ProviderCallIdentity | None = None,
    attempt_kind: ProviderAttemptKind = ProviderAttemptKind.PRIMARY,
    site_index: int = 0,
) -> Any:
    """Execute one SubAgent sync provider call under the active-task P1 lease."""
    coordinator = getattr(owner, "provider_call_coordinator", None)
    site_scope = (
        coordinator.bind_shadow_call_site(
            provider_call,
            client,
            attempt_kind=attempt_kind,
            site_index=site_index,
            provider_id=provider_id,
            model_id=model_id,
        )
        if coordinator is not None
        else nullcontext()
    )
    with subagent_provider_call_lease(
        owner,
        client,
        owner_ref=owner_ref,
        provider_id=provider_id,
        model_id=model_id,
    ), site_scope:
        return call(**kwargs)
