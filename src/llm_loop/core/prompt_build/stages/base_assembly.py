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
from dataclasses import dataclass
from typing import Any

from llm_loop.core.history import stable_digest
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session_snapshot import build_session_snapshot_text

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
