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

    def static_rewrite_hint(self, command: str, **kwargs) -> str:
        """契约：真实守卫会为可改写形态补「先落盘再执行」（RULE-AI-36 回执侧）.

        stub 返回空串即可——本用例只关心阻断/提权闭环，不关心改写建议。
        """
        return ""


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


# ── HostCapabilityGrant（DESIGN-20261107 §6.2/§6.2.1/§6.3）──────────────────
# 独立于 EscalationStore：宿主能力授权精确到 canonical path + 操作 + 工具 +
# 会话；持久化单条一文件 + append-only 审计哈希链；fail-closed 安全校验。


def _grant_store(tmp_path: Path) -> Path:

    return tmp_path / "grants-home"


def test_grant_issue_and_consume_one_shot(tmp_path: Path) -> None:
    import llm_loop.tools.escalation as esc

    target = tmp_path / "outside" / "notes.txt"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    store = esc.HostCapabilityGrantStore(_grant_store(tmp_path))
    grant = store.issue(
        tool_name="read_file",
        canonical_path=target,
        operation="read",
        requester_session_id="sess-1",
        max_uses=1,
        ttl_s=600,
    )
    assert grant["schema"] == "lfl.host-capability-grant/v1"
    assert grant["status"] == "approved"
    ok, reason = store.check(
        grant["grant_id"], tool_name="read_file", canonical_path=target,
        operation="read", requester_session_id="sess-1",
    )
    assert ok is True, reason
    consumed = store.consume(grant["grant_id"], tool_name="read_file",
                             canonical_path=target, operation="read",
                             requester_session_id="sess-1")
    assert consumed is not None
    # one-shot：第二次消费 deny(consumed)。
    again, reason = store.check(
        grant["grant_id"], tool_name="read_file", canonical_path=target,
        operation="read", requester_session_id="sess-1",
    )
    assert again is False and "consumed" in reason


def test_grant_scope_mismatch_and_path_traversal(tmp_path: Path) -> None:
    import llm_loop.tools.escalation as esc

    target = tmp_path / "outside" / "notes.txt"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    store = esc.HostCapabilityGrantStore(_grant_store(tmp_path))
    grant = store.issue(
        tool_name="read_file", canonical_path=target, operation="read",
        requester_session_id="sess-1", max_uses=1, ttl_s=600,
    )
    gid = grant["grant_id"]
    # 工具不匹配拒绝。
    ok, reason = store.check(gid, tool_name="edit_file", canonical_path=target,
                             operation="read", requester_session_id="sess-1")
    assert ok is False and "scope" in reason
    # 操作不匹配（read grant 不得写）。
    ok, reason = store.check(gid, tool_name="read_file", canonical_path=target,
                             operation="write", requester_session_id="sess-1")
    assert ok is False and "scope" in reason
    # 路径不匹配（授权外路径）。
    ok, reason = store.check(gid, tool_name="read_file",
                             canonical_path=tmp_path / "outside" / "other.txt",
                             operation="read", requester_session_id="sess-1")
    assert ok is False and "scope" in reason
    # 会话不匹配拒绝。
    ok, reason = store.check(gid, tool_name="read_file", canonical_path=target,
                             operation="read", requester_session_id="sess-2")
    assert ok is False and "scope" in reason
    # 穿越路径（.. 形态）在 issue 阶段即拒绝。
    with pytest.raises(esc.HostGrantError):
        store.issue(tool_name="read_file",
                    canonical_path=tmp_path / "a" / ".." / "b",
                    operation="read", requester_session_id="s", max_uses=1, ttl_s=60)


def test_grant_expires_and_revoke_is_immediate(tmp_path: Path) -> None:
    import llm_loop.tools.escalation as esc

    target = tmp_path / "t.txt"
    target.write_text("x", encoding="utf-8")
    store = esc.HostCapabilityGrantStore(_grant_store(tmp_path))
    short = store.issue(tool_name="read_file", canonical_path=target,
                        operation="read", requester_session_id="s1",
                        max_uses=1, ttl_s=1)
    import time as _t

    _t.sleep(1.1)
    ok, reason = store.check(short["grant_id"], tool_name="read_file",
                             canonical_path=target, operation="read",
                             requester_session_id="s1")
    assert ok is False and "expired" in reason
    other = store.issue(tool_name="read_file", canonical_path=target,
                        operation="read", requester_session_id="s1",
                        max_uses=1, ttl_s=600)
    store.revoke(other["grant_id"], revoked_by="tester")
    ok, reason = store.check(other["grant_id"], tool_name="read_file",
                             canonical_path=target, operation="read",
                             requester_session_id="s1")
    assert ok is False and "revoked" in reason


