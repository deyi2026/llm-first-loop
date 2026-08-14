"""evolve-verify 通道测试（EVO-20260813-8279507f）.

覆盖: 存储层 verified_at 字段落盘 / CLI 层核验、幂等、非 executed 拒绝、不存在.
"""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.cli import _cmd_evolve_verify
from llm_loop.introspection.evolution import EvolutionStore


def _mk_store(tmp_path, status="executed"):
    """构造一条指定状态的演进建议."""
    store = EvolutionStore(tmp_path / "audit")
    s = store.submit(content="verify 通道建议", impact_scope="cli.py")
    store.review(s.id, "accepted")
    if status == "executed":
        store.transition(s.id, status="executed", executed_at="2026-08-13T00:00:00+00:00")
    elif status == "accepted":
        pass  # 停留在 accepted
    return store, s


def _mk_engine(store):
    return SimpleNamespace(correction_ctx=SimpleNamespace(evolution_store=store))


# ── 存储层: verified_at 字段落盘 ────────────────────────────────
def test_store_verify_fields_persist(tmp_path):
    store, s = _mk_store(tmp_path)
    target = store.transition(
        s.id, status="executed", verified_at="2026-08-14T03:00:00+00:00", verify_note="人工核验通过"
    )
    assert target["status"] == "executed"  # 终态不变
    assert target["verified_at"] == "2026-08-14T03:00:00+00:00"
    assert target["verify_note"] == "人工核验通过"
    # 重读落盘确认
    got = next(it for it in store.list() if it["id"] == s.id)
    assert got["verified_at"] == "2026-08-14T03:00:00+00:00"
    assert got["verify_note"] == "人工核验通过"


# ── CLI 层: _cmd_evolve_verify ─────────────────────────────────
def test_verify_executed_success(tmp_path, capsys):
    store, s = _mk_store(tmp_path)
    rc = _cmd_evolve_verify(_mk_engine(store), s.id, "核验通过")
    assert rc == 0
    got = next(it for it in store.list() if it["id"] == s.id)
    assert got["verified_at"]  # 非空
    assert got["verify_note"] == "核验通过"
    assert "核验完成" in capsys.readouterr().out


def test_verify_idempotent(tmp_path, capsys):
    store, s = _mk_store(tmp_path)
    _cmd_evolve_verify(_mk_engine(store), s.id, "第一次")
    first_at = next(it for it in store.list() if it["id"] == s.id)["verified_at"]
    # 第二次核验 → 幂等跳过，不覆盖
    rc = _cmd_evolve_verify(_mk_engine(store), s.id, "第二次")
    assert rc == 0
    got = next(it for it in store.list() if it["id"] == s.id)
    assert got["verified_at"] == first_at  # 时间戳未被覆盖
    assert got["verify_note"] == "第一次"  # note 未被覆盖
    assert "幂等跳过" in capsys.readouterr().out


def test_verify_rejects_non_executed(tmp_path, capsys):
    store, s = _mk_store(tmp_path, status="accepted")
    rc = _cmd_evolve_verify(_mk_engine(store), s.id, "试图核验未执行")
    assert rc == 2
    assert "仅 executed 可核验" in capsys.readouterr().out


def test_verify_not_found(tmp_path, capsys):
    store, _ = _mk_store(tmp_path)
    rc = _cmd_evolve_verify(_mk_engine(store), "no-such-id", "不存在")
    assert rc == 1
    assert "建议不存在" in capsys.readouterr().out
