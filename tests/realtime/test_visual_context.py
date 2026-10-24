"""M3（`T-M3-1` / `T-M3-2`）：关键帧存储与视觉指代绑定测试。

覆盖 RTM：VIS-01/02/03/04/05/07/08/09、RET-01/02/03、SCN-01。
"""

from __future__ import annotations

import pytest

from llm_loop.realtime.keyframe import (
    CurrentValidity,
    Keyframe,
    KeyframeReadbackError,
    RetentionState,
)
from llm_loop.realtime.keyframe_store import KeyframeStore
from llm_loop.realtime.visual_context import QuestionKind, VisualContextResolver

REF_A = "artifact://v1/" + "a" * 32
REF_B = "artifact://v1/" + "b" * 32


def _frame(frame_id: str, source_id: str, *, ref: str = REF_A, epoch: int = 1, derived: bool = False) -> Keyframe:
    return Keyframe(
        frame_id=frame_id,
        source_id=source_id,
        source_epoch=epoch,
        captured_at_client_monotonic_s=100.0,
        received_at_s=100.1,
        width=1280,
        height=720,
        content_ref=ref,
        derived=derived,
    )


class TestKeyframeStore:
    def test_current_frame_is_latest_valid(self):
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        store.register(_frame("f2", "tab-1", ref=REF_B))
        assert store.current_frame("tab-1").frame_id == "f2"

    def test_bind_is_immutable_and_blocks_replace(self):
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        store.bind("f1", turn_id="turn-1")
        assert store.is_bound("f1") is True
        assert store.replace_preview("f1", _frame("f9", "tab-1", ref=REF_B)) is False  # 已绑定不丢
        assert store.get("f1") is not None

    def test_bind_to_another_turn_rejected(self):
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        store.bind("f1", turn_id="turn-1")
        with pytest.raises(ValueError):
            store.bind("f1", turn_id="turn-2")

    def test_source_change_makes_current_stale_but_keeps_history(self):
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        assert store.mark_source_stale("tab-1") == 1
        assert store.current_frame("tab-1") is None  # 当前失效
        history = store.history("tab-1")
        assert len(history) == 1 and history[0].current_validity is CurrentValidity.STALE  # 证据仍保留

    def test_expire_loses_readback_with_clear_error(self):
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        store.expire("f1")
        assert store.current_frame("tab-1") is None
        assert store.history("tab-1") == ()
        with pytest.raises(KeyframeReadbackError):
            store.readback_ref("f1")

    def test_readback_unknown_frame_is_clear_error(self):
        with pytest.raises(KeyframeReadbackError):
            KeyframeStore().readback_ref("missing")

    def test_replace_preview_only_unbound(self):
        store = KeyframeStore()
        store.register(_frame("p1", "tab-1"))
        assert store.replace_preview("p1", _frame("p2", "tab-1", ref=REF_B)) is True
        assert store.get("p1") is None
        assert store.current_frame("tab-1").frame_id == "p2"

    def test_count_by_retention(self):
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        store.register(_frame("f2", "tab-1", ref=REF_B))
        store.expire("f2")
        assert store.count() == 2
        assert store.count(retention=RetentionState.RETAINED) == 1
        assert store.count(retention=RetentionState.EXPIRED) == 1

    def test_derived_frames_do_not_masquerade_as_original(self):
        store = KeyframeStore()
        store.register(_frame("d1", "tab-1", derived=True))
        assert store.get("d1").derived is True


class TestVisualContextResolver:
    def _store_with(self) -> KeyframeStore:
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        return store

    def test_current_binds_latest_and_is_bound(self):
        store = self._store_with()
        binding = VisualContextResolver().resolve(
            store=store, turn_id="t1", source_id="tab-1", kind=QuestionKind.CURRENT
        )
        assert binding.bound is True
        assert binding.chosen.frame_id == "f1"
        assert store.is_bound("f1") is True

    def test_current_without_available_frame_asks_clarification(self):
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        store.mark_source_stale("tab-1")
        binding = VisualContextResolver().resolve(
            store=store, turn_id="t1", source_id="tab-1", kind=QuestionKind.CURRENT
        )
        assert binding.bound is False
        assert "刷新" in binding.clarification

    def test_ambiguous_sources_ask_clarification(self):
        store = self._store_with()
        binding = VisualContextResolver().resolve(
            store=store,
            turn_id="t1",
            source_id=None,
            kind=QuestionKind.CURRENT,
            available_sources=("tab-1", "tab-2"),
        )
        assert binding.bound is False
        assert "指定" in binding.clarification

    def test_single_source_auto_resolves(self):
        store = self._store_with()
        binding = VisualContextResolver().resolve(
            store=store,
            turn_id="t1",
            source_id=None,
            kind=QuestionKind.CURRENT,
            available_sources=("tab-1",),
        )
        assert binding.bound is True

    def test_unshared_source_rejected(self):
        store = self._store_with()
        binding = VisualContextResolver().resolve(
            store=store,
            turn_id="t1",
            source_id="tab-evil",
            kind=QuestionKind.CURRENT,
            available_sources=("tab-1",),
        )
        assert binding.bound is False
        assert "未在本次会话共享" in binding.clarification

    def test_history_uses_stale_frame(self):
        store = self._store_with()
        store.mark_source_stale("tab-1")
        binding = VisualContextResolver().resolve(
            store=store, turn_id="t1", source_id="tab-1", kind=QuestionKind.HISTORY
        )
        assert binding.bound is True
        assert binding.chosen.current_validity is CurrentValidity.STALE

    def test_history_without_evidence_asks_clarification(self):
        store = self._store_with()
        store.expire("f1")
        binding = VisualContextResolver().resolve(
            store=store, turn_id="t1", source_id="tab-1", kind=QuestionKind.HISTORY
        )
        assert binding.bound is False
        assert "历史证据" in binding.clarification

    def test_history_reference_in_text_overrides_current_kind_hint(self):
        # kind 提示 current，但终稿文本「刚才那页」→ 按 history 解析：
        # 源已 stop（当前失效）本应 clarify，历史指代仍绑定 Stale 帧。
        store = self._store_with()
        store.mark_source_stale("tab-1")
        binding = VisualContextResolver().resolve(
            store=store,
            turn_id="t1",
            source_id="tab-1",
            kind=QuestionKind.CURRENT,
            text="看刚才那页的报错",
        )
        assert binding.bound is True
        assert binding.kind is QuestionKind.HISTORY
        assert binding.chosen.current_validity is CurrentValidity.STALE

    def test_no_reference_words_follow_kind_hint(self):
        store = self._store_with()
        store.mark_source_stale("tab-1")
        # 无指代词：按 kind 提示走——current（当前已失效）→ clarify；history → 绑定。
        current = VisualContextResolver().resolve(
            store=store, turn_id="t1", source_id="tab-1", kind=QuestionKind.CURRENT, text="帮我看下"
        )
        assert current.bound is False
        assert "刷新" in current.clarification
        history = VisualContextResolver().resolve(
            store=store, turn_id="t2", source_id="tab-1", kind=QuestionKind.HISTORY, text="帮我看下"
        )
        assert history.bound is True

    def test_mixed_references_ask_clarification(self):
        # 同时含当前与历史指代 → 仍歧义，才 clarify（不猜）。
        store = self._store_with()
        binding = VisualContextResolver().resolve(
            store=store,
            turn_id="t1",
            source_id="tab-1",
            kind=QuestionKind.CURRENT,
            text="对比刚才那页和现在这页",
        )
        assert binding.bound is False
        assert store.is_bound("f1") is False  # 未绑定、不派发
        assert "当前与历史" in binding.clarification
