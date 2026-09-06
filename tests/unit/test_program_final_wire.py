"""R8.24-B B-5.6: B-G9 PROGRAM_FINAL wire 断言.

- 模型可读语义标签 chars=0（中文标签退役，PROTOCOL_ONLY）；
- role-shape 兼容不破坏（无连续 user 角色、工具配对完整——B6 锚点教训）；
- wire 字节稳定（engine 写入与 build 替换同源常量）。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import Message, MessageSource, ToolCall
from llm_loop.core.prompt_eligibility import (
    LEGACY_PROGRAM_FINAL_MARKER,
    PROGRAM_FINAL_PROTOCOL_BOUNDARY,
)
from llm_loop.llm.client import LLMResponse
from tests.unit.test_err1210_recovery import _mk, _resp


def _tool_resp(call_id: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name="read_file", arguments={"path": "/nonexistent/g9"})],
        provider="fake",
    )


class TestG9ProgramFinalWire:
    def test_no_semantic_label_in_wire_and_role_shape_preserved(
        self, tmp_path: Path, monkeypatch
    ):
        """程序终态后下一轮 wire: 无中文语义标签、无连续 user 角色。"""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[
                _tool_resp("c1"), _tool_resp("c2"), _tool_resp("c3"),
                _resp("g9 回答"),
            ],
        )
        object.__setattr__(engine.settings, "max_iterations", 2)
        sid = engine.session.create()
        engine.run(sid, "第一轮任务")  # E18 硬停 → 程序终态落 sess

        # 第二轮（程序终态历史在场时）
        fake.queue([_resp("第二轮回答")])
        result = engine.run(sid, "第二轮任务")
        assert "第二轮回答" in result.final_answer

        wire = fake.calls[-1]["messages"]
        roles = [m["role"] for m in wire]
        joined = "\n".join(str(m.get("content") or "") for m in wire)

        # B-G9: 语义标签 chars=0；PROTOCOL_ONLY 占位同源在场（或历史已被替换）
        assert "[程序终止边界·无模型回答]" not in joined
        # role-shape: 无连续 user（program-assistant 帧保留边界形状——B6 教训）
        for i in range(1, len(roles)):
            assert not (roles[i] == "user" and roles[i - 1] == "user"), (
                f"连续 user 角色出现在 {i}: {roles}"
            )

    def test_placeholder_byte_stable_engine_build_same_source(self):
        """engine 终态写入与 build 替换共用同一常量（wire 字节稳定）。"""
        import inspect

        # B4-CLOSE-01 步B: build 侧替换随 scrub_provider_view 迁
        # stages/base_assembly.py（同源守卫锚点随新家）
        # B5-W4-01: engine 终态写入随收尾段迁 engine_services/run_finalizer.py
        # （_persist_turn 持久化半程）——同源守卫锚点随新家
        from llm_loop.core.loop.engine_services import run_finalizer as finalizer_mod
        from llm_loop.core.prompt_build.stages import base_assembly as build_mod

        finalizer_src = inspect.getsource(finalizer_mod)
        build_src = inspect.getsource(build_mod)
        # 两处都从 prompt_eligibility 引同一常量（非字面量复制）
        assert "PROGRAM_FINAL_PROTOCOL_BOUNDARY" in finalizer_src
        assert "PROGRAM_FINAL_PROTOCOL_BOUNDARY" in build_src
        # 无第二处字面量定义（防分叉）
        assert finalizer_src.count('"[program-final]"') == 0
        assert build_src.count('"[program-final]"') == 0

    def test_legacy_program_final_replaced_to_neutral_placeholder(
        self, tmp_path: Path, monkeypatch
    ):
        """存量历史程序正文（answer_origin=program 全文）在 provider view
        统一折叠为 neutral 占位——存储真相不动。"""
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_resp("回答")])
        sid = engine.session.create()
        sess = engine.session.load(sid)
        sess.messages.append(
            Message(
                role="assistant",
                content="[模型不可用] 事实: 模型 x 不可用。\n原因: 测试遗留全文。",
                source=MessageSource.SYSTEM,
                metadata={"answer_origin": "program", "run_end_reason": "llm_error"},
            )
        )
        sess.messages.append(
            Message(role="user", content="后续任务", source=MessageSource.USER)
        )
        engine.session.save(sess)

        engine.run(sid, "后续任务")

        wire = fake.calls[-1]["messages"]
        joined = "\n".join(str(m.get("content") or "") for m in wire)
        assert "[模型不可用]" not in joined
        assert LEGACY_PROGRAM_FINAL_MARKER not in joined
        assert any(
            m.get("role") == "assistant" and m.get("content") == PROGRAM_FINAL_PROTOCOL_BOUNDARY
            for m in wire
        )
        # 存储真相不动
        persisted = engine.session.load(sid)
        assert any(
            "[模型不可用]" in str(m.content or "") for m in persisted.messages
        )

    def test_legacy_model_echo_is_scrubbed_to_empty_role_frame(
        self, tmp_path: Path, monkeypatch
    ):
        """Pre-fix model-origin [program-final] must never survive provider projection."""
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_resp("正常总结")])
        sid = engine.session.create()
        sess = engine.session.load(sid)
        sess.messages.extend(
            [
                Message(role="user", content="旧任务", source=MessageSource.USER),
                Message(
                    role="assistant",
                    content=LEGACY_PROGRAM_FINAL_MARKER,
                    source=MessageSource.USER,
                    metadata={"answer_origin": "model", "run_end_reason": "completed"},
                ),
            ]
        )
        engine.session.save(sess)

        result = engine.run(sid, "继续")
        assert result.final_answer == "正常总结"
        wire = fake.calls[-1]["messages"]
        assert LEGACY_PROGRAM_FINAL_MARKER not in "\n".join(
            str(m.get("content") or "") for m in wire
        )
        assert any(
            m.get("role") == "assistant" and m.get("content") == "" for m in wire
        )

    def test_model_echo_retries_once_without_persisting_marker(
        self, tmp_path: Path, monkeypatch
    ):
        """One leaked-marker echo is not a completed answer; next provider round may recover."""
        engine, fake = _mk(
            tmp_path,
            monkeypatch,
            responses=[_resp(LEGACY_PROGRAM_FINAL_MARKER), _resp("正常最终总结")],
        )
        sid = engine.session.create()
        result = engine.run(sid, "完成任务并总结")

        assert result.final_answer == "正常最终总结"
        assert len(fake.calls) == 2
        persisted = engine.session.load(sid)
        assert all(str(m.content or "").strip() != LEGACY_PROGRAM_FINAL_MARKER for m in persisted.messages)
        final = [m for m in persisted.messages if m.role == "assistant"][-1]
        assert (final.metadata or {}).get("answer_origin") == "model"
        assert (final.metadata or {}).get("run_end_reason") == "completed"


    def test_empty_model_output_persists_zero_content_not_program_phrase(
        self, tmp_path: Path, monkeypatch
    ):
        """Completed empty response keeps only assistant role shape; program text stays out."""
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_resp("")])
        sid = engine.session.create()
        result = engine.run(sid, "只做一次空输出测试")

        assert result.final_answer == ""
        persisted = engine.session.load(sid)
        final = [m for m in persisted.messages if m.role == "assistant"][-1]
        assert final.content == ""
        assert (final.metadata or {}).get("empty_output") is True
        assert "无回答输出" not in "\n".join(str(m.content or "") for m in persisted.messages)

    def test_repeated_model_echo_is_llm_error_not_completed(
        self, tmp_path: Path, monkeypatch
    ):
        """Two exact echoes fail truthfully instead of silently completing with a control token."""
        engine, fake = _mk(
            tmp_path,
            monkeypatch,
            responses=[_resp(LEGACY_PROGRAM_FINAL_MARKER), _resp(LEGACY_PROGRAM_FINAL_MARKER)],
        )
        sid = engine.session.create()
        result = engine.run(sid, "完成任务并总结")

        assert "LLM 输出异常" in result.final_answer
        assert len(fake.calls) == 2
        persisted = engine.session.load(sid)
        final = [m for m in persisted.messages if m.role == "assistant"][-1]
        assert final.content == PROGRAM_FINAL_PROTOCOL_BOUNDARY
        assert (final.metadata or {}).get("answer_origin") == "program"
        assert (final.metadata or {}).get("run_end_reason") == "llm_error"
        assert all(str(m.content or "").strip() != LEGACY_PROGRAM_FINAL_MARKER for m in persisted.messages)
