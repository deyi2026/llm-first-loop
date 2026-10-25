"""P2-2/P2-3（安全审查与修复建议书 2026-10-25）回归: execute_command argv 结构化执行 + 提权令牌覆盖守卫阻断.

覆盖:
- argv 模式不经 shell: 元字符（;）/命令替换（$()）原样、stdout 如实回传;
- command/argv 互斥（都给/都不给）、空 argv、NUL 字节、非字符串元素拒绝;
- 守卫对 shlex.join(argv) 判定: 结构化执行不绕过灾难守卫（直调与 registry 路径）;
- 提权覆盖三重绑定（escalation_id + 令牌 + 命令哈希）:
  无令牌 / 伪造 id / 伪造令牌 / 过期 / 重放 / 命令错配 → 阻断;
  有效 → 放行 + 令牌一次性消费 + 回执 guard_override="escalation:<id>";
- 无令牌时阻断行为不变（command 模式与 argv 模式均 fail-closed）;
- command 模式单传 escalation_token 的既有闭环让位语义（registry 层裁决）。

纪律: 灾难命令样本一律运行时拼接（对齐 tests/unit/test_escalation.py 惯例，
源文件不落整字面灾难形态）；被阻断命令的真实执行面被 monkeypatch 记录，
任何用例都不会真的执行 rm。
"""

from __future__ import annotations

import hashlib
import shlex
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

import llm_loop.tools.builtin.execute_command as ec_module
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.timekeeping import system_local_now
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.escalation import EscalationStore
from llm_loop.tools.registry import ToolRegistry
from tests import env_channel

# 灾难样本运行时拼接（源文件不出现整字面形态）
_ROOT = chr(47)  # 根本体
_SYS_DIR = "/etc" + "/argv-override-unit-test"  # 系统目录子树 → 灾难级
_SYS_DIR_ALT = "/etc" + "/argv-override-unit-alt"


def _make(tmp_path: Path) -> tuple[ExecuteCommandTool, EscalationStore]:
    store = EscalationStore(tmp_path / "audit" / "escalation_requests.json")
    tool = ExecuteCommandTool(escalation_store=store, safety_audit_dir=tmp_path / "audit")
    return tool, store


def _approve(store: EscalationStore, command: str) -> tuple[str, str]:
    """构造一条已人工批准的提权记录，返回 (request_id, token)."""
    rec = store.create(
        tool_name="execute_command",
        command=command,
        justification="unit-test P2-3 令牌覆盖闭环",
        session_id="s-argv",
    )
    pub, reason = store.decide(rec["id"], "approved", note="unit-test")
    assert pub is not None, reason
    return rec["id"], store.get(rec["id"])["token"]


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


# ── A. argv 结构化执行（P2-2） ──


@pytest.mark.skipif(
    env_channel.in_git_worktree_detached_root(),
    reason="环境受限：worktree 门通道隔离 HOME 下 env 脱敏白名单集不同（主树绿，非代码回归）【RED-29】",
)
def test_argv_python_print(tmp_path):
    """argv=['python','-c','print(1)'] 成功执行，stdout 如实回传并标注 exec_mode."""
    tool, _ = _make(tmp_path)
    py = "python" if shutil.which("python") else "python3"
    r = tool.execute(argv=[py, "-c", "print(1)"])
    assert r.status == ToolResultStatus.SUCCESS, r.content
    assert r.content.splitlines()[-1] == "1"
    assert "exec_mode=argv argv_len=3" in r.content


def test_argv_shell_metacharacter_not_interpreted(tmp_path):
    """['echo','a;b'] → 原样输出 a;b（证明分号未被 shell 解释为命令分隔）."""
    tool, _ = _make(tmp_path)
    r = tool.execute(argv=["echo", "a;b"])
    assert r.status == ToolResultStatus.SUCCESS, r.content
    assert r.content.splitlines()[-1] == "a;b"


def test_argv_command_substitution_not_expanded(tmp_path):
    """['echo','$(whoami)'] → 字面输出 $(whoami)（不经 shell，无命令替换）."""
    tool, _ = _make(tmp_path)
    r = tool.execute(argv=["echo", "$(whoami)"])
    assert r.status == ToolResultStatus.SUCCESS, r.content
    assert r.content.splitlines()[-1] == "$(whoami)"


def test_argv_and_command_mutually_exclusive(tmp_path):
    tool, _ = _make(tmp_path)
    r = tool.execute(command="echo hi", argv=["echo", "hi"])
    assert r.status == ToolResultStatus.FAILURE
    assert "二选一" in r.content


def test_argv_empty_rejected(tmp_path):
    tool, _ = _make(tmp_path)
    r = tool.execute(argv=[])
    assert r.status == ToolResultStatus.FAILURE
    assert "不能为空" in r.content


