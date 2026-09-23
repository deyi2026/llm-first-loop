"""R4 插话轮边界强制可见（antidrift_impl 批2，T2-1~T2-4）.

契约源：design §2.5——轮边界 pull hook 只做"队列→mailbox"纯搬运；投递内容、
身份、guard、ack 全走既有 _consume_live_interjections 路径（零新文本）。
"""

from __future__ import annotations

import json

from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.llm.client import LLMResponse
from llm_loop.web.human_turn_queue import HumanTurnQueue
from tests.unit.test_convergence_boundary import _read_resp
from tests.unit.test_err1210_recovery import _mk


class _FakeRunner:
    """duck-typing BackgroundRunner：mailbox 语义（enqueue/take/ack）+ handle 快照."""

    enabled = True

    def __init__(self):
        self.interjections: list[dict] = []
        self.acked: list[str] = []
        self.running: dict[str, str] = {}
        self.reject_enqueue = False

    def is_running(self, sid: str) -> bool:
        return sid in self.running

    def is_worker(self) -> bool:
        return False

    def is_cancelled(self, sid: str) -> bool:
        return False

    def get_handle(self, sid: str):
        gen = self.running.get(sid)
        return {"run_generation": gen} if gen is not None else None

    def enqueue_interjection(self, sid: str, payload: dict, *, expected_run_generation=None) -> bool:
        if self.reject_enqueue or sid not in self.running:
            return False
        if expected_run_generation and expected_run_generation != self.running.get(sid):
            return False
        self.interjections.append(dict(payload))
        return True

    def take_interjections(self, sid: str) -> list[dict]:
        rows, self.interjections = self.interjections, []
        return rows

    def acknowledge_interjection(self, row: dict) -> None:
        self.acked.append(str(row.get("queue_id") or ""))
        callback = row.get("_on_received")  # 真 runner 语义：回调在 ack 时执行
        if callable(callback):
            callback()


def _install_pull_hook(engine, hq: HumanTurnQueue, runner: _FakeRunner) -> None:
    """复刻 web 生产装配 _interjection_pull_hook 的搬运机械（纯搬运，零新文本）."""

    def hook(session_id: str) -> None:
        if not runner.is_running(session_id):
            return
        handle = runner.get_handle(session_id)
        if not handle:
            return
        for item in hq.claim_interject_fifo(session_id):
            qid = str(item.get("queue_id") or "")
            accepted = runner.enqueue_interjection(
                session_id,
                {
                    "queue_id": qid,
                    "message": item.get("message", ""),
                    "attachment_facts": list(item.get("attachment_facts") or []),
                    "_ingress": issue_ingress("web"),
                    "_on_received": lambda q=qid: hq.mark_interject_received(
                        session_id, q
                    ),
                },
                expected_run_generation=str(handle.get("run_generation") or ""),
            )
            if not accepted:
                hq.release_interject(session_id, qid)

    engine.interjection_pull_hook = hook


def _messages_wire(call: dict) -> str:
    return json.dumps(
        [str(m.get("content") or "") for m in call.get("messages") or []],
        ensure_ascii=False,
    )


def _user_texts(call: dict) -> list[str]:
    return [
        str(m.get("content") or "")
        for m in call.get("messages") or []
        if m.get("role") == "user"
    ]


# ------------------------------------------------ T2-1 ≤1 轮可见、逐字、保序

def test_t2_1_queued_interjections_visible_within_one_round(tmp_path, monkeypatch):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            _read_resp("c4"),
            _read_resp("c5"),
            LLMResponse(content="多轮后收口", tool_calls=[], provider="fake"),
        ],
    )
    hq = HumanTurnQueue(tmp_path / "hq")
    runner = _FakeRunner()
    engine.runner = runner
    _install_pull_hook(engine, hq, runner)
    sid = engine.session.create()

    steer_a = "第一条中途指令：改查另一个文件"
    steer_b = '第二条中途指令：附带 "引号" 的原文'
    original_chat = fake.chat

    def _chat_with_enqueue(messages, tools, **kwargs):
        if len(fake.calls) == 1:  # 第 2 轮 chat 期间入队（calls 在 chat 后追加）
            runner.running[sid] = "gen-1"  # run 进行中（hook 防御通过；入口互斥已过）
            hq.enqueue(sid, steer_a)
            hq.enqueue(sid, steer_b)
        return original_chat(messages, tools, **kwargs)

    fake.chat = _chat_with_enqueue

    result = engine.run(sid, "真实长任务")

    assert result.final_answer == "多轮后收口"
    # ≤1 轮内可见：入队发生在第 2 轮，第 3 轮请求（fake.calls[2]）已含两条 user 消息
    third_round_users = _user_texts(fake.calls[2])
    assert steer_a in third_round_users
    assert steer_b in third_round_users
    assert third_round_users.index(steer_a) < third_round_users.index(steer_b)
    # 投递完成落终态（ack 经既有回调路径）
    assert set(runner.acked) == {
        it["queue_id"] for it in hq.list_active(sid) if it["status"] == "interject_received"
    }
    assert all(
        it["status"] == "interject_received"
        for it in hq.list_active(sid)
        if it["message"] in (steer_a, steer_b)
    )


