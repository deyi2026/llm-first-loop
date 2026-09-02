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

import pytest

from llm_loop.core.cache_health import GATE_NOTE_CONTENT, CacheHealthMonitor
from llm_loop.core.loop.engine_services.recovery_controller import RecoveryController
from llm_loop.core.loop.engine_services.run_state import RunStateManager
from llm_loop.core.loop.err1210 import (
    InjectedEntry,
    InjectionSpan,
    SlotKind,
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
        text = pop_hotcard(session_id="sess-1", data_dir=tmp_path, authorized=True)
        # R3 pointer contract: old action prose stays in the durable card, explicit view is 2-line pointer.
        assert text and "anchor=1" in text and "ref=file:" in text
        assert "任务A" not in text
        card = json.loads(hotcard_path(tmp_path).read_text(encoding="utf-8"))
        assert card["consumed"] is True
        # 默认 reset 无授权 → 不得复活。
        assert reset_hotcard_consumed(session_id="sess-1", data_dir=tmp_path) is False
        assert reset_hotcard_consumed(
            session_id="sess-1", data_dir=tmp_path, authorized=True
        ) is True
        card = json.loads(hotcard_path(tmp_path).read_text(encoding="utf-8"))
        assert card["consumed"] is False and card["consumed_by"] == ""
        # 复位后仍需再次显式授权才能 pop；build 不会调用此路径。
        again = pop_hotcard(session_id="sess-1", data_dir=tmp_path, authorized=True)
        assert again == text

    def test_stale_card_not_reset(self, tmp_path):
        write_hotcard(origin_session="other-sess", anchor="任务A", data_dir=tmp_path)
        pop_hotcard(session_id="sess-1", data_dir=tmp_path, authorized=True)
        # 不同会话请求复位 → 拒绝（防复活已被新事件接管的卡）
        assert reset_hotcard_consumed(
            session_id="sess-2", data_dir=tmp_path, authorized=True
        ) is False

    def test_missing_card_returns_false(self, tmp_path):
        assert reset_hotcard_consumed(session_id="s", data_dir=tmp_path) is False

    def test_idempotent_double_reset(self, tmp_path):
        write_hotcard(origin_session="o", anchor="a", data_dir=tmp_path)
        pop_hotcard(session_id="s1", data_dir=tmp_path, authorized=True)
        assert reset_hotcard_consumed(
            session_id="s1", data_dir=tmp_path, authorized=True
        ) is True
        assert reset_hotcard_consumed(
            session_id="s1", data_dir=tmp_path, authorized=True
        ) is False  # 已复位


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


class _StripStub(RecoveryController):
    def __init__(self, injections):
        super().__init__(self)  # R9 B5-W1-03: stub 自身充当 host（实例态属性面不变）
        # R9-B5-W4-03: 桶字段宿主面替身（last_build_injections 读写经 RunStateManager）
        self._host._run_state_mgr = RunStateManager()
        self._host._run_state().last_build_injections = injections

    def _run_state(self):
        return self._run_state_mgr.bucket()


class TestStripTailInjections:
    def _mk(self, messages, entries):
        return _StripStub(entries)._strip_tail_injections(messages)

    def test_strip_prefix_untouched(self):
        from llm_loop.core.injection_labels import InjectionLayer, render_program_appendix

        canonical = render_program_appendix("A", InjectionLayer.REFERENCE)
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "user", "content": canonical},
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
            {"role": "user", "content": canonical},
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

    def test_r6_user_envelope_strip_preserves_exact_user_truth(self):
        """R6: 1210 strip removes only program prefix, never the human suffix."""
        from llm_loop.core.injection_labels import InjectionLayer, render_program_appendix
        from llm_loop.core.user_truth_wire import USER_TRUTH_SEPARATOR

        truth = "用户原文\n逐字保留"
        program = render_program_appendix("恢复前的程序状态", InjectionLayer.STATUS)
        wire = program + USER_TRUTH_SEPARATOR + truth
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": wire},
        ]
        entries = [
            InjectedEntry(
                msg_idx=1,
                slot_kind=SlotKind.USER_ENVELOPE,
                prefix_sha=content_prefix_sha(wire),
                user_truth=truth,
                seg_sources=(("tip", "tip source"),),
            )
        ]
        out = self._mk(msgs, entries)
        assert out is not None
        stripped, span = out
        assert stripped == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": truth},
        ]
        assert span.entries[0].slot_kind == SlotKind.USER_ENVELOPE
        assert msgs[-1]["content"] == wire  # copy-on-write


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


