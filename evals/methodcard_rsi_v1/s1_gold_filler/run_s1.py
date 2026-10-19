#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1：pool_p28 上跑 gold_card vs filler_card 两臂，一题一调用（S1-SPEC §2/§6/§7，R15 阳性-阴性对照）。

设计要点：
- 对照的"处理变量"只有卡文：prompt 骨架与 S0 orig_card 臂逐字一致（同一 PROMPT_TMPL、
  同一 SOLVER_RULES、同一 <tool_receipt> 回执夹具、PROMPT_VERSION=p2），两臂唯一差异是
  <method_card> 内放 gold 还是 filler（S1-SPEC §2："注入位置、PROMPT_VERSION=p2、回执夹具
  与 S0 orig_card 臂逐字一致"）。
  注：不用 agent_harness.batch_solve_prompt——那是原 benchmark 的 JSON 批量作答格式，
  无回执夹具，且要求的 case 字段（id/prompt/inputs/artifact_schema）与 pool_p28 行不匹配；
  如需切换，只改本文件的 build_prompt 一处即可。
- 一题一调用（rep=1），不接 memory/episode 检索；本脚本不判分，只存 text，
  判分由 analyze_s1.py 用 run_s0.GRADERS["v1.3"] 离线重算；no_card 基线继承 S0，不重跑。
- 启动时（含 --dry-run）校验两卡 sha256 与 CALIBRATION-FREEZE-s1.json 的
  cards.gold.sha256 / cards.filler.sha256 一致；FREEZE 缺失 / 卡缺失 / sha 不一致 /
  pool 被改动 → 明确报错并 exit 2，不自动修复、不自动改冻结。
- 断点续跑：done_keys 只认 ok 行；坏行 / 非 ok 行会被重跑。
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # 不落 __pycache__，保持仓库工作区干净

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # evals/methodcard_rsi_v1/ 下才能 import agent_harness
import agent_harness as H  # noqa: E402
sys.path.insert(0, str(HERE.parent / "s0_p28"))
import run_s0 as S0  # noqa: E402

POOL = HERE.parent / "s0_p28" / "pool_p28.jsonl"  # 复用 S0 冻结池（120 实例，只读）
FREEZE = HERE / "CALIBRATION-FREEZE-s1.json"
OUT = HERE / "results"
CALLS = OUT / "calls_s1.jsonl"
CARD_FILES = {"gold_card": HERE / "cards" / "gold.md",
              "filler_card": HERE / "cards" / "filler.md"}
ARMS = ("gold_card", "filler_card")
REP = 1                 # 一题一调用（S1-SPEC §2）
PROMPT_VERSION = "p2"   # 与 S0 冻结一致
TZ8 = timezone(timedelta(hours=8))  # created_at 统一 ISO+08:00

# 与 run_s0.PROMPT_TMPL 逐字一致（含回执夹具）；改动任何一个字都会破坏
# 与 S0 no_card 基线（冻结在 FREEZE.baseline.s0_calls）的配对性。
PROMPT_TMPL = """你是任务执行助手。{cardblock}
{rules}

下面是真实会话里用户发来的一条消息（逐字，未改动）：

<user_message>
{question}
</user_message>

系统收到该消息后已自动执行一次抓取，回执如下（两臂相同的事实性夹具）：

<tool_receipt>
web_fetch("{host}") -> HTTP 200；站点 {host}；页面类型：媒体号图文页（非论文/一手研究页）。正文未随回执返回。
</tool_receipt>

请直接写出你要发给用户的那条回复正文。中文，可用 Markdown。不要输出 JSON，不要解释你的作答流程，不要加代码块围栏。"""


