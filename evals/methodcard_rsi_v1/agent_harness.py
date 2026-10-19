#!/usr/bin/env python3
"""v2（agent 执行）跑批器：方法卡「变异器+受限应用」vs「自由改写」。

评分一律走 grade_holdout.check_one（纯机械，不改判分器、不改题）。
本文件只负责：把同一模型的执行器放进两臂 + 盲评解题 + 记录 token/违约。

为适配 API 并发/速率限制，解题按「一张卡 × 该 family 4 题」**一次调用**取回
（PREREG-b 偏离 #7，先于主跑登记）。

子命令
  manipcheck   M0 仪器闸门：同一批题给/不给原卡
  run          rewrite + solve
  report       汇总成 D1–D4 可裁决的 report.json
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import grade_holdout as G  # noqa: E402

SEED = 20261019
FAMILY_MAP = {
    "F1_effectiveness": "A_effectiveness",
    "F2_completion": "B_completion_gate",
    "F3_dedupe": "E_dedupe",
    "F4_edit_verify": "D_patch_verify",
}
PREREG_JSONL = HERE / "prereg_v1_cards.jsonl"
EXCLUDED = {"P21": "mutator REFUSED：正文出现在第一个 ## 段之前（v1 §6(a) 预授权排除）"}
OUT = HERE / "results_v2"
ARMS = ("mutator", "human_equivalent")


def load_env() -> dict:
    env = {}
    for line in (REPO / ".env").read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k] = v.split("#")[0].strip().strip('"').strip("'")
    return env


ENV = load_env()
BASE = ENV["LLM_BASE_URL"].rstrip("/")
KEY = ENV["GLM_API_KEY"]
MODEL = ENV["LLM_MODEL"].split("/")[-1]
SEM = threading.Semaphore(int(ENV.get("HARNESS_CONCURRENCY", "2") or 2))
LOCK = threading.Lock()


def call(messages: list[dict], max_tokens: int = 3000, attempts: int = 5,
         timeout: int = 120) -> dict:
    body = json.dumps({"model": MODEL, "messages": messages,
                       "temperature": 0, "max_tokens": max_tokens}).encode()
    last = ""
    for i in range(attempts):
        try:
            with SEM:
                req = urllib.request.Request(
                    BASE + "/chat/completions", data=body,
                    headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.load(r)
            ch = data["choices"][0]
            txt = (ch["message"].get("content") or "").strip()
            if not txt and ch.get("finish_reason") == "length":
                last = "empty content (max_tokens exhausted by reasoning)"
                time.sleep(2)
                continue
            return {"text": txt, "finish": ch.get("finish_reason"),
                    "usage": data.get("usage", {}), "attempts": i + 1}
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.read()[:160].decode(errors='replace')}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(min(3 * (i + 1), 30) + random.random())
                continue
            raise RuntimeError(last)
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(min(3 * (i + 1), 30))
    raise RuntimeError(f"call failed after {attempts}: {last}")


# ---------------- prompts ----------------

def render_inputs(case: dict) -> str:
    parts = []
    for inp in case["inputs"]:
        lc = inp.get("line_count")
        head = f"#### {inp['name']}" + (f"（共 {lc} 行）" if lc else "")
        parts.append(head + "\n" + inp["text"])
    return "\n\n".join(parts)


SOLVER_RULES = ("规则：先按方法卡的 Trigger / Discriminator / Short path 判断；"
                "方法卡未覆盖或与本例无关的部分，用你自己的判断。")


def batch_solve_prompt(cases: list[dict], card: str | None) -> str:
    cardblock = ("方法卡全文如下：\n<method_card>\n" + card + "\n</method_card>\n"
                 if card else "本次不提供方法卡。\n")
    blocks = []
    for c in cases:
        blocks.append(f"### 题目 {c['id']}\n题目：{c['prompt']}\n\n输入资料：\n{render_inputs(c)}\n\n"
                      f"该题输出 JSON 的字段与含义：{json.dumps(c['artifact_schema'], ensure_ascii=False)}")
    ids = ", ".join(f'"{c["id"]}"' for c in cases)
    return f"""你是方法卡执行器。{cardblock}
{SOLVER_RULES}

