from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from llm_loop.event_log.model import (
    EVENT_PROVIDER_TRANSPORT_OPENED,
    EVENT_PROVIDER_TRANSPORT_SETTLED,
    Event,
)
from llm_loop.event_log.store import EventStore
from llm_loop.resources.contracts import (
    ExecutionClass,
    FactProvenance,
    FactSource,
    ResourceDimension,
    ResourceKey,
    ResourceProductIdentity,
    ResourceRequirement,
    ResourceScopeKind,
    ServicePriority,
)
from llm_loop.resources.ledger_projection import (
    AccountingWindow,
    CoverageState,
    FactFreshness,
    FactValidity,
    FactValidityKind,
    ProjectionCoverage,
    ProjectionIngestOutcome,
    ProviderResourceBinding,
    ProviderSettlementProjectionIndex,
    ShadowAdmissionFacts,
    ShadowFactGap,
    SourceSessionWatermark,
)
from llm_loop.resources.provider_settlement import (
    ProviderAttemptKind,
    ProviderCallOutcome,
    ProviderCallPurpose,
    ProviderCallSettlementJournal,
    ProviderCallSite,
    ProviderTransportOutcome,
)


def _prov(at: float = 10.0) -> FactProvenance:
    return FactProvenance(
        source=FactSource.OPERATOR_CONFIG,
        source_ref="test:rg3d-explicit-binding",
        recorded_at=at,
    )


def _key(provider_id: str = "provider-a", scope_id: str = "account-main") -> ResourceKey:
    return ResourceKey(provider_id, ResourceScopeKind.ACCOUNT, scope_id)


def _binding(
    provider_id: str = "provider-a",
    model_id: str = "model-a",
    *,
    key: ResourceKey | None = None,
    validity: FactValidity | None = None,
) -> ProviderResourceBinding:
    resource_key = key or _key(provider_id)
    return ProviderResourceBinding(
        provider_id=provider_id,
        model_id=model_id,
        resource_keys=(resource_key,),
        provenance=_prov(),
        validity=validity or FactValidity(FactValidityKind.OPEN_ENDED, valid_from=1.0),
    )


def _journal(
    tmp_path: Path,
    *,
    clock=lambda: 20.0,
) -> tuple[EventStore, ProviderSettlementProjectionIndex, ProviderCallSettlementJournal]:
    event_store = EventStore(tmp_path / "events")
    index = ProviderSettlementProjectionIndex(tmp_path / "audit" / "projection.sqlite3")
    journal = ProviderCallSettlementJournal(
        event_store,
        clock=clock,
        projection_sink=index,
    )
    return event_store, index, journal


def _one_attempt(
    journal: ProviderCallSettlementJournal,
    *,
    session_id: str,
    provider_id: str = "provider-a",
    model_id: str = "model-a",
    execution_class: ExecutionClass = ExecutionClass.FOREGROUND_TASK,
    purpose: ProviderCallPurpose = ProviderCallPurpose.TASK,
    usage: dict[str, int | str | None] | None = None,
    settle_attempt: bool = True,
    idempotency_key: str = "call-1",
):
    call = journal.open_call(
        session_id=session_id,
        idempotency_key=idempotency_key,
        owner_ref=f"owner:{session_id}:{idempotency_key}",
        execution_class=execution_class,
        service_priority=(
            ServicePriority.P0_FOREGROUND
            if execution_class is ExecutionClass.FOREGROUND_TASK
            else ServicePriority.P1_ACTIVE_TASK_AUXILIARY
        ),
        purpose=purpose,
    )
    attempt = journal.open_transport_attempt(
        ProviderCallSite(
            call=call,
            attempt_kind=ProviderAttemptKind.PRIMARY,
            site_index=0,
            provider_id=provider_id,
            model_id=model_id,
        ),
        transport_retry_index=0,
    )
    if settle_attempt:
        journal.settle_transport_attempt(
            session_id=session_id,
            attempt=attempt,
            outcome=ProviderTransportOutcome.SUCCESS,
            usage=usage
            or {
                "input_tokens": 10,
                "output_tokens": 2,
                "cached_input_tokens": 0,
                "reasoning_tokens": 1,
                "total_tokens": 12,
            },
            usage_observations=1,
            status_code=200,
            provider_code=None,
            retry_after_seconds=None,
            rate_limits=(),
            error_type=None,
        )
    journal.settle_call(call, ProviderCallOutcome.SUCCESS)
    return call, attempt