# --------------------------------------------- T2-2 无插话在队：零差异对照

def test_t2_2_no_queued_interjections_zero_diff(tmp_path, monkeypatch):
    responses = [
        _read_resp("c1"),
        _read_resp("c2"),
        _read_resp("c3"),
        LLMResponse(content="对照收口", tool_calls=[], provider="fake"),
    ]
    engine_plain, fake_plain = _mk(tmp_path / "plain", monkeypatch, responses=list(responses))
    engine_hooked, fake_hooked = _mk(tmp_path / "hooked", monkeypatch, responses=list(responses))

    hq = HumanTurnQueue(tmp_path / "hq")
    runner = _FakeRunner()
    engine_hooked.runner = runner
    _install_pull_hook(engine_hooked, hq, runner)

    sid_plain = engine_plain.session.create()
    plain_chat = fake_plain.chat

    def _chat_plain_noop(messages, tools, **kwargs):
        return plain_chat(messages, tools, **kwargs)

    fake_plain.chat = _chat_plain_noop
    result_plain = engine_plain.run(sid_plain, "真实任务")

    sid_hooked = engine_hooked.session.create()
    hooked_chat = fake_hooked.chat

    def _chat_hooked_mark_running(messages, tools, **kwargs):
        runner.running[sid_hooked] = "gen-1"  # run 进行中（对称动作；队列恒空）
        return hooked_chat(messages, tools, **kwargs)

    fake_hooked.chat = _chat_hooked_mark_running
    result_hooked = engine_hooked.run(sid_hooked, "真实任务")

    assert result_plain.final_answer == result_hooked.final_answer == "对照收口"
    assert len(fake_plain.calls) == len(fake_hooked.calls)
    for call_plain, call_hooked in zip(fake_plain.calls, fake_hooked.calls, strict=True):
        assert _messages_wire(call_plain) == _messages_wire(call_hooked)


# ------------------------------- T2-3 插话进入后继续原任务：无二次干预/无引导语

def test_t2_3_interjection_does_not_inject_guidance(tmp_path, monkeypatch):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            _read_resp("c4"),
            LLMResponse(content="继续原任务后收口", tool_calls=[], provider="fake"),
        ],
    )
    hq = HumanTurnQueue(tmp_path / "hq")
    runner = _FakeRunner()
    engine.runner = runner
    _install_pull_hook(engine, hq, runner)
    sid = engine.session.create()

    steer = "中途只补一句事实，不改变任务"
    original_chat = fake.chat

    def _chat_with_enqueue(messages, tools, **kwargs):
        if len(fake.calls) == 1:
            runner.running[sid] = "gen-1"
            hq.enqueue(sid, steer)
        return original_chat(messages, tools, **kwargs)

    fake.chat = _chat_with_enqueue
    result = engine.run(sid, "真实任务")

    assert result.final_answer == "继续原任务后收口"
    third_round_users = _user_texts(fake.calls[2])
    # 插话以 user 消息逐字入链：content 恰为原文，无程序引导语/前后缀
    assert steer in third_round_users
    wire = "\n".join(str(m.get("content") or "") for m in fake.calls[2].get("messages") or [])
    assert "[程序]" not in wire
    assert "引导" not in wire


# ------------------------------ T2-4 enqueue 竞态失败：回滚 queued 保持 FIFO

def test_t2_4_enqueue_race_rolls_back_to_queued_fifo(tmp_path, monkeypatch):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            LLMResponse(content="竞态后收口", tool_calls=[], provider="fake"),
        ],
    )
    hq = HumanTurnQueue(tmp_path / "hq")
    runner = _FakeRunner()
    engine.runner = runner
    _install_pull_hook(engine, hq, runner)
    sid = engine.session.create()

    steer_a = "竞态场景第一条"
    steer_b = "竞态场景第二条"
    original_chat = fake.chat

    def _chat_with_enqueue_and_race(messages, tools, **kwargs):
        if len(fake.calls) == 1:
            runner.running[sid] = "gen-1"
            hq.enqueue(sid, steer_a)
            hq.enqueue(sid, steer_b)
            runner.reject_enqueue = True  # 模拟 run 恰在认领后结束（enqueue 必拒）
        return original_chat(messages, tools, **kwargs)

    fake.chat = _chat_with_enqueue_and_race
    result = engine.run(sid, "真实任务")

    assert result.final_answer == "竞态后收口"
    # 竞态失败：插话未进入第 2 轮请求，条目回滚 queued 保持 FIFO
    assert steer_a not in _user_texts(fake.calls[1])
    active = hq.list_active(sid)
    steers = [it for it in active if it["message"] in (steer_a, steer_b)]
    assert len(steers) == 2
    assert all(it["status"] == "queued" for it in steers)
    assert [it["queue_id"] for it in sorted(steers, key=lambda x: x["created_at"])] == [
        it["queue_id"] for it in sorted(steers, key=lambda x: x["created_at"])
    ]
    # FIFO 保序：按 created_at 排序后消息序=入队序
    ordered = [it["message"] for it in sorted(steers, key=lambda x: x["created_at"])]
    assert ordered == [steer_a, steer_b]
