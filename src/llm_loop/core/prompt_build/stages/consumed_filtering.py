"""consumed_filtering 防护模块（design A-1 consumed 半面 / B4-C3-02 / D13 验收面①）

INJECTION-GOVERNANCE R8.5/R8.20 eligibility：resolved episode 退休后
不得经 packet 侧通道复活；memory_snapshot 未授权零投影（E-G1
automatic memory chars=0）；授权轮经 eligibility 注册槽
（memory_authorized）校验 + 语义标注后准注入（双面 wire/packet 由
调用面执行）。纯判定无副作用——shadow 计数与决策日志事件由调用面
基于判定结果发出，模块可独立单测。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_loop.core.injection_labels import (
    ensure_semantic_label,
    strip_program_appendix_notice,
)
from llm_loop.core.prompt_eligibility import dynamic_prompt_layer

ADMIT = "admit"
SKIP_RESOLVED_EPISODE = "skip_resolved_episode"
SKIP_NOT_MEMORY = "skip_not_memory"
SKIP_UNAUTHORIZED = "skip_unauthorized"
SKIP_BLANK = "skip_blank"
SKIP_NOT_ELIGIBLE = "skip_not_eligible"


@dataclass(slots=True)
class MemoryAdmission:
    """memory_snapshot 准入判定结果（kind 见模块常量；chars 供 shadow 计数）."""

    kind: str
    labeled: str | None = None
    chars: int = 0


def memory_snapshot_admission(message: Any, *, mem_authorized: bool) -> MemoryAdmission:
    """单条消息准入判定（判定序与原 build 内联逻辑逐字等价）."""
    _md = getattr(message, "metadata", None) or {}
    if _md.get("resolved_episode_ref"):
        return MemoryAdmission(SKIP_RESOLVED_EPISODE)
    if _md.get("injection_kind") != "memory_snapshot":
        return MemoryAdmission(SKIP_NOT_MEMORY)
    if not mem_authorized:
        return MemoryAdmission(
            SKIP_UNAUTHORIZED, chars=len(str(getattr(message, "content", "") or ""))
        )
    _c = str(getattr(message, "content", "") or "")
    if not _c.strip():
        return MemoryAdmission(SKIP_BLANK)
    # snapshot 自身已有 outer appendix；嵌入 decision packet 时去掉 outer
    # notice（避免一个 appendix 内重复仲裁声明）；授权投影经 eligibility
    # 注册槽显式校验（memory_authorized），非 allowlist 外旁路。
    _stripped = strip_program_appendix_notice(_c)
    _mem_layer = dynamic_prompt_layer(_stripped, slot_kind="memory_authorized")
    if _mem_layer is None:
        return MemoryAdmission(SKIP_NOT_ELIGIBLE)
    return MemoryAdmission(
        ADMIT,
        labeled=ensure_semantic_label(_stripped, _mem_layer, slot_kind="memory_authorized"),
        chars=len(_stripped),
    )
