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
from types import SimpleNamespace

from llm_loop.core.loop.events import _EventsMixin
from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import Message, MessageSource
from llm_loop.introspection.search import RecordSearcher
from llm_loop.llm.client import StreamDelta
from llm_loop.memory.episode import EpisodeStore

_STOP_TEXT = "（已停止——用户点击停止按钮，本轮回答终止）"


# ── 桩：只承载 _EventsMixin（_on_llm_interrupted 单元面）──
class _StubEngine(_EventsMixin):
    def __init__(self, event_store=None, *, data_dir="."):
        self._event_store = event_store
        self.settings = SimpleNamespace(data_dir=str(data_dir))
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


def test_b1_interrupted_row_is_storage_truth_but_not_provider_history() -> None:
    from llm_loop.core.episode_history import provider_message_visible

    eng, sess = _run_interrupted(
        (["partial-answer"], ["partial-reasoning"]), reason="cancelled"
    )
    assert eng._last_interrupted["partial_chars"] > 0
    assert len(sess.messages) == 1
    assert sess.messages[0].metadata["llm_interrupted"] is True
    assert provider_message_visible(sess.messages[0]) is False


def test_inflight_partial_checkpoint_persists_exact_model_tails(tmp_path) -> None:
    """Hard-restart recovery source is event-only model state, not a chat message."""
    from llm_loop.event_log.store import EventStore

    es = EventStore(tmp_path / "checkpoint-events")
    eng = _StubEngine(es)
    sess, _store = eng.new()
    eng._on_llm_partial_checkpoint(
        sess,
        text_parts=["MODEL-", "PARTIAL"],
        reasoning_parts=["THINK-", "TAIL"],
        round_no=4,
        provider="glm",
        model="glm/glm-5.3",
    )

    rows = [e for e in es.read(sess.session_id) if e.type == "llm.partial_checkpoint"]
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload["round"] == 4
    assert payload["provider"] == "glm"
    assert payload["model"] == "glm/glm-5.3"
    assert payload["text_tail"] == "MODEL-PARTIAL"
    assert payload["reasoning_tail"] == "THINK-TAIL"
    assert payload["text_chars"] == len("MODEL-PARTIAL")
    assert payload["reasoning_chars"] == len("THINK-TAIL")
    assert len(payload["partial_sha256"]) == 64
    assert sess.messages == []


def test_inflight_native_state_uses_private_sidecar_and_supports_native_only_checkpoint(
    tmp_path,
) -> None:
    """Opaque reasoning/tool drafts are durable without becoming chat history/tool calls."""
    from llm_loop.event_log.store import EventStore

    es = EventStore(tmp_path / "native-events")
    eng = _StubEngine(es, data_dir=tmp_path)
    sess, _store = eng.new()
    replay = {
        "provider": "minimax",
        "fields": {
            "reasoning_details": [
                {"type": "reasoning.text", "text": "plan", "signature": "sig-1"}
            ]
        },
    }
    drafts = [
        {
            "index": 0,
            "id": "call-1",
            "name": "read_file",
            "arguments_raw": '{"path":"py',
        }
    ]
    eng._on_llm_partial_checkpoint(
        sess,
        text_parts=[],
        reasoning_parts=[],
        round_no=2,
        provider="minimax",
        model="minimax/MiniMax-M3",
        provider_replay=replay,
        tool_call_drafts=drafts,
    )

    rows = [e for e in es.read(sess.session_id) if e.type == "llm.partial_checkpoint"]
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload["tool_call_draft_count"] == 1
    assert payload["native_state_chars"] > 0
    assert len(payload["native_state_sha256"]) == 64
    sidecar = tmp_path / "audit" / "inflight" / f"{sess.session_id}.json"
    assert sidecar.exists()
    native = json.loads(sidecar.read_text(encoding="utf-8"))
    assert native["provider_replay"] == replay
    assert native["tool_call_drafts"] == drafts
    assert sess.messages == []


