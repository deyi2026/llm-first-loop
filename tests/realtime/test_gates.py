"""门禁测试：T25 / T26 / T27（`T-GATE-6/7/8`）。

覆盖 RTM：CAP-09/11/12/13/14、SEC-08、AUD-01、TOL-16、PLY-07、INP-01/02/09、AUD-03、
EVD-06、OBS-05/09、PRF-01/02/03/04、CAP-07、CAP-03。
"""

from __future__ import annotations

import pytest

from llm_loop.realtime.capability_profile_check import (
    CapabilityProfileIncompleteError,
    ObservationItem,
    missing_profile_fields,
    transcription_session_boundaries,
    validate_capability_profile,
)
from llm_loop.realtime.dual_asr_corrector import DualASRCorrector
from llm_loop.realtime.evidence_grading import (
    EvidenceLevel,
    PerformanceReport,
    PerformanceSample,
    probe_ab_status,
    service_level_is_not_acceptance,
)
from llm_loop.realtime.provider_adapter import LocalStackProfile, RecoveryMode
from llm_loop.realtime.turn_aggregator import TurnAggregator

FULL = {
    "realtime_ws_url": "ws://127.0.0.1:8000/v1/realtime",
    "transcription_http_url": "http://127.0.0.1:8000/v1/audio/transcriptions",
    "tts_http_url": "http://127.0.0.1:8000/v1/audio/speech",
    "local_stack_version": "mlx-audio-0.x",
    "streaming_asr_model": "nemotron-3.5-asr-streaming-0.6b",
    "final_asr_model": "Qwen3-ASR-0.6B",
    "tts_model": "Qwen3-TTS-0.6B",
    "vad_model": "silero-vad",
    "licenses": (("Qwen3-ASR-0.6B", "apache-2.0"),),
}


class TestT25CapabilityAndBoundaries:
    def test_complete_profile_passes(self):
        validate_capability_profile(LocalStackProfile(**FULL))  # type: ignore[arg-type]

    def test_missing_fields_reported_explicitly(self):
        profile = LocalStackProfile(realtime_ws_url=FULL["realtime_ws_url"], transcription_http_url=FULL["transcription_http_url"])  # type: ignore[arg-type]
        missing = missing_profile_fields(profile)
        assert "local_stack_version" in missing
        assert "licenses" in missing
        with pytest.raises(CapabilityProfileIncompleteError):
            validate_capability_profile(profile)

    def test_missing_license_is_explicit(self):
        without_license = {k: v for k, v in FULL.items() if k != "licenses"}
        profile = LocalStackProfile(**without_license)  # type: ignore[arg-type]
        with pytest.raises(CapabilityProfileIncompleteError):
            validate_capability_profile(profile)

    def test_non_local_recovery_rejected(self):
        profile = LocalStackProfile(**{**FULL, "recovery_mode": RecoveryMode.REMOTE_TOKEN})  # type: ignore[arg-type]
        with pytest.raises(CapabilityProfileIncompleteError):
            validate_capability_profile(profile)

    def test_transcription_session_has_no_response_create_or_tool_loopback(self):
        boundaries = transcription_session_boundaries()
        assert boundaries["transcribes_only"] is True
        assert boundaries["has_tool_loopback"] is False
        assert boundaries["produces_audio"] is False
        assert boundaries["requires_response_create"] is False

    def test_observation_item_must_not_ship_first_release(self):
        with pytest.raises(ValueError):
            ObservationItem(name="voicechat-full-duplex", first_release=True)

    def test_observation_item_is_auditable(self):
        item = ObservationItem(
            name="voicechat-full-duplex",
            falsification_evidence=("中英文返回同一段英文寒暄", "延迟 4-6x 实时"),
            root_cause_candidates=("mlx 移植接线", "系统提示/语言设置"),
            exit_conditions=("出现可复现证据证明中文实时对话达标",),
        )
        assert item.is_released() is False
        assert item.is_auditable() is True


