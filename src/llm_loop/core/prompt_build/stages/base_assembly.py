"""base 装配阶段（design T5-C 第二批 / B4-C2-02）.

前缀装配与稳定段指纹：interop 外部协调观测（模型输入已退出）、L3 门禁预检。
会话状态快照保留为工具/状态能力，不再在 build 中构造 program Message。
副作用经显式传参与出口对象收窄：stable_fp 由调用点回写 self 面。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from llm_loop.core.cache_health import strip_cache_telemetry_lines
from llm_loop.core.history import stable_digest
from llm_loop.core.message import Message
from llm_loop.core.prompt_eligibility import (
    LEGACY_PROGRAM_FINAL_MARKER,
    PROGRAM_FINAL_PROTOCOL_BOUNDARY,
)
from llm_loop.feedback.honesty import PROGRAM_FEEDBACK_PREFIXES

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BaseAssemblyResult:
    """base 装配产出（过程值：prefix_len/stable_fp 滚动，base 续投影）."""

    base: list[Any]
    prefix_len: int
    stable_fp: str = ""


def run_base_assembly(
    *,
    base: list[Any],
    system_prompt: str,
    session_id: str,
    sess_message_count: int,
    sess_anchor: Any,
    inject_interop: Callable[..., Any],
    cache_monitor: Any,
    tool_prefix_fp: str = "",
) -> BaseAssemblyResult:
    """interop 注入 + 门禁预检 + 快照节流（产出 prefix_len/stable_fp/base）."""
    result = BaseAssemblyResult(base=base, prefix_len=0)
    # RULE-AI-14 协调通道: 程序级自动注入 DSH→LFL 待处理消息（每轮 run 必感知，
    # 非仅提示词引导；实现见 core/loop/interop.py _InteropMixin，fail-open）
    # 注入位置: memory 之后、历史之前（2026-08-16 优化: system_prompt+memory 前缀
    # 有/无消息轮字节级一致，服务端缓存命中不受 inbox 影响）
    result.base, result.prefix_len = inject_interop(
        base, result.prefix_len, session_id
    )
    # EVO-20260817-72fcd94a L3 发送前门禁·预检（程序常态锚点管理）: 稳定段指纹
    # （system+注入）与该 session 基线不符 → 强制缓存友好压缩，当次 build 即合规化。fail-open。
    try:
        _base_fp = stable_digest(
            [(m.role, m.content) for m in result.base[: result.prefix_len]]
            + [system_prompt]
        )
        # Tool schemas are part of the actual provider request prefix/surface.
        # A schema/order change invalidates the previous cache boundary even when
        # system + stable chat bytes are unchanged. Keep the original digest for
        # direct/legacy callers that did not project a tool surface.
        result.stable_fp = (
            stable_digest({"base_fp": _base_fp, "tools_fp": tool_prefix_fp})
            if tool_prefix_fp
            else _base_fp
        )
        cache_monitor.preflight(session_id, result.stable_fp)
    except Exception:  # noqa: BLE001
        result.stable_fp = ""
    # Agency-first: session snapshot is runtime/status data, not model input. The old
    # build-time snapshot Message and its throttling plumbing have been removed.
    return result



@dataclass(slots=True)
class ProviderViewScrub:
    """provider 视图预清洗产物（base 序列 + 原始索引重映射）."""

    base: list[Message]
    base_original_indices: list[int]


def scrub_provider_view(
    *,
    base: list[Message],
    base_original_indices: list[int],
) -> ProviderViewScrub:
    """base 提交视图三段预清洗（B4-CLOSE-01 步B；语义原样迁自 build.py）.

    ① 缓存遥测剥离 ② program 协议边界收敛；
    存档/存储原文零改动（仅 provider 视图）。
    """
    # P1 遥测内容/传输分层（2026-08-25）: legacy 历史（旧会话已把 ⚡ 缓存命中率
    # 行写进 assistant 正文）与模型伪造行——build 提交视图一律剥离（正文=纯回答；
    # 权威遥测走 metadata.cache_health → transport 渲染）。剥离只影响提交视图，
    # 存档/存储原文不动（archive_sink 收到的是剥离后副本——遥测行属噪音，无信息损失）。
    if any(
        m.role == "assistant" and "缓存命中率" in (m.content or "") for m in base
    ):
        base = [
            replace(m, content=strip_cache_telemetry_lines(m.content))
            if (m.role == "assistant" and "缓存命中率" in (m.content or ""))
            else m
            for m in base
        ]
    # R8.10 / P0-B2 + 2026-09-03 echo-loop correction: program finals are storage/event
    # truth only.  Keep the assistant *role frame* to avoid provider user→user 1210, but
    # project zero content.  A visible marker taught models to echo the control token as
    # a normal final answer.  Legacy model-origin echoes are scrubbed too, even when old
    # metadata incorrectly said answer_origin=model.  Storage/event truth is untouched.
    base = [
        (
            replace(m, content=PROGRAM_FINAL_PROTOCOL_BOUNDARY, reasoning_content=None)
            if (
                m.role == "assistant"
                and (
                    (m.metadata or {}).get("answer_origin") == "program"
                    or str(m.content or "").startswith(PROGRAM_FEEDBACK_PREFIXES)
                    or str(m.content or "").strip() == LEGACY_PROGRAM_FINAL_MARKER
                )
            )
            else m
        )
        for m in base
    ]
    return ProviderViewScrub(base=base, base_original_indices=base_original_indices)
