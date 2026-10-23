"""T-CONTRACT-8：本地媒体计量记录与任务预算适配层单元测试。

覆盖 RTM：BUD-01/02/03/04/05/07、CMP-01、LIF-05/07、STP-06。

硬约束：
- 首版**不改 `BudgetDimension` 合同**：旧额度/旧记录反序列化不因媒体计量而失败；
- 缺用量标 `incomplete`，**不标零**；
- 媒体用量分计（音频输入/输出、图像）按本地算力/许可口径。
"""

from __future__ import annotations

import pytest

from llm_loop.realtime.media_usage import (
    AdmissionDecision,
    MediaModality,
    MediaUsageBudgetAdapter,
    MediaUsageLedger,
    MediaUsageRecord,
    ResidualConcurrencyLimiter,
    UsageStatus,
    decide_budget_admission,
)
from llm_loop.resources.task_budget_contracts import BudgetDimension, TaskBudgetLimits


def _record(**over: object) -> MediaUsageRecord:
    base = {
        "media_session_id": "sess-1",
        "modality": MediaModality.AUDIO_INPUT_MS,
        "quantity": 1000,
    }
    base.update(over)
    return MediaUsageRecord(**base)  # type: ignore[arg-type]


class TestMediaUsageRecord:
    def test_requires_bounded_identifier(self):
        with pytest.raises(ValueError):
            _record(media_session_id="")

    def test_rejects_non_enum_modality(self):
        with pytest.raises(TypeError):
            _record(modality="audio_input_ms")

    def test_rejects_negative_quantity_and_bool(self):
        with pytest.raises(ValueError):
            _record(quantity=-1)
        with pytest.raises(ValueError):
            _record(quantity=True)

    def test_rejects_negative_local_compute(self):
        with pytest.raises(ValueError):
            _record(local_compute_ms=-5)

    def test_rejects_non_enum_status(self):
        with pytest.raises(TypeError):
            _record(status="settled")

    def test_to_dict_roundtrip_shape(self):
        rec = _record(
            status=UsageStatus.SETTLED,
            local_compute_ms=7140,
            license_id="apache-2.0",
            event_id="evt-1",
        )
        d = rec.to_dict()
        assert d["modality"] == "audio_input_ms"
        assert d["status"] == "settled"
        assert d["local_compute_ms"] == 7140


class TestMediaUsageLedger:
    def test_empty_session_is_incomplete_not_zero(self):
        ledger = MediaUsageLedger()
        assert ledger.status("missing") is UsageStatus.INCOMPLETE
        assert ledger.totals("missing") == {}

    def test_totals_by_modality(self):
        ledger = MediaUsageLedger()
        ledger.record(_record(quantity=1000))
        ledger.record(_record(quantity=500))
        ledger.record(_record(modality=MediaModality.TTS_CHARS, quantity=42))
        assert ledger.totals("sess-1") == {"audio_input_ms": 1500, "tts_chars": 42}

    def test_status_precedence_incomplete_over_estimated_over_settled(self):
        ledger = MediaUsageLedger()
        ledger.record(_record(status=UsageStatus.SETTLED))
        assert ledger.status("sess-1") is UsageStatus.SETTLED
        ledger.record(_record(status=UsageStatus.ESTIMATED))
        assert ledger.status("sess-1") is UsageStatus.ESTIMATED
        ledger.record(_record(status=UsageStatus.INCOMPLETE))
        assert ledger.status("sess-1") is UsageStatus.INCOMPLETE

    def test_settle_only_converts_estimated_and_keeps_incomplete(self):
        ledger = MediaUsageLedger()
        ledger.record(_record(status=UsageStatus.ESTIMATED))
        ledger.record(_record(status=UsageStatus.INCOMPLETE))
        assert ledger.settle("sess-1") == 1
        statuses = [r.status for r in ledger.records]
        assert UsageStatus.SETTLED in statuses
        assert UsageStatus.INCOMPLETE in statuses

    def test_settle_ignores_other_sessions(self):
        ledger = MediaUsageLedger()
        ledger.record(_record(media_session_id="sess-2", status=UsageStatus.ESTIMATED))
        assert ledger.settle("sess-1") == 0
        assert ledger.records[0].status is UsageStatus.ESTIMATED

    def test_local_compute_ms_sums_present_values_only(self):
        ledger = MediaUsageLedger()
        ledger.record(_record(local_compute_ms=1000))
        ledger.record(_record(local_compute_ms=None))
        ledger.record(_record(local_compute_ms=2000))
        assert ledger.local_compute_ms("sess-1") == 3000

    def test_record_rejects_foreign_object(self):
        with pytest.raises(TypeError):
            MediaUsageLedger().record(object())  # type: ignore[arg-type]

    def test_summary_reports_incomplete_for_empty(self):
        summary = MediaUsageLedger().summary("nope")
        assert summary["status"] == "incomplete"
        assert summary["totals"] == {}