def test_fact_validity_requires_explicit_interval_and_reports_freshness() -> None:
    bounded = FactValidity(FactValidityKind.BOUNDED, valid_from=10.0, valid_until=20.0)
    assert bounded.freshness_at(9.0) is FactFreshness.NOT_YET_VALID
    assert bounded.freshness_at(10.0) is FactFreshness.CURRENT
    assert bounded.freshness_at(19.999) is FactFreshness.CURRENT
    assert bounded.freshness_at(20.0) is FactFreshness.EXPIRED
    assert FactValidity(FactValidityKind.UNKNOWN).freshness_at(10.0) is FactFreshness.UNKNOWN
    assert (
        FactValidity(FactValidityKind.IMMUTABLE_EVENT, valid_from=10.0).freshness_at(10000.0)
        is FactFreshness.CURRENT
    )
    with pytest.raises(ValueError, match="bounded validity"):
        FactValidity(FactValidityKind.BOUNDED, valid_from=10.0)
    with pytest.raises(ValueError, match="unknown validity"):
        FactValidity(FactValidityKind.UNKNOWN, valid_from=10.0)


def test_provider_resource_binding_is_explicit_and_provider_consistent() -> None:
    key = _key("provider-a")
    product = ResourceProductIdentity(
        provider_id="provider-a",
        product_id="product-x",
        account_alias="account-main",
        provenance=_prov(),
    )
    binding = ProviderResourceBinding(
        provider_id="provider-a",
        model_id="model-a",
        resource_keys=(key,),
        provenance=_prov(),
        validity=FactValidity(FactValidityKind.OPEN_ENDED, valid_from=1.0, version_ref="cfg:v3"),
        product=product,
    )
    assert binding.includes(key)
    assert binding.validity.version_ref == "cfg:v3"
    with pytest.raises(ValueError, match="resource key provider_id"):
        _binding("provider-a", key=_key("provider-b"))


def test_projection_sink_is_idempotent_and_rebuildable_from_eventstore(tmp_path: Path) -> None:
    event_store, index, journal = _journal(tmp_path)
    call, _ = _one_attempt(journal, session_id="s1")
    aggregate = index.aggregate(
        binding=_binding(), resource_key=_key(), window=AccountingWindow("w", 0.0, 100.0)
    )
    assert aggregate.calls == 1
    assert aggregate.attempts_opened == aggregate.attempts_settled == 1
    assert aggregate.attempts_complete is True
    assert aggregate.known_usage_sum["total_tokens"] == 12
    assert all(aggregate.usage_complete.values())
    assert aggregate.execution_class_counts == {"foreground_task": 1}
    assert aggregate.purpose_counts == {"task": 1}

    # A brand-new derived index rebuilt solely from EventStore reaches the same aggregate.
    rebuilt = ProviderSettlementProjectionIndex(tmp_path / "audit" / "rebuilt.sqlite3")
    report = rebuilt.reconcile_event_store(event_store, [call.session_id])
    assert report.coverage.source_set is CoverageState.COMPLETE
    assert report.coverage.provider_global is CoverageState.UNKNOWN
    assert report.coverage.source_watermark_ref.startswith("eventstore-watermark:")
    assert report.coverage.source_watermarks == (
        SourceSessionWatermark("s1", last_seq=4, event_count=4, skipped_lines=0),
    )
    assert report.conflicts == 0
    assert rebuilt.aggregate(
        binding=_binding(), resource_key=_key(), window=AccountingWindow("w", 0.0, 100.0)
    ) == aggregate

    # Reconciliation is idempotent: no new accounting rows appear.
    again = rebuilt.reconcile_event_store(event_store, [call.session_id])
    assert again.inserted == 0
    assert again.duplicates == 4


