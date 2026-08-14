"""D4 pre-step 过滤钩子（design.md §2.2.2-D / spec §5.4）.

在 EventStore.append 入口插入钩子链（filter/desensitize/transform），
fail-open 不阻断事件写入；过滤后不可逆，replay 报告标注处理统计。

- 钩子链默认空 → 零行为零回归
- filter 判定丢弃返回 None + 审计标记
- desensitize 对目标字段路径执行脱敏
- transform 对目标字段路径执行转换
- 钩子执行异常 → fail-open 写原始事件 + 审计标注
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_HOOK_TIMEOUT_MS = 5  # 钩子链超时阈值（spec §5.4.3-3）


@dataclass
class HookAudit:
    """钩子审计记录（spec §6.3）.

    event_meta 仅含元信息 {event_id, session_id, type, ts} 不含原始 payload 敏感内容。
    """

    hook_name: str
    action_type: str  # filter/desensitize/transform
    event_meta: dict
    reason: str = ""
    transformed_from: str = ""
    fail_open: bool = False


@dataclass
class FilterRule:
    """过滤规则：匹配条件 + 动作（drop/keep）."""

    match: dict  # 匹配条件（字段路径 → 期望值）
    action: str = "drop"  # "drop" / "keep"


@dataclass
class DesensitizeRule:
    """脱敏规则：目标字段 + 方法."""

    target_fields: list[str]  # 字段路径（如 ["payload", "content"]）
    method: str = "mask"  # "mask" / "replace" / "delete"
    replacement: str = "***"


@dataclass
class TransformRule:
    """转换规则：目标字段 + 转换函数."""

    target_fields: list[str]
    transform_fn: Callable[[Any], Any]
    rule_name: str = ""  # 计入 transformed_from


class HookRegistry:
    """钩子注册表（按优先级注册，spec §5.4.1-1）."""

    def __init__(self) -> None:
        self._hooks: list[dict] = []  # [{name, priority, action_type, rule}]

    def register(
        self, name: str, priority: int, action_type: str, rule: Any
    ) -> None:
        """注册钩子（priority 升序执行，同优先级按注册顺序稳定排序）."""
        self._hooks.append(
            {"name": name, "priority": priority, "action_type": action_type, "rule": rule}
        )

    def unregister(self, name: str) -> None:
        """注销钩子."""
        self._hooks = [h for h in self._hooks if h["name"] != name]

    def chain(self) -> HookChain:
        """构建执行链."""
        sorted_hooks = sorted(self._hooks, key=lambda h: h["priority"])
        return HookChain(sorted_hooks)

    def names(self) -> list[str]:
        return [h["name"] for h in self._hooks]


class HookChain:
    """钩子执行链（按 priority 升序执行 filter/desensitize/transform）."""

    def __init__(self, hooks: list[dict]) -> None:
        self._hooks = hooks

    def process(self, event: Any) -> tuple[Any | None, list[HookAudit]]:
        """处理事件 → (处理后事件 | None, 审计记录列表).

        - 钩子链默认空 → 返回 (event, []) 零行为
        - filter 丢弃 → 返回 (None, [audit])
        - desensitize/transform → 返回 (处理后事件, [audit])
        - 钩子异常 → fail-open 写原始事件 + 审计标注
        """
        if not self._hooks:
            return event, []

        audits: list[HookAudit] = []
        current = event
        meta = self._event_meta(event)

        for hook in self._hooks:
            try:
                result = self._exec_hook(hook, current, meta, audits)
                if result is None:
                    return None, audits
                current = result
            except Exception as exc:  # noqa: BLE001 — fail-open
                logger.warning("钩子执行异常（fail-open）: %s: %s", hook["name"], exc)
                audits.append(
                    HookAudit(
                        hook_name=hook["name"],
                        action_type=hook["action_type"],
                        event_meta=meta,
                        reason=f"异常: {exc}",
                        fail_open=True,
                    )
                )
        return current, audits

    def _exec_hook(
        self, hook: dict, event: Any, meta: dict, audits: list[HookAudit]
    ) -> Any | None:
        """执行单个钩子."""
        name = hook["name"]
        action_type = hook["action_type"]
        rule = hook["rule"]

        if action_type == "filter":
            if self._match_filter(event, rule):
                audits.append(
                    HookAudit(hook_name=name, action_type="filter", event_meta=meta, reason="matched")
                )
                return None
            return event

        if action_type == "desensitize":
            new_event = self._desensitize(event, rule)
            audits.append(
                HookAudit(hook_name=name, action_type="desensitize", event_meta=meta)
            )
            return new_event

        if action_type == "transform":
            new_event = self._transform(event, rule)
            audits.append(
                HookAudit(
                    hook_name=name,
                    action_type="transform",
                    event_meta=meta,
                    transformed_from=rule.rule_name,
                )
            )
            return new_event

        return event

    @staticmethod
    def _event_meta(event: Any) -> dict:
        """提取事件元信息（不含原始 payload 敏感内容，spec §6.3-3）."""
        return {
            "event_id": getattr(event, "event_id", ""),
            "session_id": getattr(event, "session_id", ""),
            "type": getattr(event, "type", ""),
            "ts": getattr(event, "ts", ""),
        }

    @staticmethod
    def _match_filter(event: Any, rule: FilterRule) -> bool:
        """检查事件是否匹配过滤条件."""
        for path, expected in rule.match.items():
            value = HookChain._get_field(event, path)
            if value != expected:
                return False
        return True

    @staticmethod
    def _desensitize(event: Any, rule: DesensitizeRule) -> Any:
        """对目标字段执行脱敏."""
        from llm_loop.event_log.model import Event

        payload = dict(event.payload)
        for field_path in rule.target_fields:
            key = field_path.split(".")[-1]
            if key in payload:
                if rule.method == "delete":
                    del payload[key]
                elif rule.method == "replace":
                    payload[key] = rule.replacement
                else:  # mask
                    val = str(payload[key])
                    payload[key] = rule.replacement if val else val
        return Event(
            event_id=event.event_id,
            session_id=event.session_id,
            seq=event.seq,
            type=event.type,
            ts=event.ts,
            payload=payload,
        )

    @staticmethod
    def _transform(event: Any, rule: TransformRule) -> Any:
        """对目标字段执行转换."""
        from llm_loop.event_log.model import Event

        payload = dict(event.payload)
        for field_path in rule.target_fields:
            key = field_path.split(".")[-1]
            if key in payload:
                payload[key] = rule.transform_fn(payload[key])
        return Event(
            event_id=event.event_id,
            session_id=event.session_id,
            seq=event.seq,
            type=event.type,
            ts=event.ts,
            payload=payload,
        )

    @staticmethod
    def _get_field(event: Any, path: str) -> Any:
        """按路径获取字段值（如 'type' / 'payload.content'）."""
        parts = path.split(".")
        value: Any = event
        for part in parts:
            value = value.get(part) if isinstance(value, dict) else getattr(value, part, None)
            if value is None:
                return None
        return value
