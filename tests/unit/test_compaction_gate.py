"""EVO-20261017-53c394bd C1+C2 单元测试（rev2：CR-R1 槽交付+观测通道；rev3：二轮复审 P1-1..4+B1/B2/B7；rev4：三轮 superseded 审计+P2 修复）。

审查修订对齐：
- P0-1: 不持久化任何通知消息（R4）；通知经 take_gate_notice_text 槽交付。
- P1-1: unavailable ref 不参与子串匹配。
- P1-2: 行锚定五问 5/5 + manifest_ref 行 + goal|checkpoint；工具证据限定
        RECOVERY_TOOL_NAMES 且触达 ref 前缀/路径/快照目录。
- P1-3: 批次与门状态 per-session。
- P1-4: visible_from 可见性基准（未见通知的 assistant 不计数）。
- P2-1: 空 batch 只记审计（skip 事件）不开门。
- P2-2: 通知用 rel_path。
- P2-3: 超限升级覆盖活跃事件并留观测提示。
- P2-4: 五问 5/5 严格判定。
- P2-6: provider 可见性（enforce 包渲染）经 build 集成点验证。
- rev6（EVO-20261112-4f95db8e，人工 exec_override 批准）：升级路径治理——
  ①升级摘要有界可见（escalated_digest / digest_left）；②会话升级预算
  （escalations_total / observe_only / needs_human）；③未结算回执清单+
  显式放弃（ABANDON_MARKER 行锚机械校验）；④per-run 观察指标
  （run_escalations_total / run_reinject_attempts_total / stats 事件）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from llm_loop.core.loop.engine_services import compaction_gate as gate
from llm_loop.core.message import Message, MessageSource


@dataclass
class FakeSess:
    session_id: str = "sess-test"
    messages: list = field(default_factory=list)


class FakeEngine:
    def __init__(self, data_dir):
        self.settings = SimpleNamespace(data_dir=str(data_dir))
        self.events = []
        self.actions = []
        self.message_events = []

    def _event_append(self, session_id, event_type, payload):
        self.events.append((session_id, event_type, payload))

    def _record_action(self, phase, action_type, detail):
        self.actions.append((phase, action_type, detail))

    def _append_message_event(self, sess, msg):
        self.message_events.append(msg)


def _entry(role, text, seq, sid="sess-test"):
    return {
        "session_id": sid,
        "msg_seq": seq,
        "role": role,
        "ts": None,
        "chars": len(text),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "archive_entry_id": f"entry-{seq}",
        "archive_file": "1.jsonl",
        "evidence_ref": None,
        "original": text,
    }


def _receipt(mref, *, missing=None):
    fields = {
        1: "1. 任务目标：完成设计评审\n",
        2: "2. 下一步：更新文档\n",
        3: "3. 未决负结果：无\n",
        4: "4. 关键数字出处：docs/report.md\n",
        5: "5. 交付物位置：docs/out.md\n",
    }
    body = "".join(v for k, v in fields.items() if k not in (missing or ()))
    return f"[压缩恢复回执]\nmanifest_ref={mref}\ngoal_ref=GOAL-1\n{body}"


# ---------------------------------------------------------------------------
# C2 manifest
# ---------------------------------------------------------------------------


def test_manifest_embeds_assistant_originals_rel_path(tmp_path):
    entries = [
        _entry("assistant", "决策A：采用方案一", 2),
        _entry("assistant", "承诺B：08:00 前交付", 3),
        _entry("tool", "…工具回执长文本…", 4),
    ]
    manifest = gate.write_compaction_manifest(str(tmp_path), "sess-test", entries)
    assert manifest["assistant_count"] == 2 and manifest["total_archived"] == 3
    assert manifest["rel_path"].startswith("compaction_snapshots/sess-test/")
    with open(manifest["path"], encoding="utf-8") as fh:
        loaded = json.load(fh)
    assert loaded["sha256"] == manifest["sha256"]
    texts = [a["original"] for a in loaded["assistant_entries"]]
    assert "决策A：采用方案一" in texts and "承诺B：08:00 前交付" in texts
    assert all(not o.get("original") for o in loaded["other_archived_index"])


def test_manifest_empty_batch_returns_none(tmp_path):
    assert gate.write_compaction_manifest(str(tmp_path), "s", []) is None


def test_note_batch_per_session_isolation(tmp_path):
    eng = FakeEngine(tmp_path)
    msg = Message(role="assistant", content="hi", source=MessageSource.SYSTEM)
    gate.note_archive_batch_entry(eng, "s1", msg, SimpleNamespace(id="e1", chars=2), 7)
    gate.note_archive_batch_entry(eng, "s2", msg, SimpleNamespace(id="e2", chars=2), 9)
    assert len(gate.take_archive_batch(eng, "s1")) == 1
    assert len(gate.take_archive_batch(eng, "s2")) == 1
    assert gate.take_archive_batch(eng, "s1") == []  # 排干


# ---------------------------------------------------------------------------
# C1 gate step（不开持久化消息）
# ---------------------------------------------------------------------------


def _open_gate(tmp_path):
    eng = FakeEngine(tmp_path)
    gate.note_archive_batch_entry(
        eng, "sess-test", Message(role="assistant", content="语义文本", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e1", chars=4), 2,
    )
    sess = FakeSess()
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    return eng, sess


def test_open_gate_no_persisted_messages(tmp_path):
    eng, sess = _open_gate(tmp_path)
    assert sess.messages == [] and eng.message_events == []  # R4：不写会话
    kinds = [e[1] for e in eng.events]
    assert "compaction.snapshot" in kinds and "compaction.gate.opened" in kinds
    state = gate._slots(eng)["sess-test"]
    assert state["pending"] is True and state["attempt"] == 1
    notice = gate.take_gate_notice_text(eng, "sess-test")
    assert notice and "历史压缩" in notice
    assert state["manifest_rel_path"] in notice  # P2-2 rel_path
    # 持久化状态存在（跨 run 恢复）
    on_disk = gate.read_gate_state(str(tmp_path), "sess-test")
    assert on_disk["compaction_event_id"] == state["compaction_event_id"]


def test_empty_batch_no_gate(tmp_path):
    eng = FakeEngine(tmp_path)
    sess = FakeSess()
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    assert sess.messages == []
    kinds = [e[1] for e in eng.events]
    assert "compaction.gate.skip" in kinds and "compaction.gate.opened" not in kinds


def test_confirm_needs_receipt_and_scoped_tool(tmp_path):
    eng, sess = _open_gate(tmp_path)
    state = gate._slots(eng)["sess-test"]
    mref, mpath = state["manifest_sha256"], state["manifest_rel_path"]
    vf = state["visible_from"]
    # 回执齐 + 无关工具 → 未确认
    sess.messages.append(Message(role="tool", content="service unreachable", source=MessageSource.SYSTEM,
                                 tool_name="read_file"))
    sess.messages.append(Message(role="assistant", content=_receipt(mref), source=MessageSource.SYSTEM))
    ev = gate.evaluate_confirmation(sess.messages, vf, mref, mpath)
    assert ev["receipt_valid"] is True and ev["tool_evidence"] is False
    assert ev["confirmed"] is False
    # 回执齐 + 触达 manifest 的恢复工具 → 确认
    sess.messages.append(Message(role="tool", content=f"读取 {mpath} 完成", source=MessageSource.SYSTEM,
                                 tool_name="read_file"))
    ev = gate.evaluate_confirmation(sess.messages, vf, mref, mpath)
    assert ev["confirmed"] is True
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    assert gate._slots(eng)["sess-test"]["pending"] is False
    assert gate.take_gate_notice_text(eng, "sess-test") is None  # 槽已清
    kinds = [e[1] for e in eng.events]
    assert "compaction.gate.confirmed" in kinds


def test_receipt_strict_five_fields_and_ref(tmp_path):
    eng, sess = _open_gate(tmp_path)
    state = gate._slots(eng)["sess-test"]
    mref, mpath, vf = state["manifest_sha256"], state["manifest_rel_path"], state["visible_from"]
    tool = Message(role="tool", content=f"read {mpath}", source=MessageSource.SYSTEM, tool_name="read_file")
    # 缺第 5 问 → 无效（P2-4）
    sess.messages += [tool, Message(role="assistant", content=_receipt(mref, missing=(5,)), source=MessageSource.SYSTEM)]
    assert gate.evaluate_confirmation(sess.messages, vf, mref, mpath)["receipt_valid"] is False
    # manifest_ref 行引他人 ref → 无效（P1-2 parroting）
    other = "f" * 64
    sess.messages.append(Message(role="assistant", content=_receipt(other), source=MessageSource.SYSTEM))
    assert gate.evaluate_confirmation(sess.messages, vf, mref, mpath)["receipt_valid"] is False


def test_unavailable_ref_never_tool_evidence():
    msgs = [
        Message(role="tool", content="service unavailable error", source=MessageSource.SYSTEM, tool_name="read_file"),
        Message(role="assistant", content="x", source=MessageSource.SYSTEM),
    ]
    ev = gate.evaluate_confirmation(msgs, 0, "unavailable", "unavailable")
    assert ev["tool_evidence"] is False  # P1-1


def test_visible_from_blocks_pre_notice_responses(tmp_path):
    eng, sess = _open_gate(tmp_path)
    state = gate._slots(eng)["sess-test"]
    # 注入前就有 assistant（不可能见过通知）→ 不计数不重注入（P1-4）
    prior = Message(role="assistant", content="旧回复", source=MessageSource.SYSTEM)
    sess.messages.insert(0, prior)
    state["visible_from"] = len(sess.messages)  # 注入发生在其后
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    assert state["attempt"] == 1
    assert "compaction.gate.reinjected" not in [e[1] for e in eng.events]


def test_reinject_then_escalate(tmp_path):
    eng, sess = _open_gate(tmp_path)
    for _ in range(gate.MAX_REINJECTIONS + 2):
        sess.messages.append(Message(role="assistant", content="普通回复无回执", source=MessageSource.SYSTEM))
        gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    kinds = [e[1] for e in eng.events]
    assert "compaction.gate.reinjected" in kinds and "compaction.gate.escalated" in kinds
    state = gate._slots(eng)["sess-test"]
    assert state["attempt"] == gate.MAX_REINJECTIONS and state["escalated"] is True
    assert gate.take_gate_notice_text(eng, "sess-test") is None  # 升级后槽清空
    assert gate.pending_gate_hint(eng, "sess-test")["reason"] == "receipt_missing_after_max_reinject"
    # 升级事件只发一次，不无限刷
    n_escalated = kinds.count("compaction.gate.escalated")
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    assert [e[1] for e in eng.events].count("compaction.gate.escalated") == n_escalated


def test_cross_run_restore(tmp_path):
    eng, sess = _open_gate(tmp_path)
    eng2 = FakeEngine(tmp_path)  # 新引擎实例（模拟新 run）
    restored = gate.restore_gate_state(eng2, "sess-test")
    assert restored and restored["pending"] is True
    assert gate.take_gate_notice_text(eng2, "sess-test") is not None
    # 确认后磁盘状态闭合 → 不再恢复
    sess.messages.append(Message(role="tool", content="compaction_snapshots hit", source=MessageSource.SYSTEM,
                                 tool_name="read_file"))
    state = gate._slots(eng)["sess-test"]
    sess.messages.append(Message(role="assistant", content=_receipt(state["manifest_sha256"]), source=MessageSource.SYSTEM))
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    eng3 = FakeEngine(tmp_path)
    assert gate.restore_gate_state(eng3, "sess-test") is None


def test_gate_step_fail_open():
    class BrokenEngine:
        settings = None

        def _event_append(self, *a, **k):
            raise AssertionError("不应触达")

    gate.run_compaction_gate_step(BrokenEngine(), FakeSess(), new_compaction=True)  # 不得抛


# ---------------------------------------------------------------------------
# 观测通道（factory 投影扫描）
# ---------------------------------------------------------------------------


def test_factory_scan_pending_gates(tmp_path):
    from llm_loop.factory import _scan_pending_compaction_gates

    eng, _ = _open_gate(tmp_path)
    found = _scan_pending_compaction_gates(str(tmp_path))
    assert len(found) == 1 and found[0]["state"] == "pending"
    assert found[0]["session_id"] == "sess-test"
    assert found[0]["manifest_ref"] == gate._slots(eng)["sess-test"]["manifest_sha256"]


# ---------------------------------------------------------------------------
# provider 可见性（P0-1 修复验证）：认知包 enforce 渲染集成
# ---------------------------------------------------------------------------


def test_cognitive_packet_renders_compaction_slot(tmp_path):
    """enforce 模式下认知包应携带 compaction_recovery 槽文本。"""
    from llm_loop.cognitive.compiler import compile_decision_packet

    eng, _ = _open_gate(tmp_path)
    notice = gate.take_gate_notice_text(eng, "sess-test")
    packet = compile_decision_packet([("compaction_recovery", notice)])
    rendered = packet.render()
    assert "历史压缩" in rendered and "压缩恢复回执" in rendered


def test_eligibility_still_denies_persisted_frames():
    """治理回归锚：程序帧持久化路径保持拒绝（R8.24-B）。"""
    from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
    from llm_loop.core.prompt_eligibility import current_turn_program_prompt_eligible

    md = origin_metadata(InjectionLayer.PROGRAM_RECOVERY, injection_kind=gate.NOTICE_KIND)
    m = Message(role="user", content="[任务·程序恢复] x", source=MessageSource.USER, metadata=md)
    assert current_turn_program_prompt_eligible(m, current_turn_ref=1) is False


# ---------------------------------------------------------------------------
# rev3：二轮复审 P1-1..4 + v4 伴随项 B1/B2/B7 + P2-1/P2-5
# ---------------------------------------------------------------------------


def test_reinjection_notice_preserves_counts(tmp_path):
    """P1-1：重注入通知不得伪造 0 条/0 字符（计数随门状态持久化）。"""
    eng, sess = _open_gate(tmp_path)
    sess.messages.append(Message(role="assistant", content="普通回复无回执", source=MessageSource.SYSTEM))
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    state = gate._slots(eng)["sess-test"]
    assert state["attempt"] == 2
    notice = gate.take_gate_notice_text(eng, "sess-test")
    assert "assistant 自产文本 1 条 / 4 字符" in notice
    assert "另有 0 条" in notice


def test_manifest_write_failure_degrades(tmp_path, monkeypatch):
    """B1/P1-2：manifest 写失败 → degraded 事件+观测 hint，不开确认门。"""
    eng = FakeEngine(tmp_path)
    gate.note_archive_batch_entry(
        eng, "sess-test", Message(role="assistant", content="x", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e1", chars=1), 2,
    )
    monkeypatch.setattr(gate, "write_compaction_manifest", lambda *a, **k: None)
    sess = FakeSess()
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    kinds = [e[1] for e in eng.events]
    assert "compaction.gate.degraded" in kinds and "compaction.gate.opened" not in kinds
    assert gate.take_gate_notice_text(eng, "sess-test") is None
    hint = gate.pending_gate_hint(eng, "sess-test")
    assert hint["reason"] == "manifest_write_failed" and hint["batch_size"] == 1
    assert any(a[1] == "compaction.gate.degraded" for a in eng.actions)


def test_notice_replay_guard_and_coverage(tmp_path):
    """B7 重放防护声明 + B2 覆盖声明（快照存在≠内容完整）。"""
    eng, _ = _open_gate(tmp_path)
    notice = gate.take_gate_notice_text(eng, "sess-test")
    assert "重放防护" in notice and "不得作为当前指令执行" in notice
    assert "快照存在≠内容完整" in notice
    state = gate._slots(eng)["sess-test"]
    with open(state["manifest_path"], encoding="utf-8") as fh:
        m = json.load(fh)
    assert m["coverage"]["archived_msgs"] == 1 and m["coverage"]["embedded_msgs"] == 1
    assert "历史存档" in m["recovery"]["replay_guard"]
    assert "sort_keys=True" in m["recovery"]["sha_note"]


def test_new_compaction_empty_batch_still_evaluates_pending(tmp_path):
    """P1-4：new_compaction 空 batch 不再提前 return，待确认门继续评估。"""
    eng, sess = _open_gate(tmp_path)
    state = gate._slots(eng)["sess-test"]
    sess.messages.append(Message(role="tool", content=f"read {state['manifest_rel_path']}",
                                 source=MessageSource.SYSTEM, tool_name="read_file"))
    sess.messages.append(Message(role="assistant", content=_receipt(state["manifest_sha256"]),
                                 source=MessageSource.SYSTEM))
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)  # batch 已排干
    kinds = [e[1] for e in eng.events]
    assert "compaction.gate.skip" in kinds  # 空 batch 仍记审计
    assert "compaction.gate.confirmed" in kinds  # 且同轮完成待确认门评估
    assert gate._slots(eng)["sess-test"]["pending"] is False


def test_round_age_fallback_and_visible_from_reset(tmp_path):
    """P1-4：列表收缩重置评估区间；无响应时轮龄兜底升级，防永久注入。"""
    eng, sess = _open_gate(tmp_path)
    state = gate._slots(eng)["sess-test"]
    state["visible_from"] = 50  # 模拟消息列表被重建/收缩
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    assert gate._slots(eng)["sess-test"]["visible_from"] == 0
    for _ in range(gate.ROUND_AGE_ESCALATE):
        gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    state = gate._slots(eng)["sess-test"]
    assert state["escalated"] is True and state["pending"] is False
    hint = gate.pending_gate_hint(eng, "sess-test")
    assert hint["reason"] == "round_age_fallback"
    assert hint["delivery_mode"] == "off"  # rev4.2 P2-1：模式标签可区分伪升级


def test_nonassistant_batch_entry_not_retained(tmp_path):
    """P2-5：非 assistant 批驻留不存原文；assistant 保留。"""
    eng = FakeEngine(tmp_path)
    gate.note_archive_batch_entry(
        eng, "s", Message(role="tool", content="t" * 100, source=MessageSource.SYSTEM),
        SimpleNamespace(id="e1", chars=100), 3,
    )
    gate.note_archive_batch_entry(
        eng, "s", Message(role="assistant", content="keep", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e2", chars=4), 4,
    )
    batch = gate.take_archive_batch(eng, "s")
    tool_entry = next(e for e in batch if e["role"] == "tool")
    asst = next(e for e in batch if e["role"] == "assistant")
    assert tool_entry["original"] is None and tool_entry["chars"] == 100
    assert asst["original"] == "keep"


def test_factory_scan_ttl_and_mtime(tmp_path):
    """P2-1：mtime 倒序 + 24h TTL，陈旧门不计入投影。"""
    import os as _os
    import time as _time

    from llm_loop.factory import _GATE_SCAN_TTL_SECONDS, _scan_pending_compaction_gates

    _open_gate(tmp_path)  # sess-test（较新）
    eng2 = FakeEngine(tmp_path)
    gate.note_archive_batch_entry(
        eng2, "sess-old", Message(role="assistant", content="x", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e1", chars=1), 1,
    )
    gate.run_compaction_gate_step(eng2, FakeSess(session_id="sess-old"), new_compaction=True)
    stale = tmp_path / "compaction_snapshots" / "sess-old" / "gate_state.json"
    _os.utime(stale, (_time.time() - _GATE_SCAN_TTL_SECONDS - 60,) * 2)
    found = _scan_pending_compaction_gates(str(tmp_path))
    ids = [f["session_id"] for f in found]
    assert "sess-old" not in ids and "sess-test" in ids


def test_new_compaction_supersedes_pending_gate(tmp_path):
    """rev4 P1-1：pending 期间再次压缩——旧门 superseded 留审计，stale_events 累积共享回执。"""
    eng, sess = _open_gate(tmp_path)
    old_event = gate._slots(eng)["sess-test"]["compaction_event_id"]
    gate.note_archive_batch_entry(
        eng, "sess-test", Message(role="assistant", content="语义文本2", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e2", chars=5), 3,
    )
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    kinds = [e[1] for e in eng.events]
    assert "compaction.gate.superseded" in kinds and "compaction.gate.opened" in kinds
    state = gate._slots(eng)["sess-test"]
    assert state["stale_events"] == 1 and state["pending"] is True
    assert state["compaction_event_id"] != old_event
    notice = gate.take_gate_notice_text(eng, "sess-test")
    assert "另有 1 个历史压缩事件尚未确认" in notice
    # 确认新门 = 回执同时覆盖历史未确认事件
    sess.messages.append(Message(role="tool", content=f"read {state['manifest_rel_path']}",
                                 source=MessageSource.SYSTEM, tool_name="read_file"))
    sess.messages.append(Message(role="assistant", content=_receipt(state["manifest_sha256"]),
                                 source=MessageSource.SYSTEM))
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    conf = [e for e in eng.events if e[1] == "compaction.gate.confirmed"]
    assert conf and conf[-1][2].get("stale_covered") == 1
    assert gate._slots(eng)["sess-test"]["pending"] is False


def test_degraded_state_persisted_for_projection(tmp_path, monkeypatch):
    """rev4 P2-2：degraded 状态落盘，重启后投影仍可见（state=degraded）。"""
    eng = FakeEngine(tmp_path)
    gate.note_archive_batch_entry(
        eng, "sess-dg", Message(role="assistant", content="x", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e1", chars=1), 2,
    )
    monkeypatch.setattr(gate, "write_compaction_manifest", lambda *a, **k: None)
    gate.run_compaction_gate_step(eng, FakeSess(session_id="sess-dg"), new_compaction=True)
    st = tmp_path / "compaction_snapshots" / "sess-dg" / "gate_state.json"
    assert st.exists()
    payload = json.loads(st.read_text(encoding="utf-8"))
    assert payload["status"] == "degraded" and payload["pending"] is False
    assert payload["session_id"] == "sess-dg"  # rev4.2 P2-3：投影不回退目录名
    from llm_loop.factory import _scan_pending_compaction_gates
    found = [f for f in _scan_pending_compaction_gates(str(tmp_path)) if f["session_id"] == "sess-dg"]
    assert found and found[0]["state"] == "degraded"


def test_degraded_supersedes_pending_gate_with_audit(tmp_path, monkeypatch):
    """rev4.1 P2-2：pending 门存续期间 manifest 写失败——旧门先审计再落 degraded。"""
    eng, sess = _open_gate(tmp_path)  # 开一个 pending 门
    gate.note_archive_batch_entry(
        eng, "sess-test", Message(role="assistant", content="第二批", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e2", chars=3), 3,
    )
    monkeypatch.setattr(gate, "write_compaction_manifest", lambda *a, **k: None)
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    kinds = [e[1] for e in eng.events]
    assert "compaction.gate.superseded" in kinds and "compaction.gate.degraded" in kinds
    sup = [e for e in eng.events if e[1] == "compaction.gate.superseded"][-1]
    assert sup[2].get("by_reason") == "degraded"
    payload = json.loads(
        (tmp_path / "compaction_snapshots" / "sess-test" / "gate_state.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "degraded" and payload.get("stale_events") == 1


# ---------------------------------------------------------------------------
# rev6（EVO-20261112-4f95db8e）：升级路径治理
# ---------------------------------------------------------------------------


def _escalate_first_gate(eng, sess):
    """恰好推到升级（3 步：重注入→重注入→升级），不多走消化摘要的步。"""
    for _ in range(gate.MAX_REINJECTIONS):
        sess.messages.append(
            Message(role="assistant", content="普通回复无回执", source=MessageSource.SYSTEM)
        )
        gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    assert gate._slots(eng)["sess-test"]["escalated"] is True


def test_escalated_digest_bounded_visibility(tmp_path):
    """rev6①：升级摘要经 CR-R1 槽可见，ESCALATED_DIGEST_ROUNDS 轮后归零。"""
    eng, sess = _open_gate(tmp_path)
    _escalate_first_gate(eng, sess)
    state = gate._slots(eng)["sess-test"]
    digest = gate.take_gate_notice_text(eng, "sess-test")
    assert digest is not None and "receipt_missing_after_max_reinject" in digest
    assert f"{gate.MAX_REINJECTIONS}/{gate.MAX_REINJECTIONS}" in digest
    assert state["escalated_digest"] == digest and state["digest_left"] == 2
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    assert state["digest_left"] == 1 and gate.take_gate_notice_text(eng, "sess-test") is not None
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    assert state["digest_left"] == 0 and gate.take_gate_notice_text(eng, "sess-test") is None


def test_escalation_budget_needs_human_and_observe_only(tmp_path):
    """rev6②：预算穿越发 needs_human；后续新门转 observe_only 且零重注入。"""
    eng, sess = _open_gate(tmp_path)
    gate._slots(eng)["sess-test"]["escalations_total"] = gate.ESCALATION_BUDGET - 1
    _escalate_first_gate(eng, sess)
    kinds = [e[1] for e in eng.events]
    assert kinds.count("compaction.gate.escalated") == 1
    assert "compaction.gate.needs_human" in kinds
    nh = [e[2] for e in eng.events if e[1] == "compaction.gate.needs_human"][0]
    assert nh["next_gates_policy"] == "observe_only"
    assert nh["escalations_total"] == gate.ESCALATION_BUDGET
    stats = [e[2] for e in eng.events if e[1] == "compaction.gate.stats"]
    assert stats and stats[-1]["escalated_total"] == 1
    # 预算已耗尽 → 新压缩开门即 observe_only：事件带 mode，通知为空
    gate.note_archive_batch_entry(
        eng, "sess-test", Message(role="assistant", content="再压缩", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e9", chars=3), 9,
    )
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    st2 = gate._slots(eng)["sess-test"]
    assert st2["observe_only"] is True and st2["notice_text"] is None
    opened = [e[2] for e in eng.events if e[1] == "compaction.gate.opened"][-1]
    assert opened["mode"] == "observe_only"
    assert opened["escalations_total"] == gate.ESCALATION_BUDGET
    for _ in range(4):
        sess.messages.append(Message(role="assistant", content="继续任务", source=MessageSource.SYSTEM))
        gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    kinds = [e[1] for e in eng.events]
    assert kinds.count("compaction.gate.reinjected") == gate.MAX_REINJECTIONS - 1  # 全部来自第一门


def test_observe_only_round_age_close(tmp_path):
    """rev6②：observe-only 门轮龄兜底关门（审计事件），投影可见 mode。"""
    from llm_loop.factory import _scan_pending_compaction_gates

    eng, sess = _open_gate(tmp_path)
    gate._slots(eng)["sess-test"]["escalations_total"] = gate.ESCALATION_BUDGET
    gate.note_archive_batch_entry(
        eng, "sess-test", Message(role="assistant", content="新批次", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e5", chars=3), 5,
    )
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    st = gate._slots(eng)["sess-test"]
    assert st["observe_only"] is True
    found = _scan_pending_compaction_gates(str(tmp_path))
    assert found and all(f["mode"] == "observe_only" for f in found)
    for _ in range(gate.ROUND_AGE_ESCALATE + 1):
        sess.messages.append(Message(role="assistant", content="x", source=MessageSource.SYSTEM))
        gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    closed = [e[2] for e in eng.events if e[1] == "compaction.gate.closed"]
    assert closed and closed[0]["closed_by"] == "observe_only_round_age"
    assert gate._slots(eng)["sess-test"]["pending"] is False
    assert [e[1] for e in eng.events].count("compaction.gate.reinjected") == 0


def test_abandon_marker_closes_gate(tmp_path):
    """rev6③：行锚放弃（ref 前缀匹配）机械关门；错误 ref 不识别。"""
    eng, sess = _open_gate(tmp_path)
    state = gate._slots(eng)["sess-test"]
    mref = state["manifest_sha256"]
    wrong = ("a" if mref[0] != "a" else "b") + mref[1:24]
    sess.messages.append(
        Message(role="assistant", content=f"压缩恢复回执：放弃确认 manifest_ref={wrong}",
                source=MessageSource.SYSTEM)
    )
    ev = gate.evaluate_confirmation(sess.messages, state["visible_from"], mref, state["manifest_rel_path"])
    assert ev["abandoned"] is False  # ref 不匹配 → 视为普通文本
    sess.messages.append(
        Message(role="assistant", content=f"压缩恢复回执：放弃确认 manifest_ref={mref[:12]}",
                source=MessageSource.SYSTEM)
    )
    ev = gate.evaluate_confirmation(sess.messages, state["visible_from"], mref, state["manifest_rel_path"])
    assert ev["abandoned"] is True and ev["confirmed"] is False
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    state = gate._slots(eng)["sess-test"]
    assert state["abandoned"] is True and state["pending"] is False
    assert gate.take_gate_notice_text(eng, "sess-test") is None
    kinds = [e[1] for e in eng.events]
    assert "compaction.gate.abandoned" in kinds and "compaction.gate.escalated" not in kinds
    ab = [e[2] for e in eng.events if e[1] == "compaction.gate.abandoned"][0]
    assert ab["by"] == "model_explicit" and ab["manifest_ref"] == mref


def test_receipts_list_threshold_in_notice():
    """rev6③：rounds_open 达阈值才渲染未结算回执清单+放弃指令（阈值 ≤ MAX-1，审查 P1-1）。"""
    manifest = {
        "sha256": "a" * 64,
        "rel_path": "compaction_snapshots/s/1.json",
        "assistant_count": 1,
        "assistant_chars": 5,
        "total_archived": 2,
    }
    assert gate.RECEIPTS_LIST_ROUNDS <= gate.MAX_REINJECTIONS - 1  # 审查 P1-1 不变量
    below = gate.render_gate_notice_text(manifest, attempt=1, rounds_open=gate.RECEIPTS_LIST_ROUNDS - 1)
    assert "未结算回执清单" not in below and gate.ABANDON_MARKER not in below
    at = gate.render_gate_notice_text(
        manifest, attempt=2, rounds_open=gate.RECEIPTS_LIST_ROUNDS, stale_events=2
    )
    assert "未结算回执清单" in at and gate.ABANDON_MARKER in at
    assert "2 个历史压缩事件" in at and f"2/{gate.MAX_REINJECTIONS}" in at


def test_receipts_list_reachable_in_dominant_flow(tmp_path):
    """审查 P1-1 实测（主导失败流）：响应但不确认——第一次重注入即渲染清单。"""
    eng, sess = _open_gate(tmp_path)
    sess.messages.append(Message(role="assistant", content="普通回复无回执", source=MessageSource.SYSTEM))
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    notice = gate.take_gate_notice_text(eng, "sess-test")
    assert "未结算回执清单" in notice and gate.ABANDON_MARKER in notice


def test_receipts_list_reachable_in_no_response_flow(tmp_path):
    """审查 P1-1 实测（无响应流）：等待分支达阈值刷新清单——round_age 路径也可达。"""
    eng, sess = _open_gate(tmp_path)
    first = gate.take_gate_notice_text(eng, "sess-test")
    assert "未结算回执清单" not in first
    for _ in range(gate.RECEIPTS_LIST_ROUNDS):
        gate.run_compaction_gate_step(eng, sess, new_compaction=False)  # 无 assistant 响应
    notice = gate.take_gate_notice_text(eng, "sess-test")
    assert "未结算回执清单" in notice and gate.ABANDON_MARKER in notice
    state = gate._slots(eng)["sess-test"]
    assert state["attempt"] == 1  # 等待分支不计数不重注入（P1-4 语义保持）


def test_cross_run_ledger_inheritance_from_disk(tmp_path):
    """审查 P2-4：跨 run 账本继承走盘上分支——重启后预算仍生效。"""
    eng, sess = _open_gate(tmp_path)
    # 连续三扇门全部升级，耗尽预算（槽内继承路径）
    for i in range(gate.ESCALATION_BUDGET):
        _escalate_first_gate(eng, sess)
        gate.note_archive_batch_entry(
            eng, "sess-test",
            Message(role="assistant", content=f"批次{i}", source=MessageSource.SYSTEM),
            SimpleNamespace(id=f"e{i}", chars=2), i + 10,
        )
        gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    assert gate._slots(eng)["sess-test"]["escalations_total"] == gate.ESCALATION_BUDGET
    # 新引擎（模拟重启）：slots 为空 → 账本必须从盘上 gate_state.json 继承
    eng2 = FakeEngine(tmp_path)
    gate.note_archive_batch_entry(
        eng2, "sess-test",
        Message(role="assistant", content="重启后压缩", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e99", chars=6), 99,
    )
    gate.run_compaction_gate_step(eng2, FakeSess(), new_compaction=True)
    st = gate._slots(eng2)["sess-test"]
    assert st["observe_only"] is True  # 盘上 escalations_total=3 ≥ 预算
    assert st["notice_text"] is None
    opened = [e[2] for e in eng2.events if e[1] == "compaction.gate.opened"][-1]
    assert opened["mode"] == "observe_only"


def test_abandon_on_observe_only_gate(tmp_path):
    """审查 P2-4：observe-only 门同样接受显式放弃（注释声明「任意 pending 门」）。"""
    eng, sess = _open_gate(tmp_path)
    gate._slots(eng)["sess-test"]["escalations_total"] = gate.ESCALATION_BUDGET
    gate.note_archive_batch_entry(
        eng, "sess-test", Message(role="assistant", content="新批次", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e5", chars=3), 5,
    )
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    assert gate._slots(eng)["sess-test"]["observe_only"] is True
    mref = gate._slots(eng)["sess-test"]["manifest_sha256"]
    sess.messages.append(
        Message(role="assistant", content=f"压缩恢复回执：放弃确认 manifest_ref={mref[:12]}",
                source=MessageSource.SYSTEM)
    )
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    state = gate._slots(eng)["sess-test"]
    assert state["abandoned"] is True and state["pending"] is False
    kinds = [e[1] for e in eng.events]
    assert "compaction.gate.abandoned" in kinds
    stats = [e[2] for e in eng.events if e[1] == "compaction.gate.stats"]
    assert stats  # 审查 P2-2：放弃关门也输出 stats 事件


def test_observe_only_no_response_stays_silent(tmp_path):
    """复审 R2 P1-1：observe-only 门 + 无响应流——通知恒为空（零注入硬契约）。

    等待分支的清单刷新（R1 修复引入）不得绕过预算：预算耗尽的会话在
    任何流（含轮龄兜底路径）都不得重新收到确认通知。
    """
    eng, sess = _open_gate(tmp_path)
    gate._slots(eng)["sess-test"]["escalations_total"] = gate.ESCALATION_BUDGET
    gate.note_archive_batch_entry(
        eng, "sess-test", Message(role="assistant", content="新批次", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e6", chars=3), 6,
    )
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    assert gate._slots(eng)["sess-test"]["observe_only"] is True
    assert gate.take_gate_notice_text(eng, "sess-test") is None
    for _ in range(gate.RECEIPTS_LIST_ROUNDS + 3):  # 无 assistant 响应等待流
        gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    assert gate.take_gate_notice_text(eng, "sess-test") is None  # 零通知契约保持
    assert [e[1] for e in eng.events].count("compaction.gate.reinjected") == 0


def test_run_metrics_in_event_payloads(tmp_path):
    """rev6④：escalated/reinjected 事件带 run 级累计计数。"""
    eng, sess = _open_gate(tmp_path)
    _escalate_first_gate(eng, sess)
    esc = [e[2] for e in eng.events if e[1] == "compaction.gate.escalated"][-1]
    assert esc["run_escalations_total"] == 1 and esc["escalations_total"] == 1
    reinj = [e[2] for e in eng.events if e[1] == "compaction.gate.reinjected"]
    assert [r["run_reinject_attempts_total"] for r in reinj] == [1, 2]
    assert reinj[-1]["rounds_open"] >= 1
