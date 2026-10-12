"""AI 自检闭环端到端测试（spec.md 5.5.1 / design.md §2.4.5 / tasks.md T6.3）.

模拟 AI 行为序列：感知（architecture_status）→ 决策+执行（adjust_strategy）→ 验证（architecture_status 复查）。
断言"感知→决策→执行→验证"全链路可达，闭环不被程序约束打断（AI 自主决策无程序拦截）。
"""

from __future__ import annotations


class TestAISelfCheckLoop:
    def test_perceive_decide_execute_verify_loop(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "ok"}])

        snap1 = engine.status.snapshot()
        assert "pending_actions" in snap1
        assert "context_usage" in snap1
        assert snap1["pending_actions"] is not None

        result = engine.corrections.execute(
            "adjust_strategy", {"strategy": {"max_iterations": 30}}
        )
        assert result.status.value == "success"

        snap2 = engine.status.snapshot()
        assert "pending_actions" in snap2
        assert snap2["pending_actions"] is not None

    def test_loop_not_interrupted_by_program(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "ok"}])

        for val in (30, 40, 50):
            engine.status.snapshot()
            r = engine.corrections.execute(
                "adjust_strategy", {"strategy": {"max_iterations": val}}
            )
            assert r.status.value == "success"
            engine.status.snapshot()

    def test_pending_actions_visible_throughout_loop(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "ok"}])

        for _ in range(3):
            snap = engine.status.snapshot()
            assert "pending_actions" in snap
            pa = snap["pending_actions"]
            assert isinstance(pa, dict)