class TestT26FinalCorrection:
    def test_delta_never_enters_committed(self):
        agg = TurnAggregator(DualASRCorrector(lambda segment: "语音链路"))
        agg.start("turn-1")
        agg.on_delta("语音路")  # 流式错字，仅显示
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        committed = agg.commit()
        assert committed.text == "语音链路"
        assert "语音路" not in committed.text
        assert agg.display_text == "语音路"  # 仅显示保留

    def test_typed_error_samples_do_not_enter_committed(self):
        for wrong, correct in (("语音路", "语音链路"), ("克龙", "克隆")):
            agg = TurnAggregator(DualASRCorrector(lambda segment, c=correct: c))
            agg.start("turn-x")
            agg.on_delta(wrong)
            agg.on_speech_end()
            agg.final_pass(b"\x00" * 320)
            committed = agg.commit()
            assert committed.text == correct
            assert wrong not in committed.text

    def test_final_comes_from_high_precision_pass(self):
        calls: list[bytes] = []

        def recorder(segment: bytes) -> str:
            calls.append(segment)
            return "高精度终稿"

        agg = TurnAggregator(DualASRCorrector(recorder))
        agg.start("turn-1")
        agg.on_delta("低精度增量")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        assert agg.commit().text == "高精度终稿"
        assert calls and calls[0] == b"\x00" * 320  # 整段音频进了高精度重转写

    def test_conservative_fallback_carries_precision_notice(self):
        agg = TurnAggregator(DualASRCorrector())
        agg.start("turn-1")
        agg.on_delta("保守文本")
        agg.on_speech_end()
        agg.final_pass(None, timed_out=True)
        committed = agg.commit()
        assert committed.text == "保守文本"
        assert committed.precision_notice


class TestT27EvidenceGrading:
    def test_service_level_never_fills_browser_percentile(self):
        report = PerformanceReport()
        report.add(PerformanceSample(EvidenceLevel.SERVICE_LEVEL, "e2e_ms", 12230))
        assert report.percentile(EvidenceLevel.BROWSER_LINK, metric="e2e_ms", p=0.5) is None
        assert report.percentile(EvidenceLevel.SERVICE_LEVEL, metric="e2e_ms", p=0.5) == 12230

    def test_mixed_computation_is_zero(self):
        report = PerformanceReport()
        report.add(PerformanceSample(EvidenceLevel.SERVICE_LEVEL, "stop_ms", 120))
        report.add(PerformanceSample(EvidenceLevel.BROWSER_LINK, "stop_ms", 90))
        assert report.mixed_computation_count() == 0

    def test_service_level_is_not_acceptance_when_browser_missing(self):
        report = PerformanceReport()
        report.add(PerformanceSample(EvidenceLevel.SERVICE_LEVEL, "e2e_ms", 12230))
        assert service_level_is_not_acceptance(report) is True

    def test_browser_samples_are_accepted(self):
        report = PerformanceReport()
        report.add(PerformanceSample(EvidenceLevel.SERVICE_LEVEL, "e2e_ms", 12230))
        report.add(PerformanceSample(EvidenceLevel.BROWSER_LINK, "e2e_ms", 1800))
        assert report.browser_link_accepted() is True
        assert service_level_is_not_acceptance(report) is False
        assert report.percentile(EvidenceLevel.BROWSER_LINK, metric="e2e_ms", p=0.5) == 1800

    def test_probe_ab_not_passed_by_service_level(self):
        assert probe_ab_status(service_level_ok=True, browser_link_ok=False) == "partially_lifted_not_passed"
        assert probe_ab_status(service_level_ok=True, browser_link_ok=True) == "passed"
        assert probe_ab_status(service_level_ok=False, browser_link_ok=False) == "blocked"

    def test_report_groups_samples_by_level(self):
        report = PerformanceReport()
        report.add(PerformanceSample(EvidenceLevel.SERVICE_LEVEL, "e2e_ms", 1.0))
        report.add(PerformanceSample(EvidenceLevel.BROWSER_LINK, "e2e_ms", 2.0))
        grouped = report.as_dict()
        assert grouped["service_level"] == [{"metric": "e2e_ms", "value_ms": 1.0}]
        assert grouped["browser_link"] == [{"metric": "e2e_ms", "value_ms": 2.0}]
