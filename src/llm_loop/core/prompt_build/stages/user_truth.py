"""user truth wire 阶段（R6 ingress 冻结；design §2.1.2 #15 / T5-C 第一批）.

KEEP-HARD（用户语义保真）：storage/event history 原文零改动，仅 provider
视图投影为 program appendix -> fixed boundary -> exact user truth 单信封。
工具跟随轮被 current_ingress_user_truth() 刻意排除——assistant(tool_calls)
->tool(result) 配对永不重排、用户文本在 round 2+ 永不重放（其判定在
调用侧 build.py 入口段完成，本模块只承接投影与登记）。
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any

from llm_loop.core.loop.err1210 import InjectedEntry, SlotKind, content_prefix_sha
from llm_loop.core.user_truth_wire import project_user_truth_tail

logger = logging.getLogger(__name__)


def run_user_truth_wire(
    built: list[dict[str, Any]],
    *,
    ingress_truth: str | None,
    injections: list[InjectedEntry],
    record_action: Callable[..., Any],
) -> tuple[list[dict[str, Any]], list[InjectedEntry], bool]:
    """R6 initial human-ingress wire projection（就地投影 + 登记）.

    返回 (built, injections, applied)：
    - violation：保持原 payload 供上层拒绝/诊断（只 error 日志 + 登记）；
    - changed：built 原位替换为投影消息序列，injections 重写为单 USER_ENVELOPE
      条目（吸收段的 seg_sources 并入）；
    - 异常：保持原 payload（不静默改写用户文本），applied=False。
    """
    _r6_applied = False
    if ingress_truth is None:
        return built, injections, _r6_applied
    try:
        _r6 = project_user_truth_tail(built, ingress_truth)
        if _r6.violation:
            logger.error(
                "build: R6 user-truth wire invariant 未能投影（%s），保持原 payload 供上层拒绝/诊断",
                _r6.violation,
            )
            with contextlib.suppress(Exception):
                record_action("action.user_truth_wire", "violation", _r6.violation)
        elif _r6.changed:
            _seg_sources: list[tuple[str, str]] = []
            for _entry in injections:
                if _entry.msg_idx in set(_r6.absorbed_indices):
                    _seg_sources.extend(_entry.seg_sources or ())
            built[:] = _r6.messages
            injections = [
                InjectedEntry(
                    msg_idx=_r6.envelope_index,
                    slot_kind=SlotKind.USER_ENVELOPE,
                    prefix_sha=content_prefix_sha(
                        str(built[_r6.envelope_index].get("content") or "")
                    ),
                    message_ref=None,
                    seg_sources=tuple(_seg_sources),
                    user_truth=ingress_truth,
                )
            ]
            _r6_applied = True
            with contextlib.suppress(Exception):
                record_action(
                    "action.user_truth_wire",
                    "projected",
                    f"absorbed={len(_r6.absorbed_indices)}; envelope_idx={_r6.envelope_index}",
                )
    except Exception:  # noqa: BLE001 — do not silently rewrite user text on error
        logger.exception("build: R6 user-truth projection 异常，保持原 payload")
    return built, injections, _r6_applied
