"""M4：说话期间暂缓副作用派发 + 外部幂等键与不明结果核对（`T-M4-1` / `T-M4-2`）。

> **本模块标注：不进首版验收**（`RTM-EVD-05`、`DESIGN v1.3 §7`）。首版仅支持只读
> `read_file`；此处为**可写扩展**的契约预留与专用测试，**不倒算首版能力**。

对应需求：`RTM-TOL-14/15/07/08`、`RTM-EVD-05`。

- **说话期间暂缓副作用派发**：`WRITE` 类副作用在用户说话期间**暂缓**（不静默执行、不丢弃），
  只读照常；带**精确目标**（`target_key`）；取消边界明确；
- **不把只读结论泛化为「任意工具安全执行」**：`READ_ONLY` 与 `WRITE` 明确分列；
- **外部幂等键**：可声明外部系统的幂等键 → 内部 `call_key` 映射；
- **不明结果核对**：`outcome_unknown` 时**先核外部事实、禁止盲重试**。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class EffectClass(StrEnum):
    """副作用类别：**明确分列**，不相互泛化。"""

    READ_ONLY = "read_only"
    WRITE = "write"


class GateDecision(StrEnum):
    ALLOW = "allow"
    DEFERRED = "deferred"
    DENIED = "denied"


@dataclass(frozen=True)
class EffectRequest:
    session_id: str
    effect_class: EffectClass
    target_key: str
    call_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.effect_class, EffectClass):
            raise TypeError("effect_class must be EffectClass")
        for name in ("session_id", "target_key", "call_key"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")


class SideEffectGate:
    """说话期间暂缓**写类**副作用；只读照常；精确目标；取消边界明确。"""

    def __init__(self) -> None:
        self._speaking: set[str] = set()
        self._pending: dict[str, list[EffectRequest]] = {}

    def set_speaking(self, session_id: str, speaking: bool) -> None:
        if speaking:
            self._speaking.add(session_id)
        else:
            self._speaking.discard(session_id)

    def is_speaking(self, session_id: str) -> bool:
        return session_id in self._speaking

    def admit(self, request: EffectRequest) -> GateDecision:
        """只读照常放行；写类在说话期间**暂缓**（记录精确目标，供说话结束后派发）。"""
        if request.effect_class is EffectClass.READ_ONLY:
            return GateDecision.ALLOW
        if self.is_speaking(request.session_id):
            self._pending.setdefault(request.session_id, []).append(request)
            return GateDecision.DEFERRED
        return GateDecision.ALLOW

    def pending_for(self, session_id: str) -> tuple[EffectRequest, ...]:
        return tuple(self._pending.get(session_id, ()))

    def drain(self, session_id: str) -> tuple[EffectRequest, ...]:
        """说话结束：取出待派发写类副作用（由调用方按精确目标逐项派发）。"""
        return tuple(self._pending.pop(session_id, ()))

    def cancel_pending(self, session_id: str, *, target_key: str) -> int:
        """取消边界：仅取消**精确目标**的待派发写副作用，返回取消数量。"""
        items = self._pending.get(session_id, [])
        kept = [r for r in items if r.target_key != target_key]
        cancelled = len(items) - len(kept)
        if kept:
            self._pending[session_id] = kept
        else:
            self._pending.pop(session_id, None)
        return cancelled


class IdempotencySource(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"


@dataclass(frozen=True)
class IdempotencyDeclaration:
    external_key: str
    call_key: str
    source: IdempotencySource = IdempotencySource.EXTERNAL

    def __post_init__(self) -> None:
        if not self.external_key or not self.call_key:
            raise ValueError("external_key and call_key are required")


class ExternalIdempotencyRegistry:
    """外部系统幂等键 → 内部稳定 `call_key` 映射（`RTM-TOL-15`）。"""

    def __init__(self) -> None:
        self._by_external: dict[str, IdempotencyDeclaration] = {}

    def declare(self, declaration: IdempotencyDeclaration) -> IdempotencyDeclaration:
        existing = self._by_external.get(declaration.external_key)
        if existing is not None and existing.call_key != declaration.call_key:
            raise ValueError("external key already bound to a different call_key")
        self._by_external[declaration.external_key] = declaration
        return declaration

    def lookup(self, external_key: str) -> IdempotencyDeclaration | None:
        return self._by_external.get(external_key)


class ReconcileOutcome(StrEnum):
    SUCCEEDED = "resolved_succeeded"
    FAILED = "resolved_failed"
    NOT_EXECUTED = "resolved_not_executed"
    STILL_UNKNOWN = "still_unknown"


class UnresolvedReconciler:
    """不明结果核对：**先核外部事实、禁止盲重试**（`RTM-TOL-07/08`）。"""

    def reconcile(
        self, call_key: str, *, probe: Callable[[str], ReconcileOutcome | None]
    ) -> ReconcileOutcome:
        observed = probe(call_key)
        if observed is None:
            return ReconcileOutcome.STILL_UNKNOWN  # 未核到事实：不得盲目重派
        return observed
