"""T1 溯源标记修复测试（tasks 2.5，design §2.4 T1，spec 5.2.1 验收）.

- origin_metadata 恒等式全层枚举断言（四层 × program_origin 真值表）
- E2 子代理消息标记断言（spec 5.2.1-1a）
- 全仓 origin_layer 字面量扫描归零断言（spec 5.2.1-2a，复用 ingress_audit）
- 程序生成消息标记与真实来源一致性抽查（spec 5.2.1-4a 零误标）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.trace_leak.invariant import (
    correct_mislabeled_metadata,
    metadata_satisfies_invariant,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_FORENSICS_DIR = _PROJECT_ROOT / "scripts" / "forensics"
if str(_FORENSICS_DIR) not in sys.path:
    sys.path.insert(0, str(_FORENSICS_DIR))


class TestOriginMetadataInvariant:
    """恒等式全层真值表（spec 6.1-2）。"""

    @pytest.mark.parametrize(
        "layer,expected_po",
        [
            (InjectionLayer.USER_INSTRUCTION, False),
            (InjectionLayer.PROGRAM_RECOVERY, True),
            (InjectionLayer.REFERENCE, True),
            (InjectionLayer.STATUS, True),
        ],
    )
    def test_truth_table(self, layer: InjectionLayer, expected_po: bool) -> None:
        md = origin_metadata(layer)
        assert md["origin_layer"] == layer.value
        assert md["program_origin"] is expected_po
        assert metadata_satisfies_invariant(md) is True

    def test_str_layer_accepted(self) -> None:
        md = origin_metadata("user_instruction", injection_kind=None)
        assert md == {"origin_layer": "user_instruction", "program_origin": False}

    def test_invalid_layer_raises(self) -> None:
        with pytest.raises(ValueError):
            origin_metadata("no_such_layer")

    def test_missing_keys_fail_open_none(self) -> None:
        assert metadata_satisfies_invariant({}) is None
        assert metadata_satisfies_invariant(None) is None
        assert metadata_satisfies_invariant({"origin_layer": "status"}) is None

    def test_mislabel_correction(self) -> None:
        bad = {"origin_layer": "user_instruction", "program_origin": True}
        assert metadata_satisfies_invariant(bad) is False
        fixed = correct_mislabeled_metadata(bad)
        assert fixed["origin_layer"] == "program_recovery"
        assert fixed["program_origin"] is True
        assert fixed["injection_kind"] == "leak_downgrade"
        assert metadata_satisfies_invariant(fixed) is True

    def test_correction_preserves_extra_keys(self) -> None:
        bad = {
            "origin_layer": "reference",
            "program_origin": False,
            "turn_ref": 7,
            "query_fp": "abc123",
        }
        fixed = correct_mislabeled_metadata(bad)
        assert fixed["turn_ref"] == 7 and fixed["query_fp"] == "abc123"


class TestSubagentProvenanceMark:
    """E2 子代理消息标记（spec 5.2.1-1a；决策 D6）。"""

    def test_subagent_task_message_marked(self, build_test_engine) -> None:
        from llm_loop.core.message import ToolCall
        from llm_loop.llm.client import LLMResponse
        from llm_loop.subagent.runner import SubAgentRunner

        engine, fake = build_test_engine([])
        runner = SubAgentRunner(
            llm=fake, registry=engine.registry, session_store=engine.session
        )

        def seq(calls):
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="c1", name="read_file", arguments={"path": "/nonexistent/x"})
                ],
                provider="fake",
            )

        fake._responses = [seq, LLMResponse(content="完成", tool_calls=[], provider="fake")]
        result = runner.run(task="检查文件", depth=0)
        assert result.refused is False

        # 子代理会话落盘首消息携带程序附录层标记
        import json

        sid_prefix = "subagent_"
        files = [
            p
            for p in Path(engine.session._dir).glob(f"{sid_prefix}*.json")
        ]
        assert files, "子代理会话应已落盘"
        data = json.loads(files[-1].read_text(encoding="utf-8"))
        first = data["messages"][0]
        assert first["role"] == "user"
        md = first.get("metadata") or {}
        assert md.get("program_origin") is True
        assert md.get("origin_layer") == "program_recovery"
        assert md.get("injection_kind") == "subagent_task"
        # role/source/消息序零改动（决策 D6）
        assert first.get("source") == "user"

    def test_prompt_projection_unchanged(self) -> None:
        """metadata 不进 to_llm_dict() 投影（子代理 LLM 行为零感知）。"""
        m = Message(
            role="user",
            content="x",
            source=MessageSource.USER,
            metadata=origin_metadata(
                InjectionLayer.PROGRAM_RECOVERY, injection_kind="subagent_task"
            ),
        )
        assert m.to_llm_dict() == {"role": "user", "content": "x"}


class TestLiteralScanClean:
    """全仓 origin_layer 字面量扫描归零（spec 5.2.1-2a）。"""

    def test_production_zero_hand_built_literals(self) -> None:
        from ingress_audit import audit_ingress_points

        report = audit_ingress_points(_PROJECT_ROOT)
        literals = [f for f in report.findings if f.kind == "origin_layer_literal"]
        # 唯一允许：单一真相源本体（injection_labels.py）
        allowed = [f for f in literals if f.file.endswith("core/injection_labels.py")]
        assert len(literals) == len(allowed) == 1, (
            f"生产代码 origin_layer 手工构造点未归零: {[f'{f.file}:{f.line}' for f in literals]}"
        )

    def test_turn_context_gate_view_uses_truth_source(self) -> None:
        """turn_context 门控合成视图已改为经真相源构造（行为零变化）。"""
        src = (
            _PROJECT_ROOT / "src/llm_loop/core/loop/turn_context.py"
        ).read_text(encoding="utf-8")
        assert '"origin_layer": "user_instruction"' not in src
        assert "origin_metadata(InjectionLayer.USER_INSTRUCTION)" in src


class TestProgramMessageMarkConsistency:
    """程序生成消息标记与真实来源 100% 一致抽查（spec 5.2.1-4a）。"""

    def test_guard_downgrade_marking_consistent(self) -> None:
        from llm_loop.core.trace_leak.user_ingress_guard import downgrade_message

        m = Message(
            role="user",
            content="程序降级内容",
            source=MessageSource.USER,
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        )
        downgraded = downgrade_message(m)
        md = downgraded.metadata
        assert md["program_origin"] is True
        assert md["origin_layer"] == "program_recovery"
        assert md["injection_kind"] == "leak_downgrade"  # 可定位来源细类（spec 6.1-3）
        assert metadata_satisfies_invariant(md) is True
        # role/content 不变（仅来源判定如实化）
        assert downgraded.role == "user" and downgraded.content == "程序降级内容"

    def test_memory_snapshot_marking_consistent(self) -> None:
        """memory_snapshot 先例：程序层标记 + persisted_injection（4.5-2 语义不变）。"""
        md = origin_metadata(
            InjectionLayer.STATUS,
            injection_kind="memory_snapshot",
            persisted_injection=True,
            turn_ref=3,
        )
        assert md["program_origin"] is True
        assert md["persisted_injection"] is True
        assert metadata_satisfies_invariant(md) is True
