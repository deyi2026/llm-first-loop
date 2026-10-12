"""RG-3D cross-session provider settlement projection for shadow admission facts.

The EventStore remains the durable source of truth. This module maintains a
rebuildable SQLite projection over RG-3C provider call/attempt events so later
resource adapters can ask mechanical questions across sessions without turning
per-call completeness into account/quota completeness.

No admission, routing, fallback, retry, pricing, quota, trust, or task-semantic
authority lives here.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from llm_loop.event_log.model import (
    EVENT_PROVIDER_CALL_OPENED,
    EVENT_PROVIDER_CALL_SETTLED,
    EVENT_PROVIDER_TRANSPORT_OPENED,
    EVENT_PROVIDER_TRANSPORT_SETTLED,
    Event,
)
from llm_loop.resources.contracts import (
    FactProvenance,
    ResourceKey,
    ResourceProductIdentity,
    ResourceRequirement,
)

_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
    "total_tokens",
)


class FactValidityKind(StrEnum):
    """How a mechanical fact's validity interval is known."""

    IMMUTABLE_EVENT = "immutable_event"
    OPEN_ENDED = "open_ended"
    BOUNDED = "bounded"
    UNKNOWN = "unknown"


class FactFreshness(StrEnum):
    CURRENT = "current"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    UNKNOWN = "unknown"


class CoverageState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ProjectionIngestOutcome(StrEnum):
    INSERTED = "inserted"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    IGNORED = "ignored"


class ShadowFactGap(StrEnum):
    SCOPE_UNBOUND = "scope_unbound"
    BINDING_NOT_CURRENT = "binding_not_current"
    SOURCE_SET_COVERAGE_PARTIAL = "source_set_coverage_partial"
    SOURCE_SET_COVERAGE_UNKNOWN = "source_set_coverage_unknown"
    PROVIDER_GLOBAL_COVERAGE_PARTIAL = "provider_global_coverage_partial"
    PROVIDER_GLOBAL_COVERAGE_UNKNOWN = "provider_global_coverage_unknown"
    PROVIDER_GLOBAL_COVERAGE_NOT_CURRENT = "provider_global_coverage_not_current"
    ATTEMPTS_INCOMPLETE = "attempts_incomplete"
    USAGE_INCOMPLETE = "usage_incomplete"


@dataclass(frozen=True)
class FactValidity:
    """Explicit validity only; absence never means infinite freshness."""

    kind: FactValidityKind
    valid_from: float | None = None
    valid_until: float | None = None
    version_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ("valid_from", "valid_until"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be >= 0")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_from >= self.valid_until
        ):
            raise ValueError("valid_from must be earlier than valid_until")
        if self.kind is FactValidityKind.BOUNDED:
            if self.valid_from is None or self.valid_until is None:
                raise ValueError("bounded validity requires valid_from and valid_until")
        elif self.kind is FactValidityKind.OPEN_ENDED:
            if self.valid_from is None:
                raise ValueError("open-ended validity requires valid_from")
            if self.valid_until is not None:
                raise ValueError("open-ended validity cannot carry valid_until")
        elif self.kind is FactValidityKind.IMMUTABLE_EVENT:
            if self.valid_until is not None:
                raise ValueError("immutable-event validity cannot expire")
        elif self.kind is FactValidityKind.UNKNOWN and (
            self.valid_from is not None or self.valid_until is not None
        ):
            raise ValueError("unknown validity cannot invent interval bounds")
        if self.version_ref is not None and not self.version_ref.strip():
            raise ValueError("version_ref must be non-empty when provided")

    def freshness_at(self, as_of: float) -> FactFreshness:
        if as_of < 0:
            raise ValueError("as_of must be >= 0")
        if self.kind is FactValidityKind.UNKNOWN:
            return FactFreshness.UNKNOWN
        if self.valid_from is not None and as_of < self.valid_from:
            return FactFreshness.NOT_YET_VALID
        if self.kind is FactValidityKind.BOUNDED:
            assert self.valid_until is not None
            return FactFreshness.CURRENT if as_of < self.valid_until else FactFreshness.EXPIRED
        return FactFreshness.CURRENT


