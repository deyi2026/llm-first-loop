"""err1210 P0 恢复回归测试（.codeartsdoer/specs/err1210_locating，tasks 1.3/2.4/3.7/5.x）.

覆盖:
- T1.3 payload_trace 按日轮转 + 过期清理 + 无代码读取方固化
- T2.4 三函数边界（parse_provider_error_code / reset_hotcard_consumed / restore_gate_note）
- T3.7 模块级（is_err1210 / InjectionSpan / 剥离身份复核 / 快照凭据排除 / 耗尽生命周期）
- T5.x engine 级全分支（恢复/defer 回存/防误触/防循环/二阶失败）

零真实网络（_FakeLLMClient 可编程异常队列）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from llm_loop.core.cache_health import GATE_NOTE_CONTENT, CacheHealthMonitor
from llm_loop.core.loop.err1210 import (
    InjectedEntry,
    InjectionSpan,
    SlotKind,
    _Err1210Mixin,
    content_prefix_sha,
    is_err1210,
    record_defer_event,
    snapshot_offending_payload,
)
from llm_loop.core.loop.hotcard import (
    hotcard_path,
    pop_hotcard,
    reset_hotcard_consumed,
    write_hotcard,
)
from llm_loop.core.message import Message, MessageSource
from llm_loop.llm.client import _cleanup_trace_shards, _maybe_rotate_trace_file
from llm_loop.llm.errors import LLMHTTPError, parse_provider_error_code

from .test_model_attribution import (
    _FakeLLMClient,
    _make_engine,
    _make_pool,
    _settings,
)

_ERR1210_BODY = '{"error":{"code":"1210","message":"Invalid parameter"}}'


def _e1210() -> LLMHTTPError:
    return LLMHTTPError("400 Invalid parameter", status_code=400, body=_ERR1210_BODY)


# ── T1.3: payload_trace 轮转 ──


class TestTraceRotation:
    def test_rotate_on_cross_day_mtime(self, tmp_path, monkeypatch):
        active = tmp_path / "payload_trace.jsonl"
        active.write_text('{"a":1}\n', encoding="utf-8")
        # 伪造昨日 mtime
        old = time.time() - 86400 * 2
        os.utime(active, (old, old))
        import llm_loop.llm.client as client_mod

        monkeypatch.setattr(client_mod, "_TRACE_ROTATE_LAST_CHECK", 0.0)
        out = _maybe_rotate_trace_file(str(active))
        assert out == str(active)
        shards = list(tmp_path.glob("payload_trace-*.jsonl"))
        assert len(shards) == 1
        assert not active.exists() or active.read_text() == ""  # 活跃文件已切走

    def test_no_rotate_same_day(self, tmp_path, monkeypatch):
        active = tmp_path / "payload_trace.jsonl"
        active.write_text('{"a":1}\n', encoding="utf-8")
        import llm_loop.llm.client as client_mod

        monkeypatch.setattr(client_mod, "_TRACE_ROTATE_LAST_CHECK", 0.0)
        _maybe_rotate_trace_file(str(active))
        assert active.exists()
        assert not list(tmp_path.glob("payload_trace-*.jsonl"))

    def test_throttled_within_hour(self, tmp_path, monkeypatch):
        active = tmp_path / "payload_trace.jsonl"
        active.write_text('{"a":1}\n', encoding="utf-8")
        old = time.time() - 86400 * 2
        os.utime(active, (old, old))
        import llm_loop.llm.client as client_mod

        monkeypatch.setattr(client_mod, "_TRACE_ROTATE_LAST_CHECK", time.time() - 60)
        _maybe_rotate_trace_file(str(active))
        assert active.exists()  # 节流期内不实际检查

    def test_cleanup_expired_shards(self, tmp_path, monkeypatch):
        active = tmp_path / "payload_trace.jsonl"
        active.write_text("{}", encoding="utf-8")
        stale = tmp_path / "payload_trace-20200101.jsonl"
        stale.write_text("{}", encoding="utf-8")
        old = time.time() - 86400 * 30  # 清理按 mtime 判定（文件名仅命名约定）
        os.utime(stale, (old, old))
        fresh = tmp_path / "payload_trace-20990101.jsonl"
        fresh.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("LLM_PAYLOAD_TRACE_RETAIN_DAYS", "7")
        _cleanup_trace_shards(active)
        assert not stale.exists()
        assert fresh.exists()

    def test_no_code_reader_regression(self):
        """固化'全仓无 payload_trace 代码读取方'事实（防未来新增读取方忽略跨分片聚合）."""
        import subprocess
        import sys

        root = Path(__file__).resolve().parents[2]
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                "import subprocess,sys\n"
                "out = subprocess.run(['git','-C',sys.argv[1],'grep','-n','payload_trace','--','src/'],\n"
                "                     capture_output=True, text=True).stdout\n"
                "lines = [l for l in out.splitlines() if 'payload_trace' in l]\n"
                "print('\\n'.join(lines))",
                str(root),
            ],
            capture_output=True,
            text=True,
        )
        hits = [line for line in r.stdout.splitlines() if line.strip()]

        def _is_comment_ref(line: str) -> bool:
            # git grep 输出格式 src/path:lineno:content——注释行（# 开头）是说明性引用非读取方
            content = line.split(":", 2)[-1].lstrip()
            return content.startswith("#")

        # 允许: ① client.py 写入侧本体（trace 函数/轮转/清理/诊断）② 任意文件的注释性提及
        # （如 err1210.py trace_key 注释——git grep 只搜 tracked 文件，e9a2e6b 落库后
        # 该注释进入扫描范围；本测试防的是"读取方代码"，注释不构成读取）
        allowed = all(
            (("llm/client.py" in line or "llm\\client.py" in line) or _is_comment_ref(line))
            and "read" not in line.lower()
            for line in hits
        )
        assert allowed, f"payload_trace 出现了写入侧之外的引用:\n{chr(10).join(hits)}"

    def test_wildcard_aggregation(self, tmp_path, monkeypatch):
        """轮转后 payload_trace*.jsonl 通配聚合可覆盖活跃+历史分片（离线消费习惯）."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "payload_trace.jsonl").write_text('{"i":1}\n', encoding="utf-8")
        (tmp_path / "payload_trace-20200101.jsonl").write_text('{"i":0}\n', encoding="utf-8")
        rows = []
        for p in sorted(tmp_path.glob("payload_trace*.jsonl")):
            rows.extend(json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip())
        assert [r["i"] for r in rows] == [0, 1]


