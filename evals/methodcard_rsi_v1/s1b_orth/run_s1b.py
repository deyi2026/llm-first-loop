#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1b：gold vs 正交 filler（无关技能：Markdown 列表排序去重）阴性对照。

与 S1 的唯一差异是 filler 卡换成行为正交的无关技能卡：不含"先校验 / 暂停 / 请确认 /
给选项"的步骤，因此不会像旧 filler（CSV schema 校验）那样把谨慎程度一并抬高。
prompt（PROMPT_TMPL / build_prompt）、池、模型、回执夹具、PROMPT_VERSION 全部与 S1
逐字一致，由 import run_s1 保证。

本脚本不判分，只存 text；判分由 analyze_s1b.py 用 grade_v14 离线重算。
启动时（含 --dry-run）校验两卡 sha256、pool sha256、S0 基线 sha256 与
CALIBRATION-FREEZE-s1b.json 一致；不一致即 exit 2，不自动修复、不自动改冻结。
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # 不落 __pycache__

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "s0_p28"))
sys.path.insert(0, str(ROOT / "s1_gold_filler"))
import agent_harness as H  # noqa: E402
import run_s0 as S0  # noqa: E402
import run_s1 as R1  # noqa: E402  只复用 PROMPT_TMPL / build_prompt / 常量

POOL = ROOT / "s0_p28" / "pool_p28.jsonl"
S0_CALLS = ROOT / "s0_p28" / "results" / "calls.jsonl"
FREEZE = HERE / "CALIBRATION-FREEZE-s1b.json"
OUT = HERE / "results"
CALLS = OUT / "calls_s1b.jsonl"
CARD_FILES = {
    "gold_card": ROOT / "s1_gold_filler" / "cards" / "gold.md",
    "filler_orth_card": HERE / "cards" / "filler_orth.md",
}
ARMS = ("gold_card", "filler_orth_card")
REP = R1.REP
PROMPT_VERSION = R1.PROMPT_VERSION
TZ8 = R1.TZ8


