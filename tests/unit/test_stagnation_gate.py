"""GPT 审计批次4（2026-08-28）: stagnation evidence-validity gate 测试.

核心: 停滞熔断前校验本 run 是否有成功工具回执（有效证据）——
无证据时报告 unresolved/replan，不得暗示"基于已获得的信息"可作答。
"""

from llm_loop.feedback.honesty import stagnation_feedback


class TestStagnationFeedbackEvidenceGate:
    def test_has_evidence_default_advice(self):
        """R8.24-B B-D3 收口后: 有证据 → 纯事实（回执可检索），建议句式取消."""
        msg = stagnation_feedback("search_files", 5, ["search_files"])
        assert "基于已获得的信息给出最终回答" not in msg.content
        assert "历史回执" in msg.content  # 证据事实行在场
        assert "[停滞熔断]" in msg.content

    def test_no_evidence_reports_unresolved(self):
        """无证据: 报 unresolved（事实），不暗示已有答案、无建议性指令."""
        msg = stagnation_feedback("search_files", 5, ["search_files"], has_evidence=False)
        assert "unresolved" in msg.content
        assert "基于已获得的信息给出最终回答" not in msg.content
        assert "[停滞熔断]" in msg.content  # 事实/原因行保留

    def test_positional_call_compat(self):
        """老调用方式（位置参数三件套）不炸——默认 has_evidence=True."""
        msg = stagnation_feedback("t", 3, [])
        assert "已连续 3 次" in msg.content


class TestEvidenceGateWiring:
    """源码断言: 接线钉死（防回退）。"""

    def test_engine_break_gate_wired(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2] / "src/llm_loop/core/loop/engine.py").read_text(
            encoding="utf-8"
        )
        assert '_has_evidence = any(t.get("status") == "success" for t in tool_trace)' in src
        assert "has_evidence=_has_evidence" in src

    def test_tool_trace_status_recorded(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[2] / "src/llm_loop/core/loop/tool_exec.py"
        ).read_text(encoding="utf-8")
        assert '"status": result.status.value' in src
