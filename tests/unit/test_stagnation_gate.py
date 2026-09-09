"""GPT 审计批次4（2026-08-28）: stagnation evidence-validity gate 测试.

核心: 停滞熔断前校验本 run 是否有成功工具回执（有效证据）——
无证据时报告 unresolved/replan，不得暗示"基于已获得的信息"可作答。
"""

from llm_loop.feedback.honesty import stagnation_feedback


class TestStagnationFeedbackEvidenceGate:
    def test_has_evidence_default_advice(self):
        """默认（有证据）: 保留"基于已获得的信息给出最终回答"建议（向后兼容）."""
        msg = stagnation_feedback("search_files", 5, ["search_files"])
        assert "基于已获得的信息给出最终回答" in msg.content
        assert "[停滞熔断]" in msg.content

    def test_no_evidence_reports_unresolved(self):
        """无证据: 报 unresolved/replan，禁止推测性结论，不暗示已有答案."""
        msg = stagnation_feedback("search_files", 5, ["search_files"], has_evidence=False)
        assert "unresolved" in msg.content
        assert "禁止给出推测性结论" in msg.content
        assert "基于已获得的信息给出最终回答" not in msg.content
        assert "[停滞熔断]" in msg.content  # 事实/原因行保留

    def test_positional_call_compat(self):
        """老调用方式（位置参数三件套）不炸——默认 has_evidence=True."""
        msg = stagnation_feedback("t", 3, [])
        assert "已连续 3 次" in msg.content


class TestEvidenceGateWiring:
    """源码断言（分支适配）: B-G2/P2-A 契约——engine 无 breaker authority.

    origin/main 的硬熔断接线（stagnation.break/_stagnation_should_break）
    与本分支契约冲突，移植时已摘除；本守卫防其回流（回流即回归
    test_stagnation_control_plane / test_loopbreaker_integration）。
    """

    def test_engine_has_no_breaker_wiring(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2] / "src/llm_loop/core/loop/engine.py").read_text(
            encoding="utf-8"
        )
        # 停滞判定不得接线主循环（观测留在 tool_cycle: tool.repeat_observed）
        assert "_stagnation_should_break" not in src
        # 程序终止动作不存在（无 breaker authority）
        assert '"stagnation.break"' not in src

    def test_tool_trace_status_recorded(self):
        from pathlib import Path

        # M53 拆分: 回执落盘移至 tool_cycle._record_single_receipt（T1.3 指纹摘要
        # 与 status 同处）——断言钉拆分后权威位置，不回退巨型 tool_exec。
        src = (
            Path(__file__).resolve().parents[2]
            / "src/llm_loop/core/loop/engine_services/tool_cycle.py"
        ).read_text(encoding="utf-8")
        assert '"status": result.status.value' in src
