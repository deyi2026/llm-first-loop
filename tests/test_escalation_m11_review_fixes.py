"""M1.1 复审修复批（LFL_Sandbox_Escalation_Implementation_Review_2026-11-06）红→绿测试.

对应问题：
- R1 (P1): 跨进程写回把派生标记 _sig_unverified 混入持久层，破坏原签名进程 MAC
  —— 分离「持久记录」与「验证视图」：任何进程写回不得改动他进程记录字段集。
- R1 迁移: 历史盘上被旧代码污染的记录（本进程签名 + 他进程注入标记）受控恢复。
- R4: list 无稳定游标 —— 补 before_id 稳定游标，待审队列可单调读完。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import llm_loop.tools.escalation as esc_mod
from llm_loop.tools.escalation import EscalationStore

_SRC = str(Path(__file__).resolve().parents[1] / "src")
_KEY_A = b"a" * 32
_KEY_B = b"b" * 32


def _disk_records(state: Path) -> list[dict]:
    return json.loads(state.read_text(encoding="utf-8"))


class _ProcessKey:
    """把模块级签名密钥切到指定值——同进程内模拟另一进程的独立内存密钥视图."""

    def __init__(self, key: str):
        self._key = key

    def __enter__(self) -> None:
        self._saved = esc_mod._STATE_SIGNING_KEY
        esc_mod._STATE_SIGNING_KEY = self._key

    def __exit__(self, *exc) -> None:
        esc_mod._STATE_SIGNING_KEY = self._saved


# ── R1: 跨进程写回零污染 ──


def test_r1_foreign_writeback_must_not_pollute_local_records(tmp_path):
    """A 创建 → B 创建/审批自己的 → A 仍可验证并审批自己的；盘面零派生字段."""
    state = tmp_path / "escalation_requests.json"

    with _ProcessKey(_KEY_A):
        store_a = EscalationStore(state)
        r1 = store_a.create(tool_name="t", command="cmd-a1", justification="j", session_id="sa")

    with _ProcessKey(_KEY_B):
        store_b = EscalationStore(state)
        r2 = store_b.create(tool_name="t", command="cmd-b1", justification="j", session_id="sb")
        out_b, reason_b = store_b.decide(r2["id"], "denied", decided_by="B")
        assert out_b is not None, f"B 应能审批自己的记录: {reason_b}"

    # 盘面：任何记录都不得携带 _sig_unverified 派生字段（R1 核心）
    for rec in _disk_records(state):
        assert "_sig_unverified" not in rec, f"派生标记混入持久层: {rec.get('id')}"

    with _ProcessKey(_KEY_A):
        got = store_a.get(r1["id"])
        assert got is not None
        assert not got.get("_sig_unverified"), "A 自己的记录被他进程写回污染（R1）"
        out_a, reason_a = store_a.decide(r1["id"], "denied", decided_by="A")
        assert out_a is not None, f"A 应仍能审批自己的记录: {reason_a}"
        assert out_a["status"] == "denied"


def test_r1_reverse_alternation(tmp_path):
    """交替在反方向执行一次：A 写回后，B 自己的记录同样零污染."""
    state = tmp_path / "escalation_requests.json"

    with _ProcessKey(_KEY_B):
        store_b = EscalationStore(state)
        rb = store_b.create(tool_name="t", command="cmd-b1", justification="j", session_id="sb")

    with _ProcessKey(_KEY_A):
        store_a = EscalationStore(state)
        ra = store_a.create(tool_name="t", command="cmd-a1", justification="j", session_id="sa")
        out_a, _ = store_a.decide(ra["id"], "denied", decided_by="A")
        assert out_a is not None
        # 再触发一次 A 写回（此时 B 的记录在 A 视角是只读视图）
        store_a.create(tool_name="t", command="cmd-a2", justification="j", session_id="sa")

    with _ProcessKey(_KEY_B):
        got_b = store_b.get(rb["id"])
        assert got_b is not None
        assert not got_b.get("_sig_unverified"), "B 的记录被 A 写回污染（反向交替）"
        out_b, reason_b = store_b.decide(rb["id"], "approved", decided_by="B")
        assert out_b is not None, f"B 应仍能审批自己的记录: {reason_b}"
        assert out_b["status"] == "approved"

    for rec in _disk_records(state):
        assert "_sig_unverified" not in rec


def test_r1_migration_recovers_historically_polluted_local_records(tmp_path):
    """历史盘上被旧代码污染的本进程记录：受控验证迁移恢复（不得直接采信或删除）."""
    state = tmp_path / "escalation_requests.json"
    store = EscalationStore(state)
    rec = store.create(tool_name="t", command="cmd-m", justification="j", session_id="s")

    # 模拟 M1 旧代码写回污染：他进程把派生标记注入磁盘载荷，sig 保留原值
    data = _disk_records(state)
    assert len(data) == 1 and data[0].get("sig")
    data[0]["_sig_unverified"] = True
    state.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    got = store.get(rec["id"])
    assert got is not None
    assert not got.get("_sig_unverified"), "历史污染的本进程记录应被受控恢复"
    out, reason = store.decide(rec["id"], "denied", decided_by="migration")
    assert out is not None, f"恢复后应可审批: {reason}"
    # 恢复写回后盘面清洗派生标记
    assert "_sig_unverified" not in _disk_records(state)[0]


def test_r1_migration_does_not_trust_foreign_records(tmp_path):
    """迁移只恢复可验证记录：他进程签名记录剥离标记后仍无法本地验证 → 保持只读."""
    state = tmp_path / "escalation_requests.json"
    with _ProcessKey(_KEY_B):
        store_b = EscalationStore(state)
        rb = store_b.create(tool_name="t", command="cmd-foreign", justification="j", session_id="sb")
        # B 退出前盘面被旧代码注入标记（模拟历史污染的他进程记录）
    data = _disk_records(state)
    data[0]["_sig_unverified"] = True
    state.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    with _ProcessKey(_KEY_A):
        store_a = EscalationStore(state)
        got = store_a.get(rb["id"])
        assert got is not None, "他进程记录仍需可见（审计完整性），只是不可操作"
        assert got.get("_sig_unverified"), "他进程记录剥离标记后无法验证，必须保持失效视图"
        out, reason = store_a.decide(rb["id"], "approved", decided_by="A")
        assert out is None and "无法验证来源" in reason
        assert store_a.pending_count() == 0


def test_r1_foreign_records_stay_fail_closed(tmp_path):
    """R1 修复不得弱化 fail-closed：他进程 pending 不被幂等复用/计数/审批/消费."""
    state = tmp_path / "escalation_requests.json"
    with _ProcessKey(_KEY_B):
        store_b = EscalationStore(state)
        rb = store_b.create(tool_name="t", command="shared-cmd", justification="j", session_id="ss")

    with _ProcessKey(_KEY_A):
        store_a = EscalationStore(state)
        ra = store_a.create(tool_name="t", command="shared-cmd", justification="j", session_id="ss")
        assert ra["id"] != rb["id"], "他进程失效 pending 不得幂等复用（ESC-03 保持）"
        assert store_a.pending_count() == 1, "只计本进程可操作 pending"
        out, reason = store_a.decide(rb["id"], "approved", decided_by="A")
        assert out is None and "无法验证来源" in reason
        hit, _ = store_a.consume("whatever-token", "t", "shared-cmd")
        assert hit is None


def test_r1_real_cross_process_smoke(tmp_path):
    """真实子进程（独立随机密钥）读改写后，本进程记录零污染（真实多进程冒烟）."""
    state = tmp_path / "escalation_requests.json"
    store = EscalationStore(state)
    mine = store.create(tool_name="t", command="cmd-a1", justification="j", session_id="sa")

    script = (
        "import sys\n"
        f"sys.path.insert(0, {_SRC!r})\n"
        "from llm_loop.tools.escalation import EscalationStore\n"
        "store = EscalationStore(sys.argv[1])\n"
        "r = store.create(tool_name='t', command='cmd-child', justification='j', session_id='child')\n"
        "out, reason = store.decide(r['id'], 'denied', decided_by='child')\n"
        "assert out is not None, reason\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, str(state)], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"子进程失败:\n{proc.stderr}"

    for rec in _disk_records(state):
        assert "_sig_unverified" not in rec, f"真实双进程写回污染: {rec.get('id')}"
    got = store.get(mine["id"])
    assert got is not None and not got.get("_sig_unverified")
    out, reason = store.decide(mine["id"], "denied", decided_by="parent")
    assert out is not None, reason


# ── R4: list 稳定游标 ──


def test_r4_list_before_id_stable_cursor(tmp_path):
    store = EscalationStore(tmp_path / "escalation_requests.json")
    ids = [
        store.create(tool_name="t", command=f"cmd-{i}", justification="j", session_id="s")["id"]
        for i in range(5)
    ]
    # 新→旧
    assert [r["id"] for r in store.list(limit=2)] == [ids[4], ids[3]]
    assert [r["id"] for r in store.list(limit=2, before_id=ids[3])] == [ids[2], ids[1]]
    assert [r["id"] for r in store.list(limit=2, before_id=ids[1])] == [ids[0]]
    assert store.list(limit=2, before_id=ids[0]) == []
    # 游标指向已消失记录 → 降级从头读（前端按 id 去重），不抛错不静默吞
    assert [r["id"] for r in store.list(limit=2, before_id="ESC-gone")] == [ids[4], ids[3]]
