"""R8.24 全量落地终验常驻断言（六条结构硬门 final verification）.

验收来源: docs/ANALYSIS-20260831-model-agency-obstruction-audit.md §13.1（六条
结构硬门）+ §12 末尾（金丝雀/R9 冻结条款）；docs/r824/README.md 五包一览；
docs/r824/CORE9-final-ruling.md（CORE 相关断言以终判为准——CORE 集合维持 9 工具，
路由路线 2 逃生门已随 R8.24-C 落地，本文件不重复 A/B 评估断言）。

终验语义（任务口径）: 按"重启后生产默认态"测——本文件组一是七开关默认值快照
断言，是金丝雀/R9 解锁判定的常驻锚点，也是未来 shadow→enforce 切换提交的
验收锚点（切换默认值时本组断言须随切换同步更新，形成一一对应的切换回执）。

覆盖缺口分析（相对既有承载，见 final-verification-report.md 映射矩阵）:
- 既有测试对 LFL_TOOL_GUIDANCE / LFL_EVIDENCE_CAPSULE / CACHE_GUARD_PERF_BLOCK
  全部在 off/enforce 态断言零值，LFL_LATENT_CHANNEL 默认值无直接断言——组一补；
- 既有 H1 wire 断言均为故障场景（停滞/空搜/溢出/1210/轮数耗尽），正常任务轮
  无独立断言——组二补；
- H3/H4/H6 三门"机制 READY 但默认未切 enforce"的现状需要行为级固化（防静默
  漂移，也为切换提交提供反例锚点）——组三补。

sk- 虚构样例说明: 本文件沿用 test_cache_block_reclassification.py 先例
（scripts/git_security_scan.sh _ALLOWLIST 已登记该文件；本文件样例同为全大写
字母+数字序列的明显虚构值，且复用 privacy_leak 检测目标形态 sk- 前缀——
改前缀会破坏 D-G5 断言语义）。
"""

from __future__ import annotations

import inspect

import pytest

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.tools.registry import tool_result_to_message

# 复用既有断言口径（零改动现有文件——import 复用）
from tests.unit.test_runtime_zero_prompt import _PROGRAM_MARKERS, _wire_text
from tests.unit.test_tool_result_factualization import (
    ADVISORY_PATTERNS,
    _enforce_registry,
)

_GATES_ENV_KEYS = (
    "LFL_TOOL_GUIDANCE",
    "LFL_EVIDENCE_CAPSULE",
    "LFL_LEAK_QUARANTINE",
    "LFL_LEAK_GUARD_MODE",
    "LFL_LATENT_CHANNEL",
    "LFL_COG_ENFORCE_FREEZE",
    "CACHE_GUARD_PERF_BLOCK",
)


