"""EVO-20260818 cache_window_converge: 窗口感知预算与载荷校验测试（spec §5.5.1-8，grill-me Q18）.

覆盖: _effective_history_budget（M54: min(全局, context×2×0.5) + provider 预算收紧）、
_check_context_fit（M53: 超限载荷拒绝不发送——豁免配置切小窗口模型时不 provider 400）。
"""

from types import SimpleNamespace

from llm_loop.core.loop.routing import _RoutingMixin


class _Spec:
    history_budget_chars = None
    context = 131072


class _Registry:
    providers = {"test": _Spec()}


class _Pool:
    registry = _Registry()


class _DummyRouting(_RoutingMixin):
    """免装配 routing mixin（仅测预算/载荷函数）."""

    def __init__(self, global_budget: int = 1000000, ctx: int | None = 131072):
        self.runtime = None
        self.settings = SimpleNamespace(history_max_chars=global_budget)
        self.llm_pool = _Pool()
        self._ctx = ctx

    def _current_context_limit(self, model_label: str) -> int | None:
        return self._ctx

    def _runtime_history_budget(self) -> int:
        return self.settings.history_max_chars


def test_effective_budget_clamped_to_window():
    """1M 豁免 + 131K 窗口 → effective = min(1M, 131072×0.6×0.5) = 39321 字符.

    2026-08-24 估算校准（拷问产出）: _CHARS_PER_TOKEN_EST 2 → 0.6（实测大上下文
    1.676 tok/char）——窗口感知预算随估算同步收紧（131072×2×0.5=131072 → 39321）。
    """
    r = _DummyRouting(global_budget=1000000, ctx=131072)
    assert r._effective_history_budget("test/m") == 39321


def test_effective_budget_unknown_window_with_pool():
    """有 pool 且窗口未知（ctx=None）→ 8K 保守兜底（M53: 防小窗口模型必超限）.

    零回归路径（无 pool → 全局预算）由 test_model_aware_budget::test_no_pool_zero_regression 覆盖。
    """
    r = _DummyRouting(global_budget=1000000, ctx=None)
    assert r._effective_history_budget("test/m") == 8000


def test_effective_budget_provider_cap():
    """provider 级 history_budget_chars 收紧（本地慢模型 prefill 优化）."""

    class _SpecCap:
        history_budget_chars = 12000
        context = 131072

    class _RegCap:
        providers = {"local": _SpecCap()}

    class _PoolCap:
        registry = _RegCap()

    r = _DummyRouting(global_budget=1000000, ctx=131072)
    r.llm_pool = _PoolCap()
    assert r._effective_history_budget("local/m") == 12000


def test_check_context_fit_rejects_overflow():
    """超限载荷 → 拒绝文案（不发送，无 provider 400）."""
    big = "x" * 300_000  # 300K 字符 ≈ 150K tokens > 131072×0.9（安全边距后）
    msgs = [{"role": "user", "content": big}]
    refusal = _RoutingMixin._check_context_fit(msgs, [], 131072, "test/m")
    assert refusal is not None
    assert "[上下文超限]" in refusal
    assert "131072" in refusal


def test_check_context_fit_allows_within():
    """未超限 → None（放行）."""
    msgs = [{"role": "user", "content": "hi" * 1000}]
    assert _RoutingMixin._check_context_fit(msgs, [], 131072, "test/m") is None


def test_check_context_fit_accounts_max_tokens_output_budget():
    # EVO-20260818: 输出预算占用窗口——local 131K + 16K 输出时允许输入须扣减
    # 2026-08-24 估算校准后（0.6 chars/token）: 边界字符 = (131072-16384)×0.6 ≈ 68.8K 字符
    big = 'x' * 240_000  # est 400K tokens >> 窗口——必拒绝
    msgs = [{'role': 'user', 'content': big}]
    refusal = _RoutingMixin._check_context_fit(msgs, [], 131072, 'local/m', max_tokens=16384)
    assert refusal is not None, '240K 字符载荷（est 400K tokens）超 131K 窗口——应拒绝'
    # 69.5K 字符 ≈ 115.8K tokens（0.6 估算）: 无 max_tokens 放行（≤0.9 边距 117965），
    # +16K 输出扣减后（≤114688）拒绝——验证"输出预算占用窗口"扣减语义
    msgs3 = [{'role': 'user', 'content': 'x' * 69_500}]
    assert _RoutingMixin._check_context_fit(msgs3, [], 131072, 'test/m') is None
    assert _RoutingMixin._check_context_fit(msgs3, [], 131072, 'local/m', max_tokens=16384) is not None
    # 无 max_tokens（默认 0）→ 行为不变（0.9 边距）
    assert _RoutingMixin._check_context_fit(msgs, [], 131072, 'test/m') is not None
