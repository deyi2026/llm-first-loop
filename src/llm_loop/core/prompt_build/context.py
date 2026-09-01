"""prompt_build 五显式对象 schema（design v1.1 T5-B / §2.3.2）.

骨架阶段（B4-PREP-05）：仅类型声明，零运行时副作用，零 llm_loop 依赖。
依赖方向声明（单向）：context ← stages ← pipeline；cycles=0 恒断言即本包守卫。
字段组自 build.py 实际数据流提炼；各对象读写权限契约见 T5-B 表。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BuildContext:
    """单次 build 全程上下文（构造一次，各阶段只读）."""

    sess: Any  # SessionStore 引用（读取面在各阶段显式收窄后传入）
    resolved_label: str
    provider_id: str
    max_chars: int
    model: str
    emergency_compact: bool
    tool_round_zero: bool
    registry_snapshot: dict[str, Any]
    history_anchors: dict[str, Any]  # sess_anchor 锚点值组


@dataclass(slots=True)
class BuildInputs:
    """resolve_inputs 阶段产出（下游只读）."""

    base_messages: list[Any]  # list(sess.messages) 快照（Message 对象序列，经四过滤器链收窄）
    base_index_by_id: dict[int, int]  # _original_base_index_by_id：id(Message) -> 原始下标
    r6_ingress_truth: Any  # R6 ingress 冻结真值（user_truth 阶段消费）
    memory_msgs: list[Any]  # 记忆注入消息序列（入口参数显式化）
    stale_cleanup: dict[str, Any]  # 过期清理结果集（A-3 语义可指认）
    filtered_indices: list[int] = field(default_factory=list)  # 四过滤器链后原下标重映射段尾值（trace_isolation 消费）


@dataclass(slots=True)
class BuildDecision:
    """各判定阶段增量写入（每项决策含来源引用；A-4 防护决策显式化）."""

    trace_isolation: dict[str, Any] | None = None
    authorization_slots: dict[str, Any] | None = None  # task frontier/goal（A-2）
    injection_eligibility: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None
    cog_freeze: dict[str, Any] | None = None
    consumed_filtering: dict[str, Any] | None = None  # 过滤决策显式可追溯（A-4）
    compacted: bool = False  # P1-01：locals().get("_compressed_this_build") 显式化落位
    history_total_chars: int = -1  # P1-01：locals().get("_history_total") 显式化；-1 = 未测算哨兵（复刻缺省 "?" 语义区分位）

    @property
    def pre_chars_fallback(self) -> int | str:
        """压缩审计缺省值：-1 哨兵（未测算）复刻旧 locals().get 缺省 "?"（P1-01）."""
        return self.history_total_chars if self.history_total_chars >= 0 else "?"


@dataclass(slots=True)
class ProviderProjection:
    """wire_projection 阶段产出（终态；与现行返回值逐字节对应）."""

    system_text: str = ""
    wire_messages: list[dict[str, Any]] = field(default_factory=list)
    anchor_advance: Any = None  # 锚点推进值（替代 anchor_out 容器）
    compacted: bool = False  # 替代 compacted_out


@dataclass(slots=True)
class BuildAudit:
    """全程追加（收口只读）."""

    injections_registry: list[dict[str, Any]] = field(default_factory=list)  # _last_build_injections 旁路
    projection_fingerprint: str = ""
    compaction_audit: dict[str, Any] = field(default_factory=dict)  # L2265-2290 段产出
    decision_trace: list[dict[str, Any]] = field(default_factory=list)  # Decision 时间线视图
