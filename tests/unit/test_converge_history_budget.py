"""EVO-20260818 cache_window_converge: converge_history_budget 单元测试（spec §5.1.1）.

覆盖: 未配置物理窗口诊断/兜底、显式合法值、下限边界、非法输入、
嵌入式路径（不经 factory 的 `_runtime_history_budget` 同源收敛）。
"""

from types import SimpleNamespace

from llm_loop.core.history import converge_history_budget
from llm_loop.core.loop.engine_services.runtime_params import RuntimeParamsService


class _EmbeddedEngine:
    """不经 factory 的嵌入式路径（settings.history_max_chars=None 时运行期自适应）.

    B5-W4-02a: _RuntimeParamsMixin 退役——替身沿 engine 委托壳形态持
    RuntimeParamsService（self._host = 替身实例，_current_context_limit/
    _default_model_label 宿主面桩语义不变）.
    """

    def __init__(self, ctx_limit: int | None) -> None:
        self.runtime = None
        self.settings = SimpleNamespace(history_max_chars=None)
        self._ctx_limit = ctx_limit
        self._runtime_params = RuntimeParamsService(self)

    def _runtime_history_budget(self) -> int:
        return self._runtime_params._runtime_history_budget()

    def _current_context_limit(self, _model_label: str) -> int | None:
        return self._ctx_limit

    def _default_model_label(self) -> str:
        return "test/model"


def test_converge_unset_with_262k_window():
    budget, note = converge_history_budget(None, model_window=262000)
    assert budget == 141480  # 262000 × 0.9 × 0.6
    assert note is None


def test_converge_unset_with_1m_window():
    budget, note = converge_history_budget(None, model_window=1000000)
    assert budget == 540000  # 1M × 0.9 × 0.6；不再硬封 200K
    assert note is None


def test_converge_unset_window_unknown_fallback():
    budget, note = converge_history_budget(None, model_window=None)
    assert budget == 100000
    assert note is not None and "兜底" in note


def test_converge_unset_window_invalid_fallback():
    budget, note = converge_history_budget(None, model_window="oops")
    assert budget == 100000
    assert note is not None and "兜底" in note


def test_converge_unset_window_nonpositive_fallback():
    budget, note = converge_history_budget(None, model_window=0)
    assert budget == 100000
    assert note is not None and "兜底" in note


def test_converge_explicit_within_range():
    budget, note = converge_history_budget(150000, model_window=262000)
    assert budget == 150000
    assert note is None


def test_converge_explicit_large_value_is_plain_operator_cap():
    budget, note = converge_history_budget(500000, model_window=262000)
    assert budget == 500000
    assert note is None  # 不再存在无事实依据的 200K 上限/豁免语义


def test_converge_explicit_at_lower_bound():
    budget, note = converge_history_budget(1000, model_window=262000)
    assert budget == 1000
    assert note is None


def test_converge_explicit_below_lower_bound_fallback():
    budget, note = converge_history_budget(500, model_window=262000)
    assert budget == 100000  # <1000 非法 → 兜底
    assert note is not None and "兜底" in note


def test_converge_explicit_negative_fallback():
    budget, note = converge_history_budget(-1, model_window=262000)
    assert budget == 100000
    assert note is not None and "兜底" in note


def test_converge_explicit_non_int_fallback():
    budget, note = converge_history_budget("abc", model_window=262000)
    assert budget == 100000
    assert note is not None and "兜底" in note


def test_converge_explicit_bool_fallback():
    budget, note = converge_history_budget(True, model_window=262000)  # noqa: E712 — bool 非 int 语义
    assert budget == 100000
    assert note is not None and "兜底" in note


# ── 嵌入式路径（tasks §2.2 补充: 不经 factory，settings=None 时运行期走 converge 同源）──


def test_embedded_runtime_budget_262k_window():
    engine = _EmbeddedEngine(ctx_limit=262000)
    assert engine._runtime_history_budget() == 141480


def test_embedded_runtime_budget_1m_window():
    engine = _EmbeddedEngine(ctx_limit=1000000)
    assert engine._runtime_history_budget() == 540000


def test_embedded_runtime_budget_window_unknown():
    engine = _EmbeddedEngine(ctx_limit=None)
    assert engine._runtime_history_budget() == 100000