class _DeferStub(RecoveryController):
    def __init__(self, data_dir):
        super().__init__(self)  # R9 B5-W1-03: stub 自身充当 host（实例态属性面不变）
        self._host.settings = SimpleNamespace(data_dir=str(data_dir))
        self._host._cache_monitor = CacheHealthMonitor()
        self._host._interop_tail_messages = None
        self._host._tip_tail_messages = None
        # R9-B5-W4-03: 桶字段宿主面替身（deferred_replay_* 读写经 RunStateManager）
        self._host._run_state_mgr = RunStateManager()
        self._host._run_state().deferred_replay_refs = []
        self._host._run_state().deferred_replay_slots = set()

    def _run_state(self):
        return self._run_state_mgr.bucket()


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
        assert {s for s, _ in stub._run_state().deferred_replay_refs} == {SlotKind.INTEROP, SlotKind.TIP}

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
        pop_hotcard(session_id="sess-d1", data_dir=tmp_path, authorized=True)  # 显式消费
        stub = _DeferStub(tmp_path)
        entries = [
            InjectedEntry(msg_idx=0, slot_kind=SlotKind.HOTCARD, prefix_sha="h" * 64),
            InjectedEntry(msg_idx=1, slot_kind=SlotKind.GATE_NOTE, prefix_sha="g" * 64),
        ]
        assert stub._defer_store(self._sess(), entries) is True
        assert stub._cache_monitor.take_gate_note("sess-d1") is True  # 已置位
        card = json.loads(hotcard_path(tmp_path).read_text(encoding="utf-8"))
        assert card["consumed"] is True and card["consumed_by"] == "sess-d1"
        assert pop_hotcard(
            session_id="sess-d1", data_dir=tmp_path, authorized=True
        ) is None  # err1210 不得复位/复活 HOTCARD

    def test_overflow_drops_non_interop(self, tmp_path):
        stub = _DeferStub(tmp_path)
        write_hotcard(origin_session="o", anchor="a", data_dir=tmp_path)
        pop_hotcard(session_id="sess-d1", data_dir=tmp_path, authorized=True)
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

    def test_aggregated_seg_sources_restores_full_content(self, tmp_path):
        """CR-R1.1（审查项5）: AGGREGATED defer 优先 seg_sources 恢复投影前原文.

        WARM 投影把 wire 段截到 120 chars——wire 反推会把 314 chars 原文永久
        缩水；seg_sources 是唯一恢复源（Projection 是 view 不是 Source of Truth）。
        """
        stub = _DeferStub(tmp_path)
        long_interop = "I" * 300
        long_tip = "T" * 314  # 审查实测场景：原文 314 → WARM 投影 wire 120
        wire = (
            "--- [tier:warm][slot:interop] ---\n" + long_interop[:120] + "\n"
            "--- [tier:warm][slot:tip] ---\n" + long_tip[:120] + "\n"
        )
        entries = [
            InjectedEntry(
                msg_idx=0,
                slot_kind=SlotKind.AGGREGATED,
                prefix_sha="a" * 64,
                seg_sources=(
                    ("interop", long_interop),
                    ("tip", long_tip),
                ),
            )
        ]
        messages = [{"role": "user", "content": wire}]
        assert stub._defer_store(self._sess(), entries, messages) is True
        # 恢复的是投影前全文，而非 wire 截断版（后 194 chars 不丢失）
        assert stub._interop_tail_messages[0].content == long_interop
        assert stub._tip_tail_messages[0].content == long_tip
        assert len(stub._tip_tail_messages[0].content) == 314

    def test_aggregated_fallback_wire_without_seg_sources(self, tmp_path):
        """无 seg_sources（旧 entry/构造缺省）时 fallback wire 反推，行为兼容不变."""
        stub = _DeferStub(tmp_path)
        seg = "旧路径兼容段"
        wire = "--- [slot:tip] ---\n" + seg + "\n"
        entries = [
            InjectedEntry(msg_idx=0, slot_kind=SlotKind.AGGREGATED, prefix_sha="a" * 64)
        ]
        messages = [{"role": "user", "content": wire}]
        assert stub._defer_store(self._sess(), entries, messages) is True
        assert stub._tip_tail_messages[0].content == seg

    def test_r6_user_envelope_defer_uses_seg_sources_not_human_suffix(self, tmp_path):
        """R6: one-shot slots recover from sidecar; exact human suffix is never parsed as a slot."""
        from llm_loop.core.user_truth_wire import USER_TRUTH_SEPARATOR

        stub = _DeferStub(tmp_path)
        truth = "human truth must not become program replay"
        wire = "program projection" + USER_TRUTH_SEPARATOR + truth
        entries = [
            InjectedEntry(
                msg_idx=0,
                slot_kind=SlotKind.USER_ENVELOPE,
                prefix_sha=content_prefix_sha(wire),
                seg_sources=(("interop", "I-full"), ("tip", "T-full")),
                user_truth=truth,
            )
        ]
        messages = [{"role": "user", "content": wire}]
        assert stub._defer_store(self._sess(), entries, messages) is True
        assert stub._interop_tail_messages[0].content == "I-full"
        assert stub._tip_tail_messages[0].content == "T-full"
        assert truth not in stub._interop_tail_messages[0].content
        assert truth not in stub._tip_tail_messages[0].content

    def test_r6_user_envelope_without_oneshot_sources_needs_no_defer(self, tmp_path):
        """Persisted/compact program context is durable; envelope defer is a successful no-op."""
        stub = _DeferStub(tmp_path)
        entries = [
            InjectedEntry(
                msg_idx=0,
                slot_kind=SlotKind.USER_ENVELOPE,
                prefix_sha="a" * 64,
                user_truth="truth",
            )
        ]
        assert stub._defer_store(self._sess(), entries, [{"role": "user", "content": "x"}]) is True
        assert stub._interop_tail_messages is None
        assert stub._tip_tail_messages is None


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


