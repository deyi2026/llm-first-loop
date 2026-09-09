"""R8.24-B B-5.4: B-G5 sess.messages 零 runtime notice 扫描断言.

五类事件（E12/E15/E16/E17/E18）全触发后扫描会话存储：程序创作通知
chars=0（E19/B-D7）；event/status 观测轨在场（可观测性不降级对照）。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import ToolCall
from llm_loop.core.prompt_eligibility import PROGRAM_FINAL_PROTOCOL_BOUNDARY
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import LLMError, LLMHTTPError
from tests.unit.test_err1210_recovery import _mk, _resp

# B-G5 扫描口径: 程序创作通知标记（runtime notice 类；占位符与工具回执事实不在此列）
_RUNTIME_NOTICE_MARKERS = (
    "[停滞提醒]",
    "[搜索空结果提醒]",
    "[轮数预警]",
    "[轮次决策请求]",
    "[上下文溢出]",
    "[任务·程序恢复]",
    "恢复动作=",
)


def _scan_sess_notices(sess) -> list[str]:
    hits: list[str] = []
    for m in sess.messages:
        content = str(m.content or "")
        for marker in _RUNTIME_NOTICE_MARKERS:
            if marker in content:
                hits.append(marker)
    return hits


def _tool_resp(call_id: str, name: str, args: dict) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
        provider="fake",
    )


def _spy_actions(engine):
    recorded: list[tuple[str, str]] = []
    orig = engine._record_action

    def _spy(phase: str, action_type: str, detail: str = ""):
        recorded.append((phase, action_type))
        return orig(phase, action_type, detail)

    engine._record_action = _spy
    return recorded


class TestG5SessMessagesZeroNotice:
    def test_e15_stagnation_path(self, tmp_path: Path, monkeypatch):
        engine, fake = _mk(
            tmp_path,
            monkeypatch,
            responses=[
                _tool_resp("c1", "read_file", {"path": "/nonexistent/g5-stag"}),
                _tool_resp("c2", "read_file", {"path": "/nonexistent/g5-stag"}),
                _tool_resp("c3", "read_file", {"path": "/nonexistent/g5-stag"}),
                _resp("g5 停滞路径回答"),
            ],
        )
        actions = _spy_actions(engine)
        sid = engine.session.create()
        engine.run(sid, "真实任务")

        persisted = engine.session.load(sid)
        assert _scan_sess_notices(persisted) == []
        # 观测轨在场（可观测性对照）
        assert ("tool.repeat_observed", "observed") in actions

    def test_e16_empty_search_path(self, tmp_path: Path, monkeypatch):
        engine, fake = _mk(
            tmp_path,
            monkeypatch,
            responses=[
                _tool_resp(
                    "c1", "execute_command", {"command": f"find {tmp_path} -name 'g5-missing-*'"}
                ),
                _tool_resp(
                    "c2", "execute_command", {"command": f"find {tmp_path} -name 'g5-missing-*'"}
                ),
                _resp("g5 空搜索路径回答"),
            ],
        )
        actions = _spy_actions(engine)
        sid = engine.session.create()
        engine.run(sid, "真实任务")

        persisted = engine.session.load(sid)
        assert _scan_sess_notices(persisted) == []
        assert ("tool.empty_search_observed", "observed") in actions

    def test_e17_overflow_path(self, tmp_path: Path, monkeypatch):
        overflow = LLMError("provider says maximum context length exceeded")
        engine, fake = _mk(tmp_path, monkeypatch, responses=[overflow, overflow])
        actions = _spy_actions(engine)
        sid = engine.session.create()
        engine.run(sid, "真实任务")

        persisted = engine.session.load(sid)
        assert _scan_sess_notices(persisted) == []
        assert ("overflow.compact", "budget_shrunk") in actions
        assert ("overflow.end", "terminated") in actions

    def test_e18_exhaustion_path_program_final_placeholder(self, tmp_path: Path, monkeypatch):
        """E18 硬停: sess 尾部 assistant 为 PROTOCOL_ONLY 占位，全文不落存储."""
        engine, fake = _mk(
            tmp_path,
            monkeypatch,
            responses=[
                _tool_resp("c1", "read_file", {"path": "/nonexistent/g5-e18"}),
                _tool_resp("c2", "read_file", {"path": "/nonexistent/g5-e18"}),
                _tool_resp("c3", "read_file", {"path": "/nonexistent/g5-e18"}),
            ],
        )
        object.__setattr__(engine.settings, "max_iterations", 2)
        sid = engine.session.create()
        result = engine.run(sid, "真实任务")

        persisted = engine.session.load(sid)
        assert _scan_sess_notices(persisted) == []
        # B-D7/B-D11: 程序终态在存储面只留 neutral 协议占位；全文经 LoopResult 交付
        last_assistant = [m for m in persisted.messages if m.role == "assistant"][-1]
        assert last_assistant.content == PROGRAM_FINAL_PROTOCOL_BOUNDARY
        assert "[已达轮数上限]" in result.final_answer
        assert "[已达轮数上限]" not in str(last_assistant.content)
        # 终态元数据在场（B-G3 结束原因事实）
        assert (last_assistant.metadata or {}).get("answer_origin") == "program"
        assert (last_assistant.metadata or {}).get("run_end_reason") == "max_iterations"

    def test_e12_err1210_path(self, tmp_path: Path, monkeypatch):
        e1210 = LLMHTTPError(
            "400 Invalid parameter",
            status_code=400,
            body='{"error":{"code":"1210","message":"Invalid parameter"}}',
        )
        engine, fake = _mk(tmp_path, monkeypatch, responses=[e1210])
        sid = engine.session.create()
        engine.run(sid, "真实任务")
        persisted = engine.session.load(sid)
        assert _scan_sess_notices(persisted) == []
        assert len(fake.calls) == 1