def _clear_gates_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清除七开关 env（模拟重启后生产默认态；conftest autouse 的 guard=observe 一并还原）."""
    for key in _GATES_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# ══════════════ 组一: 七开关默认生产态快照（终验锚点）══════════════


class TestFinalGateSwitchDefaults:
    """组一: 重启后生产默认态实测断言（2026-09-01 终验时点快照）.

    判定语义:
    - enforce 语义已生效的开关（quarantine=off / guard=enforce / latent=off /
      cog_freeze=on）→ H2/H5 侧硬门默认态达标的开关面证据；
    - 仍处 shadow 观测态的开关（tool_guidance=on / capsule=on / perf_block=on）
      → H3/H4/H6 默认态未达标的开关面证据（机制 READY 由组三与既有 off/enforce
      态承载测试证明，切换动作属生产配置变更，不属本验收测量权限）。
    """

    def test_tool_guidance_default_off_enforced(self, monkeypatch):
        """H3 开关面: LFL_TOOL_GUIDANCE 默认 off=最终治理态（批 2/3 切换，R9-P0-01）."""
        from llm_loop.tools.registry import _tool_guidance_mode

        _clear_gates_env(monkeypatch)
        assert _tool_guidance_mode() == "off"

    def test_evidence_capsule_default_off_enforced(self, monkeypatch):
        """H4 开关面: LFL_EVIDENCE_CAPSULE 默认 off=最终治理态（批 1/3 切换，R9-P0-01）."""
        from llm_loop.tools.evidence_enforce import _capsule_mode

        _clear_gates_env(monkeypatch)
        assert _capsule_mode() == "off"

    def test_leak_quarantine_default_off_enforced(self, monkeypatch):
        """H5 开关面: LFL_LEAK_QUARANTINE 默认 off=quarantine+provider chars=0（enforce 态）."""
        from llm_loop.core.trace_leak.leak_events import current_quarantine_mode

        _clear_gates_env(monkeypatch)
        assert current_quarantine_mode() == "off"

    def test_leak_guard_default_enforce_fail_closed(self, monkeypatch):
        """H5 开关面: LFL_LEAK_GUARD_MODE 默认 enforce（fail-closed；覆盖 conftest observe）."""
        from llm_loop.core.trace_leak.user_ingress_guard import (
            DEFAULT_GUARD_MODE,
            current_guard_mode,
        )

        assert DEFAULT_GUARD_MODE == "enforce"
        _clear_gates_env(monkeypatch)
        assert current_guard_mode() == "enforce"

    def test_latent_channel_default_off_enforced(self, monkeypatch):
        """H2 开关面: LFL_LATENT_CHANNEL 默认 off=E07/E08/E35 通道关闭（enforce 态）."""
        from llm_loop.core.loop.input_authorization import (
            DEFAULT_LATENT_CHANNEL_MODE,
            current_latent_channel_mode,
        )

        assert DEFAULT_LATENT_CHANNEL_MODE == "off"
        _clear_gates_env(monkeypatch)
        assert current_latent_channel_mode() == "off"

    def test_cog_enforce_freeze_default_on(self, monkeypatch):
        """H2 开关面: LFL_COG_ENFORCE_FREEZE 默认 on=allowlist promote 禁止（冻结态）."""
        from llm_loop.core.loop.build import _cog_freeze_enabled

        _clear_gates_env(monkeypatch)
        assert _cog_freeze_enabled() is True

    def test_cache_perf_block_default_on(self):
        """H6 开关面: CACHE_GUARD_PERF_BLOCK 默认 on=性能 BLOCK 保留（enforce 未切）.

        沿 test_cache_block_reclassification.test_perf_mode_default_is_on 先例：
        不用 importlib.reload（会重定义 guard 模块类对象，污染同进程先期绑定），
        以源码默认参数静态断言守护。
        """
        import llm_loop.cache_guard.guard as guard_mod

        src = inspect.getsource(guard_mod)
        assert 'os.environ.get("CACHE_GUARD_PERF_BLOCK", "on")' in src


# ══════════════ 组二: H1 正常任务轮 wire 零程序注入（默认态）══════════════


class TestH1NormalTurnWireZeroProgramProse:
    """组二: 正常任务轮（无故障注入场景）wire 零 program-authored 自然语言.

    既有 H1 承载（test_runtime_zero_prompt.py）覆盖 E12/E15/E16/E17/E18 全故障
    场景；本组补"纯正常轮"（直接回答轮 + 正常工具成功轮）的默认态 wire 断言，
    并核对用户消息原文不被程序改写（H1 的 programmatic rewrite 面）。
    """

    def test_normal_direct_answer_turn_zero_program_prose(self, tmp_path, monkeypatch):
        from tests.unit.test_err1210_recovery import _mk, _resp

        # 注: 不清 guard env——conftest autouse observe 是测试基建对 user 写入面的
        # 合法覆盖（组一已独立断言生产默认 enforce）；注入面开关（guidance/capsule/
        # perf_block/latent/cog_freeze）未被 conftest 覆盖，本组即生产默认注入态。
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_resp("正常轮直接回答")])
        sid = engine.session.create()

        result = engine.run(sid, "真实任务")

        assert "正常轮直接回答" in result.final_answer
        wire = _wire_text(fake)
        for marker in _PROGRAM_MARKERS:
            assert marker not in wire, f"正常轮程序注入泄漏: {marker}"
        for pattern in ADVISORY_PATTERNS:
            assert pattern not in wire, f"正常轮 advisory 泄漏: {pattern}"
        # 用户消息原文未被程序改写（首轮 user content 必须逐字节等于用户输入）
        user_contents = [
            str(m.get("content") or "")
            for call in fake.calls
            for m in call["messages"]
            if m.get("role") == "user"
        ]
        assert user_contents == ["真实任务"]

    def test_normal_tool_success_turn_zero_program_prose(self, tmp_path, monkeypatch):
        from llm_loop.llm.client import LLMResponse
        from tests.unit.test_err1210_recovery import _mk

        target = tmp_path / "normal.txt"
        target.write_text("正常工具轮内容", encoding="utf-8")
        engine, fake = _mk(
            tmp_path,
            monkeypatch,
            responses=[
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="c-ok", name="read_file", arguments={"path": str(target)})
                    ],
                    provider="fake",
                ),
                LLMResponse(content="工具成功后的正常回答", tool_calls=[], provider="fake"),
            ],
        )
        sid = engine.session.create()

        result = engine.run(sid, "读取该文件并总结")

        assert "工具成功后的正常回答" in result.final_answer
        wire = _wire_text(fake)
        assert "正常工具轮内容" in wire  # 事实层（工具真实输出）保留
        for marker in _PROGRAM_MARKERS:
            assert marker not in wire, f"正常工具轮程序注入泄漏: {marker}"
        for pattern in ADVISORY_PATTERNS:
            assert pattern not in wire, f"正常工具轮 advisory 泄漏: {pattern}"


# ══════════════ 组三: H3/H4/H6 机制 READY 复核 + 默认态现状登记 ══════════════


class TestH3H4H6MechanismReadyAndCurrentState:
    """组三: 三未切门的"机制 READY（off/enforce 态零值）+ 默认态现状在场"双面固化.

    默认态在场断言是终验事实的常驻登记（现状=on）：未来 enforce 切换提交必须
    同步翻转本组断言——防止切换被静默遗漏或回滚后无人察觉。
    """

    # ── H3: tool result advisory-prose ──

    def test_h3_default_failure_receipt_advisory_absent(self, monkeypatch):
        """H3 现状登记: 默认态失败回执 advisory chars=0（批 2/3 切换后现状）."""
        _clear_gates_env(monkeypatch)
        result = ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[文件不存在] /tmp/final-gate-none.txt 不存在。",
            tool_call_id="h3-final",
            tool_name="read_file",
        )
        msg = tool_result_to_message(result)
        assert "可选项（判断归你）" not in msg.content

    def test_h3_off_mode_advisory_chars_zero_mechanism_ready(self, monkeypatch):
        """H3 机制 READY: off 态同一回执 advisory chars=0（复核对既有承载的抽样）."""
        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "off")
        result = ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[文件不存在] /tmp/final-gate-none.txt 不存在。",
            tool_call_id="h3-off",
            tool_name="read_file",
        )
        msg = tool_result_to_message(result)
        for pattern in ADVISORY_PATTERNS:
            assert pattern not in msg.content, f"off 态 advisory 残留: {pattern}"

    # ── H4: evidence full-result capsule ──

    def test_h4_default_capsule_absent_and_off_zero(self, tmp_path, monkeypatch):
        """H4 双面: 默认态 capsule chars=0（批 1/3 切换后现状登记）；off 态机制 READY 同态复核.

        两态各用独立文件——同文件二次读会触发 EvidenceSourceResolver 的 reuse
        内联短路（C-G8 面），不复现 enforcer 投影路径。
        """
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        path_default = tmp_path / "h4-final-a.txt"
        path_default.write_text("H4 FINAL GATE A", encoding="utf-8")
        path_off = tmp_path / "h4-final-b.txt"
        path_off.write_text("H4 FINAL GATE B", encoding="utf-8")

        registry, _, _ = _enforce_registry(tmp_path, projection_budget_chars=900)

        # 默认态（GATES env 清理后 = 生产重启默认 off——批 1/3 切换后）
        _clear_gates_env(monkeypatch)
        result_default = registry.execute(
            ToolCall(
                id="h4-d", name="read_file", arguments={"path": str(path_default), "full": True}
            )
        )
        assert result_default.status is ToolResultStatus.SUCCESS
        assert result_default.evidence_projection_complete is True
        assert "[evidence]" not in result_default.content  # 现状登记: capsule chars=0

        # off 态（机制 READY）
        monkeypatch.setenv("LFL_EVIDENCE_CAPSULE", "off")
        result_off = registry.execute(
            ToolCall(
                id="h4-o", name="read_file", arguments={"path": str(path_off), "full": True}
            )
        )
        assert result_off.status is ToolResultStatus.SUCCESS
        assert result_off.evidence_projection_complete is True
        assert "[evidence]" not in result_off.content  # C-G2: capsule chars=0
        assert "[/evidence]" not in result_off.content
        # 审计 metadata 六字段完整（数据不静默丢）
        assert result_off.evidence_ref is not None
        assert result_off.evidence_source_label.startswith("read_file:")
        assert result_off.evidence_coverage_label

    # ── H6: cache hit/performance alone BLOCK ──

    def test_h6_default_perf_block_present_and_enforce_zero(self, tmp_path, monkeypatch):
        """H6 双面: 默认态 ratio>95% BLOCK（现状登记）；enforce 态同一场景 WARN（机制 READY）.

        privacy/safety BLOCK 双态保留（D-G5 一票否决项）同场景复核。
        perf 模式经 setattr 显式钉住（进程常量默认 on 由组一源码断言守护——
        setattr 与重启默认等价，且免疫测试进程 env 漂移）。
        """
        import llm_loop.cache_guard.guard as guard_mod

        msgs_over = [
            {"role": "system", "content": "s" * 1000},
            {"role": "user", "content": "u" * 5000},
        ]

        # 默认态现状登记（on=重启生产默认）
        monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "on")
        d_on = guard_mod.validate_request(
            system_text="s" * 1000,
            messages=msgs_over,
            meta={"history_budget": 6000, "breaker_active": False},
            audit_file=tmp_path / "h6-on.jsonl",
        )
        assert d_on.verdict == "BLOCK"
        assert d_on.rule == "submit_ratio"

        # enforce 态机制 READY（D-G4 主断言复检）
        monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "enforce")
        d_enforce = guard_mod.validate_request(
            system_text="s" * 1000,
            messages=msgs_over,
            meta={"history_budget": 6000, "breaker_active": False},
            audit_file=tmp_path / "h6-enforce.jsonl",
        )
        assert d_enforce.verdict == "WARN"
        assert d_enforce.rule == "submit_ratio_perf"
        assert d_enforce.audit.get("would_block") is True

        # privacy/safety BLOCK 双态保留（硬门后半句不受影响）
        for mode in ("on", "enforce"):
            monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", mode)
            d_priv = guard_mod.validate_request(
                system_text="key sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890",
                messages=[
                    {"role": "system", "content": "k"},
                    {"role": "user", "content": "hi"},
                ],
                meta={},
                audit_file=tmp_path / f"h6-priv-{mode}.jsonl",
            )
            assert d_priv.verdict == "BLOCK", f"privacy BLOCK 双态保留: mode={mode}"
            assert d_priv.rule == "privacy_leak"
