"""M1「提权审批可信可恢复」存储层红→绿测试（2026-11-06 设计书）.

对应问题：
- ESC-04 到期时间缺失/格式非法时消费被放行（fail-open）→ FR-04 fail-closed
- ESC-09 过期状态投影不一致（list/wait/consume 各说各话）→ FR-09 统一状态计算
- ESC-03 跨进程失效 pending 被幂等复用 → FR-03 失效记录不复用/新 ID
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from llm_loop.tools.escalation import EscalationStore, system_local_now
from llm_loop.tools import escalation as escalation_module

_CMD = ["bash", "-lc", "echo probe"]
_CMD_STR = "bash -lc 'echo probe'"


def _store(tmp_path) -> EscalationStore:
    return EscalationStore(tmp_path / "escalation_requests.json")


def _mk_pending(store: EscalationStore) -> str:
    rec = store.create(
        tool_name="execute_command",
        command=_CMD_STR,
        justification="测试用途" * 3,
        session_id="s-test",
    )
    return rec["id"]


def _force_field(store: EscalationStore, rid: str, field: str, value) -> None:
    """以本进程签名合法地写入畸形字段（绕过 MAC，模拟损坏/旧版本记录）。"""

    def _mut(records):
        for r in records:
            if r.get("id") == rid:
                r[field] = value
        return records

    store._mutate(_mut)


# ---------------------------------------------------------------- ESC-04 ----


def test_consume_rejects_missing_expiry_fail_closed(tmp_path):
    s = _store(tmp_path)
    rid = _mk_pending(s)
    s.decide(rid, "approved", note="ok")
    token = s.get(rid)["token"]
    _force_field(s, rid, "token_expires_at", "")

    hit, reason = s.consume(token, "execute_command", _CMD_STR)
    assert hit is None, "缺失到期时间的令牌必须 fail-closed 拒绝"
    assert reason, "拒绝必须给原因"


def test_consume_rejects_corrupt_expiry_fail_closed(tmp_path):
    s = _store(tmp_path)
    rid = _mk_pending(s)
    s.decide(rid, "approved", note="ok")
    token = s.get(rid)["token"]
    _force_field(s, rid, "token_expires_at", "not-a-timestamp")

    hit, reason = s.consume(token, "execute_command", _CMD_STR)
    assert hit is None, "格式非法的到期时间必须 fail-closed 拒绝"
    assert reason, "拒绝必须给原因"

    hit2, reason2 = s.consume_for_execution(rid, token, s.get(rid)["command_sha256"])
    assert hit2 is None, "consume_for_execution 同样 fail-closed"
    assert reason2


def test_consume_rejected_expiry_clears_token(tmp_path):
    """fail-closed 拒绝时应清除令牌，避免无限重试。"""
    s = _store(tmp_path)
    rid = _mk_pending(s)
    s.decide(rid, "approved", note="ok")
    token = s.get(rid)["token"]
    _force_field(s, rid, "token_expires_at", "")

    s.consume(token, "execute_command", _CMD_STR)
    rec = s.get(rid)
    assert not rec.get("token"), "被拒后令牌应被清除"


# ---------------------------------------------------------------- ESC-09 ----


def _expire_token(store: EscalationStore, rid: str) -> None:
    past = (system_local_now() - timedelta(minutes=1)).isoformat()
    _force_field(store, rid, "token_expires_at", past)


def test_list_projects_expired_uniformly(tmp_path):
    s = _store(tmp_path)
    rid = _mk_pending(s)
    s.decide(rid, "approved", note="ok")
    _expire_token(s, rid)

    items = {r["id"]: r for r in s.list()}
    assert items[rid]["status"] == "expired", "list 投影应惰性计算过期，而非裸存状态"


def test_wait_for_decision_projects_expired(tmp_path):
    s = _store(tmp_path)
    rid = _mk_pending(s)
    s.decide(rid, "approved", note="ok")
    _expire_token(s, rid)

    rec = s.wait_for_decision(rid, 0.2)
    assert rec is not None
    assert rec["status"] == "expired", "wait 不得把过期令牌当成 approved 返回给 AI"


def test_consume_after_projection_expired(tmp_path):
    s = _store(tmp_path)
    rid = _mk_pending(s)
    s.decide(rid, "approved", note="ok")
    token = s.get(rid)["token"]
    _expire_token(s, rid)

    hit, reason = s.consume(token, "execute_command", _CMD_STR)
    assert hit is None
    assert "过期" in reason or "expired" in reason.lower(), reason


# ---------------------------------------------------------------- ESC-03 ----


def test_create_does_not_reuse_cross_process_stale_pending(tmp_path):
    """跨进程（签名失效）的 pending 记录不得被幂等复用为'在等审批'。"""
    s = _store(tmp_path)
    rec1 = s.create(
        tool_name="execute_command",
        command=_CMD_STR,
        justification="跨进程复现" * 3,
        session_id="s1",
    )

    old_key = escalation_module._STATE_SIGNING_KEY
    escalation_module._STATE_SIGNING_KEY = secrets.token_bytes(32)
    try:
        s2 = _store(tmp_path)
        assert s2.get(rec1["id"]).get("_sig_unverified") is True
        rec2 = s2.create(
            tool_name="execute_command",
            command=_CMD_STR,
            justification="跨进程复现" * 3,
            session_id="s1",
        )
    finally:
        escalation_module._STATE_SIGNING_KEY = old_key

    assert rec2["id"] != rec1["id"], "失效 pending 不得复用旧 ID，必须创建新记录"
    assert rec2["status"] == "pending"


def test_wait_tool_fails_fast_on_unverified_record(tmp_path):
    """失效记录上的等待应立即失败提示重申请，而不是等满超时返回 pending。"""
    from llm_loop.tools.builtin.escalation import EscalationWaitTool

    s = _store(tmp_path)
    rec = s.create(
        tool_name="execute_command",
        command=_CMD_STR,
        justification="快速失败" * 3,
        session_id="s1",
    )

    old_key = escalation_module._STATE_SIGNING_KEY
    escalation_module._STATE_SIGNING_KEY = secrets.token_bytes(32)
    try:
        s2 = _store(tmp_path)
        tool = EscalationWaitTool(store=s2)
        result = tool.execute(request_id=rec["id"], timeout_s=2)
    finally:
        escalation_module._STATE_SIGNING_KEY = old_key

    assert result.status == "failure", "失效申请应快速失败而非静默等待"
    assert "重新申请" in result.content or "失效" in result.content, result.content


def test_projection_expired_when_expiry_missing_or_corrupt(tmp_path):
    """P2-2 复审意见采纳：approved+到期时间缺失/不可解析 → 投影 expired（与 consume 同语义）。"""
    s = _store(tmp_path)
    rid = _mk_pending(s)
    s.decide(rid, "approved", note="ok")
    _force_field(s, rid, "token_expires_at", "")
    items = {r["id"]: r for r in s.list()}
    assert items[rid]["status"] == "expired", "缺失到期时间的 approved 投影应 expired"
    assert s.get(rid)["status"] == "expired"

    _force_field(s, rid, "token_expires_at", "garbage-ts")
    rec = s.wait_for_decision(rid, 0.1)
    assert rec is not None and rec["status"] == "expired", "不可解析到期时间投影 expired"


def test_pending_filter_excludes_unverified_records(tmp_path):
    """FR-03/FR-07: 待审专用查询排除跨进程失效 pending（面板无法审批）。"""
    s = _store(tmp_path)
    rec1 = s.create(
        tool_name="execute_command",
        command=_CMD_STR,
        justification="失效排除" * 3,
        session_id="s1",
    )
    old_key = escalation_module._STATE_SIGNING_KEY
    escalation_module._STATE_SIGNING_KEY = secrets.token_bytes(32)
    try:
        s2 = _store(tmp_path)
        assert s2.list(status="pending") == [], "失效 pending 不得出现在待审查询"
        assert s2.pending_count() == 0, "失效 pending 不计入待审计数"
        # 历史视图（无过滤）仍如实呈现
        assert any(r.get("id") == rec1["id"] for r in s2.list())
    finally:
        escalation_module._STATE_SIGNING_KEY = old_key