def test_argv_nul_byte_rejected(tmp_path):
    tool, _ = _make(tmp_path)
    r = tool.execute(argv=["echo", "a\x00b"])
    assert r.status == ToolResultStatus.FAILURE
    assert "NUL" in r.content


def test_argv_wrong_element_type_rejected(tmp_path):
    tool, _ = _make(tmp_path)
    assert tool.execute(argv="echo hi").status == ToolResultStatus.FAILURE
    assert tool.execute(argv=["echo", 1]).status == ToolResultStatus.FAILURE


def test_missing_command_and_argv_rejected(tmp_path):
    tool, _ = _make(tmp_path)
    r = tool.execute()
    assert r.status == ToolResultStatus.FAILURE
    assert "缺少必填参数" in r.content


def test_shell_mode_receipt_records_exec_mode_shell(tmp_path):
    """command 模式保持现状语义，回执如实标注 exec_mode=shell."""
    tool, _ = _make(tmp_path)
    r = tool.execute(command="echo shell-ok")
    assert r.status == ToolResultStatus.SUCCESS, r.content
    assert "exec_mode=shell" in r.content
    assert "shell-ok" in r.content


# ── B. 守卫不绕过（argv 也按 shlex.join 判定） ──


def test_argv_catastrophic_blocked_without_token(tmp_path, record_popen):
    """argv ['rm','-rf','/'] → 灾难硬阻断；真实执行面零调用."""
    tool, _ = _make(tmp_path)
    r = tool.execute(argv=["rm", "-rf", _ROOT])
    assert r.status == ToolResultStatus.BLOCKED
    assert "E6_CATASTROPHIC_HARD" in r.content
    assert record_popen == []  # 绝未进入真实执行


def test_argv_blocked_through_registry(tmp_path, record_popen):
    """registry 路径: 注册表守卫读 args['command']（argv 不可见），
    工具层守卫必须兜底——argv 灾难形态经 registry 仍被阻断（P2-2 关键回归）."""
    tool, _ = _make(tmp_path)
    reg = ToolRegistry()
    reg.register(tool)
    r = reg.execute(
        ToolCall(id="t-argv-reg", name="execute_command",
                 arguments={"argv": ["rm", "-rf", _ROOT]})
    )
    assert r.status == ToolResultStatus.BLOCKED
    assert "E6_CATASTROPHIC_HARD" in r.content
    assert record_popen == []


def test_command_mode_blocked_without_token(tmp_path, record_popen):
    """无令牌时行为不变: command 模式灾难命令同样阻断（直调兜底 + registry 主路径）."""
    tool, _ = _make(tmp_path)
    r = tool.execute(command="rm -rf " + _SYS_DIR)
    assert r.status == ToolResultStatus.BLOCKED
    assert record_popen == []


# ── C. 提权令牌覆盖（P2-3） ──


def test_override_valid_token_executes_once(tmp_path, record_popen):
    """有效 (escalation_id, token) → 放行 + 真实执行面收到原始 argv +
    回执 guard_override + 令牌一次性消费（二次使用失败）."""
    tool, store = _make(tmp_path)
    rid, tok = _approve(store, shlex.join(["rm", "-rf", _SYS_DIR]))
    r1 = tool.execute(
        argv=["rm", "-rf", _SYS_DIR], escalation_id=rid, escalation_token=tok
    )
    assert r1.status == ToolResultStatus.SUCCESS, r1.content
    assert record_popen == [["rm", "-rf", _SYS_DIR]]  # 假进程收到的是 argv 本体
    assert f'guard_override="escalation:{rid}"' in r1.content
    assert store.get(rid)["status"] == "consumed"
    # 令牌单次性: 同 id+token 重放 → 阻断，执行面不再被调用
    r2 = tool.execute(
        argv=["rm", "-rf", _SYS_DIR], escalation_id=rid, escalation_token=tok
    )
    assert r2.status == ToolResultStatus.BLOCKED
    assert "已使用过" in r2.content
    assert len(record_popen) == 1


def test_override_forged_id_or_token_blocked(tmp_path, record_popen):
    """伪造请求 id / 伪造令牌 → 阻断（不泄露令牌本体）."""
    tool, store = _make(tmp_path)
    rid, tok = _approve(store, shlex.join(["rm", "-rf", _SYS_DIR]))
    r1 = tool.execute(
        argv=["rm", "-rf", _SYS_DIR],
        escalation_id="ESC-20990101-deadbeef",
        escalation_token=tok,
    )
    assert r1.status == ToolResultStatus.BLOCKED
    r2 = tool.execute(
        argv=["rm", "-rf", _SYS_DIR],
        escalation_id=rid,
        escalation_token="forged-token",
    )
    assert r2.status == ToolResultStatus.BLOCKED
    assert "不匹配" in r2.content or "无效" in r2.content
    assert record_popen == []