class TestMediaUsageBudgetAdapter:
    def test_payload_bytes_for_16k_pcm16_audio(self):
        adapter = MediaUsageBudgetAdapter()
        records = [_record(quantity=1000)]
        # 16000 Hz * 2 B / 1000 ms = 32 B per ms
        assert adapter.payload_bytes(records) == 32000

    def test_budget_hint_uses_existing_dimension_only(self):
        adapter = MediaUsageBudgetAdapter()
        hint = adapter.budget_hint([_record()])
        assert set(hint) == {"payload_bytes"}

    def test_does_not_change_budget_dimension_contract(self):
        # 旧额度字段集合不变，严格反序列化继续工作
        fields = {d.value for d in BudgetDimension}
        assert fields == {
            "logical_calls",
            "physical_attempts",
            "rounds",
            "tool_invocations",
            "input_tokens",
            "output_tokens",
            "payload_bytes",
        }
        limits = TaskBudgetLimits.from_dict({f: None for f in fields})
        assert limits.to_dict() == {f: None for f in fields}

    def test_strict_validation_still_rejects_unknown_fields(self):
        fields = {d.value for d in BudgetDimension}
        with pytest.raises(ValueError):
            TaskBudgetLimits.from_dict({**{f: None for f in fields}, "media_ms": 1})

    def test_realtime_and_task_budget_stay_independent(self):
        adapter = MediaUsageBudgetAdapter()
        before = TaskBudgetLimits(input_tokens=10)
        adapter.budget_hint([_record(quantity=1000000)])
        assert before.input_tokens == 10  # 适配层不改写任务预算策略


class TestAdmissionDecision:
    def test_admit_within_limit(self):
        assert decide_budget_admission(limit=10, used=5, requested=5) is AdmissionDecision.ADMIT

    def test_stop_when_over_limit(self):
        assert (
            decide_budget_admission(limit=10, used=6, requested=5)
            is AdmissionDecision.STOP_NEW_REQUESTS
        )

    def test_unqualified_limit_admits(self):
        assert decide_budget_admission(limit=None, used=10**9, requested=10**9) is AdmissionDecision.ADMIT

    def test_rejects_bool_and_negative(self):
        with pytest.raises(TypeError):
            decide_budget_admission(limit=1, used=True, requested=0)
        with pytest.raises(ValueError):
            decide_budget_admission(limit=1, used=-1, requested=0)
        with pytest.raises(ValueError):
            decide_budget_admission(limit=-1, used=0, requested=0)


class TestResidualConcurrencyLimiter:
    def test_limit_must_be_positive(self):
        with pytest.raises(ValueError):
            ResidualConcurrencyLimiter(0)
        with pytest.raises(ValueError):
            ResidualConcurrencyLimiter(True)

    def test_saturates_at_limit(self):
        limiter = ResidualConcurrencyLimiter(2)
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is False
        assert limiter.inflight == 2
        assert limiter.saturated is True

    def test_release_frees_slot(self):
        limiter = ResidualConcurrencyLimiter(1)
        assert limiter.try_acquire() is True
        assert limiter.saturated is True
        limiter.release()
        assert limiter.saturated is False
        assert limiter.try_acquire() is True

    def test_release_without_acquire_raises(self):
        with pytest.raises(ValueError):
            ResidualConcurrencyLimiter(1).release()
