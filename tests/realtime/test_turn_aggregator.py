"""T-CONTRACT-5：输入状态机、终稿校正、轮次分类与事件去重测试。

覆盖 RTM：INP-01/02/03/04/05/08/09、AUD-05/06、STP-03。
"""

from __future__ import annotations

import pytest

from llm_loop.realtime.dual_asr_corrector import (
    CONSERVATIVE_PRECISION_NOTICE,
    CorrectionOutcome,
    DualASRCorrector,
    FinalCorrection,
)
from llm_loop.realtime.event_normalizer import EventNormalizer, NormalizedKind
from llm_loop.realtime.turn_aggregator import (
    TurnAggregator,
    TurnCapacityError,
    TurnIntent,
    TurnState,
    TurnStateError,
    default_classify,
)


def _precise(text: str = "逐字正确的终稿") -> DualASRCorrector:
    return DualASRCorrector(lambda segment: text)


def _agg(corrector: DualASRCorrector | None = None, **kw: object) -> TurnAggregator:
    return TurnAggregator(corrector or DualASRCorrector(), **kw)  # type: ignore[arg-type]


class TestStateMachine:
    def test_collecting_to_awaiting_final(self):
        agg = _agg()
        agg.start("turn-1")
        assert agg.state is TurnState.COLLECTING
        agg.on_speech_end()
        assert agg.state is TurnState.AWAITING_FINAL

    def test_final_pass_precise(self):
        agg = _agg(_precise("语音链路"))
        agg.start("turn-1")
        agg.on_delta("语音路")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        assert agg.state is TurnState.FINAL
        assert agg.final_text == "语音链路"
        assert agg.precision_notice == ""

    def test_delta_never_enters_committed(self):
        agg = _agg(_precise("语音链路"))
        agg.start("turn-1")
        agg.on_delta("语音路")  # 流式错字，仅显示
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        committed = agg.commit()
        assert committed.text == "语音链路"  # 使用终稿，非 delta
        assert "语音路" not in committed.text

    def test_delta_only_allowed_while_collecting(self):
        agg = _agg()
        agg.start("turn-1")
        agg.on_speech_end()
        with pytest.raises(TurnStateError):
            agg.on_delta("迟到的增量")

    def test_final_pass_requires_awaiting_final(self):
        agg = _agg()
        agg.start("turn-1")
        with pytest.raises(TurnStateError):
            agg.final_pass(b"\x00" * 320)


class TestConservativeFinal:
    def test_no_final_transcriber_is_conservative_with_notice(self):
        agg = _agg(DualASRCorrector())
        agg.start("turn-1")
        agg.on_delta("流式错字文本")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        assert agg.state is TurnState.CONSERVATIVE_FINAL
        assert agg.final_text == "流式错字文本"
        assert agg.precision_notice == CONSERVATIVE_PRECISION_NOTICE

    def test_timeout_is_conservative(self):
        agg = _agg(_precise("不应使用"))
        agg.start("turn-1")
        agg.on_delta("保守收口")
        agg.on_speech_end()
        agg.final_pass(None, timed_out=True)
        assert agg.state is TurnState.CONSERVATIVE_FINAL
        assert agg.final_text == "保守收口"

    def test_transcriber_exception_is_conservative(self):
        def boom(segment: bytes) -> str:
            raise RuntimeError("asr down")

        agg = _agg(DualASRCorrector(boom))
        agg.start("turn-1")
        agg.on_delta("免责文本")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        assert agg.state is TurnState.CONSERVATIVE_FINAL
        assert agg.precision_notice


class TestConservativeFallbackBoundaries:
    """高精度重转写「有通道但结果不可用」的兜底边界（RTM-INP-09 / RTM-AUD-03）。"""

    def test_empty_transcription_result_is_conservative(self):
        agg = _agg(DualASRCorrector(lambda segment: ""))
        agg.start("turn-1")
        agg.on_delta("流式文本")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        assert agg.state is TurnState.CONSERVATIVE_FINAL
        assert agg.final_text == "流式文本"
        assert agg.precision_notice == CONSERVATIVE_PRECISION_NOTICE

    def test_whitespace_transcription_result_is_conservative(self):
        agg = _agg(DualASRCorrector(lambda segment: "   \n "))
        agg.start("turn-1")
        agg.on_delta("流式文本")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        assert agg.state is TurnState.CONSERVATIVE_FINAL
        assert agg.final_text == "流式文本"
        assert agg.precision_notice == CONSERVATIVE_PRECISION_NOTICE

    def test_empty_audio_never_reaches_high_precision_transcriber(self):
        calls: list[bytes] = []

        def recorder(segment: bytes) -> str:
            calls.append(segment)
            return "不应被调用"

        agg = _agg(DualASRCorrector(recorder))
        agg.start("turn-1")
        agg.on_delta("保守收口")
        agg.on_speech_end()
        agg.final_pass(b"")
        assert calls == []  # 无音频不得送高精度重转写
        assert agg.state is TurnState.CONSERVATIVE_FINAL
        assert agg.final_text == "保守收口"

    def test_timeout_never_reaches_high_precision_transcriber(self):
        calls: list[bytes] = []

        def recorder(segment: bytes) -> str:
            calls.append(segment)
            return "不应被调用"

        agg = _agg(DualASRCorrector(recorder))
        agg.start("turn-1")
        agg.on_delta("保守收口")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320, timed_out=True)
        assert calls == []  # 已超时不得再发起高精度重转写
        assert agg.state is TurnState.CONSERVATIVE_FINAL
        assert agg.final_text == "保守收口"