def test_cross_session_aggregate_keeps_execution_and_purpose_breakdown(tmp_path: Path) -> None:
    _event_store, index, journal = _journal(tmp_path)
    _one_attempt(journal, session_id="task-s", idempotency_key="task")
    _one_attempt(
        journal,
        session_id="sub-s",
        execution_class=ExecutionClass.SUBAGENT,
        purpose=ProviderCallPurpose.SUBAGENT,
        idempotency_key="sub",
        usage={
            "input_tokens": 20,
            "output_tokens": 4,
            "cached_input_tokens": 5,
            "reasoning_tokens": 2,
            "total_tokens": 24,
        },
    )
    aggregate = index.aggregate(
        binding=_binding(), resource_key=_key(), window=AccountingWindow("all", 0.0, 100.0)
    )
    assert aggregate.calls == 2
    assert aggregate.attempts_opened == 2
    assert aggregate.known_usage_sum == {
        "input_tokens": 30,
        "output_tokens": 6,
        "cached_input_tokens": 5,
        "reasoning_tokens": 3,
        "total_tokens": 36,
    }
    assert aggregate.execution_class_counts == {"foreground_task": 1, "subagent": 1}
    assert aggregate.purpose_counts == {"task": 1, "subagent": 1}


def test_cross_provider_fallback_is_attributed_to_actual_transport_target(tmp_path: Path) -> None:
    _event_store, index, journal = _journal(tmp_path)
    call = journal.open_call(
        session_id="s1",
        idempotency_key="fallback-chain",
        owner_ref="task:s1:round:1",
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        purpose=ProviderCallPurpose.TASK,
    )
    first = journal.open_transport_attempt(
        ProviderCallSite(call, ProviderAttemptKind.PRIMARY, 0, "provider-a", "model-a"),
        transport_retry_index=0,
    )
    journal.settle_transport_attempt(
        session_id="s1",
        attempt=first,
        outcome=ProviderTransportOutcome.ERROR,
        usage=None,
        usage_observations=0,
        status_code=503,
        provider_code=None,
        retry_after_seconds=None,
        rate_limits=(),
        error_type="HTTPError",
    )
    second = journal.open_transport_attempt(
        ProviderCallSite(call, ProviderAttemptKind.FALLBACK, 1, "provider-b", "model-b"),
        transport_retry_index=0,
    )
    journal.settle_transport_attempt(
        session_id="s1",
        attempt=second,
        outcome=ProviderTransportOutcome.SUCCESS,
        usage={
            "input_tokens": 9,
            "output_tokens": 1,
            "cached_input_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 10,
        },
        usage_observations=1,
        status_code=200,
        provider_code=None,
        retry_after_seconds=None,
        rate_limits=(),
        error_type=None,
    )
    journal.settle_call(call, ProviderCallOutcome.SUCCESS)

    a = index.aggregate(
        binding=_binding("provider-a", "model-a"),
        resource_key=_key("provider-a"),
        window=AccountingWindow("w", 0.0, 100.0),
    )
    b = index.aggregate(
        binding=_binding("provider-b", "model-b"),
        resource_key=_key("provider-b"),
        window=AccountingWindow("w", 0.0, 100.0),
    )
    assert a.attempts_opened == 1 and a.attempts_settled == 1
    assert a.known_usage_sum["total_tokens"] == 0
    assert a.usage_complete["total_tokens"] is False
    assert b.attempts_opened == 1 and b.known_usage_sum["total_tokens"] == 10


