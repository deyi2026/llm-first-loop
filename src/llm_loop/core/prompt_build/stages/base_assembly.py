"""base 装配阶段（design T5-C 第二批 / B4-C2-02）.

前缀装配与稳定段指纹：interop 外部协调注入（RULE-AI-14，memory 之后/
历史之前——服务端缓存命中不受 inbox 影响）、L3 门禁预检（稳定段指纹
不符 → 强制缓存友好压缩，fail-open）、会话状态快照节流尾部追加
（EVO-20260818-8c8791c2：快照不驻留前缀区，前缀字节稳定）。
副作用经显式传参与出口对象收窄：stable_fp/last_snapshot_count 由
调用点回写 self 面。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from llm_loop.core.cache_health import strip_cache_telemetry_lines
from llm_loop.core.history import stable_digest
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt_eligibility import PROGRAM_FINAL_PROTOCOL_BOUNDARY
from llm_loop.core.session_snapshot import build_session_snapshot_text
from llm_loop.feedback.honesty import PROGRAM_FEEDBACK_PREFIXES

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BaseAssemblyResult:
    """base 装配产出（过程值：prefix_len/stable_fp 滚动，base 续投影）."""

    base: list[Any]
    prefix_len: int
    stable_fp: str = ""
    last_snapshot_count: int = 0


def run_base_assembly(
    *,
    base: list[Any],
    system_prompt: str,
    session_id: str,
    sess_message_count: int,
    sess_anchor: Any,
    inject_interop: Callable[..., Any],
    cache_monitor: Any,
    runtime_extract_interval: Callable[[], int],
    memory: Any,
    evolution_store: Any,
    last_snapshot_count: int,
) -> BaseAssemblyResult:
    """interop 注入 + 门禁预检 + 快照节流（产出 prefix_len/stable_fp/base）."""
    result = BaseAssemblyResult(
        base=base, prefix_len=0, last_snapshot_count=last_snapshot_count
    )
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
        result.stable_fp = stable_digest(
            [(m.role, m.content) for m in result.base[: result.prefix_len]]
            + [system_prompt]
        )
        cache_monitor.preflight(session_id, result.stable_fp)
    except Exception:  # noqa: BLE001
        result.stable_fp = ""
    # EVO-20260811-9ccdec97: 会话状态快照节流——每间隔注入状态帧（定位锚点，fail-open）
    # M58 配置面收敛: 间隔走 runtime（动态优先，AI 可调）
    # P1-10: 仅无锚时注入（锚定后快照为推送式注入（已打标被跳过提交）, 且避免锚点换算复杂化）
    # EVO-20260818-8c8791c2: 快照【尾部追加】而非 insert(0)——前缀区只留 system+稳定历史头，
    # 快照内容（消息数/记忆数/演进摘要）每轮变化，驻留前缀区即每轮断前缀（gate_drift_count=12
    # 实证，命中 17%↔98% 间歇）；尾部追加后变化只影响尾部新增段，前缀字节稳定（对齐 memory/interop）
    if sess_anchor == 0:
        try:
            interval = runtime_extract_interval()
            if sess_message_count - result.last_snapshot_count >= interval:
                evo_summary = None
                if evolution_store is not None and hasattr(
                    evolution_store, "summary"
                ):
                    try:
                        s = evolution_store.summary()
                        evo_summary = s if isinstance(s, dict) else None
                    except Exception:
                        evo_summary = None
                snapshot = Message(
                    role="system",
                    content=build_session_snapshot_text(
                        sess_message_count, memory.count(), evo_summary
                    ),
                    source=MessageSource.SYSTEM,
                    metadata={
                        "injected_system": True
                    },  # P1-7: 快照=推送式注入（本地 provider 下不进提交）
                )
                result.base.append(
                    snapshot
                )  # EVO-20260818-8c8791c2: 尾部追加（原 insert(0) 驻留前缀区断前缀）
                # prefix_len 不再 +1（快照不进前缀区——稳定段指纹 base[:prefix_len] 不含动态内容）
                result.last_snapshot_count = sess_message_count
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "会话状态快照注入失败（fail-open）", exc_info=True
            )
    return result


def _tool_round_zero_tail(msgs: list[Message]) -> list[Message]:
    """工具轮极小窗口: 保留【最近用户指令 + 最近完整协议配对组】.

    结构: [user(当前任务), assistant(tool_calls 最后声明), ...其全部 tool 回执]。
    中间轮次（早期配对组）不入载荷——极小窗口本意（任务锚点摘要补偿早期动作）。

    两项硬约束（2026-08-24 实证修复）:
    1. C1 协议: 声明↔回执必须同窗（原固定 base[-2:] 在多回执时截断配对组 → 孤儿回执;
       实证 "声明 3 个工具调用仅 1 条回执缺 2 条"）。
    2. 聊天模板: llama.cpp Qwen 模板要求载荷含 user 消息, 缺 user 直接 500
       "No user query found in messages"（实证 llama-server Qwen3.8 500）——
       故必须带上最近一条 user（任务指令）, 不能只发配对组。
    """
    n = len(msgs)
    if n == 0:
        return msgs
    group_start = -1
    for i in range(n - 1, -1, -1):
        if getattr(msgs[i], "role", "") == "assistant" and getattr(msgs[i], "tool_calls", None):
            group_start = i
            break
    user_idx = -1
    for i in range(n - 1, -1, -1):
        if getattr(msgs[i], "role", "") == "user":
            user_idx = i
            break
    if user_idx >= 0 and group_start >= 0:
        if user_idx >= group_start:
            # 最近 user 已在配对组之后（中断恢复/续跑）→ 整段保留, 不重复前置
            return msgs[group_start:]
        return msgs[user_idx : user_idx + 1] + msgs[group_start:]
    if user_idx >= 0:  # 无配对组 → 从任务指令起（模型可能直接回答）
        return msgs[user_idx:]
    if group_start >= 0:  # 无 user（异常会话）→ 配对组兜底（模板可能拒, 但保协议）
        return msgs[group_start:]
    return msgs[-2:] if n >= 2 else msgs


@dataclass(slots=True)
class ProviderViewScrub:
    """provider 视图预清洗产物（base 序列 + 原始索引重映射）."""

    base: list[Message]
    base_original_indices: list[int]


def scrub_provider_view(
    *,
    base: list[Message],
    base_original_indices: list[int],
    tool_round_zero: bool = False,
) -> ProviderViewScrub:
    """base 提交视图三段预清洗（B4-CLOSE-01 步B；语义原样迁自 build.py）.

    ① 缓存遥测剥离 ② program 协议边界收敛 ③ tool_round_zero 极小窗口；
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
    # 2026-08-21 工具轮零历史（TOOL_ROUND_ZERO_HISTORY=1 / provider 配置）: 工具轮只发
    # system+摘要+最近完整协议配对组（assistant(tool_calls)+全部 tool 回执）——前缀
    # （system+摘要）固定 → KV 命中 → prefill 秒级（本地模型实测 4-13 tokens
    # prefill 仅 0.2-0.8s）。
    # 注意: 保留最近配对组而非固定 -2 条（2026-08-24: 多回执截断会破坏 C1 配对）。
    # R8.10 / P0-B2 supersession: a persisted program final is user-visible storage
    # truth, but its fault/cancel/guard prose has no automatic next-turn authority.
    # Dropping the assistant frame outright would turn user→program-assistant→user into
    # consecutive user roles and can recreate the provider 1210 shape.  Provider view
    # therefore keeps only one byte-stable assistant protocol boundary while retiring
    # all historical program-result detail.  Storage/event truth remains untouched.
    base = [
        (
            replace(m, content=PROGRAM_FINAL_PROTOCOL_BOUNDARY, reasoning_content=None)
            if (
                m.role == "assistant"
                and (
                    (m.metadata or {}).get("answer_origin") == "program"
                    or str(m.content or "").startswith(PROGRAM_FEEDBACK_PREFIXES)
                )
            )
            else m
        )
        for m in base
    ]
    if tool_round_zero:
        _pre_zero_base = base
        _pre_zero_pos = {id(_m): _idx for _idx, _m in enumerate(_pre_zero_base)}
        base = _tool_round_zero_tail(base)
        base_original_indices = [
            base_original_indices[_pre_zero_pos[id(_m)]]
            for _m in base
            if id(_m) in _pre_zero_pos
        ]
    return ProviderViewScrub(base=base, base_original_indices=base_original_indices)
