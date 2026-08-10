"""故障可自愈性分类器 FaultClassifier（design.md §5.1.1 / FR-AUTO-SELFHEAL-01/02）.

将程序故障按（组件 + 异常类型）确定性映射为可自愈性分类 + 可修复行动建议。
无 LLM 往返、无额外成本、如实可验证（程序只提供信息，是否修复由 LLM 决策）。
未命中 → 默认分类（healable=False + 如实标注），不误导。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FaultClassification:
    """故障可自愈性分类结果（如实标注，不误导）."""

    healable: bool  # True=可自愈（AI 可尝试修复）/ False=不可自愈（建议人工介入）
    category: str  # 分类键
    suggested_actions: tuple[str, ...] = field(
        default_factory=tuple
    )  # 可修复行动建议（引用修正工具名）
    note: str = ""  # 如实说明（如"需人工介入：数据损坏不可自动恢复"）


# ── 分类映射表（确定性常量，收敛于本文件）──
# key: (component, error_type) → (healable, category, suggested_actions, note)
_CLASSIFICATION_TABLE: dict[tuple[str, str], tuple[bool, str, tuple[str, ...], str]] = {
    # ── 可自愈：瞬态/可重试/可重载 ──
    ("llm", "LLMTimeoutError"): (
        True,
        "transient_timeout",
        ("retry_tool", "refresh_config"),
        "瞬态超时：可重试 LLM 调用或重载配置",
    ),
    ("llm", "LLMNetworkError"): (
        True,
        "transient_network",
        ("retry_tool", "refresh_config"),
        "瞬态网络：可重试 LLM 调用（网络可能已恢复）",
    ),
    ("tool", "TimeoutError"): (
        True,
        "tool_timeout",
        ("retry_tool", "adjust_strategy"),
        "工具超时：可重试或调整超时参数",
    ),
    ("memory", "OSError"): (
        True,
        "storage_io",
        ("retry_tool", "recover_state"),
        "存储 IO 故障：可重试或尝试恢复存储状态",
    ),
    ("session", "OSError"): (
        True,
        "storage_io",
        ("retry_tool", "recover_state"),
        "会话存储 IO 故障：可重试（磁盘可能临时不可写）",
    ),
    ("archive", "OSError"): (
        True,
        "storage_io",
        ("retry_tool", "recover_state"),
        "压缩档案 IO 故障：可重试",
    ),
    ("config", "ValueError"): (
        True,
        "config_reload",
        ("refresh_config",),
        "配置异常：可重载配置",
    ),
    # ── 不可自愈：数据损坏/需人工介入 ──
    ("memory", "json.JSONDecodeError"): (
        False,
        "data_corruption",
        (),
        "记忆索引损坏，不可自动恢复，需人工介入重建",
    ),
    ("session", "json.JSONDecodeError"): (
        False,
        "data_corruption",
        (),
        "会话文件损坏，不可自动恢复",
    ),
    ("embedder", "Exception"): (
        False,
        "dependency_failure",
        (),
        "嵌入服务故障，建议人工检查配置（可继续用关键词检索）",
    ),
}


class FaultClassifier:
    """故障类型 → 可自愈性分类 + 可修复行动建议（确定性映射）."""

    def classify(self, component: str, error: Exception) -> FaultClassification:
        """按 (component, error_type) 查映射表分类.

        未命中 → 默认分类（healable=False + 如实标注，不误导）。
        """
        key = (component, type(error).__name__)
        hit = _CLASSIFICATION_TABLE.get(key)
        if hit is None:
            # 尝试宽松匹配: (component, "Exception") 兜底
            hit = _CLASSIFICATION_TABLE.get((component, "Exception"))
        if hit is None:
            return FaultClassification(
                healable=False,
                category="unknown",
                suggested_actions=(),
                note=f"无法判定 '{component}/{type(error).__name__}' 的可自愈性，建议基于现有上下文继续或人工介入",
            )
        healable, category, actions, note = hit
        return FaultClassification(
            healable=healable,
            category=category,
            suggested_actions=actions,
            note=note,
        )
