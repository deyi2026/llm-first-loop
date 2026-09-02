"""B1/B2(EVO-20260902-41898b20)：取消/出错中断的半截产物限量落盘 + truncated episode 索引.

B1: user_stop/llm_error 中断时，半截可见文本（尾 4000）+ 推理尾（8000）如实标注
    落会话（answer_origin=program → 投影层既有谓词替换为字节稳定占位，零新增
    provider 面）+ llm.interrupted 事件恒写 + run 内至多一行。
B2: 一切非 completed 终态 → {sid}.truncated.jsonl 一行（幂等键=(sid, run_end seq)，
    非退休型）；episode 检索空查询合并展示，truncated ref 走 compact 水合。
"""

from __future__ import annotations

import json
import queue
import threading

from llm_loop.core.loop.events import _EventsMixin
from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import Message, MessageSource
from llm_loop.introspection.search import RecordSearcher
from llm_loop.llm.client import StreamDelta
from llm_loop.memory.episode import EpisodeStore

_STOP_TEXT = "（已停止——用户点击停止按钮，本轮回答终止）"


# ── 桩：只承载 _EventsMixin（_on_llm_interrupted 单元面）──
class _StubEngine(_EventsMixin):
    def __init__(self, event_store=None):
        self._event_store = event_store
        self.status = None
        self.saved = 0
        self.recorded: list[Message] = []
        self._append_message_event = lambda sess, msg: self.recorded.append(msg)  # noqa: SLF001

    class _Sess:
        saved = 0

        def __init__(self):
            self.session_id = "s-test"
            self.messages: list[Message] = []

    class _Store:
        def save(self, sess):
            sess.saved += 1

    def new(self):
        return self._Sess(), self._Store()


def _run_interrupted(stub_parts, *, reason="cancelled", error_digest="", monkeypatch=None,
                     env=None):
    if env and monkeypatch is not None:
        for k, v in env.items():
            monkeypatch.setenv(k, v)
    eng = _StubEngine()
    sess, store = eng.new()
    eng.session = store
    eng._on_llm_interrupted(
        sess,
        text_parts=stub_parts[0],
        reasoning_parts=stub_parts[1],
        reason=reason,
        error_digest=error_digest,
        round_no=3,
    )
    return eng, sess


def test_b1_tail_limited_save_with_honest_annotation(monkeypatch):
    """超限内容仅保存尾段并在标注中如实给出 N/M 计数（不伪装完整）。"""
    text = "A" * 10000
    reasoning = "R" * 12000
    eng, sess = _run_interrupted(([text], [reasoning]), reason="cancelled")
    assert len(sess.messages) == 1
    msg = sess.messages[0]
    assert msg.source == MessageSource.SYSTEM
    assert msg.content.startswith("A" * 4000) and "A" * 4001 not in msg.content
    assert "保存尾 4000/10000 字符" in msg.content
    assert "推理保存尾 8000/12000 字符" in msg.content
    assert msg.reasoning_content == "R" * 8000
    md = msg.metadata
    assert md["answer_origin"] == "program" and md["llm_interrupted"] is True
    assert md["run_end_reason"] == "cancelled" and md["partial_chars"] == 22000
    assert len(md["partial_sha256"]) == 64
    # B2 数据源缓存：原始尾段（非裁剪前全文）
    assert eng._last_interrupted["text_tail"] == "A" * 4000
    assert eng._last_interrupted["reasoning_tail"] == "R" * 8000
    assert eng._last_interrupted["partial_chars"] == 22000


def test_b1_env_zero_disables_tails_but_cancelled_still_annotated(monkeypatch):
    """env=0 关闭尾段：推理不入行；cancelled 仍留独立标注行（0/0 如实）。"""
    eng, sess = _run_interrupted(
        (["部分回答"], ["推理内容"]),
        reason="cancelled",
        monkeypatch=monkeypatch,
        env={"INTERRUPT_TEXT_TAIL_CHARS": "0", "INTERRUPT_REASONING_TAIL_CHARS": "0"},
    )
    assert len(sess.messages) == 1
    msg = sess.messages[0]
    assert "部分回答" not in msg.content
    assert "保存尾 0/4 字符" in msg.content
    assert msg.reasoning_content is None
    assert eng._last_interrupted["text_tail"] == ""


def test_b1_llm_error_zero_content_no_message_row_but_event_cached():
    """llm_error 且零半截产物：不加消息行（不加噪）；llm.interrupted 事件恒写。"""
    eng = _StubEngine()
    sess, store = eng.new()
    eng.session = store
    eng._on_llm_interrupted(
        sess, text_parts=[], reasoning_parts=[], reason="llm_error",
        error_digest="500 fake boom", round_no=2,
    )
    assert sess.messages == [] and eng.recorded == []
    assert eng._last_interrupted["reason"] == "llm_error"
    assert eng._last_interrupted["error_digest"] == "500 fake boom"


