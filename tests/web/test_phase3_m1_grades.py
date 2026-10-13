"""Phase3 M1 插话分级回执（G1）+ D2 持久化二分 单元/集成测试.

覆盖设计书 §3 G1 验收：
- applied（判据①终答出口 / 判据②工具派发）
- denied（ingress 守卫拒绝 → interject_denied 终态 + deny_reason，不再与孤儿混淆）
- continued_before_final（终答结算边界拦截）
- accepted 受理≠生效（202 回执 grade 提示）
- D2 二分（definitely_not_committed / commit_outcome_uncertain → 503 分级错误码）
- GET /api/v1/chat/queue/item 只读分级查询
日志红线（D6）：denied/applied/cbf 的 detail 不含插话正文。
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import llm_loop.web.human_turn_queue as htq_mod
from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse
from llm_loop.web import build_app
from llm_loop.web.human_turn_queue import HumanTurnQueue, QueuePersistError


def _wait_tool_started(engine, timeout=3.0):
    tool = engine.registry.get("execute_command")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if getattr(tool, "_active_procs", None):
            return True
        time.sleep(0.01)
    return False


def _wait_done(q, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            ev = q.get_nowait()
        except Exception:  # noqa: BLE001
            time.sleep(0.02)
            continue
        if ev.get("type") in ("done", "error"):
            return ev
    return {"type": "timeout"}


def _hq_of(client, engine):
    store = getattr(client.app.state, "human_turn_queues", None) or {}
    data_dir = str(Path(engine.settings.data_dir).expanduser().resolve())
    return store.get(data_dir) or next(iter(store.values()))


def _item(hq, sid, qid):
    for it in hq.snapshot_items():
        if it.get("queue_id") == qid and it.get("session_id") == sid:
            return it
    return None


def _setup(build_test_engine, responses):
    engine, fake = build_test_engine(responses)
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    return engine, fake, runner, client, sid


def _interject_during_tool(client, runner, sid, text):
    r1 = client.post("/api/v1/chat/queue", json={"session_id": sid, "message": text})
    assert r1.status_code == 202
    qid = r1.json()["queue_id"]
    gen = (runner.get_handle(sid) or {}).get("run_generation")
    r2 = client.post(
        "/api/v1/chat/queue/interject",
        json={"session_id": sid, "queue_id": qid, "run_generation": gen},
    )
    return qid, r1, r2


# ── applied 判据②：工具派发 ─────────────────────────────────────────
def test_grade_applied_via_tool_dispatch(build_test_engine):
    engine, fake, runner, client, sid = _setup(
        build_test_engine,
        [
            {
                "content": "先慢命令",
                "tool_calls": [
                    ToolCall(id="m1c1", name="execute_command", arguments={"command": "sleep 2"})
                ],
            },
            {
                "content": "再快命令",
                "tool_calls": [
                    ToolCall(id="m1c2", name="execute_command", arguments={"command": "echo ok"})
                ],
            },
            {"content": "final"},
        ],
    )
    _h, q = runner.start(sid, "跑两步")
    assert _wait_tool_started(engine)
    qid, _, r2 = _interject_during_tool(client, runner, sid, "第二改用B")
    assert r2.status_code == 202, r2.text
    assert r2.json()["grade"] == "accepted"  # 受理≠生效提示
    final = _wait_done(q)
    assert final["type"] == "done"
    item = _item(_hq_of(client, engine), sid, qid)
    assert item["status"] == "interject_received"
    assert item["grade"] == "applied"
    assert "tool_dispatched_round" in item["applied_detail"]
    # 模型确实看到插话（第二次调用）
    assert any("第二改用B" in (m.get("content") or "") for m in fake.calls[1]["messages"])
    runner.cancel(sid)


# ── applied 判据①：终答出口 ─────────────────────────────────────────
def test_grade_applied_via_final_answer(build_test_engine):
    engine, _fake, runner, client, sid = _setup(
        build_test_engine,
        [
            {
                "content": "慢",
                "tool_calls": [
                    ToolCall(id="m1c1", name="execute_command", arguments={"command": "sleep 2"})
                ],
            },
            {"content": "final-answer"},
        ],
    )
    _h, q = runner.start(sid, "跑一步")
    assert _wait_tool_started(engine)
    qid, _, r2 = _interject_during_tool(client, runner, sid, "然后收尾")
    assert r2.status_code == 202
    final = _wait_done(q)
    assert final["type"] == "done"
    item = _item(_hq_of(client, engine), sid, qid)
    assert item["grade"] == "applied"
    assert item["applied_detail"] == "final_answer_after_interjection"
    runner.cancel(sid)


# ── denied：ingress 守卫拒绝 ────────────────────────────────────────
def test_grade_denied_on_ingress_guard(build_test_engine, monkeypatch):
    from llm_loop.core.trace_leak import user_ingress_guard as uig
    from llm_loop.core.trace_leak.user_ingress_guard import GuardAction

    engine, _fake, runner, client, sid = _setup(
        build_test_engine,
        [
            {
                "content": "慢",
                "tool_calls": [
                    ToolCall(id="m1c1", name="execute_command", arguments={"command": "sleep 2.5"})
                ],
            },
            {"content": "final"},
        ],
    )
    real_guard = uig.guard_user_write

    def fake_guard(sess, msg, token, entry=None, data_dir=None):
        verdict = real_guard(sess, msg, token, entry=entry, data_dir=data_dir)
        if entry == "engine.interject" and verdict.action is not GuardAction.DENY:
            # 仅拒绝插话入口（run 初始 ingress 不受影响）；保留 message 结构，
            # 仅改判定（守卫本身有自己的测试）
            return SimpleNamespace(
                action=GuardAction.DENY, message=verdict.message, reason="test_forced_replay"
            )
        return verdict

    monkeypatch.setattr(uig, "guard_user_write", fake_guard)
    _h, q = runner.start(sid, "run")
    assert _wait_tool_started(engine)
    qid, _, r2 = _interject_during_tool(client, runner, sid, "会被拒绝的消息")
    assert r2.status_code == 202
    final = _wait_done(q, timeout=30)
    assert final["type"] == "done"
    item = _item(_hq_of(client, engine), sid, qid)
    assert item["status"] == "interject_denied"
    assert item["grade"] == "denied"
    assert item["deny_reason"] == "test_forced_replay"
    # denied 项不进入会话历史（守卫拒绝=不可投递）
    sess = engine.session.load(sid)
    assert not any("会被拒绝的消息" in (m.content or "") for m in sess.messages)
    runner.cancel(sid)


# ── continued_before_final：终答结算边界拦截 ────────────────────────
def test_grade_cbf_at_final_gate(build_test_engine):
    def delayed_final(calls):
        time.sleep(1.5)  # 制造终答在途窗口，插话落在结算边界前
        return LLMResponse(content="final-after-delay", tool_calls=[], provider="fake")

    engine, _fake, runner, client, sid = _setup(
        build_test_engine,
        [
            {
                "content": "慢",
                "tool_calls": [
                    ToolCall(id="m1c1", name="execute_command", arguments={"command": "sleep 1.2"})
                ],
            },
            delayed_final,
            {"content": "final-really"},
        ],
    )
    _h, q = runner.start(sid, "run")
    assert _wait_tool_started(engine)
    # 关键时序：等到第 2 次 LLM 调用（延迟终答在途）开始后再插话——
    # 消息才会落在终答结算边界前（CBF 窗口），而非第 2 轮起始消费。
    # 注：Phase6 M1 后同步调用默认开窗轮询（窗口内插话走 sync_window_poll
    # 提前打断）；本测试的语义目标是「结算边界 CBF」旧路径，故显式关闸，
    # 该路径仍服务晚到插话与关闸回退（设计 §5.6/§9）。
    _tr = engine.settings.tool_runtime
    object.__setattr__(_tr, "sync_chat_interject_checkpoint", False)
    deadline = time.monotonic() + 5.0
    while len(getattr(_fake, "calls", [])) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(_fake.calls) >= 2, "第二轮 LLM 调用未开始"
    qid, _, r2 = _interject_during_tool(client, runner, sid, "终答前补充")
    assert r2.status_code == 202
    # 插话发生在第一轮工具后、第二轮 LLM（延迟1.5s）在途期间 → 结算边界拦截
    final = _wait_done(q, timeout=30)
    assert final["type"] == "done"
    item = _item(_hq_of(client, engine), sid, qid)
    assert item["status"] == "interject_received"
    assert item.get("cbf_at"), f"cbf 未触发: {item}"
    # 终审 P1-2 修正后的语义：结算边界拦截只兑现 cbf（拦截本身=决策改变）；
    # applied 由续跑轮的真实出口兑现——本场景续跑直接给终答（无工具派发），
    # 终答出口触发 applied，detail=final_answer_after_interjection。
    assert item["grade"] == "applied"
    assert item.get("applied_detail") == "final_answer_after_interjection"
    runner.cancel(sid)


# ── D2 二分：持久化失败分级 ────────────────────────────────────────
def test_d2_definitely_not_committed(tmp_path, monkeypatch):
    hq = HumanTurnQueue(str(tmp_path / "q"))
    hq.enqueue("s", "初始")  # 正常落盘

    def boom_write(*a, **kw):
        raise OSError("simulated disk full at write")

    monkeypatch.setattr(htq_mod.tempfile, "mkstemp", boom_write)
    with pytest.raises(QueuePersistError) as ei:
        hq.enqueue("s", "第二条")
    assert ei.value.stage == "definitely_not_committed"
    # 磁盘上目标文件未变：重载后只有第一条
    hq2 = HumanTurnQueue(str(tmp_path / "q"))
    msgs = [it["message"] for it in hq2.snapshot_items()]
    assert msgs == ["初始"]


def test_d2_commit_outcome_uncertain(tmp_path, monkeypatch):
    hq = HumanTurnQueue(str(tmp_path / "q"))

    def boom_replace(src, dst):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(htq_mod.os, "replace", boom_replace)
    with pytest.raises(QueuePersistError) as ei:
        hq.enqueue("s", "内容A")
    assert ei.value.stage == "commit_outcome_uncertain"
    # 内存态已含新项但磁盘未变——不允许任何一侧被假设为真值
    # （monkeypatch 在测试收尾自动恢复 os.replace，无需手工复原）
    hq2 = HumanTurnQueue(str(tmp_path / "q"))
    msgs = [it["message"] for it in hq2.snapshot_items()]
    assert msgs == []  # 磁盘侧未提交（如实：unknown 的两侧分别可查）


def test_d2_endpoint_503_classification(build_test_engine, monkeypatch):
    engine, _fake, runner, client, sid = _setup(build_test_engine, [{"content": "ok"}])

    def boom_replace(src, dst):
        raise OSError("rename fail in endpoint")

    monkeypatch.setattr(htq_mod.os, "replace", boom_replace)
    r = client.post(
        "/api/v1/chat/queue", json={"session_id": sid, "message": "入队遇持久化失败"}
    )
    assert r.status_code == 503
    assert r.json()["error"] == "queue_persist_commit_outcome_uncertain"
    runner.cancel(sid)


# ── 只读分级查询端点 ────────────────────────────────────────────────
def test_grade_readonly_endpoint(build_test_engine):
    engine, _fake, runner, client, sid = _setup(build_test_engine, [{"content": "ok"}])
    r1 = client.post("/api/v1/chat/queue", json={"session_id": sid, "message": "排队中"})
    qid = r1.json()["queue_id"]
    r2 = client.get(
        "/api/v1/chat/queue/item", params={"session_id": sid, "queue_id": qid}
    )
    assert r2.status_code == 200
    assert r2.json()["item"]["grade"] == "queued"
    r3 = client.get(
        "/api/v1/chat/queue/item", params={"session_id": sid, "queue_id": "no-such"}
    )
    assert r3.status_code == 404
    assert r3.json()["error"] == "queue_item_not_found"


# ── D6 日志红线：分级 detail 不含插话正文 ───────────────────────────
def test_d6_no_content_leak_in_grades(build_test_engine, caplog):
    engine, _fake, runner, client, sid = _setup(
        build_test_engine,
        [
            {
                "content": "慢",
                "tool_calls": [
                    ToolCall(id="m1c1", name="execute_command", arguments={"command": "sleep 2"})
                ],
            },
            {"content": "final"},
        ],
    )
    _h, q = runner.start(sid, "run")
    assert _wait_tool_started(engine)
    secret = "绝密插话正文XYZ"
    qid, _, r2 = _interject_during_tool(client, runner, sid, secret)
    assert r2.status_code == 202
    _wait_done(q)
    hq = _hq_of(client, engine)
    item = _item(hq, sid, qid)
    assert item["grade"] == "applied"
    # applied/cbf/denied 相关 detail 字段不得包含正文
    for field in ("applied_detail", "cbf_detail", "deny_reason", "grade_reason"):
        assert secret not in str(item.get(field) or ""), field
    # 动作事件记录同样不打正文（queue_id 是安全标识）
    audit = Path(engine.settings.audit_dir) if hasattr(engine.settings, "audit_dir") else None
    if audit and audit.exists():
        for f in audit.rglob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                if "human.interjection" in line and "applied" in line:
                    assert secret not in line
    runner.cancel(sid)