def test_inflight_sidecar_keeps_full_reasoning_when_event_tail_is_bounded(
    tmp_path, monkeypatch
) -> None:
    """Append-only event stays small while private crash snapshot keeps all received bytes."""
    from llm_loop.event_log.store import EventStore

    monkeypatch.setenv("INTERRUPT_TEXT_TAIL_CHARS", "5")
    monkeypatch.setenv("INTERRUPT_REASONING_TAIL_CHARS", "7")
    es = EventStore(tmp_path / "full-events")
    eng = _StubEngine(es, data_dir=tmp_path)
    sess, _store = eng.new()
    text = "TEXT-" * 30
    reasoning = "REASON-" * 100
    eng._on_llm_partial_checkpoint(
        sess,
        text_parts=[text],
        reasoning_parts=[reasoning],
        round_no=3,
        provider="deepseek",
        model="deepseek/deepseek-v4-flash",
    )

    row = [e for e in es.read(sess.session_id) if e.type == "llm.partial_checkpoint"][-1]
    assert row.payload["text_tail"] == text[-5:]
    assert row.payload["reasoning_tail"] == reasoning[-7:]
    assert len(row.payload["native_state_sha256"]) == 64
    native = eng._load_inflight_native_state(
        sess.session_id,
        expected_sha256=row.payload["native_state_sha256"],
        expected_round=3,
        expected_provider="deepseek",
        expected_model="deepseek/deepseek-v4-flash",
        expected_partial_sha256=row.payload["partial_sha256"],
    )
    assert native is not None
    assert native["text_full"] == text
    assert native["reasoning_full"] == reasoning


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
    from llm_loop.core.loop.engine_services.interrupted_capture import (
        llm_error_digest as _llm_error_digest,
    )

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
    assert "[program-final]" not in joined, "legacy 程序 marker 不得复活到 provider 视图"
    assert any(m.get("role") == "assistant" and not str(m.get("content") or "") for m in wire), (
        "程序终态仅允许 zero-content assistant role boundary"
    )
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



def test_generic_llm_error_partial_is_not_promoted_to_adjacent_resume(build_test_engine):
    from llm_loop.core.run_context import current_session_id

    engine, _fake = build_test_engine([])
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages = [
        Message(role="user", content="compare products", source=MessageSource.USER),
        Message(
            role="assistant",
            content="PARTIAL\n[截断标注] reason=llm_error",
            reasoning_content="RUNAWAY-REASONING",
            source=MessageSource.SYSTEM,
            metadata={
                "answer_origin": "program",
                "run_end_reason": "llm_error",
                "llm_interrupted": True,
                "interrupted_text_tail": "PARTIAL",
                "interrupted_reasoning_tail": "RUNAWAY-REASONING",
            },
        ),
        Message(role="user", content="continue", source=MessageSource.USER),
    ]
    token = current_session_id.set(sid)
    try:
        engine._prepare_interruption_resume(sid, sess)
        assert engine._run_state().interruption_resume is None
    finally:
        current_session_id.reset(token)

def _digest():
    from llm_loop.core.loop.engine_services.interrupted_capture import (
        llm_error_digest as _llm_error_digest,
    )

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


def test_truncated_exact_artifact_survives_tail_projection_and_explicit_recovery(tmp_path):
    """First view may be tailed; explicit truncated:<ref> recovery returns the exact source."""
    from llm_loop.introspection.tools_status import run_search_records

    store = EpisodeStore(tmp_path / "episodes-exact")
    eng = _StubEngine(data_dir=tmp_path / "data")
    eng.episode_store = store
    sess, session_store = eng.new()
    eng.session = session_store
    text = "T" * 15_000
    reasoning = "R" * 25_000

    eng._on_llm_interrupted(
        sess,
        text_parts=[text],
        reasoning_parts=[reasoning],
        reason="llm_error",
        error_digest="500 fake boom",
        round_no=7,
        provider="fake",
        model="fake/model",
    )

    # Provider/session projection is still bounded, but exact bytes were captured first.
    assert len(sess.messages) == 1
    assert len(sess.messages[0].content.split("\n[截断标注]", 1)[0]) == 4000
    assert len(sess.messages[0].reasoning_content or "") == 8000
    info = eng._last_interrupted
    artifact_ref = str(info.get("artifact_ref") or "")
    assert artifact_ref.startswith("truncation:")
    assert store.index_truncated_run(
        sess.session_id,
        run_end_reason="llm_error",
        error_digest="500 fake boom",
        last_round=7,
        run_end_seq=77,
        text_tail=str(info.get("text_tail") or ""),
        reasoning_tail=str(info.get("reasoning_tail") or ""),
        partial_chars=int(info.get("partial_chars") or 0),
        partial_sha256=str(info.get("partial_sha256") or ""),
        artifact_ref=artifact_ref,
    )

    searcher = RecordSearcher(audit_dir=tmp_path / "audit", episode_store=store)

    class _Adapter:
        def __call__(self, **kw):
            return searcher.search(**kw)

        def hydrate_episode(self, **kw):
            return searcher.hydrate_episode(**kw)

    recovered = run_search_records(
        object(),
        _Adapter(),
        {"kind": "episode", "query": "truncated:77"},
        lambda: sess.session_id,
    )
    assert recovered.status.value == "success"
    # 40K source fits the explicit recovery hard page, so the second read is complete.
    assert "complete=true" in recovered.content
    assert "T" * 15_000 in recovered.content
    assert "R" * 25_000 in recovered.content