def test_opened_unsettled_attempt_cannot_masquerade_as_complete_window(tmp_path: Path) -> None:
    _event_store, index, journal = _journal(tmp_path)
    _one_attempt(
        journal,
        session_id="s1",
        settle_attempt=False,
        idempotency_key="lost-after-send",
    )
    aggregate = index.aggregate(
        binding=_binding(), resource_key=_key(), window=AccountingWindow("w", 0.0, 100.0)
    )
    assert aggregate.attempts_opened == 1
    assert aggregate.attempts_settled == 0
    assert aggregate.attempts_complete is False
    assert aggregate.known_usage_sum["input_tokens"] == 0
    assert aggregate.usage_complete["input_tokens"] is False


def test_known_sum_is_lower_bound_when_one_settled_attempt_has_unknown_usage(tmp_path: Path) -> None:
    _event_store, index, journal = _journal(tmp_path)
    _one_attempt(
        journal,
        session_id="known",
        idempotency_key="known",
        usage={
            "input_tokens": 30,
            "output_tokens": 4,
            "cached_input_tokens": 0,
            "reasoning_tokens": 2,
            "total_tokens": 34,
        },
    )
    _one_attempt(
        journal,
        session_id="unknown",
        idempotency_key="unknown",
        usage={
            "input_tokens": 20,
            "output_tokens": None,
            "cached_input_tokens": None,
            "reasoning_tokens": None,
            "total_tokens": None,
        },
    )
    aggregate = index.aggregate(
        binding=_binding(), resource_key=_key(), window=AccountingWindow("w", 0.0, 100.0)
    )
    assert aggregate.attempts_complete is True
    assert aggregate.known_usage_sum["input_tokens"] == 50
    assert aggregate.usage_complete["input_tokens"] is True
    assert aggregate.known_usage_sum["total_tokens"] == 34
    assert aggregate.usage_complete["total_tokens"] is False


def test_accounting_window_is_half_open(tmp_path: Path) -> None:
    event_store = EventStore(tmp_path / "events")
    index = ProviderSettlementProjectionIndex(tmp_path / "projection.sqlite3")
    journal_at_10 = ProviderCallSettlementJournal(
        event_store, clock=lambda: 10.0, projection_sink=index
    )
    _one_attempt(journal_at_10, session_id="at-start", idempotency_key="start")
    journal_at_20 = ProviderCallSettlementJournal(
        event_store, clock=lambda: 20.0, projection_sink=index
    )
    _one_attempt(journal_at_20, session_id="at-end", idempotency_key="end")
    aggregate = index.aggregate(
        binding=_binding(),
        resource_key=_key(),
        window=AccountingWindow("10-20", 10.0, 20.0),
    )
    assert aggregate.calls == 1
    assert aggregate.known_usage_sum["total_tokens"] == 12


def test_conflicting_attempt_identity_never_overwrites_original(tmp_path: Path) -> None:
    index = ProviderSettlementProjectionIndex(tmp_path / "projection.sqlite3")
    base_payload = {
        "call_id": "pcall:x",
        "attempt_id": "pattempt:x",
        "parent_attempt_id": None,
        "attempt_kind": "primary",
        "site_index": 0,
        "transport_retry_index": 0,
        "provider_id": "provider-a",
        "model_id": "model-a",
        "started_at": 10.0,
    }
    first = Event("evt-1", "s1", 1, EVENT_PROVIDER_TRANSPORT_OPENED, "t", base_payload)
    conflict = Event(
        "evt-2",
        "s1",
        2,
        EVENT_PROVIDER_TRANSPORT_OPENED,
        "t",
        {**base_payload, "provider_id": "provider-b"},
    )
    assert index.ingest_event(first) is ProjectionIngestOutcome.INSERTED
    assert index.ingest_event(first) is ProjectionIngestOutcome.DUPLICATE
    assert index.ingest_event(conflict) is ProjectionIngestOutcome.CONFLICT
    aggregate = index.aggregate(
        binding=_binding(), resource_key=_key(), window=AccountingWindow("w", 0.0, 100.0)
    )
    assert aggregate.attempts_opened == 1


