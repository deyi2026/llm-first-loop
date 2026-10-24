"""M3：指代绑定与历史/当前区分（`T-M3-2`）。

对应需求：`RTM-VIS-03/04/09`、`RTM-SCN-01`、`RTM-RET-02/03`。

- 含视觉输入的提交点**绑定候选帧**；候选不唯一/无可用画面 → **提一个澄清问题**（不猜、不强行绑定）；
- **历史 vs 当前**：``visual.kind`` 仅是提示；**终稿文本中的指代优先**——含「刚才/上一页/
  前面那页/刚才那张」等历史指代按 history 解析，含「现在/当前/这页/屏幕上」按 current；
  两侧都没有指代词时沿用 kind 提示；**同时出现两侧指代才**回到澄清（不猜）；
- 历史问题可用旧帧（含 `Stale`）；当前操作**先刷新核验**当前帧；
- 删除/到期 → 返回**明确失效**，不用摘要替代原图。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from llm_loop.realtime.keyframe import Keyframe
from llm_loop.realtime.keyframe_store import KeyframeStore

# 终稿文本指代提示（有界闭集；子串包含即命中，如「刚才那页」命中「刚才」）。
HISTORY_REFERENCE_HINTS: tuple[str, ...] = ("刚才", "上一页", "前面那页", "刚才那张")
CURRENT_REFERENCE_HINTS: tuple[str, ...] = ("现在", "当前", "这页", "屏幕上")


def _text_reference(text: str) -> tuple[bool, bool]:
    """终稿文本指代扫描：返回 (含历史指代, 含当前指代)。空文本/无命中均为 (False, False)。"""
    if not text:
        return (False, False)
    return (
        any(hint in text for hint in HISTORY_REFERENCE_HINTS),
        any(hint in text for hint in CURRENT_REFERENCE_HINTS),
    )


class QuestionKind(StrEnum):
    CURRENT = "current"
    HISTORY = "history"


@dataclass(frozen=True)
class VisualBinding:
    turn_id: str
    source_id: str
    kind: QuestionKind
    chosen: Keyframe | None
    bound: bool
    clarification: str = ""


class VisualContextResolver:
    """提交点绑定候选帧 + 澄清分支。"""

    def resolve(
        self,
        *,
        store: KeyframeStore,
        turn_id: str,
        source_id: str | None,
        kind: QuestionKind,
        available_sources: tuple[str, ...] = (),
        text: str = "",
    ) -> VisualBinding:
        if not source_id:
            if len(available_sources) != 1:
                return VisualBinding(
                    turn_id=turn_id,
                    source_id="",
                    kind=kind,
                    chosen=None,
                    bound=False,
                    clarification="存在多个共享来源，请指定要引用的来源",
                )
            source_id = available_sources[0]
        elif available_sources and source_id not in available_sources:
            return VisualBinding(
                turn_id=turn_id,
                source_id=source_id,
                kind=kind,
                chosen=None,
                bound=False,
                clarification="该来源未在本次会话共享，请重新选择来源",
            )

        # 终稿文本指代覆盖 kind 提示（RTM-VIS-09）：单侧指代定向；双侧指代 → 澄清（不猜）。
        wants_history, wants_current = _text_reference(text)
        if wants_history and wants_current:
            return VisualBinding(
                turn_id=turn_id,
                source_id=source_id,
                kind=kind,
                chosen=None,
                bound=False,
                clarification="这句话同时指向当前与历史画面，请说明要看哪一个",
            )
        if wants_history:
            kind = QuestionKind.HISTORY
        elif wants_current:
            kind = QuestionKind.CURRENT

        if kind is QuestionKind.CURRENT:
            frame = store.current_frame(source_id)
            if frame is None:
                return VisualBinding(
                    turn_id=turn_id,
                    source_id=source_id,
                    kind=kind,
                    chosen=None,
                    bound=False,
                    clarification="当前无可用画面，请刷新或重新共享后再操作",
                )
            store.bind(frame.frame_id, turn_id=turn_id)
            return VisualBinding(
                turn_id=turn_id, source_id=source_id, kind=kind, chosen=frame, bound=True
            )

        history = store.history(source_id)
        if not history:
            return VisualBinding(
                turn_id=turn_id,
                source_id=source_id,
                kind=kind,
                chosen=None,
                bound=False,
                clarification="该来源无可回读的历史证据（可能已到期或删除）",
            )
        chosen = history[-1]
        store.bind(chosen.frame_id, turn_id=turn_id)
        return VisualBinding(turn_id=turn_id, source_id=source_id, kind=kind, chosen=chosen, bound=True)