def test_b1_fail_open_on_save_failure():
    """session.save 抛错不抛穿（fail-open，与 P1-6 同纪律）。"""
    eng = _StubEngine()

    class _Boom:
        def save(self, sess):
            raise RuntimeError("disk full")

    sess, _ = eng.new()
    eng.session = _Boom()
    eng._on_llm_interrupted(sess, text_parts=["x"], reasoning_parts=[], reason="cancelled")


def test_llm_error_digest_formats_status_provider_message():
    from llm_loop.core.loop.engine import _llm_error_digest

    class _DigestProbeError(Exception):
        status_code = 400
        provider = "lmstudio"

    d = _llm_error_digest(_DigestProbeError("bad request"))
    assert d == "400 lmstudio bad request"
    assert len(_llm_error_digest(_DigestProbeError("x" * 500))) <= 200


def test_engine_cancel_stream_b1_row_event_and_b2_index(build_test_engine, tmp_path):
    """流式中 Stop：B1 标注行+llm.interrupted 事件落盘；B2 truncated 行并入收口。"""
    from llm_loop.event_log.store import EventStore

    engine, fake = build_test_engine([])
    engine.episode_store = EpisodeStore(tmp_path / "episodes")  # conftest 未装配，测试注入
    full = "ABCDEFGHIJKLMNO"

    def slow_stream(**_kwargs):
        yield StreamDelta(text="A")
        yield StreamDelta(text="", reasoning="think-part")
        for ch in full[1:]:
            yield StreamDelta(text=ch)
            threading.Event().wait(0.02)

    fake.chat_stream = slow_stream
    runner = BackgroundRunner(engine)
    engine.runner = runner
    event_store = EventStore(tmp_path / "events")
    engine._event_store = event_store
    sid = engine.session.create()
    _handle, q = runner.start(sid, "hello")
    assert q.get(timeout=2.0)["type"] == "delta"
    assert runner.cancel(sid) is True
    deadline = queue.Queue()

    def _wait():
        while True:
            ev = q.get(timeout=3.0)
            if ev["type"] == "done":
                deadline.put(ev)
                return

    threading.Thread(target=_wait, daemon=True).start()
    done = deadline.get(timeout=3.0)
    assert done["result"].final_answer == _STOP_TEXT

    # B1：独立 SYSTEM 标注行位于占位行之前；metadata 走 program 占位通道
    sess = engine.session.load(sid)
    b1_rows = [m for m in sess.messages if (m.metadata or {}).get("llm_interrupted")]
    assert len(b1_rows) == 1, "同一 run 至多一行截断标注"
    b1 = b1_rows[0]
    assert b1.metadata["answer_origin"] == "program"
    assert b1.content.startswith("A") and "[截断标注] reason=cancelled" in b1.content
    assert "think-part" in (b1.reasoning_content or "")
    idx_b1 = sess.messages.index(b1)
    assert idx_b1 < len(sess.messages) - 1, "标注行应在收尾占位行之前"

    # 事件面：llm.interrupted 恒写 + run.end reason=cancelled
    events = event_store.read(sid)
    ints = [e for e in events if e.type == "llm.interrupted"]
    assert len(ints) == 1 and ints[-1].payload["reason"] == "cancelled"
    run_ends = [e for e in events if e.type == "run.end"]
    assert run_ends[-1].payload["reason"] == "cancelled"

    # B2：truncated.jsonl 一行，幂等键 = run.end 事件 seq
    store = engine.episode_store
    hits = store.search_truncated(sid)
    assert len(hits) == 1 and hits[0]["state"] == "truncated"
    assert hits[0]["run_end_reason"] == "cancelled"
    assert int(hits[0]["ref"].split(":")[1]) == run_ends[-1].seq
    # 幂等：同键重复收口不重复写
    assert store.index_truncated_run(
        sid, run_end_reason="cancelled", run_end_seq=run_ends[-1].seq
    ) is False


def test_b1_row_wire_projection_placeholder_no_leak(build_test_engine):
    """wire 验收（设计§四）: B1 标注行在 provider 视图折叠为字节稳定占位——
    截断标注文本与推理尾零泄漏；存储真相不动。"""
    engine, fake = build_test_engine([])
    full = "ABCDEFGHIJKLMNO"

    def slow_stream(**_kwargs):
        yield StreamDelta(text="A")
        yield StreamDelta(text="", reasoning="think-part")
        for ch in full[1:]:
            yield StreamDelta(text=ch)
            threading.Event().wait(0.02)

    fake.chat_stream = slow_stream
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    _handle, q = runner.start(sid, "hello")
    assert q.get(timeout=2.0)["type"] == "delta"
    assert runner.cancel(sid) is True
    for _ in range(3):
        if q.get(timeout=3.0)["type"] == "done":
            break

    # 恢复同步 fake，跑一轮正常轮捕获 provider 视图（上一轮的 B1 行进 build）
    fake.chat_stream = None
    fake._responses = [{"content": "好的"}]
    engine.run(sid, "继续")

    wire = fake.calls[-1]["messages"]
    joined = "\n".join(str(m.get("content") or "") for m in wire)
    assert "[截断标注]" not in joined, "截断标注文本不得进 provider 视图"
    assert "think-part" not in joined, "推理尾不得进 provider 视图"
    assert "[program-final]" in joined, "程序行应折叠为字节稳定占位"
    # 存储真相不动：标注行完整保留在会话
    sess = engine.session.load(sid)
    assert any("[截断标注]" in str(m.content or "") for m in sess.messages)