def _arm_live_prompt_slot(engine, sid, text="授权恢复夹具"):
    """R8.24-E（E-D2）: 旧 tip 槽退役——live 注册 entry 改经授权投影武装.

    持久化 memory 快照（engine 理解段落盘形态）+ run 文本显式指代授权
    （类级 fixture 放宽 LFL_MEMORY_REF_KEYWORDS）→ memory_authorized 投影
    进 R6 envelope（USER_ENVELOPE entry），供 1210 strip/blind 链验证。
    """
    from llm_loop.core.injection_labels import InjectionLayer, origin_metadata

    engine.session.append(
        sid,
        Message(
            role="user",
            content=text,
            source=MessageSource.USER,
            metadata=origin_metadata(
                InjectionLayer.REFERENCE,
                injection_kind="memory_snapshot",
                persisted_injection=True,
                turn_ref=0,
                query_fp="deadbeefcafe",
            ),
        ),
    )


class TestEngineRecovery:
    # GOAL-20260829-a9a6c0f0: blind retry 默认开会前置一次原样重发，改变本类
    # "剥离重试"断言口径 → 本类显式关闭 blind，保留 strip/aggregate 回退路径
    # 的独立回归（blind 行为见 test_err1210_blind_retry.py）。
    @pytest.fixture(autouse=True)
    def _no_blind_retry(self, monkeypatch):
        monkeypatch.setenv("ERR1210_BLIND_RETRY", "0")

    @pytest.fixture(autouse=True)
    def _mem_ref_loose(self, monkeypatch):
        """R8.24-E: 授权词表放宽——本类 run 文本（任务/继续/压缩）视为显式指代.

        测试对象是 1210 恢复机械（与授权词表从严正交）；生产默认词表
        不受影响（monkeypatch 作用域限本类）。
        """
        monkeypatch.setenv("LFL_MEMORY_REF_KEYWORDS", "任务,继续,压缩")

    def test_basic_recovery(self, tmp_path, monkeypatch):
        """T5.1: 首调 1210 → 重试恰好 1 次、公共前缀一致、resp 正常合流、登记正确."""
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210(), _resp()])
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        # 武装仍具 prompt eligibility 的 tip 槽，验证 strip/defer 主链。
        _arm_live_prompt_slot(engine, sid)
        result = engine.run(sid, "长任务继续")
        assert "恢复后的正常回答" in result.final_answer
        assert result.truncated is False
        assert len(fake.calls) == 2  # 重试恰好 1 次
        orig, retry = fake.calls[0]["messages"], fake.calls[1]["messages"]
        n_inj = len(engine._run_state().last_build_injections)
        assert n_inj == 1
        assert engine._run_state().last_build_injections[0].slot_kind == SlotKind.USER_ENVELOPE
        # R6: strip only program prefix; stable prefix stays byte-identical and exact human suffix remains.
        assert retry[:-1] == orig[:-1]
        assert retry[-1] == {"role": "user", "content": "长任务继续"}
        assert str(orig[-1].get("content", "")).endswith("长任务继续")
        # R8.24-E（E-D2）: tip 槽退役——无 defer 回填（tail 消费后置 None；
        # 授权投影 envelope 由 strip 直接剥除，不经 tail defer 链）。
        assert engine._tip_tail_messages is None
        assert engine._cache_monitor.take_gate_note(sid) is False
        # 耗尽标记已写（本 run 不再二次降级——修复A per-run 语义）
        assert engine._err1210_attempted.get(sid) == engine._run_state().err1210_run_seq

    def test_defer_reinject_next_round(self, tmp_path, monkeypatch):
        """R8.24-E（E-D2）: tip replay 退出——defer 重注入链路不再复活 tip 段.

        旧语义（T5.2a defer 回填重注入）随 tip 槽退役废除：tip 武装后 wire
        恒零 tip 文本（E-G3），_tip_tail_messages 一次性消费置 None，无 defer
        引用残留；interop legacy 不复活照旧。
        """
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_e1210(), _resp(), _resp("第二轮回答")],
        )
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        m = Message(role="system", content="tip 可恢复消息", source=MessageSource.SYSTEM)
        engine._tip_tail_messages = [m]
        engine.run(sid, "任务A")
        assert engine._tip_tail_messages is None  # 一次性消费、无 defer 回填
        engine.run(sid, "任务B")
        second_msgs = fake.calls[2]["messages"]
        assert all(
            "tip 可恢复消息" not in str(x.get("content", ""))
            for x in second_msgs
            if isinstance(x, dict)
        )  # E-G3: TIP replay 恒零注入
        assert all(r is not m for r in (engine._run_state().deferred_replay_refs or []))


    def test_tip_recovery_does_not_gain_hotcard_authority(self, tmp_path, monkeypatch):
        """E24（R8.24-E 更新）: tip 退役零注入；durable hotcard 不获 prompt/defer 权限."""
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210(), _resp()])
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        engine._tip_tail_messages = [
            Message(role="system", content="经验提示 tip", source=MessageSource.SYSTEM)
        ]
        write_hotcard(origin_session="origin-sess", anchor="任务锚点",
                      data_dir=engine.settings.data_dir)
        result = engine.run(sid, "tip 活跃")
        assert "恢复后的正常回答" in result.final_answer
        assert len(fake.calls) == 2
        orig, retry = fake.calls[0]["messages"], fake.calls[1]["messages"]
        # R8.24-E（E-D2/E-G3）: tip 武装零投影（无授权指代 → 无任何注入段）
        wire = "\n".join(str(m.get("content", "")) for m in orig)
        assert "经验提示 tip" not in wire
        assert "--- [slot:" not in wire
        assert engine._run_state().last_build_injections == []
        assert retry[:-1] == orig[:-1]
        assert retry[-1] == {"role": "user", "content": "tip 活跃"}
        assert engine._tip_tail_messages is None  # 一次性消费、无 defer 回填
        card = json.loads(hotcard_path(engine.settings.data_dir).read_text(encoding="utf-8"))
        assert card["consumed"] is False
        assert not any("slot:hotcard" in str(m.get("content", "")) for m in orig)
        assert pop_hotcard(
            session_id=sid, data_dir=engine.settings.data_dir, authorized=True
        ) is not None  # explicit retrieval remains available after the run
        assert engine._interop_tail_messages in (None, [])


    def test_deferred_tip_ignores_new_durable_hotcard(self, tmp_path, monkeypatch):
        """E24（R8.24-E 更新）: tip 零注入；新写 durable hotcard 不得借 defer 复活.

        旧语义（deferred tip 与 hotcard 不混合聚合）随 tip defer 链退役简化为：
        两轮 wire 恒零 tip/hotcard 槽段（E-G3 + E24 权威边界），hotcard
        durable 存储保留（retrieval plane 不动）。
        """
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_e1210(), _resp(), _resp("第二轮回答")],
        )
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        engine._tip_tail_messages = [
            Message(role="system", content="defer 回放 tip", source=MessageSource.SYSTEM)
        ]
        engine.run(sid, "第一轮")
        assert engine._tip_tail_messages is None  # 一次性消费、无 defer 回填
        write_hotcard(origin_session="origin-sess", anchor="当轮 hotcard",
                      data_dir=engine.settings.data_dir)
        engine.run(sid, "第二轮")
        second = fake.calls[2]["messages"]
        wire = "\n".join(
            str(d.get("content", "")) for d in second if isinstance(d, dict)
        )
        assert "defer 回放 tip" not in wire  # E-G3: TIP replay 恒零注入
        assert "slot:hotcard" not in wire  # E24: hotcard 不进 prompt
        card = json.loads(hotcard_path(engine.settings.data_dir).read_text(encoding="utf-8"))
        assert card["consumed"] is False


    def test_second_1210_no_third_retry(self, tmp_path, monkeypatch):
        """T5.4a: 恢复机会一次性——三链路耗尽后不再第四发（spec 5.1.1-4a，f8e106d 口径）."""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_e1210(), _e1210(), _e1210(), _resp("不该出现")],
        )
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        _arm_live_prompt_slot(engine, sid)
        result = engine.run(sid, "长任务继续")
        assert len(fake.calls) == 3  # 原始+blind+strip/raw 耗尽；每 run 机会一次，第四不发生
        assert "[LLM 调用异常]" in (result.final_answer or "")  # 如实反馈（llm_error）
        assert "不该出现" not in (result.final_answer or "")

    def test_no_trigger_without_compact(self, tmp_path, monkeypatch):
        """T5.3a: 非 compact 场景 1210 不触发剥离（R9 语义更新: 续跑兜底一次）."""
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210(), _e1210()])
        sid = engine.session.create()
        # 不武装骤降、无 compact 标记
        result = engine.run(sid, "普通任务")
        assert len(fake.calls) == 2  # 无恢复素材 → 恢复链未触发；R9 续跑兜底一轮后终止
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
        _arm_live_prompt_slot(engine, sid)
        result = engine.run(sid, "任务")
        assert len(fake.calls) == 1
        assert "[LLM 调用异常]" in (result.final_answer or "")

    def test_new_compact_event_rearms(self, tmp_path, monkeypatch):
        """T5.4d: 新 run 后降级机会重获（修复A per-run 语义，原 compact 事件口径）."""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_e1210(), _e1210(), _e1210(), _e1210(), _resp("第三次成功")],
        )
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        _arm_live_prompt_slot(engine, sid)  # 需有 live 注入登记可供剥离
        engine.run(sid, "任务")  # f8e106d blind-first: 原始+blind+strip(剥gate_note) 3 次耗尽
        assert len(fake.calls) == 3
        # 修复A: 新 run 自动重获降级机会（run seq 递增，无需手动 compact 事件）
        _arm_compact_first(engine, sid)
        _arm_live_prompt_slot(engine, sid)
        result = engine.run(sid, "新压缩后继续")
        assert len(fake.calls) == 5  # run2: 原始 1210(4) + blind 恢复成功(5)——rearm 生效
        assert "第三次成功" in result.final_answer

    def test_second_order_failure_records_event(self, tmp_path, monkeypatch):
        """T5.2d 二阶失败 [R8.24-E 更新]: 第二 run 降级重试仍 1210 → 耗尽上抛.

        修复A（2026-08-29）语义更新: 第二 run 重新获得一次降级机会
        （attempted 键 = run seq 自动递增），重试仍 1210 → 耗尽上抛 → 二阶失败。
        R8.24-E（E-D2）: tip defer 链退役——defer_replayed/defer_lost_on_reinject
        事件源消失（授权投影 envelope 由 strip 直接剥除，无 tail defer 回存），
        二阶失败机械由 5 次调用耗尽断言承载。
        """
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_e1210(), _resp(), _e1210(), _e1210(), _e1210()],
        )
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        _arm_live_prompt_slot(engine, sid)
        engine.run(sid, "任务A")  # 第一 run: blind(第2次)恢复成功，共 2 次调用
        engine.run(sid, "任务B")  # run2: 原始(3)+blind(4)+strip(5) 均 1210 → 耗尽
        assert len(fake.calls) == 5  # 二阶失败: 重试仍 1210（每 run 至多一次降级）

    def test_noncompact_1210_recovery(self, tmp_path, monkeypatch):
        """修复A核心: 非 compact 轮 1210（主区 883b4725 形态）→ 降级重试不再静默跳过.

        旧语义: _is_compact_first_request 门禁在此静默 return（无 compact 事件、
        无骤降信号 → recovery 未触发 → 1210 直接上抛，主区三连败实证）。
        """
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210(), _resp()])
        sid = engine.session.create()
        # 刻意不 arm compact_first——非 compact、无骤降形态
        _arm_live_prompt_slot(engine, sid)
        result = engine.run(sid, "长任务继续")
        assert "恢复后的正常回答" in result.final_answer
        assert len(fake.calls) == 2  # 旧语义 1 次（静默上抛），新语义降级重试成功

    def test_request_count_updated_on_failure(self, tmp_path, monkeypatch):
        """修复B: 失败轮也更新骤降数据源（旧语义死锁式失效——连续失败 prev 越陈旧）."""
        engine, fake = _mk(
            tmp_path, monkeypatch,
            responses=[_e1210(), _e1210(), _e1210()],
        )
        sid = engine.session.create()
        _arm_live_prompt_slot(engine, sid)
        result = engine.run(sid, "任务")
        assert len(fake.calls) == 3  # 原始+blind+raw-fallback 耗尽 break（与 R9 互斥，不再续跑）
        assert "[LLM 调用异常]" in (result.final_answer or "")
        # 修复B: llm_error break 前已更新——msg_count 对齐失败轮原始 messages 量
        assert engine._last_request_msg_count_by_session.get(sid) == len(
            fake.calls[2]["messages"]
        )


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
        result = engine._recovery._try_err1210_recovery(
            exc=_e1210(), sess=SimpleNamespace(session_id=sid),
            messages=[{"role": "user", "content": "x"}],
            tools_param=[], llm_client=fake, chat_model_arg=None,
            timeout_s=1.0, session_id=sid,
        )
        assert result.attempted is True and result.exhausted is True
        assert result.recovered is False