def die(msg: str):
    print(f"[s1b-FAIL] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(2)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_freeze() -> dict:
    if not FREEZE.exists():
        die(f"CALIBRATION-FREEZE-s1b.json 缺失：{FREEZE}（拒绝运行）")
    try:
        return json.loads(FREEZE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"FREEZE 不是合法 JSON：{e}")


def expect_sha(fz: dict, dotted: str, path: Path, label: str) -> str:
    cur = fz
    for k in dotted.split("."):
        cur = (cur or {}).get(k) if isinstance(cur, dict) else None
    want = (cur or {}).get("sha256") if isinstance(cur, dict) else None
    if not want:
        die(f"FREEZE 缺少 {dotted}.sha256")
    if not path.is_file():
        die(f"{label} 文件缺失：{path}（冻结 sha256={want}）")
    got = sha256_file(path)
    if got != want:
        die(f"{label} sha256 不一致：实际 {got} != 冻结 {want}；请人工核对（不自动修复）")
    return got


def load_cards(fz: dict) -> tuple[dict, dict]:
    texts, shas = {}, {}
    for arm, path in CARD_FILES.items():
        key = arm[: -len("_card")]
        shas[arm] = expect_sha(fz, f"cards.{key}", path, f"卡 {arm}")
        texts[arm] = path.read_text(encoding="utf-8")
    return texts, shas


def load_pool(fz: dict) -> list[dict]:
    fp = fz.get("pool") or {}
    want_sha, want_n = fp.get("sha256"), fp.get("instances")
    if not POOL.is_file():
        die(f"pool 缺失：{POOL}")
    got = sha256_file(POOL)
    if want_sha and got != want_sha:
        die(f"pool sha256 不一致：{got} != 冻结 {want_sha}")
    rows = [json.loads(x) for x in POOL.read_text(encoding="utf-8").splitlines() if x.strip()]
    if want_n and len(rows) != want_n:
        die(f"pool 条数 {len(rows)} != 冻结 {want_n}")
    return rows


def append(row: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with H.LOCK:
        with CALLS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()


def done_keys() -> set[str]:
    if not CALLS.exists():
        return set()
    keys: set[str] = set()
    for line in CALLS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("ok") and row.get("key"):
            keys.add(row["key"])
    return keys


def job(j: tuple[dict, str], cards: dict, card_sha: dict) -> dict:
    inst, arm = j
    key = f"s1b|{arm}|{inst['instance_id']}|r{REP}"
    t0 = time.time()
    prompt = R1.build_prompt(inst, cards[arm])  # 与 S1 逐字一致
    try:
        r = S0.ask(prompt)
        row = {"key": key, "ok": True, "arm": arm, "rep": REP,
               "instance_id": inst["instance_id"], "cluster_id": inst["cluster_id"],
               "url_kind": inst["url_kind"], "session_id": inst["session_id"],
               "text": r["text"], "finish": r["finish"], "attempts": r["attempts"],
               "tokens": (r.get("usage") or {}).get("total_tokens"),
               "usage": r.get("usage") or {},
               "latency_s": round(time.time() - t0, 1), "model": H.MODEL,
               "card_sha256": card_sha[arm], "prompt_chars": len(prompt),
               "prompt_version": PROMPT_VERSION,
               "created_at": datetime.now(TZ8).isoformat(timespec="seconds")}
    except Exception as e:  # noqa: BLE001
        row = {"key": key, "ok": False, "arm": arm, "rep": REP,
               "instance_id": inst["instance_id"],
               "error": f"{type(e).__name__}: {e}"[:300],
               "latency_s": round(time.time() - t0, 1),
               "created_at": datetime.now(TZ8).isoformat(timespec="seconds")}
    append(row)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="S1b gold / filler_orth 两臂（不判分）")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    fz = load_freeze()
    cards, card_sha = load_cards(fz)
    pool = load_pool(fz)
    expect_sha(fz, "baseline.s0_calls", S0_CALLS, "S0 基线 calls")

    jobs = [(inst, arm) for inst in pool for arm in ARMS]
    if a.limit > 0:
        jobs = jobs[:a.limit]
    have = done_keys()
    pending = [j for j in jobs if f"s1b|{j[1]}|{j[0]['instance_id']}|r{REP}" not in have]

    conc = a.threads if a.threads and a.threads > 0 else int(H.ENV.get("HARNESS_CONCURRENCY", "2") or 2)
    print(f"[s1b] model={H.MODEL} pool={len(pool)} arms={list(ARMS)} rep={REP} "
          f"jobs={len(jobs)} pending={len(pending)} conc={conc}", flush=True)
    print(f"[s1b] freeze 校验通过：{FREEZE}", flush=True)
    for arm in ARMS:
        print(f"[s1b] {arm:<16} sha256={card_sha[arm]} chars={len(cards[arm])} （与 FREEZE 一致）",
              flush=True)
    print(f"[s1b] prompt 与 S1 同源：R1.PROMPT_TMPL chars={len(R1.PROMPT_TMPL)} "
          f"version={PROMPT_VERSION}", flush=True)

    if a.dry_run:
        if jobs:
            inst0, arm0 = jobs[0]
            print(f"[s1b] dry-run 样例（{arm0}/{inst0['instance_id']}，前 500 字符）：", flush=True)
            print(R1.build_prompt(inst0, cards[arm0])[:500], flush=True)
        return 0

    H.SEM = threading.Semaphore(conc)

    def run(j):
        return job(j, cards, card_sha)

    t0 = time.time()
    n = ok_n = 0
    with ThreadPoolExecutor(max_workers=conc) as ex:
        for r in ex.map(run, pending):
            n += 1
            ok_n += 1 if r.get("ok") else 0
            if r.get("ok"):
                tot = (r.get("usage") or {}).get("total_tokens")
                print(f"  [{n}/{len(pending)}] {r['key']:<34} chars={len(r['text'])} "
                      f"tok={tot} {r['latency_s']}s", flush=True)
            else:
                print(f"  [{n}/{len(pending)}] {r['key']:<34} ERR {r['error'][:110]}", flush=True)
            if n % 20 == 0:
                print(f"  ... elapsed {round(time.time() - t0, 1)}s", flush=True)
    print(f"[s1b] elapsed {round(time.time() - t0, 1)}s ok={ok_n} err={n - ok_n} -> {CALLS}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