# ── T2.4: 三函数边界 ──


class TestParseProviderErrorCode:
    def test_plain_json(self):
        assert parse_provider_error_code(_ERR1210_BODY) == "1210"

    def test_escaped_json_string(self):
        body = json.dumps(_ERR1210_BODY)  # '"{\\"error\\":{...}}"'
        assert parse_provider_error_code(body) == "1210"

    def test_double_escaped(self):
        body = json.dumps(json.dumps(_ERR1210_BODY))
        assert parse_provider_error_code(body) == "1210"

    def test_prefix_suffix_noise(self):
        body = f"upstream said: {_ERR1210_BODY} (truncated)"
        assert parse_provider_error_code(body) == "1210"

    def test_empty_and_garbage(self):
        assert parse_provider_error_code("") is None
        assert parse_provider_error_code("not json at all") is None
        assert parse_provider_error_code('{"error":{"code":"abc"}}') == "abc"
        assert parse_provider_error_code('{"other":1}') is None


class TestResetHotcardConsumed:
    def test_reset_and_repop(self, tmp_path):
        write_hotcard(origin_session="other-sess", anchor="任务A", data_dir=tmp_path)
        text = pop_hotcard(session_id="sess-1", data_dir=tmp_path)
        assert text and "任务A" in text
        card = json.loads(hotcard_path(tmp_path).read_text(encoding="utf-8"))
        assert card["consumed"] is True
        # 复位（身份匹配）
        assert reset_hotcard_consumed(session_id="sess-1", data_dir=tmp_path) is True
        card = json.loads(hotcard_path(tmp_path).read_text(encoding="utf-8"))
        assert card["consumed"] is False and card["consumed_by"] == ""
        # 复位后可再次 pop（重注入语义）
        again = pop_hotcard(session_id="sess-1", data_dir=tmp_path)
        assert again == text

    def test_stale_card_not_reset(self, tmp_path):
        write_hotcard(origin_session="other-sess", anchor="任务A", data_dir=tmp_path)
        pop_hotcard(session_id="sess-1", data_dir=tmp_path)
        # 不同会话请求复位 → 拒绝（防复活已被新事件接管的卡）
        assert reset_hotcard_consumed(session_id="sess-2", data_dir=tmp_path) is False

    def test_missing_card_returns_false(self, tmp_path):
        assert reset_hotcard_consumed(session_id="s", data_dir=tmp_path) is False

    def test_idempotent_double_reset(self, tmp_path):
        write_hotcard(origin_session="o", anchor="a", data_dir=tmp_path)
        pop_hotcard(session_id="s1", data_dir=tmp_path)
        assert reset_hotcard_consumed(session_id="s1", data_dir=tmp_path) is True
        assert reset_hotcard_consumed(session_id="s1", data_dir=tmp_path) is False  # 已复位


