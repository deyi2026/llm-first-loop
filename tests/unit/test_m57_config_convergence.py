"""M57/M58 配置面收敛 测试（AI 可查可调，替代 env 硬编码约束）.

覆盖:
- RuntimeParams.memory_top_k / extract_interval_msgs 动态优先（strategy 生效）/ 越界回退默认
- adjust_strategy 白名单含 memory_top_k / extract_interval_msgs（可调 + 越界拒绝）
- architecture_status snapshot 展示 runtime_params（注入后可见）
- loop 消费两项参数走 runtime（动态优先）
"""

from __future__ import annotations

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.runtime_params import RuntimeParams
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry


def test_runtime_params_memory_top_k_dynamic_priority(fake_settings):
    """memory_top_k 动态优先（strategy 生效值），未调整回退 settings 默认."""
    runtime = RuntimeParams(fake_settings)
    assert runtime.memory_top_k == fake_settings.memory_top_k  # 默认兜底
    runtime._strategy["memory_top_k"] = 10  # noqa: SLF001 — 测试直接写策略
    assert runtime.memory_top_k == 10


def test_runtime_params_memory_top_k_out_of_range_falls_back(fake_settings):
    """越界动态值校验失败 → 回退默认（不采用）."""
    runtime = RuntimeParams(fake_settings)
    runtime._strategy["memory_top_k"] = 999  # noqa: SLF001 — 超出范围 (1,50)
    assert runtime.memory_top_k == fake_settings.memory_top_k


def test_adjust_strategy_memory_top_k_whitelist():
    """adjust_strategy 白名单含 memory_top_k：可调 + 越界拒绝."""
    ctx = CorrectionContext()
    reg = CorrectionToolRegistry(ctx)
    # 合法
    r = reg.execute("adjust_strategy", {"strategy": {"memory_top_k": 12}})
    assert r.status == ToolResultStatus.SUCCESS
    assert ctx.strategy["memory_top_k"] == 12
    # 越界
    r2 = reg.execute("adjust_strategy", {"strategy": {"memory_top_k": 0}})
    assert r2.status == ToolResultStatus.FAILURE


def test_status_snapshot_runtime_params():
    """architecture_status snapshot 支持注入 runtime_params（M57；未注入向后兼容 None）."""
    from llm_loop.introspection.status import ArchitectureStatusProvider

    status = ArchitectureStatusProvider(audit_dir=None, enabled=True)
    assert status.snapshot()["context_usage"]["runtime_params"] is None

    status.set_runtime_params_fn(lambda: {"max_iterations": 30, "memory_top_k": 12})
    snap = status.snapshot()
    assert snap["context_usage"]["runtime_params"] == {
        "max_iterations": 30,
        "memory_top_k": 12,
    }


def test_loop_consumes_runtime_memory_top_k(build_test_engine, fake_settings):
    """loop 消费 memory_top_k 走 runtime（动态优先；未调整回退 settings）."""
    engine, _ = build_test_engine([])
    assert engine._runtime_memory_top_k() == fake_settings.memory_top_k
    engine.runtime._strategy["memory_top_k"] = 7  # noqa: SLF001 — 测试直接写策略
    assert engine._runtime_memory_top_k() == 7


# ── M58: extract_interval_msgs 白名单扩展 ──


def test_runtime_params_extract_interval_dynamic(fake_settings):
    """extract_interval_msgs 动态优先 + 越界回退默认."""
    default = getattr(fake_settings, "extract_interval_msgs", 20)
    runtime = RuntimeParams(fake_settings)
    assert runtime.extract_interval_msgs == default
    runtime._strategy["extract_interval_msgs"] = 50  # noqa: SLF001 — 合法范围 (5,200)
    assert runtime.extract_interval_msgs == 50
    runtime._strategy["extract_interval_msgs"] = 9999  # noqa: SLF001 — 越界
    assert runtime.extract_interval_msgs == default


def test_adjust_strategy_extract_interval_whitelist():
    """adjust_strategy 白名单含 extract_interval_msgs：可调 + 越界拒绝."""
    ctx = CorrectionContext()
    reg = CorrectionToolRegistry(ctx)
    r = reg.execute("adjust_strategy", {"strategy": {"extract_interval_msgs": 40}})
    assert r.status == ToolResultStatus.SUCCESS
    assert ctx.strategy["extract_interval_msgs"] == 40
    r2 = reg.execute("adjust_strategy", {"strategy": {"extract_interval_msgs": 3}})
    assert r2.status == ToolResultStatus.FAILURE


def test_loop_consumes_runtime_extract_interval(build_test_engine, fake_settings):
    """loop 消费 extract_interval_msgs 走 runtime（动态优先）."""
    default = getattr(fake_settings, "extract_interval_msgs", 20)
    engine, _ = build_test_engine([])
    assert engine._runtime_extract_interval() == default
    engine.runtime._strategy["extract_interval_msgs"] = 60  # noqa: SLF001 — 测试直接写策略
    assert engine._runtime_extract_interval() == 60


# ── M59: retrieve_semantic_top_k 白名单扩展 ──


def test_runtime_params_retrieve_semantic_top_k_dynamic(fake_settings):
    """retrieve_semantic_top_k 动态优先 + 越界回退默认."""
    default = getattr(fake_settings, "retrieve_semantic_top_k", 20)
    runtime = RuntimeParams(fake_settings)
    assert runtime.retrieve_semantic_top_k == default
    runtime._strategy["retrieve_semantic_top_k"] = 35  # noqa: SLF001 — 合法范围 (1,100)
    assert runtime.retrieve_semantic_top_k == 35
    runtime._strategy["retrieve_semantic_top_k"] = 9999  # noqa: SLF001 — 越界
    assert runtime.retrieve_semantic_top_k == default


def test_adjust_strategy_retrieve_semantic_top_k_whitelist():
    """adjust_strategy 白名单含 retrieve_semantic_top_k：可调 + 越界拒绝."""
    ctx = CorrectionContext()
    reg = CorrectionToolRegistry(ctx)
    r = reg.execute("adjust_strategy", {"strategy": {"retrieve_semantic_top_k": 45}})
    assert r.status == ToolResultStatus.SUCCESS
    assert ctx.strategy["retrieve_semantic_top_k"] == 45
    r2 = reg.execute("adjust_strategy", {"strategy": {"retrieve_semantic_top_k": 0}})
    assert r2.status == ToolResultStatus.FAILURE


def test_semantic_retriever_dynamic_top_k_provider():
    """SemanticRetriever.set_top_k_provider 动态生效（未注入用构造值；异常回退）."""
    from llm_loop.memory.retriever import SemanticRetriever

    r = SemanticRetriever(embedder=None, semantic_top_k=20)
    assert r._semantic_top_k() == 20  # 未注入 → 构造值
    r.set_top_k_provider(lambda: 7)
    assert r._semantic_top_k() == 7  # 动态生效
    r.set_top_k_provider(lambda: 0)  # 非法值 → 回退构造值
    assert r._semantic_top_k() == 20
    r.set_top_k_provider(lambda: (_ for _ in ()).throw(RuntimeError("boom")))  # 异常回退
    assert r._semantic_top_k() == 20
