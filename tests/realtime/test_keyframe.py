"""T-CONTRACT-7：关键帧 `current_validity` / `retention_state` 分离测试。

覆盖 RTM：VIS-02/03/05/06/09、RET-01/02/03、CAP-06、IDN-01、RET-05。

核心断言：`Stale` 只使当前画面失效、**仍可回答历史**；只有 `Expired`/`Deleted`
才失去回读能力；派生证据标 `derived`。
"""

from __future__ import annotations

import pytest

from llm_loop.realtime.keyframe import (
    CurrentValidity,
    Keyframe,
    KeyframeReadbackError,
    RetentionState,
    Selection,
)

REF = "artifact://v1/" + "a" * 32


def _frame(**over: object) -> Keyframe:
    base: dict[str, object] = {
        "frame_id": "frame-1",
        "source_id": "tab-1",
        "source_epoch": 1,
        "captured_at_client_monotonic_s": 100.0,
        "received_at_s": 100.2,
        "width": 1280,
        "height": 720,
        "content_ref": REF,
    }
    base.update(over)
    return Keyframe(**base)  # type: ignore[arg-type]


class TestBindingAndValidation:
    def test_new_frame_is_valid_and_retained(self):
        frame = _frame()
        assert frame.current_validity is CurrentValidity.VALID
        assert frame.retention_state is RetentionState.RETAINED
        assert frame.can_answer_current() is True
        assert frame.can_answer_history() is True

    def test_content_ref_must_be_artifact_reference(self):
        with pytest.raises(ValueError):
            _frame(content_ref="file:///tmp/frame.png")

    def test_requires_positive_dimensions_and_bounded_ids(self):
        with pytest.raises(ValueError):
            _frame(width=0)
        with pytest.raises(ValueError):
            _frame(frame_id="")

    def test_selection_validated(self):
        frame = _frame(selection=Selection(x=0, y=0, width=100, height=50))
        assert frame.selection.width == 100
        with pytest.raises(ValueError):
            Selection(x=0, y=0, width=0, height=10)


class TestStaleIsNotDeletion:
    def test_mark_stale_invalidates_current_but_keeps_history(self):
        frame = _frame()
        stale = frame.mark_stale()
        assert stale.current_validity is CurrentValidity.STALE
        assert stale.retention_state is RetentionState.RETAINED  # 证据保留不变
        assert stale.can_answer_current() is False
        assert stale.can_answer_history() is True  # 仍可回答历史问题
        assert stale.readback_ref() == REF  # 仍可回读

    def test_mark_stale_returns_new_object_original_unchanged(self):
        frame = _frame()
        stale = frame.mark_stale()
        assert frame.current_validity is CurrentValidity.VALID  # 保存精确源
        assert stale is not frame

    def test_mark_valid_restores_current(self):
        frame = _frame().mark_stale().mark_valid()
        assert frame.can_answer_current() is True


class TestExpiryLosesReadback:
    def test_expire_blocks_current_and_history_and_readback(self):
        frame = _frame().expire()
        assert frame.retention_state is RetentionState.EXPIRED
        assert frame.can_answer_current() is False
        assert frame.can_answer_history() is False
        with pytest.raises(KeyframeReadbackError):
            frame.readback_ref()

    def test_delete_blocks_readback(self):
        frame = _frame().delete()
        assert frame.retention_state is RetentionState.DELETED
        with pytest.raises(KeyframeReadbackError):
            frame.readback_ref()

    def test_stale_then_expire_loses_history(self):
        frame = _frame().mark_stale()
        assert frame.can_answer_history() is True
        expired = frame.expire()
        assert expired.can_answer_history() is False


class TestDerivedAndAge:
    def test_derived_flag_marks_caption_not_original(self):
        derived = _frame(derived=True)
        assert derived.derived is True
        assert _frame().derived is False

    def test_frame_age_uses_client_monotonic_clock(self):
        frame = _frame(captured_at_client_monotonic_s=100.0)
        assert frame.frame_age_s(103.5) == pytest.approx(3.5)

    def test_backwards_clock_rejected(self):
        frame = _frame(captured_at_client_monotonic_s=100.0)
        with pytest.raises(ValueError):
            frame.frame_age_s(99.0)

    def test_server_receive_time_kept_separately(self):
        frame = _frame(captured_at_client_monotonic_s=100.0, received_at_s=100.2)
        assert frame.received_at_s == pytest.approx(100.2)