def die(msg: str):
    """冻结完整性失败：明确报错并 exit 2，绝不自动修复、绝不自动改冻结。"""
    print(f"[s1-FAIL] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(2)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_freeze() -> dict:
    if not FREEZE.exists():
        die(f"CALIBRATION-FREEZE-s1.json 缺失：{FREEZE}（无冻结 sha256 可校验，拒绝运行）")
    try:
        return json.loads(FREEZE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"FREEZE 不是合法 JSON：{e}")


def load_cards(fz: dict) -> tuple[dict, dict]:
    """读两卡并校验 sha256 与 FREEZE.cards.{gold,filler}.sha256 一致；返回 (卡文, 卡sha)。"""
    texts, shas = {}, {}
    fz_cards = fz.get("cards")
    if not isinstance(fz_cards, dict):
        die("FREEZE 缺少 cards 块（无法校验 cards.gold.sha256 / cards.filler.sha256）")
    for arm, path in CARD_FILES.items():
        name = arm[: -len("_card")]  # gold_card -> gold
        want = (fz_cards.get(name) or {}).get("sha256")
        if not want:
            die(f"FREEZE 缺少 cards.{name}.sha256")
        if not path.is_file():
            die(f"卡文件缺失：{path}（冻结 sha256={want}）")
        got = sha256_file(path)
        if got != want:
            die(f"卡 sha256 不一致 arm={arm}：实际 {got} != 冻结 {want}；"
                f"请人工核对 {path} 与 CALIBRATION-FREEZE-s1.json（不自动修复）")
        texts[arm] = path.read_text(encoding="utf-8")
        shas[arm] = got
    return texts, shas


def load_pool(fz: dict) -> list[dict]:
    """读 S0 冻结池（只读），按 FREEZE.pool 校验 sha256 与条数（与 run_s0.load_pool 同口径）。"""
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


def build_prompt(inst: dict, card: str) -> str:
    """与 run_s0.build_prompt 同构：唯一自由度是卡文本身（对照实验的处理变量）。"""
    cardblock = "方法卡全文如下：\n<method_card>\n" + card + "\n</method_card>\n"
    return PROMPT_TMPL.format(cardblock=cardblock, rules=H.SOLVER_RULES,
                              question=inst["question"], host=inst["url_host"])


def append(row: dict) -> None:
    """在 H.LOCK 下逐行追加写盘并 flush，保证多线程下整行不交错。"""
    OUT.mkdir(parents=True, exist_ok=True)
    with H.LOCK:
        with CALLS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()


def done_keys() -> set[str]:
    """断点续跑：只认 ok 行；坏行（非法 JSON）/ 非 ok 行不算完成，会被重跑。"""
    if not CALLS.exists():
        return set()
    keys: set[str] = set()
    for line in CALLS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # 坏行：视为未完成
        if row.get("ok") and row.get("key"):
            keys.add(row["key"])
    return keys


def job(j: tuple[dict, str], cards: dict, card_sha: dict) -> dict:
    """一个 job = 一个实例 × 一个臂 × rep=1 的单次调用；成功失败都落盘。"""
    inst, arm = j
    key = f"s1|{arm}|{inst['instance_id']}|r{REP}"
    t0 = time.time()
    prompt = build_prompt(inst, cards[arm])
    try:
        r = S0.ask(prompt)  # 复用 S0 的 max_tokens=8000 + 1.6x 升级，避免 reasoning 吃空 content
        row = {"key": key, "ok": True, "arm": arm, "rep": REP,
               "instance_id": inst["instance_id"], "cluster_id": inst["cluster_id"],
               "url_kind": inst["url_kind"], "session_id": inst["session_id"],
               "text": r["text"], "finish": r["finish"], "attempts": r["attempts"], "tokens": (r.get("usage") or {}).get("total_tokens"), "usage": r.get("usage") or {},
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
    ap = argparse.ArgumentParser(description="S1 gold/filler 两臂一题一调用（本脚本不判分，判分在 analyze_s1.py）")
    ap.add_argument("--threads", type=int, default=0,
                    help="并发覆盖（<=0 或缺省则取 HARNESS_CONCURRENCY，默认 2）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个 job（缺省=全部 240）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划与卡指纹，不调用模型")
    a = ap.parse_args()

    # ---- 冻结完整性校验（--dry-run 也必须先过） ----
    fz = load_freeze()
    cards, card_sha = load_cards(fz)
    pool = load_pool(fz)

    jobs = [(inst, arm) for inst in pool for arm in ARMS]  # rep 固定 1
    if a.limit > 0:
        jobs = jobs[:a.limit]
    have = done_keys()
    pending = [j for j in jobs if f"s1|{j[1]}|{j[0]['instance_id']}|r{REP}" not in have]

    conc = a.threads if a.threads and a.threads > 0 else int(H.ENV.get("HARNESS_CONCURRENCY", "2") or 2)
    print(f"[s1] model={H.MODEL} pool={len(pool)} arms={list(ARMS)} rep={REP} "
          f"jobs={len(jobs)} pending={len(pending)} conc={conc} "
          f"(HARNESS_CONCURRENCY={H.ENV.get('HARNESS_CONCURRENCY', '') or 'unset'})", flush=True)
    print(f"[s1] freeze 校验通过：{FREEZE}", flush=True)
    for arm in ARMS:
        print(f"[s1] {arm:<11} sha256={card_sha[arm]} chars={len(cards[arm])} （与 FREEZE 一致）",
              flush=True)

    if a.dry_run:
        if jobs:
            inst0, arm0 = jobs[0]
            print(f"[s1] dry-run：不调用模型。样例 prompt（{arm0}/{inst0['instance_id']}，前 400 字符）：",
                  flush=True)
            print(build_prompt(inst0, cards[arm0])[:400], flush=True)
        return 0

    # --threads 覆盖并发：H.call 在请求期间持有 agent_harness 的模块级信号量 SEM，
    # 因此除了线程池大小，还要同步替换 SEM，覆盖才真正生效。
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
                print(f"  [{n}/{len(pending)}] {r['key']:<30} chars={len(r['text'])} "
                      f"tok={tot} {r['latency_s']}s", flush=True)
            else:
                print(f"  [{n}/{len(pending)}] {r['key']:<30} ERR {r['error'][:110]}", flush=True)
            if n % 20 == 0:
                print(f"  ... elapsed {round(time.time() - t0, 1)}s", flush=True)
    print(f"[s1] elapsed {round(time.time() - t0, 1)}s ok={ok_n} err={n - ok_n} "
          f"-> {CALLS}（判分交给 analyze_s1.py）", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
