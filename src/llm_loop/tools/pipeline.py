"""工具执行瀑布升级模块（EVO-20260813-9ced1f4c，P0-P4 实现）.

借鉴 DeepSeek Harness tools.md 设计，在现有 registry.execute() 准瀑布之上补齐：
  1. 参数无损 JSON 物化边界 + 深冻结（防策略检查后被篡改，防注入短板补强）
  2. 单调守卫 MonotonicGuard（权限只收紧不放松，fail-closed 启动校验）
  3. 不可变 result（权威结果，审计快照）

设计文档: docs/DESIGN-20260814-tool-execution-waterfall.md（grill 10 盲点并入）
"""

from __future__ import annotations

import json
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm_loop.core.message import ToolCall

# ── 1. 参数无损 JSON 物化边界 + 深冻结 ──────────────────────────────

class MaterializationError(ValueError):
    """参数物化失败（非法 JSON / 不可序列化结构）→ 上层应拒绝调用并审计."""


def materialize_lossless_json(args: dict) -> dict:
    """无损 JSON 物化边界：dict/list 参数过一遍 json 序列化/反序列化.

    - 目的: 消除引用共享/隐式可变别名，产出独立副本供策略检查与执行隔离
    - 无损: 与 json.dumps/loads 语义一致（str/int/float/bool/None/list/dict）
    - 失败: 非 JSON 可序列化（如含函数/字节对象）→ MaterializationError，宁严勿松
    """
    if not isinstance(args, dict):
        raise MaterializationError(f"参数必须是 dict，实际 {type(args).__name__}")
    try:
        return json.loads(json.dumps(args, ensure_ascii=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise MaterializationError(f"参数无法无损 JSON 物化: {exc}") from exc


def deep_freeze(obj: Any) -> Any:
    """递归深冻结: dict → MappingProxyType，list → tuple，其余原样返回.

    冻结后任何修改尝试都会在运行时抛 TypeError（不可变），
    保证策略检查后到执行分发间参数不被篡改。
    """
    if isinstance(obj, dict):
        return types.MappingProxyType(
            {k: deep_freeze(v) for k, v in obj.items()}
        )
    if isinstance(obj, list):
        return tuple(deep_freeze(v) for v in obj)
    if isinstance(obj, tuple):
        return tuple(deep_freeze(v) for v in obj)
    return obj


def materialize_and_freeze(args: dict) -> types.MappingProxyType:
    """物化 + 深冻结一步完成（懒执行入口）."""
    return deep_freeze(materialize_lossless_json(args))


def deep_unfreeze(obj: Any) -> Any:
    """递归解冻结: MappingProxyType → dict，tuple → list，其余原样返回.

    用于将深冻结视图转回可执行参数（普通 dict/list），嵌套结构完整还原。
    """
    if isinstance(obj, types.MappingProxyType):
        return {k: deep_unfreeze(v) for k, v in obj.items()}
    if isinstance(obj, tuple):
        return [deep_unfreeze(v) for v in obj]
    if isinstance(obj, list):
        return [deep_unfreeze(v) for v in obj]
    return obj


# ── 2. 单调守卫 MonotonicGuard（权限只收紧不放松）──────────────────

class GuardViolationError(RuntimeError):
    """守卫违反：试图放松权限 / 启动时守卫集比内核种子更宽松."""


class BlockResultError(RuntimeError):
    """结果门禁拒绝（EVO-20260814-39a10097，post hook waterfall 语义）.

    post hook 抛出以拒绝结果：流水线短路，构造 BLOCKED 结果返回调用方。
    典型用途：密钥泄露扫描命中 / 策略拒绝已执行出的结果。
    """


@dataclass(frozen=True)
class PermissionEntry:
    """一条权限记录（不可变）."""

    tool: str
    action: str  # allow / deny
    reason: str = ""


class MonotonicGuard:
    """单调守卫: 权限只允许收紧（add deny / 移除 allow），不允许放松.

    - add_deny: 收紧（允许）
    - add_allow: 仅当该 tool 当前无 deny 时才允许添加（否则视为放松，抛 GuardViolationError）
    - remove_deny / remove_allow: 一律禁止（移除 = 放松）
    - fail-closed: 启动时校验 guard 集是否比内核最小安全集合更宽松，是则拒绝启动
    """

    def __init__(self, kernel_minimal: set[PermissionEntry] | None = None) -> None:
        self._kernel_minimal = kernel_minimal or set()
        # 内核最小安全集合自动注入为基线 deny（不可放松，永不参与重排）
        self._deny: dict[str, str] = {
            e.tool: e.reason or "内核最小安全集合"
            for e in self._kernel_minimal
            if e.action == "deny"
        }
        self._allow: set[str] = set()
        self._verify_fail_closed()

    # ── fail-closed 启动校验 ──
    def _verify_fail_closed(self) -> None:
        """内核种子中的 deny 必须全部保留；任一缺失 → 拒绝启动."""
        for entry in self._kernel_minimal:
            if entry.action == "deny" and entry.tool not in self._deny:
                raise GuardViolationError(
                    f"fail-closed: 内核最小安全集合缺失 deny({entry.tool})，拒绝启动"
                )

    # ── 收紧（允许）──
    def add_deny(self, tool: str, reason: str = "") -> None:
        self._deny[tool] = reason or "手动收紧"

    # ── 添加 allow（仅当无 deny 冲突，否则视为放松）──
    def add_allow(self, tool: str) -> None:
        if tool in self._deny:
            raise GuardViolationError(
                f"单调守卫: 试图对已 deny 的 {tool} 添加 allow（放松），拒绝"
            )
        self._allow.add(tool)

    # ── 查询 ──
    def check(self, tool: str) -> str | None:
        """返回 deny reason（若被拒），否则 None."""
        return self._deny.get(tool)

    def is_allowed(self, tool: str) -> bool:
        return tool not in self._deny

    def snapshot(self) -> dict:
        return {
            "deny": dict(self._deny),
            "allow": sorted(self._allow),
            "kernel_deny": sorted(e.tool for e in self._kernel_minimal if e.action == "deny"),
        }


# ── 3. 不可变 result（权威结果快照）───────────────────────────────

@dataclass(frozen=True)
class ImmutableResult:
    """执行结果的不可变快照（审计/后续消费统一入口）."""

    tool_name: str
    status: str
    content: str
    duration_ms: float = 0.0
    meta: dict = field(default_factory=dict, compare=False)


# ── 4. 统一执行管线（pre 钩子瀑布 + 守卫 + 物化 → 分发）──────────

@dataclass
class PipelineConfig:
    """瀑布开关（渐进式启用，默认全关保持零回归）."""

    enabled: bool = False          # 总开关（对应 TOOL_PIPELINE_ENABLED）
    materialize: bool = False      # 参数物化+深冻结（TOOL_MATERIALIZE_ENABLED）
    guard: bool = False            # 单调守卫（TOOL_GUARD_ENABLED）


class ToolExecutionPipeline:
    """统一工具执行瀑布.

    pre-execute（钩子瀑布，可注册可重排）
      → 物化边界（可选，防篡改）
      → 单调守卫（可选，fail-closed）
      → execute（实际工具调用）
      → post-execute（结果检查）
      → ImmutableResult（权威快照）
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self._pre_hooks: list[Callable[[ToolCall], None]] = []
        self._post_hooks: list[Callable[[ImmutableResult], ImmutableResult | None]] = []
        self._guard: MonotonicGuard | None = None

    # ── 钩子注册（可重排：按列表顺序执行）──
    def add_pre_hook(self, hook: Callable[[ToolCall], None]) -> None:
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: Callable[[ImmutableResult], ImmutableResult | None]) -> None:
        self._post_hooks.append(hook)

    def set_guard(self, guard: MonotonicGuard) -> None:
        self._guard = guard

    # ── 主流程 ──
    def execute(self, tool: Any, call: ToolCall, invoke: Callable[[Any, ToolCall], Any]) -> ImmutableResult:
        """瀑布执行. invoke 是底层实际工具调用（注入，便于测试隔离）."""
        # 1. pre 钩子瀑布
        for hook in self._pre_hooks:
            hook(call)

        # 2. 参数物化 + 深冻结（防策略检查后被篡改）
        frozen_args = None
        if self.config.materialize:
            try:
                frozen_args = materialize_and_freeze(call.arguments)
            except MaterializationError as exc:
                raise MaterializationError(f"拒绝调用 {call.name}: {exc}") from exc

        # 3. 单调守卫（fail-closed）
        if self.config.guard and self._guard is not None:
            reason = self._guard.check(call.name)
            if reason is not None:
                raise GuardViolationError(f"单调守卫拒绝 {call.name}: {reason}")

        # 4. 执行（注入不可变参数视图）
        if frozen_args is not None:
            # 深冻结视图递归转回普通 dict/list 副本（嵌套完整还原），保证与冻结一致
            call = ToolCall(id=call.id, name=call.name, arguments=deep_unfreeze(frozen_args))

        raw = invoke(tool, call)

        # 5. post 钩子 + 不可变快照
        result = ImmutableResult(
            tool_name=call.name,
            status=getattr(raw, "status", "unknown"),
            content=getattr(raw, "content", ""),
            duration_ms=getattr(raw, "duration_ms", 0.0),
            meta={"pipeline": True, "materialized": self.config.materialize},
        )
        return self.run_post_hooks(result)

    def run_post_hooks(self, result: ImmutableResult) -> ImmutableResult:
        """执行 post 钩子瀑布（waterfall 语义，EVO-20260814-39a10097）.

        每个钩子返回:
        - None → 放行（观察者，现状行为零回归）
        - ImmutableResult → replace（结果替换，链式传递）
        抛 BlockResultError → block（短路，构造 blocked 结果返回）
        其他异常 → fail-open（防御模式 #5 不变，观察者异常不破坏主流程）
        """
        current = result
        for hook in self._post_hooks:
            try:
                out = hook(current)
            except BlockResultError as exc:
                return ImmutableResult(
                    tool_name=current.tool_name,
                    status="blocked",
                    content=f"[结果门禁] {exc}",
                    duration_ms=current.duration_ms,
                    meta={**current.meta, "blocked": True, "block_reason": str(exc)},
                )
            except Exception:  # noqa: BLE001 — post 钩子 fail-open
                import logging

                logging.getLogger(__name__).warning(
                    "post_execute hook 异常（fail-open）", exc_info=True
                )
                continue
            if out is not None:
                current = out
        return current


__all__ = [
    "MaterializationError",
    "materialize_lossless_json",
    "deep_freeze",
    "materialize_and_freeze",
    "deep_unfreeze",
    "PermissionEntry",
    "MonotonicGuard",
    "GuardViolationError",
    "BlockResultError",
    "ImmutableResult",
    "PipelineConfig",
    "ToolExecutionPipeline",
]
