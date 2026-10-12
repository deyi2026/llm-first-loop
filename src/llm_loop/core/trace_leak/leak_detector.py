"""leak_detector build 期标记失真/通道越权检测（tasks 4.1，design D1，spec 5.4.1-1）.

纯 metadata 单遍判定（无 IO / 无模型调用 / 无正则回溯——特征兜底为可选
预编译模块），单轮 build 额外耗时不超 1ms 量级（spec 4.1-1）；整体
try/except 包裹，异常返回空列表 + ``leak.detector_fault`` 告警事件
（fail-open，spec 5.4.3-1）。

检测矩阵：
- 标记失真（mislabel）：恒等式 ``program_origin == (origin_layer !=
  "user_instruction")`` 违反——纯 metadata 确定性判定。
- 通道越权（overreach）：本轮人类 ingress 消息缺白名单凭据快照
  （``ingress_channel``）——写入期 guard 之外的纵深第二层。
- 存量消息缺 metadata（两键不全）→ fail-open 放行（spec 4.5-1，不回溯）。
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass

from llm_loop.core.trace_leak import leak_events
from llm_loop.core.trace_leak.invariant import metadata_satisfies_invariant
from llm_loop.core.trace_leak.leak_events import EventSink

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LeakFinding:
    """单条发现：类型 + 消息定位 + 判定依据。"""

    kind: str  # leak_events 事件常量
    message_ref: int  # 在输入序列中的下标
    basis: str
    action: str  # "downgrade_to_appendix" | "observe_event_only"


def detect_leak_at_build(
    messages: list,
    *,
    session_id: str,
    current_ingress: object | None = None,
    sink: EventSink | None = None,
) -> list[LeakFinding]:
    """对 provider 视图候选执行单遍泄漏检测（fail-open）.

    messages: Message 对象序列（build 投影候选）。
    current_ingress: 本轮人类 ingress Message（``_r6_ingress_truth`` 身份链）；
    None 时跳过本轮越权检查。
    """
    try:
        return _detect_inner(messages, session_id, current_ingress, sink)
    except Exception:  # noqa: BLE001 — fail-open（spec 5.4.3-1）
        logger.warning("leak_detector 异常（fail-open 放行）", exc_info=True)
        with contextlib.suppress(Exception):  # noqa: BLE001 — 告警失败不放大
            leak_events.emit_leak_event(
                leak_events.LEAK_DETECTOR_FAULT,
                entry="leak_detector",
                session_id=str(session_id or "?"),
                content="",
                basis="检测层内部异常，返回空发现列表（fail-open）",
                sink=sink,
            )
        return []


def _detect_inner(
    messages: list,
    session_id: str,
    current_ingress: object | None,
    sink: EventSink | None,
) -> list[LeakFinding]:
    findings: list[LeakFinding] = []
    ingress_id = id(current_ingress) if current_ingress is not None else None

    for idx, msg in enumerate(messages):
        if getattr(msg, "role", None) != "user":
            continue
        metadata = getattr(msg, "metadata", None) or {}

        # 1) 恒等式失真（纯 metadata 确定性；缺键 None → 存量 fail-open 放行）
        invariant_ok = metadata_satisfies_invariant(metadata)
        if invariant_ok is False:
            findings.append(
                LeakFinding(
                    kind=leak_events.LEAK_MISLABEL_DETECTED,
                    message_ref=idx,
                    basis=(
                        f"恒等式违反: origin_layer={metadata.get('origin_layer')!r}, "
                        f"program_origin={metadata.get('program_origin')!r}"
                    ),
                    action="downgrade_to_appendix",
                )
            )
            continue

        # 2) 本轮 ingress 凭据缺失（越权嫌疑——写入期 guard 的纵深第二层）
        if (
            ingress_id is not None
            and id(msg) == ingress_id
            and invariant_ok is True
            and not metadata.get("ingress_channel")
        ):
            findings.append(
                LeakFinding(
                    kind=leak_events.LEAK_CHANNEL_OVERREACH,
                    message_ref=idx,
                    basis="本轮人类 ingress 无 ingress_channel 凭据快照（越权嫌疑）",
                    action="observe_event_only",
                )
            )
    # 事件落盘（fire-and-forget）
    for f in findings:
        try:
            content = str(
                getattr(messages[f.message_ref], "content", "") or ""
            )
            leak_events.emit_leak_event(
                f.kind,
                entry="build.leak_detector",
                session_id=str(session_id or "?"),
                content=content,
                basis=f.basis,
                extra={"action": f.action, "message_ref": f.message_ref},
                sink=sink,
            )
        except Exception:  # noqa: BLE001 — 事件失败不影响检测
            pass
    return findings