def test_engine_llm_error_persists_b1_row_and_b2_row(build_test_engine, tmp_path):
    """同步 chat 抛 LLMError：B1 零产物不加行 + B2 truncated 行（llm_error）。"""
    engine, fake = build_test_engine([])
    engine.episode_store = EpisodeStore(tmp_path / "episodes2")  # conftest 未装配，测试注入
    # 直接调 B1 面（run 级路由面由集成覆盖；此处断言 store/索引契约）
    from llm_loop.event_log.store import EventStore

    es = EventStore(tmp_path / "events2")
    engine._event_store = es
    sid = engine.session.create()
    sess = engine.session.load(sid)
    engine._on_llm_interrupted(
        sess, text_parts=[], reasoning_parts=[], reason="llm_error",
        error_digest=_digest(), round_no=1,
    )
    engine._run_finalizer._index_truncated_run(
        session_id=sid, run_end_reason="llm_error", rounds=1, run_end_seq=7
    )
    assert sess.messages == []  # 零产物不加行
    hits = engine.episode_store.search_truncated(sid, query="boom")
    assert len(hits) == 1 and hits[0]["run_end_reason"] == "llm_error"
    compact = engine.episode_store.hydrate_truncated(sid, hits[0]["ref"])
    assert compact["complete"] is True and compact["run_end_seq"] == 7


def _digest():
    from llm_loop.core.loop.engine import _llm_error_digest

    class _DigestProbeError(Exception):
        status_code = 500
        provider = "fake"

    return _llm_error_digest(_DigestProbeError("boom"))


def test_b2_store_idempotent_row_bounded_and_search_hydrate(tmp_path):
    """store 面：幂等、行<2KB、search/hydrate、独立文件不混 resolved 索引。"""
    store = EpisodeStore(tmp_path / "episodes")
    sid = store.create_session() if hasattr(store, "create_session") else "s1"
    big = "X" * 5000
    assert store.index_truncated_run(
        sid, run_end_reason="overflow", text_tail=big, reasoning_tail=big,
        partial_chars=10000, run_end_seq=3,
    ) is True
    assert store.index_truncated_run(
        sid, run_end_reason="overflow", text_tail=big, run_end_seq=3
    ) is False, "同 (sid, run_end_seq) 幂等命中"
    assert store.index_truncated_run(
        sid, run_end_reason="guard_blocked", run_end_seq=9
    ) is True
    path = tmp_path / "episodes" / f"{sid}.truncated.jsonl"
    assert path.exists()
    for line in path.read_text(encoding="utf-8").splitlines():
        assert line.encode("utf-8") and len(json.loads(line)["text_tail"]) <= 700
        assert len(line.encode("utf-8")) < 2048, "行级 <2KB"
    hits = store.search_truncated(sid, limit=1)
    assert len(hits) == 1 and hits[0]["run_end_reason"] == "guard_blocked"  # 时间倒序取最新
    all_hits = store.search_truncated(sid)
    assert len(all_hits) == 2
    compact = store.hydrate_truncated(sid, all_hits[0]["ref"])
    assert compact["entry_kind"] == "truncated" and compact["complete"] is True


def test_b2_searcher_merges_truncated_and_dispatches_hydrate(tmp_path):
    """检索面：resolved+truncated 按时间倒序合并；truncated ref 走 compact 水合。"""
    store = EpisodeStore(tmp_path / "episodes")
    sid = "s-search"
    store.index_truncated_run(
        sid, ts="2026-09-02T04:40:00", run_end_reason="cancelled",
        text_tail="被打断的尾段", run_end_seq=2,
    )
    store.index_truncated_run(
        sid, ts="2026-09-02T04:34:00", run_end_reason="llm_error",
        error_digest="400 bad", run_end_seq=1,
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", episode_store=store)
    hits = searcher.search(kind="episode", query="", session_id=sid)
    states = [h.get("state") for h in hits if h.get("kind") == "episode"]
    assert "truncated" in states and len([s for s in states if s == "truncated"]) == 2
    order = [h["id"] for h in hits if h.get("state") == "truncated"]
    assert order == sorted(order, reverse=True), "按 ts 倒序"
    top = [h for h in hits if h.get("state") == "truncated"][0]
    rec = searcher.hydrate_episode(session_id=sid, ref=top["ref"])
    assert rec["complete"] is True and rec["run_end_reason"] == "cancelled"
