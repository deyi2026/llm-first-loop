"""EVO-20260818 cache_window_converge: 窗口感知预算与载荷校验测试（spec §5.5.1-8，grill-me Q18）.

覆盖: _effective_history_budget（显式 operator/provider cap + 当前模型物理窗口/output reserve）。
实际 provider overflow 的恢复由 overflow lifecycle 独立测试。
"""

from types import SimpleNamespace

from llm_loop.core.loop.engine_services.routing import RoutingService


class _Spec:
    history_budget_chars = None
    context = 131072


class _Registry:
    providers = {"test": _Spec()}


class _Pool:
    registry = _Registry()


class _DummyRouting(RoutingService):
    """免装配 routing 服务（仅测预算/载荷函数；W4-02b 起自托管 _host）."""

    def __init__(self, global_budget: int | None = 1000000, ctx: int | None = 131072):
        self.runtime = None
        self.settings = SimpleNamespace(history_max_chars=global_budget)
        self.llm_pool = _Pool()
        self._ctx = ctx
        self._host = self  # W4-02b: RoutingService 宿主面 = 本假对象

    def _current_context_limit(self, model_label: str) -> int | None:
        return self._ctx

    def _runtime_history_budget(self) -> int:
        # Unconfigured path deliberately returns a tiny compatibility value to
        # prove RoutingService no longer treats this diagnostic as a hidden cap.
        return self.settings.history_max_chars or 1234


def test_effective_budget_clamped_to_window():
    """1M 全局预算 + 131K 窗口 → 只按真实输入安全边界收紧。

    2026-08-24 估算校准（拷问产出）: _CHARS_PER_TOKEN_EST 2 → 0.6（实测大上下文
    1.676 tok/char）。2026-09-04 agency-first 修正移除独立 0.5 历史启发式：
    131072×0.9×0.6 = 70778 字符；该值用于历史预算规划，不是 provider 前硬拒绝器。
    """
    r = _DummyRouting(global_budget=1000000, ctx=131072)
    assert r._effective_history_budget("test/m") == 70778


def test_unconfigured_global_budget_uses_current_model_window_not_legacy_cap():
    """history_max_chars=None → 当前路由模型窗口是 authoritative budget。"""
    r = _DummyRouting(global_budget=None, ctx=1_000_000)
    assert r._effective_history_budget("test/m") == 540_000
    detail = r._effective_history_budget_detail("test/m")
    assert detail["configured_global_budget"] is None
    assert detail["effective_budget"] == 540_000
    assert detail["limited_by"] == "model_window"


def test_unconfigured_budget_expands_when_session_switches_to_larger_window():
    """未配置 cap 时，小窗→大窗必须可扩容，不能冻结为启动模型预算。"""
    r = _DummyRouting(global_budget=None, ctx=131072)
    assert r._effective_history_budget("test/m") == 70778
    r._ctx = 1_000_000
    assert r._effective_history_budget("test/m") == 540_000


def test_explicit_global_budget_still_caps_large_window():
    """operator 显式 HISTORY_MAX_CHARS 仍是硬意图，不因大窗口被忽略。"""
    r = _DummyRouting(global_budget=160_000, ctx=1_000_000)
    assert r._effective_history_budget("test/m") == 160_000


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


def test_effective_budget_provider_input_token_cap_is_distinct_from_physical_context():
    """184K input / 16K output is an operational cap; physical context remains factual."""

    class _InputCapModel:
        max_input_tokens = None
        max_tokens = None

    class _InputCapSpec:
        history_budget_chars = None
        max_input_tokens = 184_000
        max_tokens = 16_000
        models = {"m": _InputCapModel()}

    class _InputCapRegistry:
        providers = {"cloud": _InputCapSpec()}

    class _InputCapPool:
        registry = _InputCapRegistry()

    r = _DummyRouting(global_budget=None, ctx=1_000_000)
    r.llm_pool = _InputCapPool()
    detail = r._effective_history_budget_detail("cloud/m")
    assert detail["input_token_budget"] == 184_000
    assert detail["allowed_input_tokens"] == 184_000
    assert detail["effective_budget"] == 110_400  # 184K tokens × 0.6 chars/token
    assert detail["limited_by"] == "input_token_budget"


def test_physical_window_wins_over_requested_184k_input_cap():
    """A 65,536-token local runtime must not be advertised/executed as 184K input."""

    class _LocalModel:
        max_input_tokens = None
        max_tokens = None

    class _LocalSpec:
        history_budget_chars = None
        max_input_tokens = 184_000
        max_tokens = 16_000
        models = {"m": _LocalModel()}

    class _LocalRegistry:
        providers = {"local": _LocalSpec()}

    class _LocalPool:
        registry = _LocalRegistry()

    r = _DummyRouting(global_budget=None, ctx=65_536)
    r.llm_pool = _LocalPool()
    detail = r._effective_history_budget_detail("local/m")
    assert detail["input_token_budget"] == 184_000
    assert detail["allowed_input_tokens"] == 49_536  # 65,536 - 16,000 output reserve
    assert detail["effective_budget"] == 29_721
    assert detail["limited_by"] == "model_window"


def test_tool_schema_is_reserved_inside_total_input_budget_without_semantic_tool_filtering():
    budget_info = {"model_window_budget": 110_400}
    assert RoutingService.reserve_tool_schema_from_history_budget(
        110_400, budget_info, 20_639
    ) == 89_761
    # A stricter explicit history cap remains authoritative; tool reservation must not
    # expand or otherwise rewrite it.
    assert RoutingService.reserve_tool_schema_from_history_budget(
        50_000, budget_info, 20_639
    ) == 50_000
    # Unknown physical/input-token capacity preserves legacy behavior rather than
    # inventing a new cap.
    assert RoutingService.reserve_tool_schema_from_history_budget(
        50_000, {}, 20_639
    ) == 50_000