def test_truncated_exact_recovery_over_physical_page_continues_without_repeating_head(tmp_path):
    """>100K exact source paginates monotonically instead of applying the first-view tail again."""
    from llm_loop.introspection.tools_status import run_search_records

    store = EpisodeStore(tmp_path / "episodes-page")
    sid = "s-page-exact"
    text = "HEAD-UNIQUE|" + "A" * 119_000 + "|TAIL-UNIQUE"
    artifact_ref = store.capture_truncated_artifact(
        sid,
        reason="llm_error",
        round_no=3,
        provider="fake",
        model="fake/model",
        text_full=text,
        partial_sha256="x" * 64,
    )
    assert store.index_truncated_run(
        sid,
        run_end_reason="llm_error",
        run_end_seq=88,
        text_tail=text[-700:],
        partial_chars=len(text),
        partial_sha256="x" * 64,
        artifact_ref=artifact_ref,
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", episode_store=store)

    class _Adapter:
        def __call__(self, **kw):
            return searcher.search(**kw)

        def hydrate_episode(self, **kw):
            return searcher.hydrate_episode(**kw)

    first = run_search_records(
        object(), _Adapter(), {"kind": "episode", "query": "truncated:88"}, lambda: sid
    )
    assert "complete=false" in first.content
    assert "HEAD-UNIQUE" in first.content
    next_query = first.content.split("next_query=", 1)[1].splitlines()[0].strip()
    second = run_search_records(
        object(), _Adapter(), {"kind": "episode", "query": next_query}, lambda: sid
    )
    assert "HEAD-UNIQUE" not in second.content
    assert "TAIL-UNIQUE" in second.content
    assert "complete=true" in second.content


def test_open_stream_checkpoint_is_promoted_before_sidecar_can_be_cleared(
    build_test_engine, tmp_path
) -> None:
    """Crash-only checkpoint becomes immutable searchable history on the next human ingress."""
    from llm_loop.event_log.store import EventStore

    engine, _fake = build_test_engine([])
    engine.episode_store = EpisodeStore(tmp_path / "episodes-crash")
    engine._event_store = EventStore(tmp_path / "events-crash")
    sid = engine.session.create()
    sess = engine.session.load(sid)
    text = "CRASH-TEXT-" * 900
    reasoning = "CRASH-REASON-" * 1300
    engine._on_llm_partial_checkpoint(
        sess,
        text_parts=[text],
        reasoning_parts=[reasoning],
        round_no=5,
        provider="fake",
        model="fake/model",
    )
    checkpoint = [
        e for e in engine._event_store.read(sid) if e.type == "llm.partial_checkpoint"
    ][-1]
    # Simulate the fresh human ingress after the process died before run.end.
    sess.messages = [Message(role="user", content="继续", source=MessageSource.USER)]
    engine.session.save(sess)

    engine._prepare_interruption_resume(sid, sess)
    resumed = engine._run_state().interruption_resume
    assert resumed is not None and resumed["source"] == "open_stream_checkpoint"
    assert resumed["text_tail"] == text
    assert resumed["reasoning_tail"] == reasoning
    trunc_ref = str(resumed.get("truncation_ref") or "")
    assert trunc_ref == f"truncated:checkpoint:{checkpoint.seq}"
    assert str(resumed.get("artifact_ref") or "").startswith("truncation:")

    # A later successful run may clear the overwrite-only sidecar; exact history survives.
    engine._clear_inflight_native_state(sid)
    recovered = engine.episode_store.hydrate_truncated(sid, trunc_ref, max_chars=100_000)
    assert recovered is not None and recovered["exact_artifact"] is True
    assert recovered["complete"] is True
    assert text in recovered["content"]
    assert reasoning in recovered["content"]


def test_history_compaction_flag_does_not_create_provider_truncation_index(tmp_path) -> None:
    """Prompt/history compaction and provider output truncation are different facts."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from llm_loop.core.loop.engine_services.run_finalizer import RunFinalizer

    host = MagicMock()
    host.memory = None
    host._post_run_cache_health.return_value = "done"
    host._kpi_snapshot.return_value = {}
    host._event_append.return_value = SimpleNamespace(seq=41)
    host._persist_long_answer.side_effect = lambda _sid, text: text
    host.episode_store = MagicMock()
    finalizer = RunFinalizer(host)

    answer = finalizer._settle_run_end(
        sess=SimpleNamespace(),
        session_id="s-history-compact",
        final_answer="done",
        _run_end_reason="completed",
        _cancel_reason="",
        rounds=1,
        model_used="fake/model",
        tokens_in=1,
        tokens_out=1,
        tokens_cache_hit=0,
        truncation_noted=True,
        provider_truncated=False,
        _run_started_at=0.0,
    )

    assert answer == "done"
    host.episode_store.index_truncated_run.assert_not_called()


def test_llm_interrupted_event_persists_terminal_transport_and_timing(tmp_path) -> None:
    from llm_loop.event_log.store import EventStore

    es = EventStore(tmp_path / "events")
    eng = _StubEngine(es)
    sess, _store = eng.new()
    eng._on_llm_interrupted(
        sess,
        text_parts=[],
        reasoning_parts=["R" * 32],
        reason="llm_error",
        round_no=9,
        provider="cognilocal",
        model="ornith",
        transport_facts={
            "finish_reason": "length",
            "completion_tokens": 4096,
            "reasoning_tokens": 4096,
            "provider_truncated": False,
        },
        timing={
            "provider_total_ms": 4100.0,
            "first_delta_ms": 12.0,
            "first_reasoning_ms": 12.0,
            "first_visible_ms": None,
            "first_tool_call_ms": None,
            "prefill_end_ms": None,
        },
    )
    rows = [e for e in es.read(sess.session_id) if e.type == "llm.interrupted"]
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload["completion_tokens"] == 4096
    assert payload["finish_reason"] == "length"
    assert payload["reasoning_tokens"] == 4096
    assert payload["provider_truncated"] is False
    assert payload["reasoning_tail_chars"] == 32
    assert payload["text_tail_chars"] == 0
    assert payload["timing"]["first_reasoning_ms"] == 12.0
    assert payload["timing"]["first_visible_ms"] is None
    assert payload["timing"]["prefill_end_ms"] is None


def test_interrupted_capture_carries_empty_response_transport_facts_without_replay() -> None:
    from llm_loop.core.loop.engine_services.interrupted_capture import InterruptedCapture
    from llm_loop.llm.errors import LLMEmptyResponseError

    class Host:
        def __init__(self) -> None:
            self.interrupted = None

        def _on_llm_partial_checkpoint(self, *args, **kwargs) -> None:
            return None

        def _on_llm_interrupted(self, *args, **kwargs) -> None:
            self.interrupted = kwargs

    host = Host()
    sess = SimpleNamespace(session_id="s-causal")
    cap = InterruptedCapture(host, sess=sess, round_no=4, provider="p", model="m")
    cap.mark_provider_send()
    cap.on_delta(StreamDelta(text="", reasoning="THINK"))
    exc = LLMEmptyResponseError(
        "empty",
        provider="p",
        finish_reason="length",
        completion_tokens=4096,
        reasoning_tokens=4096,
        provider_truncated=False,
    )
    cap.fire(sess, "llm_error", 4, exc)

    assert host.interrupted is not None
    assert host.interrupted["transport_facts"] == {
        "finish_reason": "length",
        "completion_tokens": 4096,
        "reasoning_tokens": 4096,
        "provider_truncated": False,
    }
    assert host.interrupted["reasoning_parts"] == ["THINK"]
    timing = host.interrupted["timing"]
    assert timing["first_reasoning_ms"] is not None
    assert timing["first_visible_ms"] is None
    assert timing["first_tool_call_ms"] is None
    assert timing["provider_total_ms"] is not None
    # Telemetry capture does not manufacture a provider replay/tool execution path.
    assert host.interrupted["provider_replay"] is None
    assert host.interrupted["tool_call_drafts"] == []
