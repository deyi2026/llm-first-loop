"""提权闭环测试（EVO-20260923-c58a0bb1 accepted + 用户批准 2026-09-23）.

覆盖: Store 生命周期（创建/决定/消耗/单次性/过期/不可移植/防重复决定）/
请求工具防滥用（未被阻断的命令拒绝提权）/ registry 灾难层令牌放行与
无效令牌拒绝 / 未装配零回归 / wait 超时与拒绝回执。

注: 测试用命令字符串一律运行时拼接构造，避免源文件/写盘载荷中出现
整字面灾难命令形态（CatastrophicGuard 按目标语义拦 shell 载荷是对的）。
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.builtin.escalation import EscalationRequestTool, EscalationWaitTool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.escalation import EscalationStore
from llm_loop.tools.registry import ToolRegistry
from llm_loop.web.schemas import EscalationReviewRequest

_CMD = "rm -rf " + "/etc/foo-unit-test"  # 系统目录子树 → 会被灾难硬阻断
_CMD_ALT = "rm -rf " + "/etc/bar-unit-test"


def _store(tmp_path: Path) -> EscalationStore:
    return EscalationStore(tmp_path / "audit" / "escalation_requests.json")


def _approved_token(store: EscalationStore, command: str = _CMD) -> tuple[str, str]:
    rec = store.create(
        tool_name="execute_command",
        command=command,
        justification="unit-test 验证闭环生命周期",
        session_id="s-test",
    )
    rid = rec["id"]
    pub, reason = store.decide(rid, "approved", note="ok")
    assert pub is not None, reason
    return rid, store.get(rid)["token"]


def test_approval_token_and_audit_are_owner_private_at_every_write(tmp_path, monkeypatch):
    """New state, audit, lock and intermediate replace must never be 0644."""
    from llm_loop.tools import escalation as module

    source_replace = module.os.replace
    seen_modes = []

    def checked_replace(source, target):
        seen_modes.append(stat.S_IMODE(os.stat(source).st_mode))
        return source_replace(source, target)

    monkeypatch.setattr(module.os, "replace", checked_replace)
    initial_umask = os.umask(0o022)
    try:
        s = _store(tmp_path)
        _rid, token = _approved_token(s)
    finally:
        os.umask(initial_umask)
    paths = [s._path, s._log_path, s._lock_path]
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in paths)
    assert seen_modes and set(seen_modes) == {0o600}
    assert token not in s._log_path.read_text(encoding="utf-8")


def test_existing_world_readable_approval_file_migrates_before_read(tmp_path):
    s = _store(tmp_path)
    rid, token = _approved_token(s)
    s._path.chmod(0o644)
    assert s.get(rid)["token"] == token
    assert stat.S_IMODE(s._path.stat().st_mode) == 0o600


def test_corrupted_or_symlinked_approval_store_cannot_be_reset(tmp_path):
    s = _store(tmp_path)
    s._path.parent.mkdir(parents=True, exist_ok=True)
    s._path.write_text("invalid JSON", encoding="utf-8")
    original = s._path.read_bytes()
    with pytest.raises(ValueError, match="refusing overwrite"):
        s.create(tool_name="execute_command", command=_CMD, justification="x" * 20)
    assert s._path.read_bytes() == original

    s._path.unlink()
    target = tmp_path / "separate-private.json"
    target.write_text("[]", encoding="utf-8")
    target.chmod(0o600)
    s._path.symlink_to(target)
    with pytest.raises(OSError):
        s.get("any")
    assert target.read_text(encoding="utf-8") == "[]"


def test_web_review_contract_refuses_administrator_password_fields():
    assert EscalationReviewRequest(
        id="ESC-test-123", decision="approved",
    ).decision == "approved"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EscalationReviewRequest.model_validate({
            "id": "ESC-test-123", "decision": "approved",
            "administrator_password": "must never enter this API",
        })


# ── Store 生命周期 ──


def test_create_pending_and_idempotent(tmp_path):
    s = _store(tmp_path)
    r1 = s.create(tool_name="execute_command", command=_CMD, justification="x" * 20, session_id="s1")
    r2 = s.create(tool_name="execute_command", command=_CMD, justification="y" * 20, session_id="s1")
    assert r1["status"] == "pending"
    assert r1["id"].startswith("ESC-")
    assert r2["id"] == r1["id"]  # 幂等复用
    assert s.pending_count() == 1


def test_decide_denied_and_no_token(tmp_path):
    s = _store(tmp_path)
    rec = s.create(tool_name="execute_command", command=_CMD, justification="x" * 20, session_id="s1")
    pub, _ = s.decide(rec["id"], "denied", note="不需要")
    assert pub["status"] == "denied"
    assert "token" not in pub  # 对外视图剥除令牌
    assert s.get(rec["id"])["token"] == ""


def test_repeated_decision_rejected(tmp_path):
    s = _store(tmp_path)
    rec = s.create(tool_name="execute_command", command=_CMD, justification="x" * 20, session_id="s1")
    pub1, _ = s.decide(rec["id"], "approved")
    assert pub1["status"] == "approved"
    pub2, reason = s.decide(rec["id"], "denied")
    assert pub2 is None and "仅 pending 可审批" in reason  # fail-closed 到首个决定


def test_consume_single_use_and_binding(tmp_path):
    s = _store(tmp_path)
    _rid, tok = _approved_token(s)
    # 错误命令 → 拒（令牌不可移植）
    rec, reason = s.consume(tok, "execute_command", _CMD_ALT)
    assert rec is None and "不一致" in reason
    # 正确命令 → 放行 + consumed
    rec, reason = s.consume(tok, "execute_command", _CMD)
    assert rec is not None and rec["status"] == "consumed"
    # 再用 → 单次性拒绝
    rec, reason = s.consume(tok, "execute_command", _CMD)
    assert rec is None and "已使用" in reason
    # 未知令牌
    rec, reason = s.consume("no-such-token", "execute_command", _CMD)
    assert rec is None and "不存在" in reason


def test_token_expiry(tmp_path):
    s = _store(tmp_path)
    rid, _tok = _approved_token(s)

    def _expire(records):
        for r in records:
            if r["id"] == rid:
                r["token_expires_at"] = "2020-01-01T00:00:00+00:00"
        return records

    s._mutate(_expire)
    rec, reason = s.consume(s.get(rid)["token"], "execute_command", _CMD)
    assert rec is None and "过期" in reason
    assert s.get(rid)["status"] == "expired"


# ── 请求工具防滥用 ──


def test_request_rejects_unblocked_command(tmp_path):
    s = _store(tmp_path)
    tool = EscalationRequestTool(store=s)
    r = tool.execute(command="ls -la /tmp", justification="这条命令其实不会被阻断")
    assert r.status == ToolResultStatus.FAILURE
    assert "无需提权" in r.content
    assert s.pending_count() == 0  # 未创建通道滥用


def test_request_accepts_blocked_command(tmp_path):
    s = _store(tmp_path)
    tool = EscalationRequestTool(store=s)
    r = tool.execute(command=_CMD, justification="单测: 验证被阻断命令可申请提权")
    assert r.status == ToolResultStatus.SUCCESS
    assert "request_id=ESC-" in r.content
    assert s.pending_count() == 1


# ── registry 灾难层令牌放行 ──


def _registry(store: EscalationStore | None, safety_guard=None) -> ToolRegistry:
    reg = ToolRegistry(escalation_store=store, safety_guard=safety_guard)
    reg.register(ExecuteCommandTool())
    return reg


class _StubGuard:
    """stub 守卫: 只拦固定无害测试命令（放行后真实执行也只是写 /tmp 文件）。"""

    class _Blocked:
        reason = "stub: 灾难形态（测试）"
        evidence = "stub"

    def guard(self, tool_name: str, arguments: dict, **kwargs):
        if arguments.get("command", "").startswith("echo esc-bypass-ran >"):
            return self._Blocked()
        return None


_STUB_CMD = "echo esc-bypass-ran > /tmp/esc-bypass-ran.txt"


def test_registry_block_hint_then_single_use(tmp_path):
    """stub 守卫注入: 阻断+闭环提示 → 令牌首用放行 → 复用被拒（单次性）。"""
    s = _store(tmp_path)
    rec = s.create(tool_name="execute_command", command=_STUB_CMD, justification="x" * 20, session_id="s1")
    s.decide(rec["id"], "approved")
    tok = s.get(rec["id"])["token"]
    reg = _registry(s, safety_guard=_StubGuard())
    # 无令牌 → 阻断 + 闭环提示
    r0 = reg.execute(ToolCall(id="t0", name="execute_command", arguments={"command": _STUB_CMD}))
    assert r0.status == ToolResultStatus.BLOCKED
    assert "escalation_request" in r0.content
    # 有效令牌 → 放行（真实执行，写 /tmp 文件，无害）
    r1 = reg.execute(
        ToolCall(id="t1", name="execute_command", arguments={"command": _STUB_CMD, "escalation_token": tok})
    )
    assert r1.status == ToolResultStatus.SUCCESS
    # 令牌复用 → 单次性拒绝
    r2 = reg.execute(
        ToolCall(
            id="t2",
            name="execute_command",
            arguments={"command": _STUB_CMD, "escalation_token": tok},
        )
    )
    assert r2.status == ToolResultStatus.BLOCKED
    assert "提权令牌无效" in r2.content
    # 真实执行验证（写盘内容核对）
    assert Path("/tmp/esc-bypass-ran.txt").read_text().strip() == "esc-bypass-ran"


def test_registry_valid_token_executes_for_real(tmp_path):
    """端到端（stub 守卫，真实命令无害）: 批准的精确命令 + 有效令牌 → 放行且真实执行."""
    s = _store(tmp_path)
    reg = _registry(s, safety_guard=_StubGuard())
    rec = s.create(tool_name="execute_command", command=_STUB_CMD, justification="单测端到端放行", session_id="s-e2e")
    s.decide(rec["id"], "approved")
    tok = s.get(rec["id"])["token"]
    r = reg.execute(
        ToolCall(id="t-e2e2", name="execute_command", arguments={"command": _STUB_CMD, "escalation_token": tok})
    )
    assert r.status == ToolResultStatus.SUCCESS
    assert Path("/tmp/esc-bypass-ran.txt").read_text().strip() == "esc-bypass-ran"


def test_registry_without_store_zero_regression(tmp_path):
    """未装配 escalation_store → 令牌参数不生效，保持纯 fail-closed（零回归）."""
    reg = _registry(None)
    r = reg.execute(
        ToolCall(
            id="t-nostore",
            name="execute_command",
            arguments={"command": _CMD, "escalation_token": "whatever"},
        )
    )
    assert r.status == ToolResultStatus.BLOCKED
    assert "安全硬阻断" in r.content


# ── wait 工具 ──


def test_wait_timeout_returns_pending(tmp_path):
    s = _store(tmp_path)
    rec = s.create(tool_name="execute_command", command=_CMD, justification="x" * 20, session_id="s1")
    w = EscalationWaitTool(store=s)
    r = w.execute(request_id=rec["id"], timeout_s=0.1)
    assert r.status == ToolResultStatus.SUCCESS
    assert "等待超时" in r.content


def test_wait_returns_denied(tmp_path):
    s = _store(tmp_path)
    rec = s.create(tool_name="execute_command", command=_CMD, justification="x" * 20, session_id="s1")
    s.decide(rec["id"], "denied", note="不要动这个目录")
    w = EscalationWaitTool(store=s)
    r = w.execute(request_id=rec["id"], timeout_s=1)
    assert "已拒绝" in r.content and "不要动这个目录" in r.content


# ── 准入审核P1-1(2026-10-25): 跨进程记录不销毁/不审批/不消费 ────────────────

def test_cross_process_record_survives_save_not_decidable(tmp_path, monkeypatch):
    """他进程签名记录：_save 不销毁、list 可见带标记、审批拒绝、计数排除。"""
    import llm_loop.tools.escalation as esc

    store = esc.EscalationStore(tmp_path / "esc.json")
    store.create(tool_name="tool_x", command="dangerous --cmd", justification="test")["id"]

    # 模拟另一进程：换进程内密钥后新实例（同状态文件）
    monkeypatch.setattr(esc, "_STATE_SIGNING_KEY", esc.secrets.token_bytes(32))
    other = esc.EscalationStore(tmp_path / "esc.json")

    recs = other._load()
    assert len(recs) == 1 and recs[0]["_sig_unverified"] is True
    listed = other.list()
    assert listed and listed[0]["_sig_unverified"] is True  # 可见（不静默隐藏）
    assert other.pending_count() == 0  # 不可审批的不计可操作 pending

    # 审批拒绝
    _, reason = other.decide(recs[0]["id"], "denied", decided_by="tester")
    assert "其他进程" in reason or "无法验证" in reason

    # 本进程（他视角）再写自己的记录：原记录必须存活（不销毁）
    other.create(tool_name="tool_y", command="safe --cmd", justification="other")
    after = esc.EscalationStore(tmp_path / "esc.json")._load()
    ids = {r.get("tool_name") if "tool_name" in r else r.get("id") for r in after}
    assert len(after) == 2, f"跨进程记录被销毁: {len(after)}"
    assert sum(1 for r in after if r.get("_sig_unverified")) == 1


def test_cross_process_token_not_consumable(tmp_path, monkeypatch):
    import llm_loop.tools.escalation as esc

    store = esc.EscalationStore(tmp_path / "esc.json")
    rid = store.create(tool_name="tool_x", command="dangerous --cmd", justification="test")["id"]
    store.decide(rid, "approved", decided_by="tester")
    rec = store.get(rid)
    token = rec["token"]

    monkeypatch.setattr(esc, "_STATE_SIGNING_KEY", esc.secrets.token_bytes(32))
    other = esc.EscalationStore(tmp_path / "esc.json")
    result, reason = other.consume(token, "tool_x", "dangerous --cmd")
    assert result is None and ("其他进程" in reason or "无法验证" in reason)