@dataclass(frozen=True)
class AccountingWindow:
    """Exact half-open projection window [start_at, end_at)."""

    window_ref: str
    start_at: float
    end_at: float

    def __post_init__(self) -> None:
        if not self.window_ref.strip():
            raise ValueError("window_ref must be non-empty")
        if self.start_at < 0 or self.end_at < 0:
            raise ValueError("window bounds must be >= 0")
        if self.start_at >= self.end_at:
            raise ValueError("window start_at must be earlier than end_at")


@dataclass(frozen=True)
class ProviderResourceBinding:
    """Explicit provider/model -> resource-scope mapping; never URL/name inferred."""

    provider_id: str
    model_id: str
    resource_keys: tuple[ResourceKey, ...]
    provenance: FactProvenance
    validity: FactValidity
    product: ResourceProductIdentity | None = None

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.model_id.strip():
            raise ValueError("provider_id and model_id must be non-empty")
        if not self.resource_keys:
            raise ValueError("resource_keys must be non-empty")
        if len(set(self.resource_keys)) != len(self.resource_keys):
            raise ValueError("resource_keys contains duplicates")
        if any(key.provider_id != self.provider_id for key in self.resource_keys):
            raise ValueError("resource key provider_id must match binding provider_id")
        if self.product is not None and self.product.provider_id != self.provider_id:
            raise ValueError("product provider_id must match binding provider_id")

    def includes(self, key: ResourceKey) -> bool:
        return key in self.resource_keys