def test_grant_store_insecure_file_is_rejected_not_repaired(tmp_path: Path) -> None:
    import llm_loop.tools.escalation as esc

    target = tmp_path / "t.txt"
    target.write_text("x", encoding="utf-8")
    home = _grant_store(tmp_path)
    store = esc.HostCapabilityGrantStore(home)
    grant = store.issue(tool_name="read_file", canonical_path=target,
                        operation="read", requester_session_id="s",
                        max_uses=1, ttl_s=600)
    gid = grant["grant_id"]
    grant_file = home / "grants" / f"{gid}.json"
    # 改成 0777 → grant_store_insecure（拒绝该 grant，不"顺手修权限"）。
    grant_file.chmod(0o777)
    ok, reason = store.check(gid, tool_name="read_file", canonical_path=target,
                             operation="read", requester_session_id="s")
    assert ok is False and "grant_store_insecure" in reason
    grant_file.chmod(0o600)
    # 换成 symlink → 同样拒绝。
    link = home / "grants" / "link.json"
    link.symlink_to(grant_file)
    link_id = link.stem
    with pytest.raises(esc.HostGrantError):
        store.issue(tool_name="read_file", canonical_path=target,
                    operation="read", requester_session_id="s",
                    max_uses=1, ttl_s=600, grant_id=link_id)


def test_grant_audit_chain_broken_stops_new_issues(tmp_path: Path) -> None:
    import llm_loop.tools.escalation as esc

    target = tmp_path / "t.txt"
    target.write_text("x", encoding="utf-8")
    home = _grant_store(tmp_path)
    store = esc.HostCapabilityGrantStore(home)
    store.issue(tool_name="read_file", canonical_path=target,
                operation="read", requester_session_id="s",
                max_uses=1, ttl_s=600)
    store.issue(tool_name="read_file", canonical_path=target,
                operation="read", requester_session_id="s",
                max_uses=1, ttl_s=600)
    audit = home / "grants" / "audit.jsonl"
    lines = audit.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 2
    # 篡改第一行（历史被改写 → 第二行 prev_hash 无法对账 → 链断）。
    first = __import__("json").loads(lines[0])
    first["event"] = "tampered"
    lines[0] = __import__("json").dumps(first, ensure_ascii=False)
    audit.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(esc.HostGrantError) as exc:
        store.issue(tool_name="read_file", canonical_path=target,
                    operation="read", requester_session_id="s",
                    max_uses=1, ttl_s=600)
    assert "audit_chain_broken" in str(exc.value)


def test_grant_concurrent_consume_single_winner(tmp_path: Path) -> None:
    import llm_loop.tools.escalation as esc

    target = tmp_path / "t.txt"
    target.write_text("x", encoding="utf-8")
    store = esc.HostCapabilityGrantStore(_grant_store(tmp_path))
    grant = store.issue(tool_name="read_file", canonical_path=target,
                        operation="read", requester_session_id="s",
                        max_uses=1, ttl_s=600)
    gid = grant["grant_id"]
    from concurrent.futures import ThreadPoolExecutor

    def attempt(_: int) -> bool:
        s = esc.HostCapabilityGrantStore(_grant_store(tmp_path))
        got = s.consume(gid, tool_name="read_file", canonical_path=target,
                        operation="read", requester_session_id="s")
        return got is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert results.count(True) == 1  # 仅一个成功，另一个 deny(consumed)