class TestRestoreGateNote:
    def test_restore_then_take(self):
        mon = CacheHealthMonitor()
        sid = "sess-x"
        assert mon.take_gate_note(sid) is False  # 无标记
        mon.restore_gate_note(sid)  # 对不存在桶 fail-open 置位
        assert mon.take_gate_note(sid) is True
        assert mon.take_gate_note(sid) is False  # 一次性


# ── T3.7: 模块级 ──


class TestIsErr1210:
    def test_positive(self):
        assert is_err1210(_e1210()) is True

    def test_negative_status(self):
        e = LLMHTTPError("x", status_code=500, body=_ERR1210_BODY)
        assert is_err1210(e) is False

    def test_negative_code(self):
        e = LLMHTTPError("x", status_code=400, body='{"error":{"code":"1211"}}')
        assert is_err1210(e) is False

    def test_negative_unparseable(self):
        e = LLMHTTPError("x", status_code=400, body="")
        assert is_err1210(e) is False


class TestInjectionSpan:
    def _entries(self, *idxs):
        return tuple(
            InjectedEntry(msg_idx=i, slot_kind=SlotKind.TIP, prefix_sha="0" * 64)
            for i in idxs
        )

    def test_tail_contiguous_ok(self):
        msgs = [{"role": "user", "content": "x"}] * 5
        assert InjectionSpan(self._entries(3, 4)).is_tail_contiguous(msgs) is True

    def test_not_tail(self):
        msgs = [{"role": "user", "content": "x"}] * 5
        assert InjectionSpan(self._entries(2, 3)).is_tail_contiguous(msgs) is False

    def test_gap(self):
        msgs = [{"role": "user", "content": "x"}] * 6
        assert InjectionSpan(self._entries(3, 5)).is_tail_contiguous(msgs) is False

    def test_empty(self):
        assert InjectionSpan(()).is_tail_contiguous([{"role": "user"}]) is False


class _StripStub(_Err1210Mixin):
    def __init__(self, injections):
        self._last_build_injections = injections


