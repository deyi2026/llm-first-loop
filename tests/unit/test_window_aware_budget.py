"""EVO-20260818 cache_window_converge: 窗口感知预算与载荷校验测试（spec §5.5.1-8，grill-me Q18）.

覆盖: _effective_history_budget（M54: min(全局, context×2×0.5) + provider 预算收紧）、
_check_context_fit（M53: 超限载荷拒绝不发送——豁免配置切小窗口模型时不 provider 400）。
"""

from types import SimpleNamespace

from llm_loop.core.loop.routing import _model_context_env_overrides, _RoutingMixin


class _ModelEntry:
    def __init__(self, context: int | None):
        self.context = context


class _Spec:
    def __init__(self, context: int | None = None):
        self.history_budget_chars = None
        self.models = {"m": _ModelEntry(context)}


class _Registry:
    def __init__(self, spec: _Spec):
        self.providers = {"test": spec}


class _Pool:
    def __init__(self, registry: _Registry):
        self.registry = registry


class _DummyRouting(_RoutingMixin):
    """免装配 routing mixin（仅测预算/载荷函数）.

    不覆写 _current_context_limit——走 mixin 真实现（spec.context → env override
    → resolver），使 EVO-20260811-10dc2533 L1 的 env 覆盖路径可测。
    """

    def __init__(self, global_budget: int = 1000000, ctx: int | None = 131072):
        self.runtime = None
        self.settings = SimpleNamespace(history_max_chars=global_budget)
        self.llm_pool = _Pool(_Registry(_Spec(ctx)))

    def _pool_registry_snapshot(self):
        return self.llm_pool.registry

    def _runtime_history_budget(self) -> int:
        return self.settings.history_max_chars


def test_effective_budget_clamped_to_window():
    """1M 豁免 + 131K 窗口 → effective = min(1M, (131072−2048)×0.6×0.5) = 38707 字符.

    2026-08-24 校准（拷问产出）: _CHARS_PER_TOKEN_EST 2 → 0.6（实测大上下文
    1.676 tok/char）；EVO-20260811-10dc2533 L2: 先扣 completion 预留 2048 再
    分账（131072×0.6×0.5=39321 → 38707，微收紧 ~1.6%）。
    """
    r = _DummyRouting(global_budget=1000000, ctx=131072)
    assert r._effective_history_budget("test/m") == 38707


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
        models = {"m": _ModelEntry(131072)}

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


# ---- EVO-20260811-10dc2533 L1/L2/L3 新增用例 ----


def test_small_window_ratio_applied():
    """L2: 8K 小窗口 → (8192−2048)×0.6×0.3 = 1105 字符（0.3 档保守占比）."""
    r = _DummyRouting(global_budget=1000000, ctx=8192)
    assert r._effective_history_budget("test/m") == 1105


def test_boundary_32k_uses_half_ratio():
    """L2: 32K 恰好非小窗口 → (32768−2048)×0.6×0.5 = 9216 字符（0.5 档）."""
    r = _DummyRouting(global_budget=1000000, ctx=32768)
    assert r._effective_history_budget("test/m") == 9216


def test_env_override_full_label(monkeypatch):
    """L1: MODEL_CONTEXT_OVERRIDE 全限定名优先——131K 窗口被 env 覆盖为 8K."""
    monkeypatch.setenv(
        "MODEL_CONTEXT_OVERRIDE", '{"test/m": 8192}'
    )
    _model_context_env_overrides.cache_clear()
    try:
        r = _DummyRouting(global_budget=1000000, ctx=131072)
        assert r._current_context_limit("test/m") == 8192
        # 预算链联动: 小窗口档生效 1105
        assert r._effective_history_budget("test/m") == 1105
    finally:
        _model_context_env_overrides.cache_clear()


def test_env_override_bare_model(monkeypatch):
    """L1: 裸模型名兜底匹配（未注册 provider 的裸标签）."""
    monkeypatch.setenv("MODEL_CONTEXT_OVERRIDE", '{"my-model": 16384}')
    _model_context_env_overrides.cache_clear()
    try:
        r2 = _DummyRouting(global_budget=1000000, ctx=None)
        got = r2._current_context_limit("other/my-model")
        assert got == 16384
    finally:
        _model_context_env_overrides.cache_clear()


def test_env_override_invalid_json_fail_open(monkeypatch):
    """L1: env JSON 非法 → fail-open 空 override，零回归走注册表."""
    monkeypatch.setenv("MODEL_CONTEXT_OVERRIDE", "{not-json")
    _model_context_env_overrides.cache_clear()
    try:
        r = _DummyRouting(global_budget=1000000, ctx=131072)
        assert r._effective_history_budget("test/m") == 38707
    finally:
        _model_context_env_overrides.cache_clear()


def test_top_k_small_window_dedup():
    """L3: 小窗口 top_k 降档——<32K→2、<8K→1、大窗口/未知零回归."""
    from types import SimpleNamespace

    from llm_loop.core.loop.runtime import _RuntimeParamsMixin

    class _TopK(_RuntimeParamsMixin):
        def __init__(self, ctx):
            self.runtime = None
            self.settings = SimpleNamespace(memory_top_k=5)
            self._ctx = ctx

        def _current_context_limit(self, model_label: str) -> int | None:
            return self._ctx

        def _default_model_label(self, *, registry_snapshot=None) -> str:
            return "test/m"

    assert _TopK(8192)._runtime_memory_top_k() == 2  # 8K → 2
    assert _TopK(4096)._runtime_memory_top_k() == 1  # 4K → 1
    assert _TopK(131072)._runtime_memory_top_k() == 5  # 大窗口 → base 零回归
    assert _TopK(None)._runtime_memory_top_k() == 5  # 窗口未知 → fail-open
