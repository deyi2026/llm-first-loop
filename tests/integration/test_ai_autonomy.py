"""集成测试: AI 自主闭环（T54 / FR-AUTO 系列端到端）.

FakeLLM 场景: 故障反馈含建议 → AI 调 retry_tool 修复；AI 调 adjust_strategy → 循环按新参数运行；
AI submit_evolution → 落盘。
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall


def test_fault_feedback_with_heal_suggestion(build_test_engine):
    """故障反馈含可修复行动建议（SELFHEAL-01）→ AI 收到后可决策."""
    engine, fake = build_test_engine([{"content": "最终回答。"}])

    # 装配分类器（默认 engine 未装配时手动验证 _fault_feedback）
    from llm_loop.feedback.fault_classifier import FaultClassifier

    engine.fault_classifier = FaultClassifier()  # type: ignore[attr-defined]
    msg = engine._fault_feedback(
        "llm", __import__("llm_loop.llm.errors", fromlist=["LLMTimeoutError"]).LLMTimeoutError("t")
    )  # noqa: SLF001
    assert "可自愈性" in msg.content
    assert "retry_tool" in msg.content  # 建议动作


def test_adjust_strategy_takes_effect_in_loop(build_test_engine):
    """PARAM-01 接线: AI 调 adjust_strategy → 轮数上限按新值生效（核心缺口修复验证）."""
    engine, fake = build_test_engine(
        [
            {
                "tool_calls": [
                    ToolCall(
                        id="c1",
                        name="adjust_strategy",
                        arguments={"strategy": {"max_iterations": 10}},
                    )
                ]
            },
            {
                "tool_calls": [
                    ToolCall(id="c2", name="read_file", arguments={"path": "/nonexistent"})
                ]
            },
            {"content": "回答。"},
        ]
    )
    object.__setattr__(engine.settings, "max_iterations", 20)
    sid = engine.session.create()
    engine.run(sid, "调参")
    # 调整后轮数上限应为 10（动态值）——验证 PARAM-01 接线生效
    assert engine.runtime is not None
    assert engine.runtime.max_iterations == 10  # 调整生效


def test_submit_evolution_tool_in_loop(build_test_engine, tmp_path):
    """AI submit_evolution → 落盘 + 回执（EVOLVE-02）."""
    from llm_loop.introspection.evolution import EvolutionStore

    engine, fake = build_test_engine(
        [
            {
                "tool_calls": [
                    ToolCall(
                        id="c1",
                        name="submit_evolution",
                        arguments={"content": "建议合并记忆检索模块", "impact_scope": "memory/"},
                    )
                ]
            },
            {"content": "已提交演进建议。"},
        ]
    )
    # 装配 evolution_store
    store = EvolutionStore(tmp_path / "data" / "audit")
    engine.correction_ctx.evolution_store = store  # type: ignore[attr-defined]
    sid = engine.session.create()
    result = engine.run(sid, "提交改进建议")
    names = [t["name"] for t in result.tool_calls]
    assert "submit_evolution" in names
    # 落盘可检索
    assert store.search("合并")  # 建议已落盘


def test_evolution_boundary_only_suggest(build_test_engine, tmp_path):
    """EVOLVE-03/04: 涉安全边界 → requires_human（AI 不能执行）."""
    from llm_loop.introspection.evolution import EvolutionStore

    engine, fake = build_test_engine([{"content": "回答。"}])
    store = EvolutionStore(tmp_path / "data" / "audit")
    engine.correction_ctx.evolution_store = store  # type: ignore[attr-defined]
    suggestion = store.submit(content="修改安全边界", impact_scope="safety", session_id="s1")
    assert suggestion.requires_human is True