class TestStripTailInjections:
    def _mk(self, messages, entries):
        return _StripStub(entries)._strip_tail_injections(messages)

    def test_strip_prefix_untouched(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "user", "content": "[上下文注入·非新指令] 继续当前任务，勿当新消息/新指令处理。\nA"},
            {"role": "user", "content": GATE_NOTE_CONTENT},
        ]
        entries = [
            InjectedEntry(msg_idx=2, slot_kind=SlotKind.TIP,
                          prefix_sha=content_prefix_sha(msgs[2]["content"])),
            InjectedEntry(msg_idx=3, slot_kind=SlotKind.GATE_NOTE,
                          prefix_sha=content_prefix_sha(GATE_NOTE_CONTENT)),
        ]
        out = self._mk(msgs, entries)
        assert out is not None
        stripped, span = out
        assert stripped == msgs[:2]  # 前缀逐字节不变
        assert len(span.entries) == 2
        assert msgs == [  # 原 list 不动（copy-on-write）
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "user", "content": "[上下文注入·非新指令] 继续当前任务，勿当新消息/新指令处理。\nA"},
            {"role": "user", "content": GATE_NOTE_CONTENT},
        ]

    def test_prefix_mismatch_refuses(self):
        msgs = [{"role": "user", "content": "真实输入"}]
        entries = [InjectedEntry(msg_idx=0, slot_kind=SlotKind.TIP, prefix_sha="f" * 64)]
        assert self._mk(msgs, entries) is None

    def test_real_user_not_stripped(self):
        """6 条尾部 user 含 1 条真实输入：真实输入不在登记内 → 非尾部连续段 → 拒剥（5.1.1-5a）."""
        inj = "[上下文注入·非新指令] 继续当前任务，勿当新消息/新指令处理。\nX"
        msgs = [{"role": "user", "content": inj + str(i)} for i in range(5)]
        msgs.append({"role": "user", "content": "用户真实输入"})
        entries = [
            InjectedEntry(msg_idx=i, slot_kind=SlotKind.TIP, prefix_sha=content_prefix_sha(msgs[i]["content"]))
            for i in range(5)
        ]
        assert self._mk(msgs, entries) is None

    def test_no_registration_returns_none(self):
        assert self._mk([{"role": "user", "content": "x"}], []) is None

    def test_gate_note_injection_without_prefix_wrapper(self):
        """gate_note 恒等校验（GATE_NOTE_CONTENT 而非 _INJECTION_PREFIX）."""
        msgs = [{"role": "user", "content": GATE_NOTE_CONTENT}]
        entries = [InjectedEntry(msg_idx=0, slot_kind=SlotKind.GATE_NOTE,
                                 prefix_sha=content_prefix_sha(GATE_NOTE_CONTENT))]
        out = self._mk(msgs, entries)
        assert out is not None and out[0] == []


class TestSnapshot:
    def test_snapshot_content_and_no_credentials(self, tmp_path):
        msgs = [{"role": "user", "content": "x"}]
        p = snapshot_offending_payload(
            messages=msgs, tools=[{"name": "t"}], params={"model": "m"},
            session_id="sess-123456789", model="m", is_compact_first=True,
            span=None, data_dir=tmp_path,
        )
        assert p is not None and p.exists()
        snap = json.loads(p.read_text(encoding="utf-8"))
        assert snap["messages"] == msgs
        assert snap["is_compact_first"] is True
        assert "api_key" not in json.dumps(snap)
        assert "headers" not in json.dumps(snap)

    def test_snapshot_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ERR1210_SNAPSHOT", "0")
        assert snapshot_offending_payload(
            messages=[], tools=[], params={}, session_id="s", model="m",
            is_compact_first=False, span=None, data_dir=tmp_path,
        ) is None


class _DeferStub(_Err1210Mixin):
    def __init__(self, data_dir):
        self.settings = SimpleNamespace(data_dir=str(data_dir))
        self._cache_monitor = CacheHealthMonitor()
        self._interop_tail_messages = None
        self._tip_tail_messages = None
        self._deferred_replay_refs = []
        self._deferred_replay_slots = set()


