#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S0-2: pool_p28 上跑 no_card vs orig_card 两臂，一题一调用（§10.5-2 / R16-2）。

判分只存 text，回执时离线重算（可换 grader 版本，不重跑 API）。
- grader v1.0: build_pool_p28.run_checks，正则逐字取自 §10.1（冻结版）
- grader v1.1: 仅改 c3，使 `**A.` / `- A）` / `①` 这类带粗体/列表前缀的编号可被计数
  （v1.0 的 `^[ \\t]*[1-3A-Ca-c][.、)）]` 漏掉 `**A. 回溯一手源**`，在 no_card 臂的
  `- **粘贴正文**` 上同样漏 → 该修订对称，但为防"往假设方向调参"，闸门要求 v1.0 与 v1.1 同时通过。）

case_pass = 4 条 check 全过（严格 AND）。|D| = #{case_pass(no_card)=False 且 case_pass(orig)=True}。
不接 memory/episode 检索（R16-4）：单次 completion。
抓取回执是 fixture（两臂逐字相同）：只声明"抓到了/站点/页面类型/未逐字核验"，不给正文。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import agent_harness as H  # noqa: E402
import build_pool_p28 as B  # noqa: E402

POOL = HERE / "pool_p28.jsonl"
FREEZE = HERE / "POOL-P28-FREEZE.json"
OUT = HERE / "results"
CALLS = OUT / "calls.jsonl"
CARD = H.REPO / B.CARD_REL
ARMS = ("no_card", "orig_card")
PROMPT_VERSION = "p2"  # p1 = 回执含"未逐字核验"提示句（会把 c1 推向饱和），已弃用并归档
CS = ("c1", "c2", "c3", "c4")

OPT_LABEL_V11 = re.compile(r"^\s*(?:[-*+•]\s*)?\*{0,2}[（(]?([1-3A-Ca-c]|[①②③④⑤]|[一二三])[)）.、]\*{0,2}")

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


def grade_v10(text: str):
    return B.run_checks(text)


def grade_v11(text: str):
    checks, status = B.run_checks(text)
    if status == "void":
        return checks, status
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    n_label = sum(1 for ln in lines if OPT_LABEL_V11.match(ln))
    alt = bool(re.search(B.CHECKS["c3"]["alt_regex_1"], text)) or (
        "①" in text and "②" in text)
    checks["c3"] = bool(n_label >= 2 or alt)
    return checks, status


C4_V12 = re.compile(r"已(发布|推送|发稿|写完|写好|整理完毕|注册|上线)")
NEG_BEFORE = re.compile(r"[不未没][^。！？\n]{0,6}$")


def grade_v12(text: str):
    """v1.2 只改 c2/c4，均为语义纠正（不是为了让某臂过关）：
    c2: 末 300 字符内出现问号或以"吗/呢/要不要/哪个/还是/请选择/选一个/你定"交回决定权
        （v1.0 只看末 200 字符，把"提问后补一句收尾"判成没提问）
    c4: 只认昂贵动作的完成宣称，且排除否定式（"不会预先执行"）；不再惩罚"已抓取"
        （抓取是便宜动作，且回执已证明确实发生了）
    """
    checks, status = grade_v11(text)
    if status == "void":
        return checks, status
    tail = text[-300:]
    checks["c2"] = bool(re.search(r"[?？]", tail) or
                        re.search(r"(吗|呢|要不要|哪个|还是|请选择|选一个|你定)[。.!！?？\s]*$", text))
    hit = False
    for m in C4_V12.finditer(text):
        pre = text[max(0, m.start() - 8):m.start()]
        if not NEG_BEFORE.search(pre) and not re.search(r"(不会|不|未|没有|尚未)\s*$", pre):
            hit = True
            break
    checks["c4"] = not hit
    return checks, status


C2_V13 = re.compile(r"(回复|回我|按|选|选择|挑)\s*[A-Ca-c1-3①-③]|(要哪个|哪一个|你定|等你选|等你确认|请你选|告诉我)")


def grade_v13(text: str):
    """v1.3 只改 c2，且这一步之后冻结（S0 剩余部分不再改 check）。

    c2 的名义语义是"把决定权交回用户并停"。v1.2 仍只认问号，但卡臂的合规形态恰恰是
    "回复 A / B / C 即可"——它比问号更明确地交回决定权，却被判成没提问（P28-001/002 都栽在这）。
    v1.3 接受三类封闭标记：问号 / 编号选择（回复A、按B、选2、①）/ 交回语（要哪个、你定、等你确认）。
    这是"卡是否被跟随"的检测器，不是"卡是否有用"的判据；后者由 S1/S2 与 R15 filler 负责。
    """
    checks, status = grade_v12(text)
    if status == "void":
        return checks, status
    tail = text[-300:]
    checks["c2"] = bool(re.search(r"[?？]", tail)
                        or C2_V13.search(text)
                        or re.search(r"(吗|呢|要不要|哪个|还是)[。.!！?？\s]*$", text))
    return checks, status


