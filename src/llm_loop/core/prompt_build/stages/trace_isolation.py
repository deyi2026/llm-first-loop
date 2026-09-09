"""trace 隔离阶段（build α 挂载点；design §2.1.2 #3 / T5-C 第一批）.

薄接线：检测/隔离/签名兜底本体在 core/trace_leak/ 与 injection_labels/
（KEEP-HARD 等价——本模块只做编排与产物显式化，行为逐字节不变）。
三态分流（R8.24-D D-D1）与 fail-open（spec 5.4.3-1）语义原样保留。
"""

from __future__ import annotations

import logging
from typing import Any

from llm_loop.core.injection_labels import InjectionLayer as _TLLayer
from llm_loop.core.injection_labels import render_program_appendix as _rpax
from llm_loop.core.prompt_build.context import BuildDecision
from llm_loop.core.trace_leak import leak_events as _tle
from llm_loop.core.trace_leak.leak_detector import detect_leak_at_build
from llm_loop.core.trace_leak.leak_events import (
    LEAK_QUARANTINED,
    LEAK_WOULD_QUARANTINE,
    current_quarantine_mode,
)
from llm_loop.core.trace_leak.leak_events import write_quarantine as _write_quarantine
from llm_loop.core.trace_leak.trace_signature import (
    content_matches_signature,
    current_signature_mode,
)

logger = logging.getLogger(__name__)


def run_trace_isolation(
    base: list[Any],
    *,
    base_indices: list[int],
    index_by_id: dict[int, int],
    sess: Any,
    current_ingress: Any,
    event_sink: Any,
    decision: BuildDecision,
) -> tuple[list[Any], list[int]]:
    """α 挂载点：user 消息投影进 provider 视图前泄漏检测（纯 metadata 单遍）.

    处置仅视图层：失真消息剔除，会话存储原文零改动（spec 5.4.1-3）。
    LFL_LEAK_QUARANTINE 三态（D-D1）：
    off（默认，enforce）= mislabel 剔除 + quarantine 隔离 + 事件
    （event+UI 双通道，不进 sess.messages）+ provider chars=0；
    shadow = 回喂照旧 + would_quarantine 计数（行为零变化）；
    on = 现状回喂（回滚通道，回滚期结束后整段退役）。

    返回 (过滤后 base, 对齐 base_indices)；隔离决策落
    decision.trace_isolation（异常路径保持 None——fail-open 放行）。
    """
    _leak_downgrade_parts: list[tuple[str | None, str]] = []
    _drop_ids: set[int] = set()
    _findings: list[Any] = []
    _quarantine_mode = "n/a"
    try:
        _quarantine_mode = current_quarantine_mode()
        _findings = detect_leak_at_build(
            base,
            session_id=sess.session_id,
            current_ingress=current_ingress,
        )
        if _findings:
            for _f in _findings:
                if _f.action == "downgrade_to_appendix" and 0 <= _f.message_ref < len(base):
                    _m = base[_f.message_ref]
                    _drop_ids.add(id(_m))
                    _leak_content = str(_m.content or "")
                    if _quarantine_mode == "off":
                        # D-D1 quarantine 承接：隔离留痕（0600）+ 事件（不含原文，
                        # sha1/preview≤200/basis）+ UI 提示；不自动回喂、不一键转正。
                        _write_quarantine(
                            LEAK_QUARANTINED,
                            session_id=sess.session_id,
                            content=_leak_content,
                            basis=(
                                "build α hook：确认 mislabel 的程序内容隔离"
                                f"（{_f.basis}；不降级注入，provider chars=0）"
                            ),
                        )
                        _tle.emit_leak_event(
                            LEAK_QUARANTINED,
                            entry="build.leak_detector",
                            session_id=sess.session_id,
                            content=_leak_content,
                            basis=(
                                "确认 mislabel 内容改 quarantine 承接"
                                "（有条内容被隔离，可在 trace_leak_quarantine "
                                "区复核；不进本轮 prompt）"
                            ),
                            extra={
                                "provider_chars": 0,
                                "quarantine_mode": _quarantine_mode,
                            },
                            sink=event_sink,
                        )
                    else:
                        if _quarantine_mode == "shadow":
                            # shadow 计数：行为与现状零变化，仅记录 would_quarantine
                            _tle.emit_leak_event(
                                LEAK_WOULD_QUARANTINE,
                                entry="build.leak_detector",
                                session_id=sess.session_id,
                                content=_leak_content,
                                basis=(
                                    "shadow 计数：若 enforce 本条将 quarantine"
                                    "（现状回喂照旧，行为零变化）"
                                ),
                                extra={
                                    "chars": len(_leak_content),
                                    "quarantine_mode": _quarantine_mode,
                                },
                                sink=event_sink,
                            )
                        _leak_downgrade_parts.append(
                            (
                                "leak_downgrade",
                                _rpax(_leak_content, _TLLayer.REFERENCE),
                            )
                        )
            if _drop_ids:
                base = [_m for _m in base if id(_m) not in _drop_ids]
                base_indices = [index_by_id[id(_m)] for _m in base if id(_m) in index_by_id]
        # 特征兜底（默认 off；warn 仅告警不改视图，spec 5.4.1-2；
        # 人类凭据消息豁免，spec 5.4.3-2）
        if current_signature_mode() == "warn":
            for _m in base:
                _md = getattr(_m, "metadata", None) or {}
                if (
                    getattr(_m, "role", None) == "user"
                    and _md.get("origin_layer") == "user_instruction"
                    and not _md.get("ingress_channel")
                    and content_matches_signature(getattr(_m, "content", ""))
                ):
                    _tle.emit_leak_event(
                        _tle.LEAK_SIGNATURE_WARNED,
                        entry="build.trace_signature",
                        session_id=sess.session_id,
                        content=str(getattr(_m, "content", "") or ""),
                        basis="思考过程标记 + 工具调用命令组合特征命中（warn 仅告警不拦截）",
                    )
        decision.trace_isolation = {
            "hook": "build.alpha",
            "mode": _quarantine_mode,
            "findings": len(_findings),
            "dropped": len(_drop_ids),
            "downgrade_parts": _leak_downgrade_parts,
        }
    except Exception:  # noqa: BLE001 — 检测层 fail-open（spec 5.4.3-1）
        logger.warning("build α 挂载点泄漏检测异常（fail-open 放行）", exc_info=True)
    return base, base_indices
