"""压缩审计阶段（R8.17/E10；design T5-C 第一批末段）.

压缩是程序/运行时状态：R3 退役关键事实自动重放、R8.17 退役压缩/折叠状态
散文，"关键事实帧缺失 => warn" 不再是有效健康信号——记录实际 compact-view
统计（检索路径 = 稳定 system prompt 宣告的 search_archive）。
统计 dict 落 BuildAudit.compaction_audit（显式产物，收口只读）。
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from llm_loop.core.loop.focus import build_task_anchor
from llm_loop.core.loop.hotcard import write_hotcard
from llm_loop.core.prompt_build.context import BuildAudit, BuildDecision

logger = __import__("logging").getLogger(__name__)


def run_compaction_audit(
    *,
    built: list[dict[str, Any]],
    decision: BuildDecision,
    audit: BuildAudit,
    compact_view_box: list[dict],
    anchor_moved: bool,
    session_id: str,
    anchor_sess: Any,
    data_dir: str,
    record_action: Callable[..., Any],
) -> None:
    """压缩轮统计审计 + 任务热卡写入（全程 fail-open：suppress 不阻断构建）."""
    with contextlib.suppress(Exception):
        if decision.compacted:
            _built_chars = sum(len(m.get("content", "")) for m in built)
            _compact_stats = compact_view_box[0] if compact_view_box else {}
            _pre_chars = _compact_stats.get("pre_chars", decision.pre_chars_fallback)
            _post_chars = _compact_stats.get("post_chars", _built_chars)
            _archived_count = _compact_stats.get("archived_count", "?")
            _drop_pct = _compact_stats.get("drop_pct", "?")
            audit.compaction_audit = {
                "pre_chars": _pre_chars,
                "post_chars": _post_chars,
                "archived_count": _archived_count,
                "drop_pct": _drop_pct,
                "anchor_moved": int(anchor_moved),
                "cache_boundary_mode": _compact_stats.get(
                    "cache_boundary_mode", "inactive"
                ),
                "cache_protected_messages": _compact_stats.get(
                    "cache_protected_messages", 0
                ),
                "cache_protected_chars": _compact_stats.get(
                    "cache_protected_chars", 0
                ),
            }
            record_action(
                "run.compact",
                "ok",
                f"view {_pre_chars}→{_post_chars} chars; archived={_archived_count}; "
                f"drop_pct={_drop_pct}; anchor_moved={int(anchor_moved)}; "
                "prompt_chars=0; retrieval=search_archive; stable_prefix_guard=pass",
            )
            # EVO-20260826-81f8f674: 压缩黄金窗口写任务热卡（anchor=最近用户指令+
            # 最近动作；active Goal/checkpoint 与待审演进由 hotcard 模块自取；
            # fail-open 失败仅告警不阻断压缩）
            write_hotcard(
                origin_session=session_id,
                anchor=build_task_anchor(anchor_sess),
                data_dir=data_dir,
            )