class TestFinalCorrectionInvariants:
    """终稿结果对象的不变量：保守终稿必须带精度标注，文本必须是 str。"""

    def test_conservative_without_notice_is_rejected(self):
        with pytest.raises(ValueError):
            FinalCorrection(text="文本", outcome=CorrectionOutcome.CONSERVATIVE)

    def test_non_str_text_is_rejected(self):
        with pytest.raises(TypeError):
            FinalCorrection(text=None, outcome=CorrectionOutcome.PRECISE)  # type: ignore[arg-type]

    def test_precise_final_carries_no_notice(self):
        correction = FinalCorrection(text="终稿", outcome=CorrectionOutcome.PRECISE)
        assert correction.precision_notice == ""


class TestCommitOnce:
    def test_commit_only_once(self):
        agg = _agg(_precise())
        agg.start("turn-1")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        agg.commit()
        with pytest.raises(TurnStateError):
            agg.commit()

    def test_commit_before_final_raises(self):
        agg = _agg()
        agg.start("turn-1")
        with pytest.raises(TurnStateError):
            agg.commit()


class TestSuspendAndCorrection:
    def test_suspend_tool_preserves_valid_input(self):
        agg = _agg(_precise("有效输入"))
        agg.start("turn-1")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        not_executed = agg.suspend_tool_unexecuted(reason="early_tool_timeout")
        assert not_executed.preserved_text == "有效输入"
        assert not_executed.reason == "early_tool_timeout"

    def test_correction_updates_before_execution(self):
        agg = _agg(_precise("初稿"))
        agg.start("turn-1")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        assert agg.apply_correction("修正稿") is True
        assert agg.final_text == "修正稿"

    def test_correction_cannot_rewrite_executed_facts(self):
        agg = _agg(_precise("已执行事实"))
        agg.start("turn-1")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        agg.mark_executed()
        assert agg.apply_correction("反向改写") is False
        assert agg.final_text == "已执行事实"


class TestSegments:
    def test_segments_are_retainable_and_reported(self):
        agg = _agg(_precise("合并终稿"))
        agg.start("turn-1")
        agg.add_segment("第一段")
        agg.add_segment("第二段")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        committed = agg.commit()
        assert committed.segments == ("第一段", "第二段")

    def test_capacity_exceeded_is_explicit_and_preserves_confirmed(self):
        agg = _agg(_precise(), max_segments=2)
        agg.start("turn-1")
        agg.add_segment("第一段")
        agg.add_segment("第二段")
        with pytest.raises(TurnCapacityError):
            agg.add_segment("超容量")
        assert agg.segments == ("第一段", "第二段")  # 已确认部分保留


class TestClassification:
    def test_four_intents(self):
        assert default_classify("帮我读一下这个文件") is TurnIntent.TASK_SUBMIT
        assert default_classify("这个函数为什么失败？") is TurnIntent.QUERY
        assert default_classify("不是，我说的是第二条") is TurnIntent.CORRECTION
        assert default_classify("今天天气不错") is TurnIntent.DIALOGUE

    def test_committed_turn_carries_intent(self):
        agg = _agg(_precise("帮我分析这个错误"))
        agg.start("turn-1")
        agg.on_speech_end()
        agg.final_pass(b"\x00" * 320)
        assert agg.commit().intent is TurnIntent.TASK_SUBMIT


class TestEventNormalizer:
    def test_maps_raw_events(self):
        norm = EventNormalizer()
        delta = norm.normalize("conversation.item.input_audio_transcription.delta", "语", turn_id="t1")
        final = norm.normalize("conversation.item.input_audio_transcription.completed", "语音", turn_id="t1")
        assert delta is not None and delta.kind is NormalizedKind.DELTA
        assert final is not None and final.kind is NormalizedKind.FINAL

    def test_final_deduplicated_per_revision(self):
        norm = EventNormalizer()
        assert norm.normalize("completed", "语音", turn_id="t1", revision=0) is not None
        assert norm.normalize("completed", "语音", turn_id="t1", revision=0) is None

    def test_new_revision_is_not_deduplicated(self):
        norm = EventNormalizer()
        assert norm.normalize("completed", "初稿", turn_id="t1", revision=0) is not None
        assert norm.normalize("completed", "修订", turn_id="t1", revision=1) is not None

    def test_unknown_raw_event_raises(self):
        with pytest.raises(ValueError):
            EventNormalizer().normalize("response.audio.delta", "x", turn_id="t1")

    def test_short_form_delta_maps_to_delta(self):
        norm = EventNormalizer()
        event = norm.normalize("delta", "语", turn_id="t1")
        assert event is not None and event.kind is NormalizedKind.DELTA

    def test_empty_text_is_normalized_to_empty_string(self):
        norm = EventNormalizer()
        event = norm.normalize("completed", "", turn_id="t1")
        assert event is not None and event.text == ""

    def test_delta_is_never_deduplicated(self):
        norm = EventNormalizer()
        first = norm.normalize("delta", "语", turn_id="t1", revision=0)
        second = norm.normalize("delta", "语音", turn_id="t1", revision=0)
        assert first is not None and second is not None
        assert second.text == "语音"  # 增量可重复，只有终稿去重

    def test_reset_turn_only_clears_that_turn(self):
        norm = EventNormalizer()
        assert norm.normalize("completed", "语音", turn_id="t1", revision=0) is not None
        assert norm.normalize("completed", "语音", turn_id="t2", revision=0) is not None
        norm.reset_turn("t1")
        # 被重置的轮次：终稿可再次归并（重连重发场景）
        assert norm.normalize("completed", "语音", turn_id="t1", revision=0) is not None
        # 未被重置的轮次：去重状态保留，重复终稿仍被丢弃
        assert norm.normalize("completed", "语音", turn_id="t2", revision=0) is None
