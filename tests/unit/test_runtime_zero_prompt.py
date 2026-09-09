"""R8.24-B B-5.1/B-5.3: B-G1 零 prompt census 回放 + B-G4 E18 零额外轮次断言.

五类事件（E12/E15/E16/E17/E18）场景回放：run 全周期 program-authored
natural-language prompt chars=0——wire 消息面（fake client 收到的全部
payload）扫描断言，strict census 口径。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import LLMError, LLMHTTPError
from tests.unit.test_err1210_recovery import _mk, _resp

# B-G8 关键词扫描清单：这些程序通知/建议句式不得出现在任何模型可见面
_PROGRAM_MARKERS = (
    "[停滞提醒]",
    "[搜索空结果提醒]",
    "[轮数预警]",
    "[轮次决策请求]",
    "[上下文溢出]",
    "[任务·程序恢复]",
    "恢复动作=",
    "请调用 adjust_strategy",
    "建议: 若预计还需多轮工具调用",
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


def _tool_resp(call_id: str, name: str, args: dict) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
        provider="fake",
    )


class TestE15StagnationReminder:
    def test_threshold_hits_event_only_zero_wire_injection(self, tmp_path: Path, monkeypatch):
        """E15: 同参 3 次达阈值 → 'tool.repeat_observed/observed' 事件在场、wire 零提醒."""
        engine, fake = _mk(
            tmp_path,
            monkeypatch,
            responses=[
                _tool_resp("c1", "read_file", {"path": "/nonexistent/stag-target"}),
                _tool_resp("c2", "read_file", {"path": "/nonexistent/stag-target"}),
                _tool_resp("c3", "read_file", {"path": "/nonexistent/stag-target"}),
                _resp("停滞后的正常回答"),
            ],
        )
        actions = _spy_actions(engine)
        sid = engine.session.create()

        result = engine.run(sid, "真实任务")

        assert "停滞后的正常回答" in result.final_answer
        assert ("tool.repeat_observed", "observed") in actions
        wire = _wire_text(fake)
        assert "[停滞提醒]" not in wire
        for marker in _PROGRAM_MARKERS:
            assert marker not in wire, f"程序注入泄漏: {marker}"


class TestE16EmptySearchReminder:
    def test_empty_search_threshold_hits_event_only(self, tmp_path: Path, monkeypatch):
        """E16: 搜索空结果 2 次达阈值 → 事件观测在场、wire 零建议层."""
        engine, fake = _mk(
            tmp_path,
            monkeypatch,
            responses=[
                _tool_resp(
                    "c1",
                    "execute_command",
                    {"command": f"find {tmp_path} -name 'nonexistent-*'"},
                ),
                _tool_resp(
                    "c2",
                    "execute_command",
                    {"command": f"find {tmp_path} -name 'nonexistent-*'"},
                ),
                _resp("空搜索后的正常回答"),
            ],
        )
        actions = _spy_actions(engine)
        sid = engine.session.create()

        result = engine.run(sid, "真实任务")

        assert "空搜索后的正常回答" in result.final_answer
        assert ("tool.empty_search_observed", "observed") in actions
        wire = _wire_text(fake)
        assert "[搜索空结果提醒]" not in wire
        # 真实空结果回执原文保留（事实层不删）
        assert "find" in wire


class TestE17Overflow:
    def test_double_overflow_deterministic_end_zero_teaching(self, tmp_path: Path, monkeypatch):
        """E17: 二次 overflow → 确定性终止；全 wire 零 overflow 教程/询问."""
        overflow = LLMError("provider says maximum context length exceeded")
        engine, fake = _mk(tmp_path, monkeypatch, responses=[overflow, overflow])
        actions = _spy_actions(engine)
        sid = engine.session.create()

        result = engine.run(sid, "真实任务")

        assert "上下文" in result.final_answer or "超限" in result.final_answer
        assert ("overflow.compact", "budget_shrunk") in actions
        assert ("overflow.end", "terminated") in actions
        wire = _wire_text(fake)
        for marker in ("[上下文溢出]", "继续", "压缩", "教程"):
            # 终态事实在 LoopResult/UI，不在 wire；wire 上不应有任何 overflow 指导文本
            assert "overflow" not in wire.lower() or marker not in wire

    def test_first_overflow_shrinks_budget_reinject(self, tmp_path: Path, monkeypatch):
        """E17: 首次 overflow → 确定性预算收缩后重发（第二次调用在场=非注入式 reinject）."""
        overflow = LLMError("provider says context length exceeded hard limit")
        engine, fake = _mk(tmp_path, monkeypatch, responses=[overflow, _resp("收缩后成功")])
        sid = engine.session.create()

        result = engine.run(sid, "真实任务")

        assert "收缩后成功" in result.final_answer
        assert len(fake.calls) == 2  # reinject = 程序侧 continue，非 prompt 注入
        assert "[上下文溢出]" not in _wire_text(fake)


class TestE18RoundExhaustion:
    def test_hard_stop_zero_extra_llm_call(self, tmp_path: Path, monkeypatch):
        """B-G4: 到达 budget 直接硬停——第 N+1 轮 LLM call=0（可区分一次额外调用）."""
        engine, fake = _mk(
            tmp_path,
            monkeypatch,
            responses=[
                _tool_resp("c1", "read_file", {"path": "/nonexistent/e18"}),
                _tool_resp("c2", "read_file", {"path": "/nonexistent/e18"}),
                _tool_resp("c3", "read_file", {"path": "/nonexistent/e18"}),
                _tool_resp("c4", "read_file", {"path": "/nonexistent/e18"}),
                _tool_resp("c5", "read_file", {"path": "/nonexistent/e18"}),
                _tool_resp("c6", "read_file", {"path": "/nonexistent/e18"}),
            ],
        )
        object.__setattr__(engine.settings, "max_iterations", 3)
        actions = _spy_actions(engine)
        sid = engine.session.create()

        result = engine.run(sid, "真实任务")

        # B-G4 核心断言：3 轮 budget → 恰好 3 次 LLM 调用（若保留决策轮会是 4）
        assert len(fake.calls) == 3
        assert len(fake.calls) != 4
        assert "[已达轮数上限]" in result.final_answer
        # 硬停默认带"用户可继续"UI 提示（LFL_E18_HARD_STOP=1）
        assert "继续" in result.final_answer
        # 观测事件：预警 suppressed（round 3 >= 80%*3 且 budget>=10 才预警——
        # budget=3 < 10 不触发预警；断言零注入即可）
        wire = _wire_text(fake)
        assert "[轮数预警]" not in wire
        assert "[轮次决策请求]" not in wire
        assert ("round.exhaustion", "decision_requested") not in actions

    def test_hard_stop_off_keeps_pure_fact(self, tmp_path: Path, monkeypatch):
        """LFL_E18_HARD_STOP=0: 终态去掉"可继续"提示行（纯事实），硬停不变."""
        monkeypatch.setenv("LFL_E18_HARD_STOP", "0")
        engine, fake = _mk(
            tmp_path,
            monkeypatch,
            responses=[
                _tool_resp("c1", "read_file", {"path": "/nonexistent/e18b"}),
                _tool_resp("c2", "read_file", {"path": "/nonexistent/e18b"}),
                _tool_resp("c3", "read_file", {"path": "/nonexistent/e18b"}),
            ],
        )
        object.__setattr__(engine.settings, "max_iterations", 2)
        sid = engine.session.create()

        result = engine.run(sid, "真实任务")

        assert len(fake.calls) == 2
        assert "[已达轮数上限]" in result.final_answer
        assert '发送"继续"' not in result.final_answer


class TestE12Err1210:
    def test_single_tail_user_1210_zero_recovery_prompt_and_zero_retry(
        self, tmp_path: Path, monkeypatch
    ):
        """P2-B: no structural wire transform => truthful 1210 end, no exact resend."""
        e1210 = LLMHTTPError(
            "400 Invalid parameter",
            status_code=400,
            body='{"error":{"code":"1210","message":"Invalid parameter"}}',
        )
        engine, fake = _mk(tmp_path, monkeypatch, responses=[e1210])
        sid = engine.session.create()
        result = engine.run(sid, "真实任务")
        assert "LLM 调用异常" in result.final_answer
        assert len(fake.calls) == 1
        wire = _wire_text(fake)
        for marker in _PROGRAM_MARKERS:
            assert marker not in wire