@dataclass(frozen=True)
class SourceSessionWatermark:
    """Exact EventStore scan high-watermark for one explicit source session."""

    session_id: str
    last_seq: int
    event_count: int
    skipped_lines: int

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must be non-empty")
        for name in ("last_seq", "event_count", "skipped_lines"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")


def _source_scope_reference(watermarks: tuple[SourceSessionWatermark, ...]) -> str:
    session_material = "\n".join(sorted(item.session_id for item in watermarks))
    digest = hashlib.sha256(session_material.encode()).hexdigest()[:24]
    return f"explicit-sessions:{digest}"


def _source_watermark_reference(watermarks: tuple[SourceSessionWatermark, ...]) -> str:
    watermark_material = "\n".join(
        f"{item.session_id}:{item.last_seq}:{item.event_count}:{item.skipped_lines}"
        for item in sorted(watermarks, key=lambda item: item.session_id)
    )
    digest = hashlib.sha256(watermark_material.encode()).hexdigest()[:24]
    return f"eventstore-watermark:{digest}"


@dataclass(frozen=True)
class ProjectionCoverage:
    """Coverage of an explicit LFL source set vs the provider/account as a whole."""

    source_set: CoverageState
    provider_global: CoverageState = CoverageState.UNKNOWN
    source_scope_ref: str = ""
    source_watermark_ref: str = ""
    source_watermarks: tuple[SourceSessionWatermark, ...] = ()
    source_session_count: int = 0
    source_event_count: int = 0
    skipped_event_lines: int = 0
    provider_global_provenance: FactProvenance | None = None
    provider_global_validity: FactValidity | None = None

    def __post_init__(self) -> None:
        for name in ("source_session_count", "source_event_count", "skipped_event_lines"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.source_set is not CoverageState.UNKNOWN:
            if not self.source_scope_ref.strip() or not self.source_watermark_ref.strip():
                raise ValueError(
                    "known source_set coverage requires source_scope_ref and source_watermark_ref"
                )
            if len(self.source_watermarks) != self.source_session_count:
                raise ValueError("source watermark count must match source_session_count")
            if self.source_scope_ref != _source_scope_reference(self.source_watermarks):
                raise ValueError("source_scope_ref does not match source_watermarks")
            if self.source_watermark_ref != _source_watermark_reference(self.source_watermarks):
                raise ValueError("source_watermark_ref does not match source_watermarks")
        elif self.source_watermarks or self.source_watermark_ref:
            raise ValueError("unknown source_set coverage cannot carry a completeness watermark")
        if len({item.session_id for item in self.source_watermarks}) != len(self.source_watermarks):
            raise ValueError("source_watermarks contains duplicate session_id")
        if sum(item.event_count for item in self.source_watermarks) != self.source_event_count:
            raise ValueError("source watermark event counts must match source_event_count")
        if sum(item.skipped_lines for item in self.source_watermarks) != self.skipped_event_lines:
            raise ValueError("source watermark skipped counts must match skipped_event_lines")
        if self.provider_global is CoverageState.UNKNOWN:
            if self.provider_global_provenance is not None or self.provider_global_validity is not None:
                raise ValueError("unknown provider_global coverage cannot carry authoritative proof")
        elif (
            self.provider_global_provenance is None
            or self.provider_global_validity is None
            or self.provider_global_validity.kind is FactValidityKind.UNKNOWN
        ):
            raise ValueError(
                "known provider_global coverage requires explicit provenance and validity"
            )


@dataclass(frozen=True)
class ReconcileReport:
    coverage: ProjectionCoverage
    inserted: int
    duplicates: int
    conflicts: int
    ignored: int


@dataclass(frozen=True)
class SettlementUsageAggregate:
    """Known LFL settlement facts for one explicit scope/window."""

    resource_key: ResourceKey
    window: AccountingWindow
    provider_id: str
    model_id: str
    calls: int
    attempts_opened: int
    attempts_settled: int
    attempts_complete: bool
    known_usage_sum: dict[str, int]
    usage_complete: dict[str, bool]
    provider_units_known: str | None
    provider_units_complete: bool
    provider_unit: str | None
    execution_class_counts: dict[str, int]
    purpose_counts: dict[str, int]


@dataclass(frozen=True)
class ShadowAdmissionFacts:
    """Observation-only input for later admission simulation; never a decision."""

    requirement: ResourceRequirement
    binding_freshness: FactFreshness
    coverage: ProjectionCoverage
    aggregate: SettlementUsageAggregate | None
    gaps: tuple[ShadowFactGap, ...]


class ProviderSettlementProjectionIndex:
    """Rebuildable global SQLite projection of RG-3C provider settlement events."""

    _SCHEMA_VERSION = 1
    _RELEVANT_EVENTS = frozenset(
        {
            EVENT_PROVIDER_CALL_OPENED,
            EVENT_PROVIDER_CALL_SETTLED,
            EVENT_PROVIDER_TRANSPORT_OPENED,
            EVENT_PROVIDER_TRANSPORT_SETTLED,
        }
    )

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projection_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_calls (
                call_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                owner_ref TEXT,
                execution_class TEXT,
                service_priority INTEGER,
                purpose TEXT,
                created_at REAL,
                open_event_id TEXT UNIQUE,
                outcome TEXT,
                settled_at REAL,
                settle_event_id TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS provider_attempts (
                attempt_id TEXT PRIMARY KEY,
                call_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                parent_attempt_id TEXT,
                attempt_kind TEXT,
                site_index INTEGER,
                transport_retry_index INTEGER,
                provider_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                started_at REAL,
                open_event_id TEXT UNIQUE,
                outcome TEXT,
                settled_at REAL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cached_input_tokens INTEGER,
                reasoning_tokens INTEGER,
                total_tokens INTEGER,
                provider_units TEXT,
                provider_unit TEXT,
                usage_observations INTEGER,
                status_code INTEGER,
                provider_code TEXT,
                retry_after_seconds REAL,
                rate_limits_json TEXT,
                error_type TEXT,
                settle_event_id TEXT UNIQUE
            );
            CREATE INDEX IF NOT EXISTS provider_attempt_target_time
            ON provider_attempts(provider_id, model_id, started_at);
            CREATE INDEX IF NOT EXISTS provider_attempt_call
            ON provider_attempts(call_id);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO projection_meta(key, value) VALUES('schema_version', ?)",
            (str(self._SCHEMA_VERSION),),
        )
        return conn

    @staticmethod
    def _norm_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None

    @staticmethod
    def _norm_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _norm_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _usage(payload: dict[str, Any]) -> dict[str, Any]:
        usage = payload.get("usage")
        return dict(usage) if isinstance(usage, dict) else {}

    @staticmethod
    def _identity_conflicts(row: sqlite3.Row, expected: dict[str, Any]) -> bool:
        return any(row[key] is not None and row[key] != value for key, value in expected.items())

    def _ingest_call_open(self, conn: sqlite3.Connection, event: Event) -> ProjectionIngestOutcome:
        payload = event.payload
        call_id = self._norm_text(payload.get("call_id"))
        if call_id is None:
            return ProjectionIngestOutcome.IGNORED
        expected = {
            "session_id": event.session_id,
            "owner_ref": self._norm_text(payload.get("owner_ref")),
            "execution_class": self._norm_text(payload.get("execution_class")),
            "service_priority": self._norm_int(payload.get("service_priority")),
            "purpose": self._norm_text(payload.get("purpose")),
            "created_at": self._norm_float(payload.get("created_at")),
        }
        row = conn.execute("SELECT * FROM provider_calls WHERE call_id=?", (call_id,)).fetchone()
        if row is not None:
            if self._identity_conflicts(row, expected):
                return ProjectionIngestOutcome.CONFLICT
            if row["open_event_id"] == event.event_id:
                return ProjectionIngestOutcome.DUPLICATE
            if row["open_event_id"] is not None:
                return ProjectionIngestOutcome.CONFLICT
            conn.execute(
                """UPDATE provider_calls SET owner_ref=?, execution_class=?, service_priority=?,
                   purpose=?, created_at=?, open_event_id=? WHERE call_id=?""",
                (
                    expected["owner_ref"],
                    expected["execution_class"],
                    expected["service_priority"],
                    expected["purpose"],
                    expected["created_at"],
                    event.event_id,
                    call_id,
                ),
            )
            return ProjectionIngestOutcome.INSERTED
        conn.execute(
            """INSERT INTO provider_calls(
                call_id, session_id, owner_ref, execution_class, service_priority,
                purpose, created_at, open_event_id
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                call_id,
                event.session_id,
                expected["owner_ref"],
                expected["execution_class"],
                expected["service_priority"],
                expected["purpose"],
                expected["created_at"],
                event.event_id,
            ),
        )
        return ProjectionIngestOutcome.INSERTED

    def _ingest_call_settled(
        self, conn: sqlite3.Connection, event: Event
    ) -> ProjectionIngestOutcome:
        payload = event.payload
        call_id = self._norm_text(payload.get("call_id"))
        if call_id is None:
            return ProjectionIngestOutcome.IGNORED
        outcome = self._norm_text(payload.get("outcome"))
        settled_at = self._norm_float(payload.get("settled_at"))
        row = conn.execute("SELECT * FROM provider_calls WHERE call_id=?", (call_id,)).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO provider_calls(
                    call_id, session_id, outcome, settled_at, settle_event_id
                ) VALUES(?,?,?,?,?)""",
                (call_id, event.session_id, outcome, settled_at, event.event_id),
            )
            return ProjectionIngestOutcome.INSERTED
        if row["session_id"] != event.session_id:
            return ProjectionIngestOutcome.CONFLICT
        if row["settle_event_id"] == event.event_id:
            return ProjectionIngestOutcome.DUPLICATE
        if row["settle_event_id"] is not None:
            return (
                ProjectionIngestOutcome.DUPLICATE
                if row["outcome"] == outcome and row["settled_at"] == settled_at
                else ProjectionIngestOutcome.CONFLICT
            )
        conn.execute(
            "UPDATE provider_calls SET outcome=?, settled_at=?, settle_event_id=? WHERE call_id=?",
            (outcome, settled_at, event.event_id, call_id),
        )
        return ProjectionIngestOutcome.INSERTED

    def _attempt_identity(self, event: Event) -> dict[str, Any] | None:
        payload = event.payload
        attempt_id = self._norm_text(payload.get("attempt_id"))
        call_id = self._norm_text(payload.get("call_id"))
        provider_id = self._norm_text(payload.get("provider_id"))
        model_id = self._norm_text(payload.get("model_id"))
        if None in (attempt_id, call_id, provider_id, model_id):
            return None
        return {
            "attempt_id": attempt_id,
            "call_id": call_id,
            "session_id": event.session_id,
            "parent_attempt_id": self._norm_text(payload.get("parent_attempt_id")),
            "attempt_kind": self._norm_text(payload.get("attempt_kind")),
            "site_index": self._norm_int(payload.get("site_index")),
            "transport_retry_index": self._norm_int(payload.get("transport_retry_index")),
            "provider_id": provider_id,
            "model_id": model_id,
            "started_at": self._norm_float(payload.get("started_at")),
        }

    def _ingest_attempt_open(
        self, conn: sqlite3.Connection, event: Event
    ) -> ProjectionIngestOutcome:
        identity = self._attempt_identity(event)
        if identity is None:
            return ProjectionIngestOutcome.IGNORED
        attempt_id = str(identity["attempt_id"])
        row = conn.execute(
            "SELECT * FROM provider_attempts WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
        if row is not None:
            if self._identity_conflicts(row, identity):
                return ProjectionIngestOutcome.CONFLICT
            if row["open_event_id"] == event.event_id:
                return ProjectionIngestOutcome.DUPLICATE
            if row["open_event_id"] is not None:
                return ProjectionIngestOutcome.CONFLICT
            conn.execute(
                """UPDATE provider_attempts SET parent_attempt_id=?, attempt_kind=?, site_index=?,
                   transport_retry_index=?, started_at=?, open_event_id=? WHERE attempt_id=?""",
                (
                    identity["parent_attempt_id"],
                    identity["attempt_kind"],
                    identity["site_index"],
                    identity["transport_retry_index"],
                    identity["started_at"],
                    event.event_id,
                    attempt_id,
                ),
            )
            return ProjectionIngestOutcome.INSERTED
        conn.execute(
            """INSERT INTO provider_attempts(
                attempt_id, call_id, session_id, parent_attempt_id, attempt_kind, site_index,
                transport_retry_index, provider_id, model_id, started_at, open_event_id
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                identity["attempt_id"],
                identity["call_id"],
                identity["session_id"],
                identity["parent_attempt_id"],
                identity["attempt_kind"],
                identity["site_index"],
                identity["transport_retry_index"],
                identity["provider_id"],
                identity["model_id"],
                identity["started_at"],
                event.event_id,
            ),
        )
        return ProjectionIngestOutcome.INSERTED

    def _ingest_attempt_settled(
        self, conn: sqlite3.Connection, event: Event
    ) -> ProjectionIngestOutcome:
        identity = self._attempt_identity(event)
        if identity is None:
            return ProjectionIngestOutcome.IGNORED
        payload = event.payload
        usage = self._usage(payload)
        terminal = {
            "outcome": self._norm_text(payload.get("outcome")),
            "settled_at": self._norm_float(payload.get("settled_at")),
            **{field: self._norm_int(usage.get(field)) for field in _USAGE_FIELDS},
            "provider_units": self._norm_text(usage.get("provider_units")),
            "provider_unit": self._norm_text(usage.get("provider_unit")),
            "usage_observations": self._norm_int(payload.get("usage_observations")),
            "status_code": self._norm_int(payload.get("status_code")),
            "provider_code": self._norm_text(payload.get("provider_code")),
            "retry_after_seconds": self._norm_float(payload.get("retry_after_seconds")),
            "rate_limits_json": json.dumps(
                payload.get("rate_limits") if isinstance(payload.get("rate_limits"), list) else [],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "error_type": self._norm_text(payload.get("error_type")),
        }
        attempt_id = str(identity["attempt_id"])
        row = conn.execute(
            "SELECT * FROM provider_attempts WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
        if row is not None and self._identity_conflicts(row, identity):
            return ProjectionIngestOutcome.CONFLICT
        if row is not None and row["settle_event_id"] is not None:
            comparable = {**identity, **terminal}
            return (
                ProjectionIngestOutcome.DUPLICATE
                if not self._identity_conflicts(row, comparable)
                else ProjectionIngestOutcome.CONFLICT
            )
        if row is None:
            columns = [*identity, *terminal, "settle_event_id"]
            values = [identity[key] for key in identity] + [terminal[key] for key in terminal]
            values.append(event.event_id)
            placeholders = ",".join("?" for _ in columns)
            conn.execute(
                f"INSERT INTO provider_attempts({','.join(columns)}) VALUES({placeholders})",  # noqa: S608 -- static column names
                values,
            )
            return ProjectionIngestOutcome.INSERTED
        assignments = ",".join(f"{key}=?" for key in terminal)
        conn.execute(
            f"UPDATE provider_attempts SET {assignments}, settle_event_id=? WHERE attempt_id=?",  # noqa: S608 -- static field list
            [terminal[key] for key in terminal] + [event.event_id, attempt_id],
        )
        return ProjectionIngestOutcome.INSERTED

    def _ingest_locked(self, conn: sqlite3.Connection, event: Event) -> ProjectionIngestOutcome:
        if event.type == EVENT_PROVIDER_CALL_OPENED:
            return self._ingest_call_open(conn, event)
        if event.type == EVENT_PROVIDER_CALL_SETTLED:
            return self._ingest_call_settled(conn, event)
        if event.type == EVENT_PROVIDER_TRANSPORT_OPENED:
            return self._ingest_attempt_open(conn, event)
        if event.type == EVENT_PROVIDER_TRANSPORT_SETTLED:
            return self._ingest_attempt_settled(conn, event)
        return ProjectionIngestOutcome.IGNORED

    def ingest_event(self, event: Event) -> ProjectionIngestOutcome:
        """Idempotently project one EventStore event; conflicts never overwrite truth."""

        if event.type not in self._RELEVANT_EVENTS:
            return ProjectionIngestOutcome.IGNORED
        with self._lock, self._connect() as conn:
            outcome = self._ingest_locked(conn, event)
            conn.commit()
            return outcome

    def reconcile_events(self, events: Iterable[Event]) -> dict[ProjectionIngestOutcome, int]:
        """Idempotently backfill/reconcile any explicit EventStore event iterable."""

        counts = {outcome: 0 for outcome in ProjectionIngestOutcome}
        with self._lock, self._connect() as conn:
            for event in events:
                outcome = self._ingest_locked(conn, event)
                counts[outcome] += 1
            conn.commit()
        return counts

    def reconcile_event_store(
        self,
        event_store: Any,
        session_ids: Iterable[str],
    ) -> ReconcileReport:
        """Reconcile an explicit session set; never calls that provider-global coverage."""

        unique = tuple(sorted({str(sid) for sid in session_ids if str(sid)}))
        counts = {outcome: 0 for outcome in ProjectionIngestOutcome}
        event_count = 0
        skipped = 0
        watermarks: list[SourceSessionWatermark] = []
        with self._lock, self._connect() as conn:
            for sid in unique:
                events = event_store.read(sid)
                sid_skipped = int(getattr(event_store, "last_read_skipped", 0) or 0)
                skipped += sid_skipped
                event_count += len(events)
                watermarks.append(
                    SourceSessionWatermark(
                        session_id=sid,
                        last_seq=max((int(event.seq) for event in events), default=0),
                        event_count=len(events),
                        skipped_lines=sid_skipped,
                    )
                )
                for event in events:
                    outcome = self._ingest_locked(conn, event)
                    counts[outcome] += 1
            conn.commit()
        source_watermarks = tuple(watermarks)
        source_state = CoverageState.COMPLETE if skipped == 0 else CoverageState.PARTIAL
        return ReconcileReport(
            coverage=ProjectionCoverage(
                source_set=source_state,
                provider_global=CoverageState.UNKNOWN,
                source_scope_ref=_source_scope_reference(source_watermarks),
                source_watermark_ref=_source_watermark_reference(source_watermarks),
                source_watermarks=source_watermarks,
                source_session_count=len(unique),
                source_event_count=event_count,
                skipped_event_lines=skipped,
            ),
            inserted=counts[ProjectionIngestOutcome.INSERTED],
            duplicates=counts[ProjectionIngestOutcome.DUPLICATE],
            conflicts=counts[ProjectionIngestOutcome.CONFLICT],
            ignored=counts[ProjectionIngestOutcome.IGNORED],
        )

    def aggregate(
        self,
        *,
        binding: ProviderResourceBinding,
        resource_key: ResourceKey,
        window: AccountingWindow,
    ) -> SettlementUsageAggregate:
        """Aggregate known settled usage for one exact explicit scope/window."""

        if not binding.includes(resource_key):
            raise ValueError("resource_key is not part of the explicit binding")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT a.*, c.execution_class, c.purpose
                   FROM provider_attempts a
                   LEFT JOIN provider_calls c ON c.call_id = a.call_id
                   WHERE a.provider_id=? AND a.model_id=?
                     AND a.started_at>=? AND a.started_at<?
                   ORDER BY a.started_at, a.attempt_id""",
                (binding.provider_id, binding.model_id, window.start_at, window.end_at),
            ).fetchall()
        opened = [row for row in rows if row["open_event_id"] is not None]
        settled = [row for row in rows if row["settle_event_id"] is not None]
        attempts_opened = len(opened)
        attempts_complete = (
            bool(rows) and len(opened) == len(rows) and len(settled) == len(rows)
        )
        known_usage_sum: dict[str, int] = {}
        usage_complete: dict[str, bool] = {}
        for field in _USAGE_FIELDS:
            values = [row[field] for row in settled]
            known_usage_sum[field] = sum(int(value) for value in values if value is not None)
            usage_complete[field] = attempts_complete and all(value is not None for value in values)

        provider_unit_values = {str(row["provider_unit"]) for row in settled if row["provider_unit"]}
        provider_units = [row["provider_units"] for row in settled]
        provider_units_complete = (
            attempts_complete
            and bool(settled)
            and len(provider_unit_values) == 1
            and all(value is not None for value in provider_units)
        )
        provider_units_known: str | None = None
        if provider_unit_values and provider_units:
            try:
                from decimal import Decimal

                total = sum(
                    (Decimal(str(value)) for value in provider_units if value is not None),
                    Decimal("0"),
                )
                provider_units_known = str(total)
            except Exception:  # noqa: BLE001 -- malformed derived row stays unknown
                provider_units_complete = False
        execution_counts: dict[str, int] = {}
        purpose_counts: dict[str, int] = {}
        call_ids = {str(row["call_id"]) for row in rows}
        for row in rows:
            execution = self._norm_text(row["execution_class"])
            purpose = self._norm_text(row["purpose"])
            if execution is not None:
                execution_counts[execution] = execution_counts.get(execution, 0) + 1
            if purpose is not None:
                purpose_counts[purpose] = purpose_counts.get(purpose, 0) + 1
        return SettlementUsageAggregate(
            resource_key=resource_key,
            window=window,
            provider_id=binding.provider_id,
            model_id=binding.model_id,
            calls=len(call_ids),
            attempts_opened=attempts_opened,
            attempts_settled=len(settled),
            attempts_complete=attempts_complete,
            known_usage_sum=known_usage_sum,
            usage_complete=usage_complete,
            provider_units_known=provider_units_known,
            provider_units_complete=provider_units_complete,
            provider_unit=next(iter(provider_unit_values)) if len(provider_unit_values) == 1 else None,
            execution_class_counts=execution_counts,
            purpose_counts=purpose_counts,
        )

    def project_shadow_admission_facts(
        self,
        *,
        requirement: ResourceRequirement,
        binding: ProviderResourceBinding | None,
        window: AccountingWindow,
        coverage: ProjectionCoverage,
        as_of: float,
    ) -> ShadowAdmissionFacts:
        """Build observation-only admission inputs; no admit/defer/reject outcome exists."""

        if binding is None or not binding.includes(requirement.key):
            return ShadowAdmissionFacts(
                requirement=requirement,
                binding_freshness=FactFreshness.UNKNOWN,
                coverage=coverage,
                aggregate=None,
                gaps=(ShadowFactGap.SCOPE_UNBOUND,),
            )
        freshness = binding.validity.freshness_at(as_of)
        gaps: list[ShadowFactGap] = []
        if freshness is not FactFreshness.CURRENT:
            gaps.append(ShadowFactGap.BINDING_NOT_CURRENT)
        if coverage.source_set is CoverageState.PARTIAL:
            gaps.append(ShadowFactGap.SOURCE_SET_COVERAGE_PARTIAL)
        elif coverage.source_set is CoverageState.UNKNOWN:
            gaps.append(ShadowFactGap.SOURCE_SET_COVERAGE_UNKNOWN)
        if coverage.provider_global is CoverageState.PARTIAL:
            gaps.append(ShadowFactGap.PROVIDER_GLOBAL_COVERAGE_PARTIAL)
        elif coverage.provider_global is CoverageState.UNKNOWN:
            gaps.append(ShadowFactGap.PROVIDER_GLOBAL_COVERAGE_UNKNOWN)
        if (
            coverage.provider_global is not CoverageState.UNKNOWN
            and coverage.provider_global_validity is not None
            and coverage.provider_global_validity.freshness_at(as_of) is not FactFreshness.CURRENT
        ):
            gaps.append(ShadowFactGap.PROVIDER_GLOBAL_COVERAGE_NOT_CURRENT)
        aggregate = self.aggregate(binding=binding, resource_key=requirement.key, window=window)
        if aggregate.attempts_opened and not aggregate.attempts_complete:
            gaps.append(ShadowFactGap.ATTEMPTS_INCOMPLETE)
        if aggregate.attempts_opened and not all(aggregate.usage_complete.values()):
            gaps.append(ShadowFactGap.USAGE_INCOMPLETE)
        return ShadowAdmissionFacts(
            requirement=requirement,
            binding_freshness=freshness,
            coverage=coverage,
            aggregate=aggregate,
            gaps=tuple(dict.fromkeys(gaps)),
        )