class TestDeferStore:
    def _sess(self):
        return SimpleNamespace(session_id="sess-d1")

    def test_interop_tip_refill(self, tmp_path):
        stub = _DeferStub(tmp_path)
        m1 = Message(role="system", content="协调A", source=MessageSource.SYSTEM)
        m2 = Message(role="system", content="提示B", source=MessageSource.SYSTEM)
        entries = [
            InjectedEntry(msg_idx=0, slot_kind=SlotKind.INTEROP, prefix_sha="a" * 64, message_ref=m1),
            InjectedEntry(msg_idx=1, slot_kind=SlotKind.TIP, prefix_sha="b" * 64, message_ref=m2),
        ]
        assert stub._defer_store(self._sess(), entries) is True
        assert stub._interop_tail_messages == [m1]
        assert stub._tip_tail_messages == [m2]
        # 重注入检测登记
        assert {s for s, _ in stub._deferred_replay_refs} == {SlotKind.INTEROP, SlotKind.TIP}

    def test_idempotent(self, tmp_path):
        stub = _DeferStub(tmp_path)
        m = Message(role="system", content="协调A", source=MessageSource.SYSTEM)
        entries = [InjectedEntry(msg_idx=0, slot_kind=SlotKind.INTEROP, prefix_sha="a" * 64, message_ref=m)]
        stub._defer_store(self._sess(), entries)
        stub._defer_store(self._sess(), entries)  # 重复执行
        assert len(stub._interop_tail_messages) == 1  # 不累积
        assert stub._interop_tail_messages[0] is m

    def test_hotcard_and_gate_note_slots(self, tmp_path):
        write_hotcard(origin_session="o", anchor="a", data_dir=tmp_path)
        pop_hotcard(session_id="sess-d1", data_dir=tmp_path)  # 消费
        stub = _DeferStub(tmp_path)
        entries = [
            InjectedEntry(msg_idx=0, slot_kind=SlotKind.HOTCARD, prefix_sha="h" * 64),
            InjectedEntry(msg_idx=1, slot_kind=SlotKind.GATE_NOTE, prefix_sha="g" * 64),
        ]
        assert stub._defer_store(self._sess(), entries) is True
        assert stub._cache_monitor.take_gate_note("sess-d1") is True  # 已置位
        assert pop_hotcard(session_id="sess-d1", data_dir=tmp_path) is not None  # 可再取出

    def test_overflow_drops_non_interop(self, tmp_path):
        stub = _DeferStub(tmp_path)
        write_hotcard(origin_session="o", anchor="a", data_dir=tmp_path)
        pop_hotcard(session_id="sess-d1", data_dir=tmp_path)
        interop = [Message(role="system", content=f"协调{i}", source=MessageSource.SYSTEM) for i in range(8)]
        entries = (
            [InjectedEntry(msg_idx=i, slot_kind=SlotKind.INTEROP, prefix_sha="a" * 64, message_ref=m)
             for i, m in enumerate(interop)]
            + [InjectedEntry(msg_idx=8, slot_kind=SlotKind.HOTCARD, prefix_sha="h" * 64)]
            + [InjectedEntry(msg_idx=9, slot_kind=SlotKind.GATE_NOTE, prefix_sha="g" * 64)]
        )
        stub._defer_store(self._sess(), entries)  # 总量 10 > 8
        assert len(stub._interop_tail_messages) == 8  # interop 优先全保留
        assert all(a is b for a, b in zip(stub._interop_tail_messages, interop, strict=True))
        assert stub._tip_tail_messages is None
        assert stub._cache_monitor.take_gate_note("sess-d1") is False  # gate_note 被丢弃
        card = json.loads(hotcard_path(tmp_path).read_text(encoding="utf-8"))
        assert card["consumed"] is True and card["consumed_by"] == "sess-d1"  # hotcard 未被复位