def test_grant_reader_waits_for_in_place_consume_write(tmp_path: Path, monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event

    import llm_loop.tools.escalation as esc

    target = tmp_path / "target.txt"
    target.write_text("x", encoding="utf-8")
    home = _grant_store(tmp_path)
    writer_store = esc.HostCapabilityGrantStore(home)
    reader_store = esc.HostCapabilityGrantStore(home)
    grant = writer_store.issue(tool_name="read_file", canonical_path=target,
                               operation="read", requester_session_id="s",
                               max_uses=1, ttl_s=600)
    gid = grant["grant_id"]
    grant_path = home / "grants" / f"{gid}.json"
    truncated, release_writer, reader_started = Event(), Event(), Event()
    native_truncate = esc.os.ftruncate
    native_read = reader_store._read_grant

    def pause_after_truncate(fd, length):
        native_truncate(fd, length)
        if length == 0 and esc.os.fstat(fd).st_ino == grant_path.stat().st_ino:
            truncated.set()
            assert release_writer.wait(5), "writer was not released"

    def read_grant(grant_id):
        reader_started.set()
        return native_read(grant_id)

    monkeypatch.setattr(esc.os, "ftruncate", pause_after_truncate)
    monkeypatch.setattr(reader_store, "_read_grant", read_grant)

    def consume(store):
        return store.consume(gid, tool_name="read_file", canonical_path=target,
                             operation="read", requester_session_id="s")

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(consume, writer_store)
        try:
            assert truncated.wait(5), "writer did not reach the locked rewrite"
            reader = pool.submit(consume, reader_store)
            assert reader_started.wait(5)
            with pytest.raises(TimeoutError):
                reader.result(timeout=0.1)
        finally:
            release_writer.set()
        assert writer.result(timeout=5)["status"] == "consumed"
        assert reader.result(timeout=5) is None


def test_grant_survives_process_restart_and_rechecks_path(tmp_path: Path) -> None:
    import llm_loop.tools.escalation as esc

    target = tmp_path / "t.txt"
    target.write_text("x", encoding="utf-8")
    home = _grant_store(tmp_path)
    first = esc.HostCapabilityGrantStore(home)
    grant = first.issue(tool_name="read_file", canonical_path=target,
                        operation="read", requester_session_id="s",
                        max_uses=1, ttl_s=600)
    # 新进程（新实例）：按磁盘重新加载并复核 canonical path。
    second = esc.HostCapabilityGrantStore(home)
    ok, reason = second.check(grant["grant_id"], tool_name="read_file",
                              canonical_path=target, operation="read",
                              requester_session_id="s")
    assert ok is True, reason
    # 授权目标被替换为 symlink 指向别处 → 拒绝（不跟随新链接逃逸）。
    moved = tmp_path / "moved-elsewhere.txt"
    moved.write_text("secret", encoding="utf-8")
    target.unlink()
    target.symlink_to(moved)
    ok, reason = second.check(grant["grant_id"], tool_name="read_file",
                              canonical_path=target, operation="read",
                              requester_session_id="s")
    assert ok is False and ("escaped" in reason or "symlink" in reason or "scope" in reason)


# ── P1-2（审查 b7691f4e）：revoke 必须与 consume 同 flock+version-CAS 语义 ──


def test_revoke_advances_version_so_stale_consume_cannot_win(tmp_path: Path) -> None:
    """确定性时序：consume 已打开 grant fd 后 revoke 发生 → consume 必须失败。

    时序注入点：store_a._open_private 以 O_RDWR 打开 grant 文件之后、flock 之前，
    由 store_b（独立实例=独立进程锁域）执行 revoke。修复前 revoke 走
    tmp+rename（换 inode、version 不变）：consume 在 stale fd 上 CAS 通过并
    返回成功——被撤销的授权被"复活"消费。修复后 revoke 在同一 inode 上
    flock 内递增 version：consume 的 CAS 必然失败，磁盘终态 revoked。
    """
    import json as _json

    import llm_loop.tools.escalation as esc

    target = tmp_path / "t.txt"
    target.write_text("x", encoding="utf-8")
    home = _grant_store(tmp_path)
    store_a = esc.HostCapabilityGrantStore(home)
    store_b = esc.HostCapabilityGrantStore(home)  # 另一"进程"
    grant = store_a.issue(tool_name="read_file", canonical_path=target,
                          operation="read", requester_session_id="s",
                          max_uses=1, ttl_s=600)
    gid = grant["grant_id"]
    stale_version = int(grant["version"])

    real_open = store_a._open_private
    fired: list[str] = []

    def hooked_open(path: Path, flags: int) -> int:
        fd = real_open(path, flags)
        if (
            "race" not in fired
            and path.name == f"{gid}.json"
            and (flags & os.O_RDWR)
        ):
            fired.append("race")
            # consume 持有 fd、尚未 flock 的窗口内完成 revoke。
            store_b.revoke(gid, revoked_by="host")
        return fd

    store_a._open_private = hooked_open  # type: ignore[method-assign]
    try:
        result = store_a.consume(
            gid, tool_name="read_file", canonical_path=target,
            operation="read", requester_session_id="s",
        )
    finally:
        store_a._open_private = real_open  # type: ignore[method-assign]

    assert result is None, "stale consume must not succeed after revoke"
    on_disk = _json.loads((home / "grants" / f"{gid}.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "revoked"
    assert int(on_disk["version"]) == stale_version + 1
    # revoke 之后的 check 必须立即拒绝。
    ok, reason = store_b.check(gid, tool_name="read_file", canonical_path=target,
                               operation="read", requester_session_id="s")
    assert ok is False and "revoked" in reason


def test_revoke_is_idempotent_and_records_audit(tmp_path: Path) -> None:
    import json as _json

    import llm_loop.tools.escalation as esc

    target = tmp_path / "t.txt"
    target.write_text("x", encoding="utf-8")
    home = _grant_store(tmp_path)
    store = esc.HostCapabilityGrantStore(home)
    grant = store.issue(tool_name="read_file", canonical_path=target,
                        operation="read", requester_session_id="s",
                        max_uses=1, ttl_s=600)
    gid = grant["grant_id"]
    store.revoke(gid, revoked_by="host")
    # 幂等：二次 revoke 不抛（已 revoked 仍 revoked，version 只再推进一次）。
    store.revoke(gid, revoked_by="host-again")
    on_disk = _json.loads((home / "grants" / f"{gid}.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "revoked"
    audit = (home / "grants" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert sum(1 for line in audit if _json.loads(line).get("event") == "revoke") == 2


# ── P2-4（审查 b7691f4e）：symlink 子例必须到达 is_symlink() 生产分支 ──


def test_issue_rejects_dangling_symlink_grant_id_reaching_symlink_branch(
    tmp_path: Path,
) -> None:
    """dangling symlink（exists()=False）只有 is_symlink() 检查能拦。

    用有效 24-hex grant id + 指向不存在目标的 symlink：ID regex 与
    exists() 都放行，唯一拦截点是 issue 的 grant_path.is_symlink()。
    删除该生产检查时 os.replace 会覆盖 symlink 落盘 → 本测试失败。
    """
    import llm_loop.tools.escalation as esc

    target = tmp_path / "t.txt"
    target.write_text("x", encoding="utf-8")
    home = _grant_store(tmp_path)
    store = esc.HostCapabilityGrantStore(home)
    gid = "c" * 24  # 有效 24-hex，通过 _GRANT_ID_RE
    grants_dir = home / "grants"
    grants_dir.mkdir(parents=True, exist_ok=True)
    grants_dir.chmod(0o700)  # 与 _ensure_layout 同标准，避免 mode 检查先触发
    dangling = grants_dir / f"{gid}.json"
    # macOS pathlib.symlink_to 对不存在目标会预检失败；os.symlink 原生支持 dangling。
    os.symlink(str(grants_dir / "nonexistent-target.json"), str(dangling))
    assert dangling.is_symlink() and not dangling.exists()  # 前置：确实 dangling
    with pytest.raises(esc.HostGrantError) as excinfo:
        store.issue(tool_name="read_file", canonical_path=target,
                    operation="read", requester_session_id="s",
                    max_uses=1, ttl_s=600, grant_id=gid)
    assert "grant_store_insecure" in str(excinfo.value)
    # symlink 本身未被覆盖/修复。
    assert dangling.is_symlink()