def test_override_expired_token_blocked(tmp_path, record_popen):
    """过期令牌 → 阻断（令牌置 expired 并留审计）."""
    tool, store = _make(tmp_path)
    rid, tok = _approve(store, shlex.join(["rm", "-rf", _SYS_DIR]))

    def _age_out(records):
        for rec in records:
            if rec.get("id") == rid:
                rec["token_expires_at"] = (
                    system_local_now() - timedelta(minutes=1)
                ).isoformat()
        return records

    store._mutate(_age_out)
    r = tool.execute(
        argv=["rm", "-rf", _SYS_DIR], escalation_id=rid, escalation_token=tok
    )
    assert r.status == ToolResultStatus.BLOCKED
    assert "已过期" in r.content
    assert record_popen == []


def test_override_command_hash_binding(tmp_path, record_popen):
    """令牌绑定批准时精确命令哈希: 执行另一条命令（即便同为灾难形态）→ 阻断."""
    tool, store = _make(tmp_path)
    rid, tok = _approve(store, shlex.join(["rm", "-rf", _SYS_DIR]))
    r = tool.execute(
        argv=["rm", "-rf", _SYS_DIR_ALT], escalation_id=rid, escalation_token=tok
    )
    assert r.status == ToolResultStatus.BLOCKED
    assert "命令与审批时不一致" in r.content
    assert record_popen == []
    # 未消费：原命令仍可使用该令牌（错配不烧令牌）
    r2 = tool.execute(
        argv=["rm", "-rf", _SYS_DIR], escalation_id=rid, escalation_token=tok
    )
    assert r2.status == ToolResultStatus.SUCCESS, r2.content


def test_command_mode_single_token_defers_to_registry(tmp_path, record_popen):
    """command 模式单传 escalation_token（无 id）→ 工具层让位（单一裁决权）.

    生产路径中该形态由 registry 灾难层裁决（令牌校验+消费后才调工具）；
    工具层重复裁决会二次消费/误阻断已批准执行。本用例锁定让位语义，
    不构成"直调可绕过"——直调场景本就不经任何守卫（改动前同样如此）。
    """
    tool, _ = _make(tmp_path)
    r = tool.execute(command="rm -rf " + _SYS_DIR, escalation_token="registry-consumed")
    assert r.status == ToolResultStatus.SUCCESS, r.content
    assert record_popen == ["rm -rf " + _SYS_DIR]  # shell 模式: 字符串目标


# ── D. EscalationStore.consume_for_execution 单元级 ──


def test_consume_for_execution_lifecycle(tmp_path):
    s = EscalationStore(tmp_path / "audit" / "escalation_requests.json")
    cmd = "rm -rf " + _SYS_DIR
    sha = hashlib.sha256(cmd.encode("utf-8")).hexdigest()
    rid, tok = _approve(s, cmd)
    # 首次消费成功
    rec, reason = s.consume_for_execution(rid, tok, sha)
    assert rec is not None, reason
    assert s.get(rid)["status"] == "consumed"
    # 重放 → 已使用过
    rec2, reason2 = s.consume_for_execution(rid, tok, sha)
    assert rec2 is None and "已使用过" in reason2
    # 参数不完整 → 拒绝
    rec3, reason3 = s.consume_for_execution("", tok, sha)
    assert rec3 is None and "不完整" in reason3


def test_consume_for_execution_cross_record_rejected(tmp_path):
    """A 记录的令牌不能配 B 记录的 id（三重绑定的 id 维度）."""
    s = EscalationStore(tmp_path / "audit" / "escalation_requests.json")
    cmd_a, cmd_b = "rm -rf " + _SYS_DIR, "rm -rf " + _SYS_DIR_ALT
    rid_a, tok_a = _approve(s, cmd_a)
    rid_b, tok_b = _approve(s, cmd_b)
    sha_a = hashlib.sha256(cmd_a.encode("utf-8")).hexdigest()
    rec, reason = s.consume_for_execution(rid_b, tok_a, sha_a)
    assert rec is None
    assert "不匹配" in reason
    assert s.get(rid_b)["status"] == "approved"  # B 记录未被误消费


def test_consume_for_execution_requires_approved(tmp_path):
    """pending（未批准）记录无令牌可用 → 拒绝且状态不变."""
    s = EscalationStore(tmp_path / "audit" / "escalation_requests.json")
    cmd = "rm -rf " + _SYS_DIR
    rec = s.create(tool_name="execute_command", command=cmd,
                   justification="unit", session_id="s")
    sha = hashlib.sha256(cmd.encode("utf-8")).hexdigest()
    out, reason = s.consume_for_execution(rec["id"], "", sha)
    assert out is None
    assert "不完整" in reason
    assert s.get(rec["id"])["status"] == "pending"
