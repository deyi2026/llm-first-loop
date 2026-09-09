"""R8.24-B B-5.5: B-G6/G7/G8 grant/resend/关键词扫描断言 + B-4.2/B-3.3 收口断言.

- B-G6: current_turn 作为 grant 的放行记录=0（would_have_granted 观察字段在场）；
- B-G7: E12 场景 programmatic user resend chars=0；runtime retry 事件在场；
- B-G8: 熔断/提醒/替代策略相关词在模型可见面 chars=0；
- P2-A: generic duplicate suppression policy is absent from runtime;
- B-3.3: repair-before-lifecycle 执行顺序固化（源码序断言）。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt_eligibility import (
    would_have_granted_snapshot,
)


class TestG6CurrentTurnGrantClosed:
    def test_would_have_granted_observation_field_present(self):
        """B-G6: 观察字段在场且可复位读取（shadow 核对面）。"""
        snapshot = would_have_granted_snapshot()
        assert set(snapshot) == {"current_turn", "memory_snapshot"}

    def test_grant_denied_but_observed(self):
        """grant 恒拒绝；turn 匹配的拒绝被 would_have_granted 计数（而非放行）。"""
        from llm_loop.core.prompt_eligibility import (
            current_turn_program_prompt_eligible,
            memory_snapshot_prompt_eligible,
        )

        current = Message(
            role="system",
            content="CURRENT-CONTROL",
            source=MessageSource.SYSTEM,
            metadata={
                "program_origin": True,
                "prompt_lifecycle": "current_turn",
                "turn_ref": 7,
                "injection_kind": "stagnation_reminder",
            },
        )
        before = would_have_granted_snapshot()["current_turn"]
        assert current_turn_program_prompt_eligible(current, current_turn_ref=7) is False
        assert would_have_granted_snapshot()["current_turn"] == before + 1

        snapshot_msg = Message(
            role="user",
            content="[相关记忆] fact",
            source=MessageSource.USER,
            metadata={"injection_kind": "memory_snapshot", "turn_ref": 7},
        )
        before_m = would_have_granted_snapshot()["memory_snapshot"]
        assert memory_snapshot_prompt_eligible(snapshot_msg, current_turn_ref=7) is False
        assert would_have_granted_snapshot()["memory_snapshot"] == before_m + 1


class TestG7ProgrammaticResendRetired:
    def test_resend_markers_absent_from_wire_and_events_scoped(self, tmp_path: Path, monkeypatch):
        """B-G7: 程序化重发文本不在任何 wire 面（端到端 runtime retry 场景见
        test_program_recovery_boundary；此处断言旧 resend 句式已无生产通路）。"""
        from llm_loop.core.loop.engine_services.recovery_controller import RecoveryController

        assert not hasattr(RecoveryController, "_err1210_try_auto_continue")
        assert not hasattr(RecoveryController, "_err1210_try_runtime_retry")

    def test_runtime_retry_event_registered(self):
        """Historical program.recovery rows remain readable; no runtime emitter is required."""
        from llm_loop.event_log.model import EVENT_PROGRAM_RECOVERY, REGISTRY

        spec = REGISTRY.spec(EVENT_PROGRAM_RECOVERY)
        assert spec is not None
        assert set(spec.fields) == {"action", "trigger", "turn_ref", "scope"}


class TestG8KeywordScan:
    def test_forbidden_program_keywords_zero_in_code_paths(self):
        """B-G8 静态面: 退役策略提示生产者从生产源码完全消失."""
        import subprocess

        for func in (
            "max_iterations_decision_message",
            "max_iterations_warning_message",
            "stagnation_reminder_message",
            "empty_search_reminder_message",
            "overflow_feedback",
        ):
            # R9-IMM-02 适配：conftest chdir 沙箱后 cwd≠仓库根，锚定 __file__ 定位 src
            from pathlib import Path

            repo_src = Path(__file__).resolve().parents[2] / "src" / "llm_loop"
            result = subprocess.run(
                ["rg", "-l", func, str(repo_src)],
                capture_output=True,
                text=True,
            )
            files = [f for f in result.stdout.splitlines() if f.strip()]
            assert files == [], f"{func} 出现在生产面: {files}"


class TestB33RepairBeforeLifecycle:
    def test_repair_hook_precedes_main_loop_in_source(self):
        """B-D8: 修复钩子接线在主循环之前（源码序固化；行为断言见 E32 既有回归）。"""
        import inspect

        from llm_loop.core.loop import engine as engine_mod

        src = inspect.getsource(engine_mod.LoopEngine._run_stream_inner)
        repair_idx = src.index("self._recover_pre_ingress_runtime_state(")
        loop_idx = src.index("while True:")
        assert repair_idx < loop_idx, "repair-before-lifecycle 顺序被破坏"
