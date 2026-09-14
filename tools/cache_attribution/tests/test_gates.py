#!/usr/bin/env python3
"""test_gates.py — Cache Attribution Scorer 的七道 Gate.

G1 Snapshot / G2 Determinism / G3 Classification / G4 Accounting /
G5 Controllability / G6 Idempotence / G7 Golden Regression。

跑法：pytest -q   或   python3 test_gates.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
SCORER = TOOLS / "scorer.py"
FREEZE = TOOLS / "freeze.py"
REAL_FROZEN = TOOLS / "fixtures" / "51da0a7a-frozen"
GOLDEN = TOOLS / "fixtures" / "golden" / "51da0a7a.golden.jsonl"


def run(*args: str, expect: int = 0) -> subprocess.CompletedProcess:
    p = subprocess.run(
        [sys.executable, str(SCORER), *args], capture_output=True, text=True
    )
    assert p.returncode == expect, f"rc={p.returncode} stderr={p.stderr[-400:]}"
    return p


def dir_hash(p: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(x for x in Path(p).rglob("*") if x.is_file()):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def make_frozen(tmp: Path, events: list[dict], session_id: str = "synthetic") -> Path:
    """走真实 freeze 管道生成合成快照（顺带测 freeze 的确定性）。"""
    src = tmp / "src"
    src.mkdir(parents=True)
    with open(src / "log.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    out = tmp / "frozen"
    p = subprocess.run(
        [sys.executable, str(FREEZE), str(src), str(out), "--session-id", session_id],
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stderr
    return out


def meta(seq: int, ts: str, rnd: int, model="glm/glm-5.3", provider="glm", folded=0):
    return {
        "seq": seq,
        "ts": ts,
        "type": "request.meta",
        "payload": {
            "round": rnd,
            "model": model,
            "generation_contract": {"provider": provider},
            "influence": {"ingress": {"tool_working_set": {"folded_results": folded}}},
        },
    }


def usage(seq: int, ts: str, rnd: int, ti: int, hit: int, fp="fp0", changed=False):
    return {
        "seq": seq,
        "ts": ts,
        "type": "request.usage",
        "payload": {
            "round": rnd,
            "tokens_in": ti,
            "cache_hit": hit,
            "stable_prefix_fp": fp,
            "prefix_changed": changed,
            "prefix_change_reason": "",
        },
    }


def load_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


# ── G1 Snapshot Gate ────────────────────────────────────────────────────────
def test_g1_snapshot_gate_rejects_tamper(tmp_path):
    frozen = tmp_path / "frozen"
    shutil.copytree(REAL_FROZEN, frozen)
    extract = frozen / "extract.jsonl"
    original = extract.read_bytes()
    extract.write_bytes(original + b'{"seq":99999,"type":"request.usage"}\n')
    run("score", str(frozen), "-o", str(tmp_path / "out.jsonl"), expect=2)  # count/hash 不符


def test_g1_snapshot_gate_source_growth_irrelevant(tmp_path):
    """源日志继续增长不得影响已冻结结果（冻结目录只认 manifest+extract）。"""
    frozen = tmp_path / "frozen"
    shutil.copytree(REAL_FROZEN, frozen)
    out1 = tmp_path / "a.jsonl"
    run("score", str(frozen), "-o", str(out1))
    # 模拟源增长：往冻结目录旁再放一个更大的源并重新 freeze 到别的目录，不影响 frozen
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(REAL_FROZEN / "extract.jsonl", src / "log.jsonl")
    with open(src / "log.jsonl", "a") as f:
        f.write(json.dumps(usage(99999, "2026-09-14T23:00:00+00:00", 99, 100, 0)) + "\n")
    out2 = tmp_path / "b.jsonl"
    run("score", str(frozen), "-o", str(out2))
    assert out1.read_bytes() == out2.read_bytes()


# ── G2 Determinism Gate ────────────────────────────────────────────────────
def test_g2_determinism_three_runs_byte_identical(tmp_path):
    outs = []
    for i in range(3):
        o = tmp_path / f"r{i}.jsonl"
        run("score", str(REAL_FROZEN), "-o", str(o))
        outs.append(o.read_bytes())
    assert outs[0] == outs[1] == outs[2]


# ── G3 Classification Gate ─────────────────────────────────────────────────
def _score_real(tmp_path) -> list[dict]:
    o = tmp_path / "real.jsonl"
    run("score", str(REAL_FROZEN), "-o", str(o))
    return load_records(o)


def test_g3_real_session_manual_cases(tmp_path):
    recs = _score_real(tmp_path)
    by_ts = {r["ts"][11:19]: r for r in recs if r.get("record_type") == "request_attribution"}
    # 人工核过的三组案例
    f = by_ts["11:47:49"]
    assert f["boundary"]["primary"] == "working_set_fold", f
    assert f["attribution"]["boundary_excess_miss"] == 7863
    for t in ("13:30:24", "13:31:11"):
        r = by_ts[t]
        assert r["boundary"]["primary"] == "history_compaction"
        assert "working_set_fold" not in r["boundary"]["types"], (
            "armed-but-not-executed fold 不得进 types（13:31 教训回归）"
        )
    e = by_ts["11:51:30"]
    assert e["boundary"]["primary"] == "provider_eviction"
    assert e["attribution"]["boundary_excess_miss"] == 29079
    # 分布覆盖真实出现的五类
    prims = {r["boundary"]["primary"] for r in recs if r.get("record_type") == "request_attribution"}
    assert {"append_only", "history_compaction", "working_set_fold", "provider_eviction", "new_run_cold_start"} <= prims


def test_g3_synthetic_route_switch(tmp_path):
    evs = [
        meta(1, "2026-09-14T10:00:00+00:00", 1, model="m/a", provider="pa"),
        usage(2, "2026-09-14T10:00:01+00:00", 1, 5000, 0),
        meta(3, "2026-09-14T10:00:10+00:00", 2, model="m/b", provider="pb"),
        usage(4, "2026-09-14T10:00:11+00:00", 2, 5000, 0),
    ]
    frozen = make_frozen(tmp_path, evs)
    o = tmp_path / "o.jsonl"
    run("score", str(frozen), "-o", str(o))
    recs = load_records(o)
    r2 = [r for r in recs if r.get("round") == 2][0]
    assert r2["boundary"]["primary"] == "route_switch"
    assert r2["attribution"]["expected_append_miss"] == 5000  # 跨路由无复用


def test_g3_synthetic_unknown(tmp_path):
    evs = [
        meta(1, "2026-09-14T10:00:00+00:00", 1, folded=3),
        usage(2, "2026-09-14T10:00:01+00:00", 1, 20000, 19000),
        meta(3, "2026-09-14T10:00:10+00:00", 2, folded=3),  # 无 fold 执行
        usage(4, "2026-09-14T10:00:11+00:00", 2, 15000, 14500),  # 回缩无证据
    ]
    frozen = make_frozen(tmp_path, evs)
    o = tmp_path / "o.jsonl"
    run("score", str(frozen), "-o", str(o))
    r2 = [r for r in load_records(o) if r.get("round") == 2][0]
    assert r2["boundary"]["primary"] == "unknown"
    assert r2["attribution"]["controllable"] == "unknown"


def test_g3_synthetic_cooccurrence_types_preserved(tmp_path):
    """共现：compaction 事务 + fold 执行同窗口 → types 两条都在，primary=history_compaction。"""
    evs = [
        meta(1, "2026-09-14T10:00:00+00:00", 1, folded=0),
        usage(2, "2026-09-14T10:00:01+00:00", 1, 20000, 19000),
        {"seq": 3, "ts": "2026-09-14T10:00:05+00:00", "type": "history.compaction",
         "payload": {"compaction_epoch": 1, "pre_history_chars": 90000, "post_chars": 50000,
                     "trigger": "projected_history_over_compact_limit",
                     "compact_ratio": 0.85, "effective_budget_chars": 85519}},
        meta(4, "2026-09-14T10:00:06+00:00", 2, folded=5),  # fold 执行（0→5）
        usage(5, "2026-09-14T10:00:07+00:00", 2, 12000, 7000),
    ]
    frozen = make_frozen(tmp_path, evs)
    o = tmp_path / "o.jsonl"
    run("score", str(frozen), "-o", str(o))
    r2 = [r for r in load_records(o) if r.get("round") == 2][0]
    assert set(r2["boundary"]["types"]) == {"history_compaction", "working_set_fold"}
    assert r2["boundary"]["primary"] == "history_compaction"
    # v1：excess 只记 primary
    assert r2["attribution"]["boundary_excess_miss"] == (12000 - 7000) - (512 + 64)


# ── G4 Accounting Gate ─────────────────────────────────────────────────────
def test_g4_reconcile_identity_and_rollup(tmp_path):
    recs = _score_real(tmp_path)
    reqs = [r for r in recs if r["record_type"] == "request_attribution"]
    rollup = [r for r in recs if r["record_type"] == "boundary_rollup"][0]
    for r in reqs:
        a = r["attribution"]
        assert a["boundary_excess_miss"] >= 0
        assert a["observed_miss"] - a["expected_append_miss"] + a["clamped_negative_tokens"] == a["boundary_excess_miss"]
    t = rollup["totals"]
    assert t["observed_miss"] == sum(r["attribution"]["observed_miss"] for r in reqs)
    assert t["boundary_excess_miss"] == sum(r["attribution"]["boundary_excess_miss"] for r in reqs)
    assert sum(b["boundary_excess_miss_sum"] for b in rollup["by_boundary"]) == t["boundary_excess_miss"]
    assert (t["controllable_excess_miss"] + t["uncontrollable_excess_miss"]
            + t["partial_excess_miss"] + t["unknown_excess_miss"]) == t["boundary_excess_miss"]


def test_g4_negative_excess_never_silent_gain(tmp_path):
    """观测好于期望（append_only 常态）必须走 clamp，不得变负收益。"""
    recs = _score_real(tmp_path)
    reqs = [r for r in recs if r["record_type"] == "request_attribution"]
    clamped = [r for r in reqs if r["attribution"]["clamped_negative_tokens"] > 0]
    assert clamped, "真实会话应存在 clamp 样本"
    for r in clamped:
        assert r["attribution"]["boundary_excess_miss"] == 0


# ── G5 Controllability Gate ────────────────────────────────────────────────
def test_g5_eviction_never_controllable(tmp_path):
    recs = _score_real(tmp_path)
    reqs = [r for r in recs if r["record_type"] == "request_attribution"]
    ev = [r for r in reqs if "provider_eviction" in r["boundary"]["types"]]
    assert ev, "真实会话存在 eviction 样本"
    for r in ev:
        assert r["attribution"]["controllable"] == "no"
    rollup = [r for r in recs if r["record_type"] == "boundary_rollup"][0]
    ctl_ids = {"history_compaction", "working_set_fold"}
    recomputed = sum(
        r["attribution"]["boundary_excess_miss"]
        for r in reqs
        if r["boundary"]["primary"] in ctl_ids and "provider_eviction" not in r["boundary"]["types"]
    )
    assert rollup["totals"]["controllable_excess_miss"] == recomputed
    assert rollup["totals"]["partial_excess_miss"] == 7488
    assert rollup["totals"]["unknown_excess_miss"] == 0
    new_run_bucket = next(b for b in rollup["by_boundary"] if b["type"] == "new_run_cold_start")
    assert new_run_bucket["controllable"] == "mixed", (
        "同一 primary 同时含 partial 与 provider_eviction/no 时必须显式 mixed"
    )


# ── G6 Idempotence Gate ────────────────────────────────────────────────────
def test_g6_fixture_untouched_and_output_stable(tmp_path):
    before = dir_hash(REAL_FROZEN)
    o1, o2 = tmp_path / "1.jsonl", tmp_path / "2.jsonl"
    run("score", str(REAL_FROZEN), "-o", str(o1))
    run("golden", str(REAL_FROZEN), str(GOLDEN))
    run("score", str(REAL_FROZEN), "-o", str(o2))
    assert dir_hash(REAL_FROZEN) == before, "scorer 不得修改冻结目录"
    assert o1.read_bytes() == o2.read_bytes(), "重复执行不得产生 epoch/序号/分类漂移"


# ── G7 Golden Regression Gate ──────────────────────────────────────────────
def test_g7_golden_check_passes(tmp_path):
    run("golden", str(REAL_FROZEN), str(GOLDEN))


def test_g7_golden_drift_fails(tmp_path):
    bad = tmp_path / "bad.golden.jsonl"
    text = GOLDEN.read_text().splitlines()
    # 篡改一条记录的 primary
    for i, line in enumerate(text):
        r = json.loads(line)
        if r.get("boundary", {}).get("primary") == "append_only":
            text[i] = line.replace('"primary":"append_only"', '"primary":"unknown"')
            break
    bad.write_text("\n".join(text) + "\n")
    run("golden", str(REAL_FROZEN), str(bad), expect=1)


if __name__ == "__main__":
    import tempfile

    failures = 0
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
                print(f"PASS {fn.__name__}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