class TestDeferTraceEvents:
    def test_events_written(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        record_defer_event("defer_stored", "s1", "interop", {"count": 2})
        p = tmp_path / "data" / "audit" / "defer_trace.jsonl"
        assert p.exists()
        row = json.loads(p.read_text(encoding="utf-8").splitlines()[-1])
        assert row["event"] == "defer_stored" and row["slot_kind"] == "interop"

    def test_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ERR1210_DEFER_TRACE", "0")
        record_defer_event("defer_stored", "s1", "interop", {})
        assert not (tmp_path / "data" / "audit" / "defer_trace.jsonl").exists()


# ── T5.x: engine 级集成 ──

_PROVIDER_JSON = json.dumps(
    {
        "zhipu": {
            "base_url": "https://api.zhipu.local/v1",
            "api_key_env": "ZHIPU_API_KEY",
            "models": {"glm-5": {"context": 300000, "thinking": True, "cost_tier": "low"}},
            "default_model": "glm-5",
        },
    }
)


def _mk(tmp_path, monkeypatch, *, responses):
    monkeypatch.setenv("ZHIPU_API_KEY", "k")
    settings = _settings(
        tmp_path,
        model_providers_raw=_PROVIDER_JSON,
        llm_model="zhipu/glm-5",
        history_max_chars=300_000,
    )
    fake = _FakeLLMClient("zhipu/glm-5")
    fake.queue(responses)
    pool = _make_pool(settings, fake, cached={"zhipu": fake})
    engine = _make_engine(tmp_path, pool, settings)
    return engine, fake


def _resp(content="恢复后的正常回答"):
    from llm_loop.llm.client import LLMResponse

    return LLMResponse(content=content, tool_calls=[], provider="fake")


def _arm_compact_first(engine, sid, *, prev_count=100):
    """骤降兜底路径武装 compact 首请求判定（prev=100 条 vs 实际 ~10 条）."""
    engine._last_request_msg_count_by_session[sid] = prev_count


class TestEngineRecovery:
    def test_basic_recovery(self, tmp_path, monkeypatch):
        """T5.1: 首调 1210 → 重试恰好 1 次、公共前缀一致、resp 正常合流、登记正确."""
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210(), _resp()])
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        # 注入槽武装: gate_note（自然走 build 注入+登记）
        engine._cache_monitor._get_bucket(sid).gate_note_pending = True
        result = engine.run(sid, "长任务继续")
        assert "恢复后的正常回答" in result.final_answer
        assert result.truncated is False
        assert len(fake.calls) == 2  # 重试恰好 1 次
        orig, retry = fake.calls[0]["messages"], fake.calls[1]["messages"]
        n_inj = len(engine._last_build_injections)  # build 登记数（gate_note 1 条）
        assert n_inj >= 1
        assert retry == orig[: len(orig) - n_inj]  # 剥离只删尾部（前缀逐字节一致）
        # defer: gate_note 已复位（下一轮可重注入）
        assert engine._cache_monitor.take_gate_note(sid) is True
        # 耗尽标记已写（本 compact 事件不再二次降级）
        assert engine._err1210_attempted.get(sid) == engine._compact_event_seq

    def test_defer_reinject_next_round(self, tmp_path, monkeypatch):
        """T5.2a: P0 恢复后 defer 的 interop 消息在下一 run 的 build 重注入."""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_e1210(), _resp(), _resp("第二轮回答")],
        )
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        m = Message(role="system", content="interop 协调消息", source=MessageSource.SYSTEM)
        engine._interop_tail_messages = [m]
        engine.run(sid, "任务A")
        # 恢复轮后 interop 槽已回填
        assert engine._interop_tail_messages and engine._interop_tail_messages[0] is m
        engine.run(sid, "任务B")  # 下一 run
        # 重注入消息进入第二轮提交（is 身份匹配消费 → defer_replayed）
        second_msgs = fake.calls[2]["messages"]
        assert any(
            isinstance(x, dict) and "interop 协调消息" in str(x.get("content", ""))
            for x in second_msgs
        )
        assert all(r is not m for r in (engine._deferred_replay_refs or []))

    def test_second_1210_no_third_retry(self, tmp_path, monkeypatch):
        """T5.4a: 连续两次 1210 → 第二次不再重发（耗尽上抛，spec 5.1.1-4a）."""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_e1210(), _e1210(), _resp("不该出现")],
        )
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        engine._cache_monitor._get_bucket(sid).gate_note_pending = True
        result = engine.run(sid, "长任务继续")
        assert len(fake.calls) == 2  # 原请求 + 1 次重试，无第三次
        assert "[LLM 调用异常]" in (result.final_answer or "")  # 如实反馈（llm_error）
        assert "不该出现" not in (result.final_answer or "")

    def test_no_trigger_without_compact(self, tmp_path, monkeypatch):
        """T5.3a: 非 compact 场景 1210 不触发剥离（保持现行行为）."""
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210()])
        sid = engine.session.create()
        # 不武装骤降、无 compact 标记
        result = engine.run(sid, "普通任务")
        assert len(fake.calls) == 1  # 无重试
        assert "[LLM 调用异常]" in (result.final_answer or "")

    def test_no_trigger_on_unparseable_400(self, tmp_path, monkeypatch):
        """T5.3b: 解析失败的 400 不触发."""
        e = LLMHTTPError("400 bad", status_code=400, body="")
        engine, fake = _mk(tmp_path, monkeypatch, responses=[e])
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        engine.run(sid, "任务")
        assert len(fake.calls) == 1

    def test_env_switch_off(self, tmp_path, monkeypatch):
        """T5.3c: ERR1210_RECOVERY=0 完全旁路（零行为）."""
        monkeypatch.setenv("ERR1210_RECOVERY", "0")
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210()])
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        engine._cache_monitor._get_bucket(sid).gate_note_pending = True
        result = engine.run(sid, "任务")
        assert len(fake.calls) == 1
        assert "[LLM 调用异常]" in (result.final_answer or "")

    def test_new_compact_event_rearms(self, tmp_path, monkeypatch):
        """T5.4d: 新 compact 事件后耗尽标记清除、降级机会重获."""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_e1210(), _e1210(), _e1210(), _resp("第三次成功")],
        )
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        engine._cache_monitor._get_bucket(sid).gate_note_pending = True  # 需有注入登记可供剥离
        engine.run(sid, "任务")  # 原请求 + 重试 1210 → 耗尽（2 次调用）
        assert len(fake.calls) == 2
        # 模拟新 compact 事件（seq 递增）
        engine._compact_event_seq += 1
        _arm_compact_first(engine, sid)
        engine._cache_monitor._get_bucket(sid).gate_note_pending = True
        result = engine.run(sid, "新压缩后继续")
        assert len(fake.calls) == 4  # 新事件 → 再次降级（第 3 次调用 1210 + 第 4 次成功）
        assert "第三次成功" in result.final_answer

    def test_second_order_failure_records_event(self, tmp_path, monkeypatch):
        """T5.2d 二阶失败 [r3-P2]: 重注入轮再 1210 → 不触发 P0 + defer_lost_on_reinject 记录."""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_e1210(), _resp(), _e1210()],
        )
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        engine._cache_monitor._get_bucket(sid).gate_note_pending = True
        engine.run(sid, "任务A")  # 第一 run: 恢复成功
        # defer 回存完成；第二轮 run: build 重注入 gate_note（defer_replayed）
        engine.run(sid, "任务B")  # 第三次调用 1210 → 二阶失败
        assert len(fake.calls) == 3
        # 二阶失败: 该轮不满足 compact 首请求（prev 已是本轮量级）→ 不重试
        # defer_lost_on_reinject 已记录
        trace = Path(os.environ.get("LFL_DATA_DIR", "data")) / "audit" / "defer_trace.jsonl"
        # conftest isolated_data_dir 设置了 LFL_DATA_DIR
        assert trace.exists()
        events = [json.loads(x) for x in trace.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert any(e["event"] == "defer_lost_on_reinject" for e in events)
        assert any(e["event"] == "defer_replayed" for e in events)


class TestExhaustLifecycle:
    def test_exhausted_flag_within_same_event(self, tmp_path, monkeypatch):
        """T3.7: 同 compact 事件不二次重试（耗尽标记生命周期）."""
        engine, fake = _mk(
            tmp_path, monkeypatch, responses=[_e1210(), _e1210(), _resp()],
        )
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        engine.run(sid, "任务")  # 耗尽（2 调用）
        # 直接再调 _try_err1210_recovery（同事件）
        result = engine._try_err1210_recovery(
            exc=_e1210(), sess=SimpleNamespace(session_id=sid),
            messages=[{"role": "user", "content": "x"}],
            tools_param=[], llm_client=fake, chat_model_arg=None,
            timeout_s=1.0, session_id=sid,
        )
        assert result.attempted is True and result.exhausted is True
        assert result.recovered is False
