"""M4（`T-M4-1` / `T-M4-2`）：说话期间暂缓副作用 + 外部幂等键与不明结果核对测试。

> **不进首版验收**（`RTM-EVD-05`）；不倒算首版只读能力。
覆盖 RTM：TOL-14/15/07/08。
"""

from __future__ import annotations

import pytest

from llm_loop.realtime.side_effect_gate import (
    EffectClass,
    EffectRequest,
    ExternalIdempotencyRegistry,
    GateDecision,
    IdempotencyDeclaration,
    IdempotencySource,
    ReconcileOutcome,
    SideEffectGate,
    UnresolvedReconciler,
)


def _request(effect_class: EffectClass, *, target: str = "file:/tmp/a", call_key: str = "c1") -> EffectRequest:
    return EffectRequest(
        session_id="s1", effect_class=effect_class, target_key=target, call_key=call_key
    )


class TestSideEffectGate:
    def test_read_only_allowed_while_speaking(self):
        gate = SideEffectGate()
        gate.set_speaking("s1", True)
        assert gate.admit(_request(EffectClass.READ_ONLY)) is GateDecision.ALLOW

    def test_write_deferred_while_speaking(self):
        gate = SideEffectGate()
        gate.set_speaking("s1", True)
        assert gate.admit(_request(EffectClass.WRITE)) is GateDecision.DEFERRED
        assert len(gate.pending_for("s1")) == 1

    def test_write_allowed_when_not_speaking(self):
        gate = SideEffectGate()
        assert gate.admit(_request(EffectClass.WRITE)) is GateDecision.ALLOW

    def test_drain_after_speaking_returns_precise_targets(self):
        gate = SideEffectGate()
        gate.set_speaking("s1", True)
        gate.admit(_request(EffectClass.WRITE, target="file:a"))
        gate.admit(_request(EffectClass.WRITE, target="file:b"))
        gate.set_speaking("s1", False)
        drained = gate.drain("s1")
        assert [r.target_key for r in drained] == ["file:a", "file:b"]
        assert gate.pending_for("s1") == ()

    def test_cancel_pending_only_precise_target(self):
        gate = SideEffectGate()
        gate.set_speaking("s1", True)
        gate.admit(_request(EffectClass.WRITE, target="file:a"))
        gate.admit(_request(EffectClass.WRITE, target="file:b"))
        assert gate.cancel_pending("s1", target_key="file:a") == 1
        assert [r.target_key for r in gate.pending_for("s1")] == ["file:b"]

    def test_read_only_not_generalized_as_write_safety(self):
        # 只读放行不意味着写类也放行（明确分列）
        gate = SideEffectGate()
        gate.set_speaking("s1", True)
        assert gate.admit(_request(EffectClass.READ_ONLY)) is GateDecision.ALLOW
        assert gate.admit(_request(EffectClass.WRITE)) is GateDecision.DEFERRED


class TestExternalIdempotencyRegistry:
    def test_declare_and_lookup(self):
        registry = ExternalIdempotencyRegistry()
        decl = registry.declare(
            IdempotencyDeclaration(external_key="ext-1", call_key="call-1", source=IdempotencySource.EXTERNAL)
        )
        assert decl.call_key == "call-1"
        assert registry.lookup("ext-1").call_key == "call-1"

    def test_conflicting_rebind_rejected(self):
        registry = ExternalIdempotencyRegistry()
        registry.declare(IdempotencyDeclaration(external_key="ext-1", call_key="call-1"))
        with pytest.raises(ValueError):
            registry.declare(IdempotencyDeclaration(external_key="ext-1", call_key="call-2"))

    def test_unknown_key_lookup(self):
        assert ExternalIdempotencyRegistry().lookup("nope") is None


class TestUnresolvedReconciler:
    def test_probe_resolves_succeeded(self):
        reconciler = UnresolvedReconciler()
        assert (
            reconciler.reconcile("call-1", probe=lambda _: ReconcileOutcome.SUCCEEDED)
            is ReconcileOutcome.SUCCEEDED
        )

    def test_no_fact_remains_unknown_and_never_blindly_retries(self):
        calls: list[str] = []

        def probe(call_key: str) -> ReconcileOutcome | None:
            calls.append(call_key)
            return None

        result = UnresolvedReconciler().reconcile("call-1", probe=probe)
        assert result is ReconcileOutcome.STILL_UNKNOWN
        assert calls == ["call-1"]  # 只核对一次，不重复盲派

    def test_probe_can_resolve_not_executed(self):
        assert (
            UnresolvedReconciler().reconcile("call-1", probe=lambda _: ReconcileOutcome.NOT_EXECUTED)
            is ReconcileOutcome.NOT_EXECUTED
        )