def test_settlement_before_open_reconciles_without_fabricating_completion(tmp_path: Path) -> None:
    index = ProviderSettlementProjectionIndex(tmp_path / "projection.sqlite3")
    identity = {
        "call_id": "pcall:x",
        "attempt_id": "pattempt:x",
        "parent_attempt_id": None,
        "attempt_kind": "primary",
        "site_index": 0,
        "transport_retry_index": 0,
        "provider_id": "provider-a",
        "model_id": "model-a",
        "started_at": 10.0,
    }
    settled = Event(
        "evt-settled",
        "s1",
        2,
        EVENT_PROVIDER_TRANSPORT_SETTLED,
        "t",
        {
            **identity,
            "outcome": "success",
            "settled_at": 11.0,
            "usage": {
                "input_tokens": 5,
                "output_tokens": 1,
                "cached_input_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 6,
                "provider_units": None,
                "provider_unit": None,
            },
            "usage_observations": 1,
            "status_code": 200,
            "provider_code": None,
            "retry_after_seconds": None,
            "rate_limits": [],
            "error_type": None,
        },
    )
    opened = Event("evt-open", "s1", 1, EVENT_PROVIDER_TRANSPORT_OPENED, "t", identity)
    assert index.ingest_event(settled) is ProjectionIngestOutcome.INSERTED
    before = index.aggregate(
        binding=_binding(), resource_key=_key(), window=AccountingWindow("w", 0.0, 100.0)
    )
    # A settlement without the durable physical-send open fact is useful but not complete.
    assert before.attempts_opened == 0
    assert before.attempts_settled == 1
    assert before.attempts_complete is False
    assert before.known_usage_sum["total_tokens"] == 6
    assert before.usage_complete["total_tokens"] is False
    assert index.ingest_event(opened) is ProjectionIngestOutcome.INSERTED
    after = index.aggregate(
        binding=_binding(), resource_key=_key(), window=AccountingWindow("w", 0.0, 100.0)
    )
    assert after.attempts_opened == 1
    assert after.attempts_settled == 1
    assert after.attempts_complete is True
    assert after.usage_complete["total_tokens"] is True


def test_explicit_source_set_complete_never_implies_provider_global_complete(tmp_path: Path) -> None:
    event_store, index, journal = _journal(tmp_path)
    _one_attempt(journal, session_id="s1")
    report = index.reconcile_event_store(event_store, ["s1"])
    assert report.coverage.source_set is CoverageState.COMPLETE
    assert report.coverage.provider_global is CoverageState.UNKNOWN
    requirement = ResourceRequirement(_key(), ResourceDimension.RATE)
    facts = index.project_shadow_admission_facts(
        requirement=requirement,
        binding=_binding(),
        window=AccountingWindow("w", 0.0, 100.0),
        coverage=report.coverage,
        as_of=20.0,
    )
    assert ShadowFactGap.PROVIDER_GLOBAL_COVERAGE_UNKNOWN in facts.gaps
    assert facts.aggregate is not None


def test_corrupt_eventstore_line_degrades_only_explicit_source_coverage(tmp_path: Path) -> None:
    event_store, index, journal = _journal(tmp_path)
    _one_attempt(journal, session_id="s1")
    with (tmp_path / "events" / "s1.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{ corrupt\n")
    report = index.reconcile_event_store(event_store, ["s1"])
    assert report.coverage.source_set is CoverageState.PARTIAL
    assert report.coverage.skipped_event_lines == 1
    assert report.coverage.provider_global is CoverageState.UNKNOWN


