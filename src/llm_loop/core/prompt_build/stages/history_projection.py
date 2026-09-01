"""历史投影调用阶段（design T5-C 第二批 / B4-C2-03②）.

P1-10 + R8.5 锚点边界换算（persisted anchor 用原始会话索引，eligibility
过滤收缩 provider 视图——调前换算 forward、调后换算 back，防有效旧锚点
跳过当前任务或孤儿化工具组）+ build_history_messages 一次性大装配调用
（Phase 7 前不动其内部）。box 系 out-params 显式化进产出对象。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from llm_loop.core.episode_history import filtered_anchor_from_original
from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message


@dataclass(slots=True)
class HistoryProjection:
    """历史投影产出（built 视图 + box 系遥测/状态）."""

    built: list[Any] = field(default_factory=list)
    anchor_arg: int = 0
    anchor_box: list[int] = field(default_factory=list)
    compacted_box: list[bool] = field(default_factory=list)
    cache_compacted_box: list[Message] = field(default_factory=list)
    compact_view_box: list[dict] = field(default_factory=list)
    degrade_box: list[dict] = field(default_factory=list)


def run_history_projection(
    *,
    base: list[Any],
    system_prompt: str,
    filtered_indices: list[int],
    sess_anchor: Any,
    prefix_len: int,
    session_id: str,
    max_chars: int | None,
    runtime_history_budget_value: int,
    compact_ratio: float,
    archive_sink: Any,
    settings: Any,
    provider_id: str,
    emergency_compact: bool,
    reasoning_tail: Any,
    r6_ingress_truth: Any,
    registry: Any,
    cache_monitor: Any,
    effective_budget: int,
    progressive_fold_k: int,
) -> HistoryProjection:
    """锚点换算 + build_history_messages 调用（参数语义逐字节原样）."""
    # P1-10 + R8.5: persisted anchor uses original sess.messages indices,
    # while resolved/recovery eligibility filters shrink the provider view.
    # Translate the boundary before build_history_messages and translate it
    # back after compaction; otherwise a valid old anchor can skip the current
    # task or orphan a tool group after resolved messages retire.
    _filtered_sess_anchor = filtered_anchor_from_original(
        filtered_indices, sess_anchor
    )
    anchor_arg = (
        _filtered_sess_anchor + prefix_len if _filtered_sess_anchor > 0 else 0
    )
    anchor_box: list[int] = []
    compacted_box: list[bool] = []
    cache_compacted_box: list[Message] = []
    compact_view_box: list[dict] = []
    degrade_box: list[dict] = []
    built = build_history_messages(
        base,
        system_prompt,
        max_chars=max_chars if max_chars is not None else runtime_history_budget_value,
        compact_ratio=compact_ratio,  # EVO-20260817: 预算分级主动压缩
        session_id=session_id,
        archive_sink=archive_sink,
        # RULE-AI-00: 不再传 summarizer（压缩路径不自动 LLM 摘要，AI 主动触发）
        layer_tool_trim=getattr(
            settings, "tool_trim_enabled", False
        ),  # EVO-20260811-7baa2737: 历史分层降级
        tool_trim_age=getattr(settings, "tool_trim_age", 0),  # R3: 0=自适应
        tool_trim_threshold=getattr(
            settings, "tool_trim_threshold", 8000
        ),  # EVO-A: 降级长度阈值（默认 8000）
        # 2026-08-20 回滚修复: 移除悬空 tool_tail 参数——history.py 的
        # build_history_messages() 不接受该参数（3点基线无此功能，config 恒为 0），
        # 回滚后每次对话 TypeError；参数支持在 backup/20260819-after-3am 分支
        reasoning_tail=reasoning_tail,
        # P1-7/spec §5.3.1-5（2026-08-18 审计断点归因绝对化）: 推送式注入（架构上报/
        # 预算预警/轮数预警/声明提醒/自我评估提醒/快照）一律不进提交视图——不再受
        # provider inject_system_notices 开关影响（原按 provider 放行 → 注入消息转 user
        # 后仍插历史中部 → 前缀断）。AI 感知走 architecture_status 等工具，不依赖注入。
        skip_injected_system=True,
        # P1-10: 窗口锚定
        history_anchor=anchor_arg,
        anchor_out=anchor_box,
        compacted_out=compacted_box,
        # EVO-20260817-9d3e1f2c: 缓存友好压缩——保留锚点头部（前缀命中）只归档中段;
        # EVO-20260818: HEAD_KEEP_RATIO 默认 0.10→0.15；2026-08-25 DeepSeek 生产实测
        # 中段分叉只有“曾作为完整请求端点”的 fixed-head 能稳定复用，因此 DeepSeek
        # 默认提高到 effective budget 的 0.35（其它 provider 仍 0.15）。配合压缩目标
        # 0.5，相当于 fixed-head 最多约占压缩后历史水位 70%，同时保留最近尾部语义。
        # 生产等价直连实测：300K→150K 视图首次压缩命中 71.1%（不含工具schema固定
        # 前缀）；0.30/0.65 档仅57.2%。force 档位 DeepSeek 默认 0.40 / 其它 provider
        # 0.20（L3 拦截强制保留——须高于常规档位，
        # max() 两侧同值会吞掉强制语义，grill-me 2.10）; 0=关闭回到锚点前移行为；env 可调
        # emergency_compact（M53 拒绝逃生）: 强制 head_keep=0——head 保留时锚点不前移
        # （history.py），超限会话历史永不缩小 → 拒绝死循环；锚点前移归档才真正缩小
        # 2026-08-25 中段压缩: progressive fold 重新允许 head_keep。被折中段写入
        # provider级 cache_compacted_for 标记，后续 build 自动过滤，所以无需靠锚点
        # 前移来防重复归档；压缩轮缓存断点从序列开头推到固定头部之后。
        head_keep_chars=(
            0  # emergency_compact 仍保留从头推进的最终逃生语义
            if emergency_compact
            else max(
                int(
                    effective_budget
                    * float(
                        os.environ.get(
                            "HEAD_KEEP_RATIO", "0.35" if provider_id == "deepseek" else "0.15"
                        )
                    )
                ),
                int(
                    effective_budget
                    * float(
                        os.environ.get(
                            "HEAD_KEEP_FORCE_RATIO",
                            "0.40" if provider_id == "deepseek" else "0.20",
                        )
                    )
                )
                if cache_monitor.force_head_keep
                else 0,
            )
        ),
        # fixed-head 占压缩目标水位上限。历史层默认 0.50 保持旧行为；DeepSeek 提到
        # 0.70，允许 0.35×effective_budget 的 head 真正留下（target=.5 时占70%），
        # 仍给最近 tail 约30%目标水位；原子组边界会自然留出更多。env 可显式覆盖调参。
        head_keep_target_ratio=float(
            os.environ.get(
                "HEAD_KEEP_TARGET_RATIO", "0.70" if provider_id == "deepseek" else "0.50"
            )
        ),
        # 2026-08-21 追加式压缩: 归档后追加确定性摘要（APPEND_COMPRESSION=1 启用,
        # 默认关零回归）——任务语义连贯 + 前缀稳定（同归档→同摘要字节→缓存命中）
        _append_summary_enabled=os.environ.get("APPEND_COMPRESSION", "0") == "1",
        # EVO-20260824-54d46549 渐进折叠: PROGRESSIVE_FOLD_K>0 时压缩每次最多折最老 K 个
        # 配对组（平滑曲线 + guard 不 BLOCK + 智力无断崖）；0=一次性大裁（零回归）
        progressive_fold=progressive_fold_k,
        # P0 压缩风暴熔断冻结（2026-08-25）: 冻结期禁压缩/禁锚点前移（前缀字节稳定）
        freeze_compression=cache_monitor.breaker_freeze_compression(
            session_id
        ),
        cache_archive_provider=provider_id,
        cache_compacted_out=cache_compacted_box,
        compact_view_stats=compact_view_box,
        degrade_out=degrade_box,
        require_archive_success=getattr(registry, "evidence_mode", "off") == "enforce",
        preserve_last_human_exact=r6_ingress_truth is not None,
    )
    return HistoryProjection(
        built=built,
        anchor_arg=anchor_arg,
        anchor_box=anchor_box,
        compacted_box=compacted_box,
        cache_compacted_box=cache_compacted_box,
        compact_view_box=compact_view_box,
        degrade_box=degrade_box,
    )
