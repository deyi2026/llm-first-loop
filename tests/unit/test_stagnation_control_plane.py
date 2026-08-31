"""R8.24-B B-5.2: B-G2/B-G3 停滞计数/熔断双断言.

- B-G2: identical_args 与空结果两路径提醒注入 chars=0 + 计数/熔断事件记录保留
        （3 次阈值事件留痕 + 5 次硬熔断）双断言；
- B-G3: 熔断终止模型可见建议文案 chars=0（"三路径替代策略"全取消）+
        结束原因事实在场（stagnation、连续 N 次、轨迹）。

注: 恢复类失败计数（recovery_fail_streak）分支全仓未实现（§0 锚点复核），
本文件不虚构断言；引入时须补对应用例。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse

from tests.unit.test_err1210_recovery import _mk

# B-G3: "三路径替代策略"建议句式（熔断回执不得再现）
_FORBIDDEN_ADVICE = (
    "search_evidence",
    "get_tool_schema",
    "基于回执",
    "建议:",
)


def _wire_text(fake) -> str:
    parts: list[str] = []
    for call in fake.calls:
        for m in call["messages"]:
            parts.append(str(m.get("content") or ""))
    return "\n".join(parts)


def _spy_actions(engine):
    recorded: list[tuple[str, str]] = []
    orig = engine._record_action

    def _spy(phase: str, action_type: str, detail: str = ""):
        recorded.append((phase, action_type))
        return orig(phase, action_type, detail)

    engine._record_action = _spy
    return recorded


def _same_arg_resp(call_id: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name="read_file", arguments={"path": "/nonexistent/break-target"})],
        provider="fake",
    )


class TestG2StagnationObservability:
    def test_reminder_event_and_break_both_recorded(self, tmp_path: Path, monkeypatch):
        """同参 5 次: 阈值事件（3 次）留痕 + 硬熔断事件在场——观测不降级."""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_same_arg_resp(f"c{i}") for i in range(1, 7)],
        )
        actions = _spy_actions(engine)
        sid = engine.session.create()

        result = engine.run(sid, "真实任务")

        # 3 次阈值事件留痕（B-G2 前半）
        assert ("stagnation.reminder", "suppressed") in actions
        # 5 次硬熔断（B-G2 后半）
        assert ("stagnation.break", "terminated") in actions
        assert "read_file" in result.final_answer
        assert "停滞熔断" in result.final_answer or "终止" in result.final_answer

    def test_identical_args_injection_chars_zero(self, tmp_path: Path, monkeypatch):
        """B-G2: identical_args 路径提醒注入 chars=0（wire + sess.messages 双面）."""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_same_arg_resp(f"c{i}") for i in range(1, 7)],
        )
        sid = engine.session.create()
        engine.run(sid, "真实任务")

        assert "[停滞提醒]" not in _wire_text(fake)
        persisted = engine.session.load(sid)
        assert not any(
            "[停滞提醒]" in str(m.content or "") for m in persisted.messages
        )

    def test_empty_search_injection_chars_zero(self, tmp_path: Path, monkeypatch):
        """B-G2: 空结果路径提醒注入 chars=0；否定帧登记事件路径保留."""
        def _find_resp(call_id: str) -> LLMResponse:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(
                    id=call_id, name="execute_command",
                    arguments={"command": f"find {tmp_path} -name 'missing-*'"},
                )],
                provider="fake",
            )

        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_find_resp("c1"), _find_resp("c2"), _find_resp("c3"), _find_resp("c4")],
        )
        actions = _spy_actions(engine)
        sid = engine.session.create()
        engine.run(sid, "真实任务")

        assert ("empty_search.reminder", "suppressed") in actions
        assert "[搜索空结果提醒]" not in _wire_text(fake)
        persisted = engine.session.load(sid)
        assert not any(
            "[搜索空结果提醒]" in str(m.content or "") for m in persisted.messages
        )


class TestG3BreakFactsOnly:
    def test_break_final_has_facts_no_advice(self, tmp_path: Path, monkeypatch):
        """B-G3: 熔断终态 = 事实（连续 N 次/工具名/轨迹），建议文案 chars=0."""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_same_arg_resp(f"c{i}") for i in range(1, 7)],
        )
        sid = engine.session.create()

        result = engine.run(sid, "真实任务")

        # 结束原因事实在场（run 终态呈现 + LoopResult 交付）
        assert "连续" in result.final_answer
        assert "read_file" in result.final_answer
        # 三路径替代策略取消
        for advice in _FORBIDDEN_ADVICE:
            assert advice not in result.final_answer
        # wire 面零建议句式
        wire = _wire_text(fake)
        for advice in _FORBIDDEN_ADVICE:
            assert advice not in wire

    def test_no_evidence_gate_states_unresolved(self, tmp_path: Path, monkeypatch):
        """证据有效性门（事实面保留）: 无成功回执时如实说明 unresolved."""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_same_arg_resp(f"c{i}") for i in range(1, 7)],
        )
        sid = engine.session.create()
        result = engine.run(sid, "真实任务")
        # /nonexistent/ 路径全部失败 → 无成功回执 → unresolved 事实
        assert "unresolved" in result.final_answer or "未获得" in result.final_answer