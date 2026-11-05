"""EVO-20261105-7eb1e99f：shadow 压缩确认门生命周期（rev5）.

(a) shadow 开启的确认门零落盘（仅观测事件流，manifest 恢复材料仍写）；
    enforce/off 落盘与确认流程不变（应拦输入：enforce 不得被误伤）。
(b) TTL 到期的确认门由 factory 状态装配（pending_actions）复用 superseded
    机制收终态并清理状态文件（manifest 保留；degraded/不可解析不动；
    TTL 内文件不动）。
(c) 存量迁移脚本默认 dry-run 只读（应拦输入：既有 pending 文件不误删、
    不产出归档文件）；--execute 才归档+删除且幂等。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

from llm_loop.core.loop.engine_services import compaction_gate as gate
from llm_loop.core.message import Message, MessageSource


@dataclass
class FakeSess:
    session_id: str = "sess-test"
    messages: list = field(default_factory=list)


class ModeEngine:
    """带 cog_runtime_mode 的最小引擎替身（事件/动作/数据目录）。"""

    def __init__(self, data_dir, mode="off"):
        self.settings = SimpleNamespace(data_dir=str(data_dir), cog_runtime_mode=mode)
        self.events = []
        self.actions = []

    def _event_append(self, session_id, event_type, payload):
        self.events.append((session_id, event_type, payload))

    def _record_action(self, phase, action_type, detail):
        self.actions.append((phase, action_type, detail))


def _entry(text, seq, sid="sess-test"):
    return {
        "session_id": sid,
        "msg_seq": seq,
        "role": "assistant",
        "ts": None,
        "chars": len(text),
        "sha256": None,
        "archive_entry_id": f"entry-{seq}",
        "archive_file": "1.jsonl",
        "evidence_ref": None,
        "original": text,
    }


def _open_gate(tmp_path, mode):
    eng = ModeEngine(tmp_path, mode=mode)
    gate.note_archive_batch_entry(
        eng,
        "sess-test",
        Message(role="assistant", content="语义文本", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e1", chars=4),
        2,
    )
    sess = FakeSess()
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    return eng, sess


def _receipt(mref):
    return (
        f"[压缩恢复回执]\nmanifest_ref={mref}\ngoal_ref=GOAL-1\n"
        "1. 任务目标：完成设计评审\n2. 下一步：更新文档\n3. 未决负结果：无\n"
        "4. 关键数字出处：docs/report.md\n5. 交付物位置：docs/out.md\n"
    )


def _state_file(tmp_path, sid="sess-test"):
    return tmp_path / "compaction_snapshots" / sid / "gate_state.json"


# ---------------------------------------------------------------------------
# (a) shadow 零落盘；enforce/off 落盘与确认流程不变（RULE-AI-35 应拦输入）
# ---------------------------------------------------------------------------


def test_enforce_gate_persists_and_confirm_flow_unchanged(tmp_path):
    """应拦输入：enforce 模式门必须仍正常落盘，确认流程不得被 shadow 改动误伤。"""
    eng, sess = _open_gate(tmp_path, mode="enforce")
    state = gate._slots(eng)["sess-test"]
    assert state["pending"] is True and state["delivery_mode"] == "enforce"
    on_disk = gate.read_gate_state(str(tmp_path), "sess-test")
    assert on_disk and on_disk["pending"] is True  # 落盘不变
    opened = [e for e in eng.events if e[1] == "compaction.gate.opened"][-1]
    assert opened[2]["delivery_mode"] == "enforce"
    # 确认流程不变：恢复类工具触达 + 五问回执 → confirmed
    sess.messages.append(
        Message(
            role="tool",
            content=f"read {state['manifest_rel_path']}",
            source=MessageSource.SYSTEM,
            tool_name="read_file",
        )
    )
    sess.messages.append(
        Message(
            role="assistant",
            content=_receipt(state["manifest_sha256"]),
            source=MessageSource.SYSTEM,
        )
    )
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    assert gate._slots(eng)["sess-test"]["pending"] is False
    assert "compaction.gate.confirmed" in [e[1] for e in eng.events]
    closed = gate.read_gate_state(str(tmp_path), "sess-test")
    assert closed["pending"] is False and closed["consumed_at"]  # 终态仍落盘（TTL 后由收割器清理）


def test_off_mode_still_persists(tmp_path):
    """off 模式维持既有落盘语义（只有 shadow 门豁免），向后兼容。"""
    _open_gate(tmp_path, mode="off")
    assert _state_file(tmp_path).exists()
    assert gate.read_gate_state(str(tmp_path), "sess-test")["delivery_mode"] == "off"


def test_shadow_gate_zero_disk_full_lifecycle(tmp_path):
    """shadow 门全生命周期零落盘；事件流与 manifest 照常（仅观测）。"""
    eng, sess = _open_gate(tmp_path, mode="shadow")
    kinds = [e[1] for e in eng.events]
    assert "compaction.snapshot" in kinds and "compaction.gate.opened" in kinds
    opened = [e for e in eng.events if e[1] == "compaction.gate.opened"][-1]
    assert opened[2]["delivery_mode"] == "shadow"
    state = gate._slots(eng)["sess-test"]
    assert state["pending"] is True and state["delivery_mode"] == "shadow"
    assert gate.take_gate_notice_text(eng, "sess-test")  # 槽内通知仍在（观测）
    # manifest（恢复材料）仍写；确认门状态零落盘
    manifest_files = list((tmp_path / "compaction_snapshots" / "sess-test").glob("*.json"))
    assert manifest_files and all("gate_state" not in f.name for f in manifest_files)
    assert not _state_file(tmp_path).exists()
    # 机械升级到 escalated 终态仍零落盘（不再产生 escalated 残留文件）
    for _ in range(gate.MAX_REINJECTIONS + 2):
        sess.messages.append(
            Message(role="assistant", content="普通回复无回执", source=MessageSource.SYSTEM)
        )
        gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    escalated = [e for e in eng.events if e[1] == "compaction.gate.escalated"]
    assert escalated and escalated[-1][2]["delivery_mode"] == "shadow"
    assert not _state_file(tmp_path).exists()
    assert gate.restore_gate_state(ModeEngine(tmp_path, mode="shadow"), "sess-test") is None


def test_shadow_supersede_reuse_leaves_no_orphan(tmp_path):
    """(b)：shadow 门 superseded 收口复用内存状态机，不留孤儿/重复文件。"""
    eng, sess = _open_gate(tmp_path, mode="shadow")
    gate.note_archive_batch_entry(
        eng,
        "sess-test",
        Message(role="assistant", content="第二批", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e2", chars=3),
        3,
    )
    gate.run_compaction_gate_step(eng, sess, new_compaction=True)
    kinds = [e[1] for e in eng.events]
    assert "compaction.gate.superseded" in kinds and "compaction.gate.opened" in kinds
    state = gate._slots(eng)["sess-test"]
    assert state["stale_events"] == 1 and state["pending"] is True
    assert not _state_file(tmp_path).exists()  # 零孤儿


def test_degraded_persists_even_in_shadow(tmp_path, monkeypatch):
    """degraded 是完整性观察非确认门：shadow 下也落盘（rev4 P2-2 语义不变）。"""
    eng = ModeEngine(tmp_path, mode="shadow")
    gate.note_archive_batch_entry(
        eng,
        "sess-dg",
        Message(role="assistant", content="x", source=MessageSource.SYSTEM),
        SimpleNamespace(id="e1", chars=1),
        2,
    )
    monkeypatch.setattr(gate, "write_compaction_manifest", lambda *a, **k: None)
    gate.run_compaction_gate_step(eng, FakeSess(session_id="sess-dg"), new_compaction=True)
    st = _state_file(tmp_path, sid="sess-dg")
    assert st.exists()
    payload = json.loads(st.read_text(encoding="utf-8"))
    assert payload["status"] == "degraded" and payload["pending"] is False


def test_shadow_flip_mid_life_no_half_state(tmp_path):
    """开门冻结 delivery_mode：shadow 开的门翻转 enforce 后也不落半状态文件。"""
    eng, sess = _open_gate(tmp_path, mode="shadow")
    eng.settings.cog_runtime_mode = "enforce"  # 运行中翻转
    sess.messages.append(
        Message(role="assistant", content="普通回复无回执", source=MessageSource.SYSTEM)
    )
    gate.run_compaction_gate_step(eng, sess, new_compaction=False)
    assert gate._slots(eng)["sess-test"]["attempt"] == 2
    assert not _state_file(tmp_path).exists()  # 开门时是 shadow → 终其生命周期不落盘


# ---------------------------------------------------------------------------
# (b) factory TTL 收割：复用 superseded 机制落终态并清理（manifest 保留）
# ---------------------------------------------------------------------------


def _make_state_file(tmp_path, sid, payload, *, age_seconds=0):
    d = tmp_path / "compaction_snapshots" / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text("{}", encoding="utf-8")  # manifest 必须保留
    p = d / "gate_state.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if age_seconds:
        old = time.time() - age_seconds
        os.utime(p, (old, old))
    return p


def test_ttl_reaper_closes_and_cleans(tmp_path):
    from llm_loop.factory import (
        _GATE_SCAN_TTL_SECONDS,
        _expire_stale_compaction_gates,
        _scan_pending_compaction_gates,
    )

    stale_age = _GATE_SCAN_TTL_SECONDS + 60
    fresh_pending = _make_state_file(
        tmp_path,
        "sess-fresh",
        {"session_id": "sess-fresh", "pending": True},
    )
    stale_pending = _make_state_file(
        tmp_path,
        "sess-stale-p",
        {"session_id": "sess-stale-p", "pending": True},
        age_seconds=stale_age,
    )
    stale_escalated = _make_state_file(
        tmp_path,
        "sess-stale-e",
        {
            "session_id": "sess-stale-e",
            "pending": False,
            "escalated": True,
            "delivery_mode": "shadow",
        },
        age_seconds=stale_age,
    )
    stale_confirmed = _make_state_file(  # 自愈路径：崩溃残留的终态文件
        tmp_path,
        "sess-stale-c",
        {"session_id": "sess-stale-c", "pending": False, "consumed_at": "2026-11-01"},
        age_seconds=stale_age,
    )
    stale_degraded = _make_state_file(
        tmp_path,
        "sess-stale-d",
        {"session_id": "sess-stale-d", "status": "degraded", "pending": False},
        age_seconds=stale_age,
    )
    # 坏 JSON 的过期文件（P2-2 修正：先写内容再置旧 mtime——写后置时的顺序
    # 会把 mtime 重置为新鲜，清理分支从未被真正覆盖）
    stale_broken = tmp_path / "compaction_snapshots" / "sess-stale-b" / "gate_state.json"
    stale_broken.parent.mkdir(parents=True, exist_ok=True)
    stale_broken.write_text("{not json", encoding="utf-8")
    _stale_ts = time.time() - stale_age
    os.utime(stale_broken, (_stale_ts, _stale_ts))

    # JSON 合法但非 dict 的过期文件（review-3 P2-4：同样归档清理，不永久计数）
    stale_nondict = tmp_path / "compaction_snapshots" / "sess-stale-nd" / "gate_state.json"
    stale_nondict.parent.mkdir(parents=True, exist_ok=True)
    stale_nondict.write_text('["not", "a", "dict"]', encoding="utf-8")
    os.utime(stale_nondict, (_stale_ts, _stale_ts))

    stats = _expire_stale_compaction_gates(str(tmp_path))

    assert stats["superseded_expired"] == 2  # stale pending + stale escalated
    assert stats["terminal_removed"] == 1  # stale confirmed（自愈）
    assert stats["stale_unparseable_removed"] == 2  # 坏 JSON+非 dict 过期 → 归档清理
    assert stats["errors"] == 0
    # 活门与保留类不动
    assert fresh_pending.exists()
    assert stale_degraded.exists()
    assert not stale_broken.exists() and not stale_nondict.exists()
    # 坏 JSON 清理留有归档审计行（reason_class=stale_unparseable）
    archive_files = sorted((tmp_path / "compaction_snapshots").glob("_migrated-*.jsonl"))
    assert archive_files, "收割归档文件应存在"
    archive_text = archive_files[-1].read_text(encoding="utf-8")
    assert "stale_unparseable" in archive_text
    # 清理的确认门：状态文件删除，manifest 保留
    for p in (stale_pending, stale_escalated, stale_confirmed):
        assert not p.exists()
        assert (p.parent / "manifest.json").exists()
    # 投影扫描不受影响：fresh pending 仍可见
    found = _scan_pending_compaction_gates(str(tmp_path))
    assert [f["session_id"] for f in found] == ["sess-fresh"]


def test_reaper_leaves_fresh_terminal_files(tmp_path):
    """TTL 内的终态文件不清理（escalated 需在 24h 窗口内对宿主可见）。"""
    from llm_loop.factory import _expire_stale_compaction_gates

    p = _make_state_file(
        tmp_path,
        "sess-new-e",
        {"session_id": "sess-new-e", "pending": False, "escalated": True},
    )
    stats = _expire_stale_compaction_gates(str(tmp_path))
    assert stats == {
        "superseded_expired": 0,
        "terminal_removed": 0,
        "stale_unparseable_removed": 0,  # 窄复审 P2-4：新增键，fresh 文件恒为 0
        "kept": 1,
        "errors": 0,
    }
    assert p.exists()


# ---------------------------------------------------------------------------
# (c) 迁移脚本：dry-run 只读（应拦输入：pending 不误删）；execute 幂等
# ---------------------------------------------------------------------------


def _migration_tree(tmp_path):
    # _make_state_file 自身会拼 <base>/compaction_snapshots/<sid>，这里传 data 根
    root = tmp_path / "data"
    snaps = root / "compaction_snapshots"
    _make_state_file(root, "m-pending", {"session_id": "m-pending", "pending": True})
    _make_state_file(
        root, "m-degraded", {"session_id": "m-degraded", "status": "degraded", "pending": False}
    )
    _make_state_file(
        root, "m-confirmed", {"session_id": "m-confirmed", "pending": False, "consumed_at": "t"}
    )
    _make_state_file(
        root, "m-superseded", {"session_id": "m-superseded", "pending": False, "superseded": True}
    )
    _make_state_file(
        root,
        "m-escalated",
        {
            "session_id": "m-escalated",
            "pending": False,
            "escalated": True,
            "delivery_mode": "shadow",
        },
    )
    (snaps / "m-broken").mkdir(parents=True, exist_ok=True)
    (snaps / "m-broken" / "gate_state.json").write_text("{broken", encoding="utf-8")
    return root


def test_migration_dry_run_is_readonly(tmp_path, capsys):
    """应拦输入：dry-run 对 pending/degraded/未知文件零删除、零归档产出。"""
    from scripts.migrate_compaction_gate_states import main

    root = _migration_tree(tmp_path)
    before = sorted(
        p.relative_to(root).as_posix()
        for p in (root / "compaction_snapshots").glob("*/gate_state.json")
    )
    rc = main(["--data-dir", str(root)])
    out = capsys.readouterr().out
    assert rc == 0 and "[dry-run]" in out
    assert "保留（pending/degraded/unknown）: 3" in out  # pending+degraded+broken
    assert "归档后删除（confirmed/superseded/escalated）: 3" in out
    after = sorted(
        p.relative_to(root).as_posix()
        for p in (root / "compaction_snapshots").glob("*/gate_state.json")
    )
    assert after == before  # 一个文件都没动（RULE-AI-35：pending 不被误删）
    assert not list((root / "compaction_snapshots").glob("_migrated-*.jsonl"))


def test_migration_execute_archives_then_deletes_idempotently(tmp_path, capsys):
    """--execute（仅测试 tmp 副本）：终态归档+删除、保留类不动、重跑幂等。"""
    from scripts.migrate_compaction_gate_states import archive_path, main

    root = _migration_tree(tmp_path)
    main(["--data-dir", str(root), "--execute"])
    capsys.readouterr()
    snaps = root / "compaction_snapshots"
    # 终态类删除；保留类（含不可解析）原样
    for sid in ("m-confirmed", "m-superseded", "m-escalated"):
        assert not (snaps / sid / "gate_state.json").exists()
    for sid in ("m-pending", "m-degraded", "m-broken"):
        assert (snaps / sid / "gate_state.json").exists()
    # 归档逐文件记录原路径 + 内容摘要 + sha256
    archive = archive_path(snaps)
    rows = [json.loads(ln) for ln in archive.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    by_path = {r["original_path"]: r for r in rows}
    esc = by_path["compaction_snapshots/m-escalated/gate_state.json"]
    assert esc["reason_class"] == "escalated"
    assert esc["content_digest"]["delivery_mode"] == "shadow"
    assert len(esc["sha256"]) == 64 and esc["evo"] == "EVO-20261105-7eb1e99f"
    # 重跑：无剩余可迁移 → 不新增归档行、保留类仍不动
    rc = main(["--data-dir", str(root), "--execute"])
    assert rc == 0
    rows2 = [json.loads(ln) for ln in archive.read_text(encoding="utf-8").splitlines()]
    assert len(rows2) == 3
    assert (snaps / "m-pending" / "gate_state.json").exists()
