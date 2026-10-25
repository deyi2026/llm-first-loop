"""P1-1（独立准入审核第四轮）回归: registry 路径 argv + 提权令牌端到端.

缺陷背景: registry 灾难层既有消费块按 args["command"] 取空串消费 argv 调用的
令牌（command-sha 永不匹配 → 已批准 (escalation_id, escalation_token) 永远被拒）；
且若本层消费成功，工具层 consume_for_execution 会再次消费（双重消耗）。

修复语义（对齐验收）:
- arguments 携带 escalation_id（任何模式）或 argv+令牌 → registry 完全 defer
  工具层（_escalation_deferred_to_tool；本层零消费，工具层唯一消费点）;
- command 模式单传 escalation_token（无 id）→ registry 层既有 consume 闭环不变
  （哈希键经 _command_text_for_guard 与工具层单一事实源对齐）;
- 无令牌 argv 灾难命令 → registry 层拦截（既有行为保持）。

纪律: 灾难样本运行时拼接（源文件不落整字面灾难形态）；真实执行面被
monkeypatch 记录，任何用例都不会真的执行 rm。
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

import llm_loop.tools.builtin.execute_command as ec_module
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.escalation import EscalationStore
from llm_loop.tools.registry import ToolRegistry, _escalation_deferred_to_tool

# 灾难样本运行时拼接（对齐 tests/test_execute_argv_and_override.py 惯例）
_SYS_DIR = "/etc" + "/argv-esc-reg-unit"  # 系统目录子树 → 灾难级
_SYS_DIR_ALT = "/etc" + "/argv-esc-reg-alt"
_ARGV = ["rm", "-rf", _SYS_DIR]
_ARGV_TEXT = shlex.join(_ARGV)  # 守卫/哈希绑定的统一文本基准
_CMD = "rm -rf " + _SYS_DIR_ALT


def _make(tmp_path: Path) -> tuple[ToolRegistry, ExecuteCommandTool, EscalationStore]:
    """registry + 工具共享同一 escalation store（镜像生产: 同一 audit 文件）."""
    store = EscalationStore(tmp_path / "audit" / "escalation_requests.json")
    tool = ExecuteCommandTool(escalation_store=store, safety_audit_dir=tmp_path / "audit")
    reg = ToolRegistry(escalation_store=store)
    reg.register(tool)
    return reg, tool, store


def _approve(store: EscalationStore, command: str) -> tuple[str, str]:
    """构造一条已人工批准的提权记录，返回 (request_id, token)."""
    rec = store.create(
        tool_name="execute_command",
        command=command,
        justification="unit-test P1-1 registry 路径 argv 提权闭环",
        session_id="s-argv-reg",
    )
    pub, reason = store.decide(rec["id"], "approved", note="unit-test")
    assert pub is not None, reason
    out = store.get(rec["id"])
    assert out is not None
    return rec["id"], out["token"]


def _status(store: EscalationStore, rid: str) -> str:
    """读记录状态（记录缺失直接让断言失败，避免 Optional 下标）."""
    rec = store.get(rid)
    assert rec is not None
    return str(rec["status"])


class _FakeProc:
    """记录型假进程: communicate 立即成功，绝不真实执行任何命令."""

    returncode = 0

    def communicate(self, timeout=None):  # noqa: ANN001
        return ("", "")

    def poll(self):  # noqa: ANN201
        return 0

    def wait(self, timeout=None):  # noqa: ANN001
        return 0

    def kill(self):  # noqa: ANN201
        pass


@pytest.fixture
def record_popen(monkeypatch):
    """monkeypatch 模块级 subprocess.Popen → 记录 argv、返回假进程."""
    calls: list = []

    def _fake(args, **kwargs):  # noqa: ANN001
        calls.append(args)
        return _FakeProc()

    monkeypatch.setattr(ec_module.subprocess, "Popen", _fake)
    return calls


@pytest.fixture
def consumption_counts(monkeypatch):
    """store 实例的 consume/consume_for_execution 调用计数器工厂.

    用法: counts = consumption_counts(store) → dict 计数。
    """

    def _install(store: EscalationStore) -> dict[str, int]:
        counts = {"consume": 0, "consume_for_execution": 0}
        orig_consume = store.consume
        orig_cfe = store.consume_for_execution

        def _consume(*a, **k):  # noqa: ANN002, ANN003
            counts["consume"] += 1
            return orig_consume(*a, **k)

        def _cfe(*a, **k):  # noqa: ANN002, ANN003
            counts["consume_for_execution"] += 1
            return orig_cfe(*a, **k)

        monkeypatch.setattr(store, "consume", _consume)
        monkeypatch.setattr(store, "consume_for_execution", _cfe)
        return counts

    return _install


# ── A. defer 谓词矩阵（单元级） ──


def test_defer_predicate_matrix() -> None:
    """escalation 裁决归属矩阵: id/argv+token → 工具层；command+token-only → registry."""
    # 携带 escalation_id（任何模式）→ defer 工具层
    assert _escalation_deferred_to_tool(
        "execute_command", {"command": "x", "escalation_id": "ESC-1"}
    )
    assert _escalation_deferred_to_tool(
        "execute_command", {"argv": ["rm"], "escalation_id": "ESC-1", "escalation_token": "t"}
    )
    # argv + 令牌（无 id 的不完整形态）→ defer 工具层兜底阻断（本层不烧令牌）
    assert _escalation_deferred_to_tool(
        "execute_command", {"argv": ["rm"], "escalation_token": "t"}
    )
    # command 模式单传 token（既有闭环）→ registry 层裁决
    assert not _escalation_deferred_to_tool(
        "execute_command", {"command": "x", "escalation_token": "t"}
    )
    # 无 escalation 参数 → registry 路径不变（含 argv 无令牌: registry 层拦截）
    assert not _escalation_deferred_to_tool("execute_command", {"argv": ["rm", "-rf", "/"]})
    assert not _escalation_deferred_to_tool("execute_command", {"command": "x"})
    # 其余破坏性工具（无工具层消费路径）永不 defer
    assert not _escalation_deferred_to_tool(
        "delete_file", {"command": "x", "escalation_id": "ESC-1", "escalation_token": "t"}
    )
    # 边界: 空白 id / 空 argv / 空令牌不构成 defer
    assert not _escalation_deferred_to_tool(
        "execute_command", {"command": "x", "escalation_id": "  "}
    )
    assert not _escalation_deferred_to_tool(
        "execute_command", {"argv": [], "escalation_token": "t"}
    )
    assert not _escalation_deferred_to_tool(
        "execute_command", {"argv": ["rm"], "escalation_token": ""}
    )


# ── B. registry 路径 argv + 有效令牌 → 放行（端到端） ──


def test_registry_argv_valid_token_executes_once(tmp_path, record_popen, consumption_counts):
    """argv 破坏性命令 + 有效 (escalation_id, token) 经 ToolRegistry → 放行执行;
    全链路恰好一次 consume_for_execution，registry 层零 consume; 重放被拒."""
    reg, _, store = _make(tmp_path)
    counts = consumption_counts(store)
    rid, tok = _approve(store, _ARGV_TEXT)
    r1 = reg.execute(
        ToolCall(
            id="t1",
            name="execute_command",
            arguments={"argv": _ARGV, "escalation_id": rid, "escalation_token": tok},
        )
    )
    assert r1.status == ToolResultStatus.SUCCESS, r1.content
    assert record_popen == [_ARGV]  # 执行面收到的是 argv 本体（不经 shell）
    assert f'guard_override="escalation:{rid}"' in r1.content
    assert _status(store, rid) == "consumed"
    # 单一消费点: registry 零 consume、工具层恰好一次 consume_for_execution
    assert counts["consume"] == 0
    assert counts["consume_for_execution"] == 1
    # 单次性: 同 (id, token) 重放 → 拒绝，执行面不再被调用
    r2 = reg.execute(
        ToolCall(
            id="t2",
            name="execute_command",
            arguments={"argv": _ARGV, "escalation_id": rid, "escalation_token": tok},
        )
    )
    assert r2.status == ToolResultStatus.BLOCKED
    assert "已使用过" in r2.content
    assert len(record_popen) == 1


def test_registry_command_mode_id_token_single_consumption(
    tmp_path, record_popen, consumption_counts
):
    """command 模式 + (escalation_id, token) 经 ToolRegistry → 放行且无双重消耗
    （修复前: registry consume 成功后工具层 consume_for_execution 报"已使用过"）."""
    reg, _, store = _make(tmp_path)
    counts = consumption_counts(store)
    rid, tok = _approve(store, _CMD)
    r = reg.execute(
        ToolCall(
            id="t3",
            name="execute_command",
            arguments={"command": _CMD, "escalation_id": rid, "escalation_token": tok},
        )
    )
    assert r.status == ToolResultStatus.SUCCESS, r.content
    assert record_popen == [_CMD]  # shell 模式: 字符串目标
    assert f'guard_override="escalation:{rid}"' in r.content
    assert _status(store, rid) == "consumed"
    assert counts["consume"] == 0
    assert counts["consume_for_execution"] == 1
    # 重放 → 已使用过（单次性由唯一消费点保证）
    r2 = reg.execute(
        ToolCall(
            id="t3b",
            name="execute_command",
            arguments={"command": _CMD, "escalation_id": rid, "escalation_token": tok},
        )
    )
    assert r2.status == ToolResultStatus.BLOCKED
    assert "已使用过" in r2.content


def test_registry_command_mode_token_only_keeps_legacy_loop(
    tmp_path, record_popen, consumption_counts
):
    """command 模式单传 escalation_token（无 id）→ registry 层既有 consume 闭环不变
    （工具层让位; 哈希键经 _command_text_for_guard 与原行为逐字等价）."""
    reg, _, store = _make(tmp_path)
    counts = consumption_counts(store)
    rid, tok = _approve(store, _CMD)
    r = reg.execute(
        ToolCall(
            id="t4",
            name="execute_command",
            arguments={"command": _CMD, "escalation_token": tok},
        )
    )
    assert r.status == ToolResultStatus.SUCCESS, r.content
    assert record_popen == [_CMD]
    assert _status(store, rid) == "consumed"
    assert counts["consume"] == 1  # registry 层消费（既有闭环）
    assert counts["consume_for_execution"] == 0  # 工具层让位，未二次消费


# ── C. registry 路径无效/不完整令牌 → 拒绝 ──


def test_registry_argv_forged_credentials_blocked_no_burn(
    tmp_path, record_popen, consumption_counts
):
    """伪造令牌 / 不存在的 escalation_id → 拒绝（可诊断错误信息），令牌不烧."""
    reg, _, store = _make(tmp_path)
    counts = consumption_counts(store)
    rid, tok = _approve(store, _ARGV_TEXT)
    r1 = reg.execute(
        ToolCall(
            id="t5",
            name="execute_command",
            arguments={"argv": _ARGV, "escalation_id": rid, "escalation_token": "forged-token"},
        )
    )
    assert r1.status == ToolResultStatus.BLOCKED
    assert "不匹配" in r1.content
    r2 = reg.execute(
        ToolCall(
            id="t5b",
            name="execute_command",
            arguments={
                "argv": _ARGV,
                "escalation_id": "ESC-20990101-deadbeef",
                "escalation_token": tok,
            },
        )
    )
    assert r2.status == ToolResultStatus.BLOCKED
    assert "不存在" in r2.content
    assert record_popen == []
    # 拒绝路径不烧令牌: 记录仍 approved，原 (id, token) 仍可用
    assert _status(store, rid) == "approved"
    r3 = reg.execute(
        ToolCall(
            id="t5c",
            name="execute_command",
            arguments={"argv": _ARGV, "escalation_id": rid, "escalation_token": tok},
        )
    )
    assert r3.status == ToolResultStatus.SUCCESS, r3.content
    assert counts["consume"] == 0


def test_registry_argv_token_without_id_blocked_no_burn(tmp_path, record_popen, consumption_counts):
    """argv + escalation_token 但缺 escalation_id（schema 声明 argv 下须成对）→
    工具层兜底阻断（成对才可能覆盖），全链路零消费、令牌不烧."""
    reg, _, store = _make(tmp_path)
    counts = consumption_counts(store)
    rid, tok = _approve(store, _ARGV_TEXT)
    r = reg.execute(
        ToolCall(
            id="t6",
            name="execute_command",
            arguments={"argv": _ARGV, "escalation_token": tok},
        )
    )
    assert r.status == ToolResultStatus.BLOCKED
    assert "E6_CATASTROPHIC_HARD" in r.content
    assert record_popen == []
    assert counts["consume"] == 0
    assert counts["consume_for_execution"] == 0
    assert _status(store, rid) == "approved"  # 不完整形态不消耗令牌


def test_registry_argv_command_hash_binding(tmp_path, record_popen):
    """argv 形态令牌绑定批准时精确命令哈希: 执行另一条灾难命令 → 拒绝且不烧令牌."""
    reg, _, store = _make(tmp_path)
    rid, tok = _approve(store, _ARGV_TEXT)
    r = reg.execute(
        ToolCall(
            id="t7",
            name="execute_command",
            arguments={
                "argv": ["rm", "-rf", _SYS_DIR_ALT],
                "escalation_id": rid,
                "escalation_token": tok,
            },
        )
    )
    assert r.status == ToolResultStatus.BLOCKED
    assert "命令与审批时不一致" in r.content
    assert record_popen == []
    # 错配不烧令牌: 原命令仍可使用该令牌
    r2 = reg.execute(
        ToolCall(
            id="t7b",
            name="execute_command",
            arguments={"argv": _ARGV, "escalation_id": rid, "escalation_token": tok},
        )
    )
    assert r2.status == ToolResultStatus.SUCCESS, r2.content


# ── D. 无令牌 argv 灾难命令 → registry 层拦截（既有行为保持） ──


def test_registry_argv_no_token_blocked_at_registry(tmp_path, record_popen, consumption_counts):
    """无令牌 argv 灾难命令 → registry 层拦截（非工具层兜底），零执行、零消费.

    区分依据: registry 层阻断文案不含 "exec_mode=argv"（该标记仅工具层
    兜底文案携带），且含既有 [安全硬阻断][E6_CATASTROPHIC_HARD] 前缀。
    """
    reg, _, store = _make(tmp_path)
    counts = consumption_counts(store)
    r = reg.execute(ToolCall(id="t8", name="execute_command", arguments={"argv": _ARGV}))
    assert r.status == ToolResultStatus.BLOCKED
    assert "[安全硬阻断]" in r.content and "E6_CATASTROPHIC_HARD" in r.content
    assert "exec_mode=argv" not in r.content  # registry 层拦截，未落到工具层文案
    assert record_popen == []
    assert counts["consume"] == 0
    assert counts["consume_for_execution"] == 0
