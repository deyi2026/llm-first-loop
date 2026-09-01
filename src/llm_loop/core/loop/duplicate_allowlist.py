"""R8.24-B B-4.2（B-D10）: exact duplicate suppression 收窄白名单.

现状锚点（2026-08-31 复核，与 tasks.md §0 一致）: 全仓无"全局同参第二次
必拦"执行实现——既有路径只有停滞指纹计数（观测，tool_exec._track_stagnation）
与阈值熔断（终止 run），无 per-call 同参拦截。本模块以声明式白名单固化
未来任何同参拦截的边界（若引入）：

- 仅对**可证明确定性/幂等且外部状态未变化**的工具启用同参拦截；
- 轮询/实时查询类合法重复永远放行；
- 全局"同参第二次必拦"取消（B-D10 被弃方案：误伤合法重试）；
- 与停滞计数边界清晰：计数是观测、拦截是执行，互不替代。

空清单 = 基线（零工具启用拦截）；任何新增条目须附幂等性证明注释并单独评审。
"""

from __future__ import annotations

DETERMINISTIC_IDEMPOTENT_TOOLS: frozenset[str] = frozenset(
    # 基线空清单（2026-08-31 评审）: 无工具通过"可证明确定性/幂等"门槛。
    # 候选示例（未启用，逐个证明后才可加入）:
    # - get_tool_schema——纯 schema 查询无副作用，但同属"复核工具"轮询场景，
    #   拦截收益低、误伤复核合法重复风险高，暂不启用。
)


def duplicate_suppression_enabled(tool_name: str) -> bool:
    """声明式判定: 工具是否启用 exact-duplicate 拦截（白名单外一律 False=放行）."""
    return str(tool_name or "").strip() in DETERMINISTIC_IDEMPOTENT_TOOLS