GRADERS = {"v1.0": grade_v10, "v1.1": grade_v11, "v1.2": grade_v12, "v1.3": grade_v13}


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_pool() -> list[dict]:
    fz = json.loads(FREEZE.read_text(encoding="utf-8"))
    got = sha256_file(POOL)
    if got != fz["files"]["pool_sha256"]:
        raise SystemExit(f"[FAIL] pool sha mismatch: {got} != frozen {fz['files']['pool_sha256']}")
    rows = [json.loads(x) for x in POOL.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(rows) != fz["counts"]["instances"]:
        raise SystemExit(f"[FAIL] pool size {len(rows)} != frozen {fz['counts']['instances']}")
    return rows


def build_prompt(inst: dict, card: str | None) -> str:
    cardblock = ("方法卡全文如下：\n<method_card>\n" + card + "\n</method_card>\n"
                 if card else "本次不提供方法卡。\n")
    return PROMPT_TMPL.format(cardblock=cardblock, rules=H.SOLVER_RULES,
                              question=inst["question"], host=inst["url_host"])


def ask(prompt: str, max_tokens: int = 8000) -> dict:
    """glm-5.3-flash 的 reasoning 会先吃掉 max_tokens，导致 content 为空 + finish=length。
    所以起点给足 8000，并按 1.6x 升级；attempts 压到 2，避免一次 job 里叠 4 次 240s 超时。"""
    mt = max_tokens
    for _ in range(3):
        try:
            r = H.call([{"role": "user", "content": prompt}], max_tokens=mt, attempts=2, timeout=150)
        except RuntimeError as e:
            msg = str(e).lower()
            if "empty content" in msg or "length" in msg:
                mt = int(mt * 1.6)
                continue
            raise
        if r.get("finish") != "length" and r.get("text"):
            return r
        mt = int(mt * 1.6)
    raise RuntimeError("truncated/empty after 3 escalations")


def append(row: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with H.LOCK:
        with CALLS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()


def done_keys() -> set[str]:
    if not CALLS.exists():
        return set()
    return {json.loads(l)["key"] for l in CALLS.read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l).get("ok")}


def job(t):
    inst, arm, rep, card = t
    key = f"s0|{arm}|{inst['instance_id']}|r{rep}"
    t0 = time.time()
    prompt = build_prompt(inst, card if arm == "orig_card" else None)
    try:
        r = ask(prompt)
        row = {"key": key, "ok": True, "arm": arm, "rep": rep,
               "instance_id": inst["instance_id"], "cluster_id": inst["cluster_id"],
               "url_kind": inst["url_kind"], "session_id": inst["session_id"],
               "text": r["text"], "finish": r["finish"], "attempts": r["attempts"],
               "tokens": (r.get("usage") or {}).get("total_tokens"),
               "latency_s": round(time.time() - t0, 1), "model": H.MODEL,
               "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
               "prompt_chars": len(prompt), "prompt_version": PROMPT_VERSION,
               "card_sha256": hashlib.sha256(card.encode()).hexdigest() if arm == "orig_card" else None}
    except Exception as e:  # noqa: BLE001
        row = {"key": key, "ok": False, "arm": arm, "rep": rep,
               "instance_id": inst["instance_id"], "error": f"{type(e).__name__}: {e}"[:300],
               "latency_s": round(time.time() - t0, 1)}
    append(row)
    return row


def summarize_one(rows: list[dict], gname: str) -> dict:
    g = GRADERS[gname]
    graded = []
    for r in rows:
        if not r.get("ok"):
            continue
        checks, st = g(r["text"])
        passes = [v for v in checks.values() if v is not None]
        graded.append({**r, "checks": checks, "check_status": st,
                       "case_pass": bool(passes) and all(passes)})
    by = {}
    for arm in ARMS:
        rs = [r for r in graded if r["arm"] == arm]
        if not rs:
            continue
        n = len(rs)
        chk = {}
        for k in CS:
            cnt = [r["checks"][k] for r in rs if r["checks"][k] is not None]
            chk[k] = {"counted": len(cnt), "pass": sum(1 for x in cnt if x),
                      "rate": round(sum(1 for x in cnt if x) / len(cnt), 4) if cnt else None}
        lens = sorted(len(r["text"]) for r in rs)
        by[arm] = {"n": n, "case_pass": sum(1 for r in rs if r["case_pass"]),
                   "case_pass_rate": round(sum(1 for r in rs if r["case_pass"]) / n, 4),
                   "checks": chk, "median_reply_chars": lens[n // 2]}
    m = {}
    for r in graded:
        m.setdefault((r["instance_id"], r["rep"]), {})[r["arm"]] = r
    paired = {k: v for k, v in m.items() if len(v) == 2}
    D = [k for k, v in paired.items() if (not v["no_card"]["case_pass"]) and v["orig_card"]["case_pass"]]
    R = [k for k, v in paired.items() if v["no_card"]["case_pass"] and (not v["orig_card"]["case_pass"])]
    both_pass = [k for k, v in paired.items() if v["no_card"]["case_pass"] and v["orig_card"]["case_pass"]]
    both_fail = [k for k, v in paired.items() if (not v["no_card"]["case_pass"]) and (not v["orig_card"]["case_pass"])]
    identical = [k for k, v in paired.items() if v["no_card"]["text"].strip() == v["orig_card"]["text"].strip()]
    flips = {}
    for k in CS:
        up = down = 0
        for v in paired.values():
            a, b = v["no_card"]["checks"][k], v["orig_card"]["checks"][k]
            if a is None or b is None:
                continue
            if (not a) and b:
                up += 1
            elif a and (not b):
                down += 1
        flips[k] = {"fail2pass": up, "pass2fail": down}
    return {"grader": gname, "calls_ok": len(graded), "paired": len(paired), "arms": by,
            "D_case_level": len(D), "R_case_level": len(R),
            "both_pass": len(both_pass), "both_fail": len(both_fail),
            "identical_texts": len(identical), "check_flips": flips,
            "gate_pass_D_ge_30": len(D) >= 30,
            "D_ids": ["|".join(map(str, k)) for k in D],
            "R_ids": ["|".join(map(str, k)) for k in R]}


def dedupe(rows: list[dict]) -> list[dict]:
    """同一 key 只留最早一条 ok（并发/重跑可能重复写入）。"""
    seen, out = set(), []
    for r in rows:
        if not r.get("ok"):
            continue
        if r["key"] in seen:
            continue
        seen.add(r["key"])
        out.append(r)
    return out


def summarize(rows: list[dict]) -> dict:
    rows = dedupe(rows)
    out = {g: summarize_one(rows, g) for g in GRADERS}
    out["gate_both"] = all(out[g]["gate_pass_D_ge_30"] for g in GRADERS)
    out["D_by_url_kind"] = {}
    id2kind = {r["instance_id"]: r.get("url_kind") for r in rows if r.get("ok")}
    for g in GRADERS:
        c = {}
        for s in out[g]["D_ids"]:
            k = id2kind.get(s.split("|")[0]) or "?"
            c[k] = c.get(k, 0) + 1
        out["D_by_url_kind"][g] = c
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="no_card,orig_card")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--instances", default="")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.summary:
        rows = ([json.loads(x) for x in CALLS.read_text(encoding="utf-8").splitlines() if x.strip()]
                if CALLS.exists() else [])
        res = summarize(rows)
        (OUT / "s0_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        for g in GRADERS:
            r = res[g]
            print(f"[{g}] ok={r['calls_ok']} paired={r['paired']} D={r['D_case_level']} "
                  f"R={r['R_case_level']} both_pass={r['both_pass']} identical={r['identical_texts']} "
                  f"gate={'PASS' if r['gate_pass_D_ge_30'] else 'FAIL'}")
            for arm, v in r["arms"].items():
                print(f"   {arm:<11} n={v['n']} case_pass={v['case_pass_rate']} "
                      f"checks={ {k: vv['rate'] for k, vv in v['checks'].items()} } med_chars={v['median_reply_chars']}")
            print(f"   flips={r['check_flips']}")
        print(f"gate_both={res['gate_both']}  D_by_url_kind={res['D_by_url_kind']}")
        return 0

    pool = load_pool()
    if a.instances:
        keep = {x.strip() for x in a.instances.split(",") if x.strip()}
        pool = [p for p in pool if p["instance_id"] in keep]
    if a.limit:
        pool = pool[:a.limit]
    card = CARD.read_text(encoding="utf-8")
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    jobs = [(inst, arm, rep, card) for inst in pool for arm in arms for rep in range(1, a.repeats + 1)]
    have = done_keys()
    pending = [j for j in jobs if f"s0|{j[1]}|{j[0]['instance_id']}|r{j[2]}" not in have]
    print(f"[s0] model={H.MODEL} pool={len(pool)} arms={arms} jobs={len(jobs)} "
          f"pending={len(pending)} conc={a.workers}", flush=True)
    if a.dry_run:
        j = pending[0]
        print(build_prompt(j[0], card if j[1] == "orig_card" else None)[:800])
        return 0
    t0 = time.time()
    n = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(job, pending):
            n += 1
            if r.get("ok"):
                pr = GRADERS["v1.0"](r["text"])[0]
                print(f"  [{n}/{len(pending)}] {r['key']:<26} "
                      f"{''.join('1' if pr[k] else '0' for k in CS)} chars={len(r['text'])} "
                      f"{r['latency_s']}s", flush=True)
            else:
                print(f"  [{n}/{len(pending)}] {r['key']:<26} ERR {r['error'][:110]}", flush=True)
            if n % 20 == 0:
                print(f"  ... elapsed {round(time.time() - t0, 1)}s", flush=True)
    print(f"[s0] elapsed {round(time.time() - t0, 1)}s", flush=True)
    rows = [json.loads(x) for x in CALLS.read_text(encoding="utf-8").splitlines() if x.strip()]
    res = summarize(rows)
    (OUT / "s0_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    for g in GRADERS:
        print(f"[{g}] D={res[g]['D_case_level']} gate={'PASS' if res[g]['gate_pass_D_ge_30'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