# ── GPT 审计批次1（2026-08-28）: 聚合兜底直接单测 + normalize 接线 + P0 stale reasoning ──

class TestAggregateTailUsers:
    """_aggregate_tail_users 直接矩阵（GPT 审计第六条: 1/2/16/17/non-str/prefix/order）。"""

    def test_single_tail_user_no_aggregate(self):
        stub = _StripStub([])
        msgs = [{"role": "assistant", "content": "a"}, {"role": "user", "content": "u1"}]
        assert stub._aggregate_tail_users(msgs) is None

    def test_two_tail_users_aggregate(self):
        stub = _StripStub([])
        msgs = [
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "u1"},
            {"role": "user", "content": "u2"},
        ]
        out = stub._aggregate_tail_users(msgs)
        assert out is not None and len(out) == 2
        assert out[-1]["role"] == "user"
        assert out[-1]["content"] == stub._AGG_SEPARATOR.join(["u1", "u2"])

    def test_sixteen_users_aggregate(self):
        stub = _StripStub([])
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(16)]
        out = stub._aggregate_tail_users(msgs)
        assert out is not None and len(out) == 1

    def test_seventeen_users_reject(self):
        stub = _StripStub([])
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(17)]
        assert stub._aggregate_tail_users(msgs) is None

    def test_non_str_content_reject(self):
        stub = _StripStub([])
        msgs = [
            {"role": "user", "content": "u1"},
            {"role": "user", "content": [{"type": "text", "text": "mm"}]},
        ]
        assert stub._aggregate_tail_users(msgs) is None

    def test_prefix_bytes_untouched_and_order_preserved(self):
        stub = _StripStub([])
        prefix = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]
        msgs = prefix + [{"role": "user", "content": f"tail{i}"} for i in range(3)]
        out = stub._aggregate_tail_users(msgs)
        assert out is not None
        assert out[:3] == prefix  # 前缀对象逐字节复用（copy-on-write）
        body = out[-1]["content"]
        idxs = [body.index(f"tail{i}") for i in range(3)]
        assert idxs == sorted(idxs)  # 内容顺序保留