def test_shadow_facts_require_explicit_current_binding_and_never_return_decision(tmp_path: Path) -> None:
    index = ProviderSettlementProjectionIndex(tmp_path / "projection.sqlite3")
    requirement = ResourceRequirement(_key(), ResourceDimension.QUOTA)
    coverage = ProjectionCoverage(CoverageState.UNKNOWN)
    unbound = index.project_shadow_admission_facts(
        requirement=requirement,
        binding=None,
        window=AccountingWindow("w", 0.0, 100.0),
        coverage=coverage,
        as_of=20.0,
    )
    assert unbound.aggregate is None
    assert unbound.gaps == (ShadowFactGap.SCOPE_UNBOUND,)

    expired = index.project_shadow_admission_facts(
        requirement=requirement,
        binding=_binding(
            validity=FactValidity(FactValidityKind.BOUNDED, valid_from=1.0, valid_until=10.0)
        ),
        window=AccountingWindow("w", 0.0, 100.0),
        coverage=coverage,
        as_of=20.0,
    )
    assert expired.binding_freshness is FactFreshness.EXPIRED
    assert ShadowFactGap.BINDING_NOT_CURRENT in expired.gaps
    assert {field.name for field in dataclasses.fields(ShadowAdmissionFacts)}.isdisjoint(
        {"outcome", "decision", "admitted", "rejected", "should_run"}
    )