下面有 {len(cases)} 道题，各自独立作答，互不影响。

{chr(10).join(blocks)}

输出要求：只输出一个 JSON 对象，键为 {ids}，每个值是该题要求的 JSON 对象。
不要输出解释，不要加代码块围栏。"""


def arm_a_prompt(original: str, defects: list, rationale: str, patch: str) -> str:
    return f"""下面是一张方法卡原文，以及一个确定性工具对该卡给出的缺陷清单/补丁/理由。该工具只做机械修复，不做创作。

<original>
{original}
</original>

<tool_report>
缺陷清单：
{json.dumps(defects, ensure_ascii=False, indent=1)}

理由：
{rationale}

补丁：
{patch}
</tool_report>

任务：产出修改后的完整卡片。
硬约束：
1. 只执行补丁要求的编辑；TODO 占位必须替换为具体内容。
2. 补丁未触及的行一律逐字保留（含 frontmatter）。
3. 不得新增方法步骤、不得新增证据、不得虚构事实。
只输出卡片全文，不要代码块围栏，不要任何解释。"""


def arm_b_prompt(original: str) -> str:
    return f"""下面是一张方法卡原文。

<original>
{original}
</original>

任务：在保持 frontmatter 不变、不虚构证据的前提下，改进这张卡的可执行性：
- Trigger 更可判别（何时该用 / 不该用）
- Short path 更具体（可照着做完）
- Stop conditions 与 Verification 条目相互对应且可核验