class TestNormalizeWiring:
    """strip 成功后残留检查接线断言（GPT 审计第五条: strip + normalize + one retry）。"""

    def test_strip_branch_wires_residual_aggregate(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[2]
            / "src/llm_loop/core/loop/engine_services/recovery_controller.py"
        ).read_text(
            encoding="utf-8"
        )
        # strip 分支内必须对 strip 结果做残留聚合检查，且保持单次重试（不新增 provider 调用）
        # （B5-W1-03: 断言随实现迁移 err1210.py → recovery_controller.py，锚点逐字不变）
        assert "residual = self._aggregate_tail_users(retry_messages)" in src
        assert '"strip+aggregate"' in src
        # strip 失败分支的原聚合路径保留（双入口）
        assert "aggregated = self._aggregate_tail_users(messages)" in src


class TestLlmErrorBranchesClearResp:
    """P0（GPT 审计第一条）: 两处 llm_error 分支 break 前必须清 resp，防 stale reasoning 嫁接。"""

    def test_llm_error_branches_clear_resp(self):
        import re
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2] / "src/llm_loop/core/loop/engine.py").read_text(
            encoding="utf-8"
        )
        # 锚点用分支内独特语句（"llm_error" 字符串在文件更早处出现，不可作锚）；
        # 2026-08-29 拆块后两分支收敛为 _e1210_llm_error_finalize 调用（语义等价）；
        # 2026-09-02 B5-W4-03 前置清障（D-B5-14）: 两分支再收敛为 _llm_error_round_exit
        # 统一出口（中断落盘 + e1210 收尾 + stale reasoning 隔离三合一，语义等价去重）
        matches = list(re.finditer(r"final_answer, resp = self\._llm_error_round_exit\(", src))
        assert len(matches) >= 2, f"llm_error 分支应 ≥2 处（fallback_exhausted/llm_error），实际 {len(matches)}"
        # 统一出口定义体内必须恒返 resp=None（单一出口全覆盖——强度不低于原逐点 resp = None 检查）
        exit_def = re.search(r"def _llm_error_round_exit\(.*?return final, None", src, re.S)
        assert exit_def, "llm_error 统一出口缺失或未清 resp：stale reasoning 会嫁接到程序反馈"