def test_rg3d_projection_has_no_sensitive_payload_columns_or_enforcement_consumers(tmp_path: Path) -> None:
    index = ProviderSettlementProjectionIndex(tmp_path / "projection.sqlite3")
    with index._connect() as conn:  # noqa: SLF001 - schema privacy invariant
        columns = {
            row[1]
            for table in ("provider_calls", "provider_attempts")
            for row in conn.execute(f"PRAGMA table_info({table})")  # noqa: S608
        }
    assert columns.isdisjoint(
        {
            "prompt",
            "messages",
            "body",
            "headers",
            "raw_headers",
            "api_key",
            "authorization",
            "cookie",
            "tool_arguments",
            "task_text",
        }
    )
    root = Path(__file__).parents[2]
    projection = (root / "src/llm_loop/resources/ledger_projection.py").read_text(encoding="utf-8")
    lowered = projection.lower()
    for vendor in ("deepseek", "minimax", "glm"):
        assert vendor not in lowered
    for rel in (
        "src/llm_loop/resources/governor.py",
        "src/llm_loop/resources/provider_calls.py",
        "src/llm_loop/core/loop/engine_services/fallback.py",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        assert "ledger_projection" not in text
        assert "project_shadow_admission_facts" not in text




def test_known_source_coverage_is_bound_to_exact_eventstore_watermark() -> None:
    with pytest.raises(ValueError, match="source_scope_ref and source_watermark_ref"):
        ProjectionCoverage(
            source_set=CoverageState.COMPLETE,
            source_session_count=1,
            source_event_count=4,
        )
    watermark = SourceSessionWatermark("s1", last_seq=4, event_count=4, skipped_lines=0)
    scope_digest = hashlib.sha256(b"s1").hexdigest()[:24]
    watermark_digest = hashlib.sha256(b"s1:4:4:0").hexdigest()[:24]
    coverage = ProjectionCoverage(
        source_set=CoverageState.COMPLETE,
        source_scope_ref=f"explicit-sessions:{scope_digest}",
        source_watermark_ref=f"eventstore-watermark:{watermark_digest}",
        source_watermarks=(watermark,),
        source_session_count=1,
        source_event_count=4,
    )
    assert coverage.source_watermarks[0].last_seq == 4
    assert coverage.provider_global is CoverageState.UNKNOWN
    with pytest.raises(ValueError, match="source_watermark_ref does not match"):
        dataclasses.replace(coverage, source_watermark_ref="eventstore-watermark:tampered")

def test_known_provider_global_coverage_requires_provenance_and_currentness(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="provenance and validity"):
        ProjectionCoverage(
            source_set=CoverageState.UNKNOWN,
            provider_global=CoverageState.COMPLETE,
        )
    coverage = ProjectionCoverage(
        source_set=CoverageState.UNKNOWN,
        provider_global=CoverageState.COMPLETE,
        provider_global_provenance=FactProvenance(
            source=FactSource.PROVIDER_CONTROL_PLANE,
            source_ref="provider-control-plane:usage-snapshot:v1",
            recorded_at=5.0,
        ),
        provider_global_validity=FactValidity(
            FactValidityKind.BOUNDED, valid_from=5.0, valid_until=10.0, version_ref="snapshot:v1"
        ),
    )
    index = ProviderSettlementProjectionIndex(tmp_path / "projection.sqlite3")
    facts = index.project_shadow_admission_facts(
        requirement=ResourceRequirement(_key(), ResourceDimension.QUOTA),
        binding=_binding(),
        window=AccountingWindow("w", 0.0, 100.0),
        coverage=coverage,
        as_of=20.0,
    )
    assert ShadowFactGap.PROVIDER_GLOBAL_COVERAGE_NOT_CURRENT in facts.gaps
    assert ShadowFactGap.PROVIDER_GLOBAL_COVERAGE_UNKNOWN not in facts.gaps

def test_projection_sink_failure_is_fail_open_for_rg3c_settlement(tmp_path: Path) -> None:
    class _BrokenProjection:
        def ingest_event(self, _event) -> None:
            raise OSError("derived projection unavailable")

    event_store = EventStore(tmp_path / "events")
    journal = ProviderCallSettlementJournal(
        event_store,
        clock=lambda: 20.0,
        projection_sink=_BrokenProjection(),
    )
    call, _ = _one_attempt(journal, session_id="s1")
    snapshot = journal.snapshot_call(call)
    assert snapshot["attempts_complete"] is True
    assert snapshot["known_usage_sum"]["total_tokens"] == 12
    assert len(event_store.read("s1")) == 4


def test_factory_assembles_projection_without_startup_history_scan(tmp_path: Path) -> None:
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://provider.invalid/v1",
        llm_model="model-a",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
    )
    # Historical provider events may exist before the process starts. RG-3D does not
    # perform an unbounded startup scan; explicit reconcile remains a separate action.
    old_store = EventStore(settings.event_logs_dir)
    old_store.append(
        "historical-s",
        EVENT_PROVIDER_TRANSPORT_OPENED,
        {
            "call_id": "pcall:old",
            "attempt_id": "pattempt:old",
            "parent_attempt_id": None,
            "attempt_kind": "primary",
            "site_index": 0,
            "transport_retry_index": 0,
            "provider_id": "provider-a",
            "model_id": "model-a",
            "started_at": 10.0,
        },
    )

    engine = build_engine(settings)
    index = engine.provider_settlement_projection_index
    assert index is not None
    assert index.path == (
        settings.audit_dir / "resource_governor" / "provider_settlement_projection.sqlite3"
    )
    assert engine.provider_call_settlement_journal._projection_sink is index  # noqa: SLF001
    assert index.path.exists() is False

    before = index.aggregate(
        binding=_binding(), resource_key=_key(), window=AccountingWindow("w", 0.0, 100.0)
    )
    assert before.attempts_opened == 0
    report = index.reconcile_event_store(old_store, ["historical-s"])
    assert report.coverage.source_set is CoverageState.COMPLETE
    after = index.aggregate(
        binding=_binding(), resource_key=_key(), window=AccountingWindow("w", 0.0, 100.0)
    )
    assert after.attempts_opened == 1
    assert after.attempts_settled == 0
    assert after.attempts_complete is False


def test_generic_projection_does_not_invent_provider_request_quota_consumption(tmp_path: Path) -> None:
    _event_store, index, journal = _journal(tmp_path)
    _one_attempt(journal, session_id="s1")
    aggregate = index.aggregate(
        binding=_binding(), resource_key=_key(), window=AccountingWindow("w", 0.0, 100.0)
    )
    assert "requests" not in aggregate.known_usage_sum
    assert set(aggregate.known_usage_sum) == {
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
        "total_tokens",
    }
