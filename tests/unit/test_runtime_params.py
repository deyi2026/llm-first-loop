"""单元测试: RuntimeParams 动态参数（T50 / FR-AUTO-PARAM-01/02/03）."""

from __future__ import annotations

from llm_loop.config import Settings
from llm_loop.core.runtime_params import RuntimeParams


def _settings() -> Settings:
    return Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        max_iterations=20,
        llm_timeout_s=120.0,
        history_max_chars=80000,
    )


def test_dynamic_priority_over_static():
    """动态值（strategy）优先于静态默认（PARAM-01 接线）."""
    s = _settings()
    rp = RuntimeParams(s, strategy={"max_iterations": 30})
    assert rp.max_iterations == 30
    assert rp.llm_timeout_s == 120.0  # 未调整参数用静态


def test_untouched_returns_static():
    """未调整 → 静态兜底（P0 零回归）."""
    s = _settings()
    rp = RuntimeParams(s)
    assert rp.max_iterations == 20
    assert rp.history_max_chars == 80000


def test_hard_cap_applied():
    """越界动态值（>HARD_CAP 500）拒绝生效 → 回退静态默认（防 AI 调参失控）."""
    s = _settings()
    rp = RuntimeParams(s, strategy={"max_iterations": 9999})
    assert rp.max_iterations == 20  # 9999 > 500 无效 → 回退静态


def test_invalid_dynamic_ignored():
    """越界/非法动态值 → 忽略回退静态."""
    s = _settings()
    rp = RuntimeParams(s, strategy={"max_iterations": 2, "timeout_s": 1})
    assert rp.max_iterations == 20  # 2 < min 5 → 回退
    assert rp.llm_timeout_s == 120.0


def test_adjust_count_and_budget():
    """单轮调整频次预算（PARAM-03）."""
    s = _settings()
    rp = RuntimeParams(s)
    rp.set_max_adjust_per_round(2)
    rp.record_adjust_multi({"max_iterations": 30})
    rp.record_adjust_multi({"timeout_s": 200})
    assert rp.can_adjust() is False  # 已用满
    rp.reset_round()
    assert rp.can_adjust() is True


def test_reset_and_persist(tmp_path):
    """reset 回滚 + 持久化可检索（PARAM-06; M18 AA3: 参数不跨进程恢复，历史可检索保留）."""
    s = _settings()
    rp = RuntimeParams(s)
    rp.set_persist_path(tmp_path / "param_adjust_history.jsonl")
    rp.record_adjust_multi({"max_iterations": 40})
    # 持久化文件存在
    assert (tmp_path / "param_adjust_history.jsonl").exists()
    # M18 AA3: restore_last 已移除（hasattr False）
    assert not hasattr(rp, "restore_last")
    # 历史可检索（DFX-MNT-05）: 新实例可读历史但参数不回滚（重启回默认）
    rp2 = RuntimeParams(s)
    rp2.set_persist_path(tmp_path / "param_adjust_history.jsonl")
    assert rp2.max_iterations == 20  # 重启回默认（不跨进程恢复）
    history = rp2.load_history()
    assert len(history) == 1
    assert history[0]["key"] == "max_iterations"
    assert history[0]["after"] == 40
    # reset 回滚
    rp2.record_adjust_multi({"max_iterations": 40})
    rp2.reset("max_iterations")
    assert rp2.max_iterations == 20


def test_current_snapshot():
    s = _settings()
    rp = RuntimeParams(s, strategy={"max_iterations": 35})
    snap = rp.current()
    assert snap["max_iterations"] == 35
    assert snap["timeout_s"] == 120.0