硬约束：不得虚构证据、不得改动 frontmatter、保持原有章节结构。
只输出卡片全文，不要代码块围栏，不要任何解释。"""


# ---------------- helpers ----------------

def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def append_jsonl(path: Path, row: dict) -> None:
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_calls(path: Path) -> dict:
    done = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("ok"):
                    done[r["key"]] = r
    return done


def strip_fence(txt: str) -> str:
    t = txt.strip()
    m = re.match(r"^```[a-zA-Z]*\n(.*?)\n```$", t, re.S)
    return m.group(1).strip() if m else t


def parse_json_loose(txt: str) -> dict:
    t = strip_fence(txt)
    i = t.find("{")
    if i < 0:
        raise ValueError("no '{' in output")
    obj, _ = json.JSONDecoder().raw_decode(t[i:])
    if not isinstance(obj, dict):
        raise ValueError("top-level not object")
    return obj


def run_mutator(card_path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([sys.executable, str(REPO / "scripts/method_mutator.py"),
                        "--card", str(card_path), "--out", str(out_dir),
                        "--allow-todo", "--json"], capture_output=True, text=True)
    if p.returncode != 0:
        return {"refused": True, "rc": p.returncode, "stderr": (p.stderr or p.stdout)[:400]}
    try:
        j = json.loads(p.stdout)
    except Exception:  # noqa: BLE001
        return {"refused": True, "rc": p.returncode, "stderr": p.stdout[:400]}
    j["refused"] = False
    hits = sorted(out_dir.glob("*/*/METHOD.md"))
    j["dir"] = str(hits[0].parent) if hits else None
    return j


def norm_lines(t: str) -> list[str]:
    return [ln.rstrip() for ln in t.replace("\r\n", "\n").split("\n")]


def arm_a_violations(candidate: str, revised: str) -> list[dict]:
    a, b = norm_lines(candidate), norm_lines(revised)
    sm = difflib.SequenceMatcher(None, a, b)
    bad = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        chunk = a[i1:i2]
        if any("TODO" in ln.upper() for ln in chunk):
            continue
        bad.append({"tag": tag, "candidate": chunk[:3], "revised": b[j1:j2][:3]})
    return bad


def frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""


def pairs() -> list[dict]:
    rows = [json.loads(l) for l in PREREG_JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if r["family"] in FAMILY_MAP and r["pair_id"] not in EXCLUDED]


def pick_pairs(per_family: int | None = None) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for p in pairs():
        buckets.setdefault(p["family"], []).append(p)
    out = []
    for fam in FAMILY_MAP:
        take = buckets.get(fam, [])
        out.extend(take if per_family is None else take[:per_family])
    return out


def families_cases() -> dict[str, list[dict]]:
    cases, _ = G.load_cases()
    byfam: dict[str, list[dict]] = {}
    for c in cases:
        byfam.setdefault(c["family"], []).append(c)
    return byfam


# ---------------- phases ----------------

def cmd_manipcheck(args) -> int:
    byfam = families_cases()
    picked = pick_pairs(args.per_family)
    calls_path = OUT / "manipcheck" / "calls.jsonl"
    done = load_calls(calls_path)
    jobs = []
    for p in picked:
        fam = FAMILY_MAP[p["family"]]
        card = Path(p["path"]).read_text(encoding="utf-8")
        for cond, ctext in (("no_card", None), ("orig_card", card)):
            key = f"mc|{p['pair_id']}|{cond}"
            if key in done:
                continue
            jobs.append((key, p, cond, byfam[fam], ctext))
    print(f"[manipcheck] pairs={len(picked)} jobs={len(jobs)} model={MODEL} conc={SEM._value}")

    def work(j):
        key, p, cond, cases, ctext = j
        t0 = time.time()
        try:
            r = call([{"role": "user", "content": batch_solve_prompt(cases, ctext)}], max_tokens=4000)
            row = {"key": key, "phase": "manipcheck", "pair_id": p["pair_id"], "family": p["family"],
                   "cond": cond, "ok": True, "text": r["text"],
                   "tokens": r["usage"].get("total_tokens"), "finish": r["finish"],
                   "attempts": r["attempts"], "latency_s": round(time.time() - t0, 1),
                   "model": MODEL, "case_ids": [c["id"] for c in cases]}
        except Exception as e:  # noqa: BLE001
            row = {"key": key, "phase": "manipcheck", "pair_id": p["pair_id"],
                   "cond": cond, "ok": False, "error": str(e)[:300]}
        append_jsonl(calls_path, row)
        return row
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(work, jobs):
            print("  ", r["key"], "OK" if r["ok"] else "ERR " + r.get("error", "")[:80])
    return 0


def cmd_run(args) -> int:
    byfam = families_cases()
    picked = pick_pairs(args.per_family)
    out = OUT / "run"
    calls_path = out / "calls.jsonl"
    done = load_calls(calls_path)

    # --- rewrite ---
    rw_jobs = []
    for p in picked:
        original = Path(p["path"]).read_text(encoding="utf-8")
        bdir = OUT / "mutator" / p["pair_id"]
        mut = run_mutator(Path(p["path"]), bdir)
        keyA = f"rw|{p['pair_id']}|mutator"
        keyB = f"rw|{p['pair_id']}|human_equivalent"
        if mut.get("refused"):
            append_jsonl(calls_path, {"key": keyA, "phase": "rewrite", "pair_id": p["pair_id"],
                                      "ok": False,
                                      "error": "mutator refused: " + str(mut.get("stderr"))[:200]})
            continue
        defects = mut.get("defects") or []
        real = Path(mut["dir"]) if mut.get("dir") else None
        if not defects:
            # 0 缺陷 → 变异器不动卡；A 臂 = 原文（确定性，不消耗 LLM 调用）
            if keyA not in done:
                cdir = out / "cards" / p["pair_id"]
                cdir.mkdir(parents=True, exist_ok=True)
                (cdir / "mutator.md").write_text(original, encoding="utf-8")
                row = {"key": keyA, "phase": "rewrite", "pair_id": p["pair_id"],
                       "family": p["family"], "arm": "mutator", "ok": True, "text": original,
                       "tokens": 0, "finish": "no_change", "attempts": 0, "latency_s": 0.0,
                       "model": MODEL, "orig_sha": sha(original), "cand_sha": sha(original),
                       "violations": [], "frontmatter_changed": False,
                       "chars": len(original), "no_change": True}
                append_jsonl(calls_path, row)
                done[keyA] = row
        elif real is None:
            append_jsonl(calls_path, {"key": keyA, "phase": "rewrite", "pair_id": p["pair_id"],
                                      "ok": False, "error": "mutator output missing"})
        elif keyA not in done:
            rw_jobs.append((keyA, p, "mutator",
                            arm_a_prompt(original, defects,
                                         (real / "RATIONALE.md").read_text(encoding="utf-8"),
                                         (real / "PATCH.diff").read_text(encoding="utf-8")),
                            original, (real / "METHOD.md").read_text(encoding="utf-8")))
        if keyB not in done:
            rw_jobs.append((keyB, p, "human_equivalent", arm_b_prompt(original), original, ""))
    print(f"[run] rewrite jobs={len(rw_jobs)}")

    def rw(j):
        key, p, arm, prompt, original, cand = j
        t0 = time.time()
        try:
            r = call([{"role": "user", "content": prompt}], max_tokens=8000)
            if r.get("finish") == "length":
                raise RuntimeError("rewrite truncated (finish=length)")
            rev = strip_fence(r["text"])
            row = {"key": key, "phase": "rewrite", "pair_id": p["pair_id"], "family": p["family"],
                   "arm": arm, "ok": True, "text": rev, "tokens": r["usage"].get("total_tokens"),
                   "finish": r["finish"], "attempts": r["attempts"],
                   "latency_s": round(time.time() - t0, 1), "model": MODEL,
                   "orig_sha": sha(original), "cand_sha": sha(cand),
                   "violations": arm_a_violations(cand, rev) if arm == "mutator" else [],
                   "frontmatter_changed": frontmatter(original) != frontmatter(rev),
                   "chars": len(rev)}
            (out / "cards" / p["pair_id"]).mkdir(parents=True, exist_ok=True)
            (out / "cards" / p["pair_id"] / f"{arm}.md").write_text(rev, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            row = {"key": key, "phase": "rewrite", "pair_id": p["pair_id"], "arm": arm,
                   "ok": False, "error": str(e)[:300]}
        append_jsonl(calls_path, row)
        return row
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(rw, rw_jobs):
            print("  ", r["key"], "OK" if r["ok"] else "ERR " + r.get("error", "")[:80])

    # --- solve (batch per card) ---
    done = load_calls(calls_path)
    sv_jobs = []
    for p in picked:
        fam = FAMILY_MAP[p["family"]]
        for arm in ARMS:
            cardfile = out / "cards" / p["pair_id"] / f"{arm}.md"
            key = f"sv|{p['pair_id']}|{arm}"
            if key in done or not cardfile.exists():
                continue
            sv_jobs.append((key, p, arm, byfam[fam], cardfile.read_text(encoding="utf-8")))
    print(f"[run] solve jobs={len(sv_jobs)}")

    def sv(j):
        key, p, arm, cases, card = j
        t0 = time.time()
        try:
            r = call([{"role": "user", "content": batch_solve_prompt(cases, card)}], max_tokens=6000)
            if r.get("finish") == "length":
                raise RuntimeError("solve truncated (finish=length)")
            row = {"key": key, "phase": "solve", "pair_id": p["pair_id"], "family": p["family"],
                   "arm": arm, "ok": True, "text": r["text"], "tokens": r["usage"].get("total_tokens"),
                   "finish": r["finish"], "attempts": r["attempts"],
                   "latency_s": round(time.time() - t0, 1), "model": MODEL,
                   "case_ids": [c["id"] for c in cases], "card_sha": sha(card)}
        except Exception as e:  # noqa: BLE001
            row = {"key": key, "phase": "solve", "pair_id": p["pair_id"], "arm": arm,
                   "ok": False, "error": str(e)[:300]}
        append_jsonl(calls_path, row)
        return row
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(sv, sv_jobs):
            print("  ", r["key"], "OK" if r["ok"] else "ERR " + r.get("error", "")[:80])
    return 0


def _grade_batch(call_row: dict, cases_by_id: dict) -> dict:
    try:
        obj = parse_json_loose(call_row["text"])
    except Exception as e:  # noqa: BLE001
        return {"parse_error": str(e)[:200], "per_case": {}, "checks_pass": 0,
                "checks_total": 0, "q_pass": 0, "q_total": 0}
    per_case, cp, ct, qp, qt = {}, 0, 0, 0, 0
    for cid in call_row.get("case_ids", []):
        case = cases_by_id[cid]
        art = obj.get(cid)
        if not isinstance(art, dict):
            chk = [{"pass": False, "detail": "missing key"}]
            per_case[cid] = {"artifact": art, "checks": chk, "pass": False}
        else:
            chk = G.check_one(case, art)
            per_case[cid] = {"artifact": art, "checks": chk,
                             "pass": all(c["pass"] for c in chk)}
        cp += sum(1 for c in chk if c["pass"])
        ct += len(chk)
        qp += 1 if per_case[cid]["pass"] else 0
        qt += 1
    return {"per_case": per_case, "checks_pass": cp, "checks_total": ct,
            "q_pass": qp, "q_total": qt}


def cmd_report(args) -> int:
    cases, hs = G.load_cases()
    byid = {c["id"]: c for c in cases}
    out = OUT / "run"
    rows = load_calls(out / "calls.jsonl")
    rw = {k: v for k, v in rows.items() if v.get("phase") == "rewrite"}
    report_rows, detail = [], {}
    for key, r in rows.items():
        if r.get("phase") != "solve":
            continue
        g = _grade_batch(r, byid)
        detail[r["pair_id"]] = detail.get(r["pair_id"], {})
        detail[r["pair_id"]][r["arm"]] = {"grade": g, "tokens": r.get("tokens"),
                                          "parse_error": g.get("parse_error"),
                                          "latency_s": r.get("latency_s")}
        rr = rw.get(f"rw|{r['pair_id']}|{r['arm']}") or {}
        report_rows.append({
            "pair_id": r["pair_id"], "arm": r["arm"], "family": r["family"],
            "passed": g["checks_pass"], "total": g["checks_total"],
            "question_passed": g["q_pass"], "question_total": g["q_total"],
            "tokens": r.get("tokens"), "rewrite_tokens": rr.get("tokens"),
            "rewrite_ok": bool(rr.get("ok")), "violations": len(rr.get("violations") or []),
            "frontmatter_changed": rr.get("frontmatter_changed"),
            "parse_error": g.get("parse_error"),
        })
    res = {"heldout_sha256": hs, "model": MODEL, "pairs": len({x["pair_id"] for x in report_rows}),
           "rows": report_rows}
    (out / "report.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "detail.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"pairs={res['pairs']} rows={len(report_rows)}")
    for x in sorted(report_rows, key=lambda y: (y["pair_id"], y["arm"])):
        print(f"  {x['pair_id']:>4} {x['arm']:<17} checks {x['passed']:>2}/{x['total']:<2} "
              f"q {x['question_passed']}/{x['question_total']} tok={x['tokens']} "
              f"rw_tok={x['rewrite_tokens']} viol={x['violations']} "
              f"{'PARSE_ERR' if x['parse_error'] else ''}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["manipcheck", "run", "report"])
    ap.add_argument("--per-family", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    if args.cmd == "manipcheck":
        return cmd_manipcheck(args)
    if args.cmd == "run":
        return cmd_run(args)
    return cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
