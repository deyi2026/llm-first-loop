#!/usr/bin/env python3
"""S1 gold/filler 阳性-阴性对照分析：只做汇总与门槛判定，不重写 grader。

冻结口径：S1-SPEC.md §3（判分）/ §4（门槛与完整性）/ §5（报告）；
          CALIBRATION-FREEZE-s1.json（cards / pool / s0_calls 的 sha256）。

复用（逐字，不重写公式）：
  - run_s0.dedupe                         同 key 留最早一条 ok
  - run_s0.GRADERS["v1.3"]                c1-c4 机械 check；void=空文本 -> 4 check 全 None
  - run_s0 的 case_pass 语义              bool(passes) and all(passes)（全 None 自然为 False）
  - analyze_s0.wilson_ci                  Wilson 95% CI
  - analyze_s0.mcnemar_exact_two_sided_p  McNemar exact 双侧 p

门槛（冻结）：G1 >= 2 且 G2 >= 2 -> gold PASS；F1 == 0 -> filler PASS；
完整性不满足 -> INCOMPLETE。S0 基线复算 D 必须 == 28（FREEZE.s0_d_v13）。

exit 码：0 正常（verdict 见 stdout / JSON）；2 缺 calls_s1（或 s0 calls）；3 复算 D != 28。
同输入两次运行（相同 --now 注入，或不注入）输出逐字节一致；不自动取当前时间。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
S0_DIR = HERE.parent / "s0_p28"
sys.dont_write_bytecode = True  # 只读纪律：import 既有模块不落 __pycache__
if str(S0_DIR) not in sys.path:
    sys.path.insert(0, str(S0_DIR))

import run_s0  # noqa: E402  复用 dedupe / GRADERS / CS / PROMPT_VERSION
import analyze_s0  # noqa: E402  复用 wilson_ci / mcnemar_exact_two_sided_p

GRADER_NAME = "v1.3"
GRADER = run_s0.GRADERS[GRADER_NAME]
CS = run_s0.CS
S1_ARMS = ("gold_card", "filler_card")
CARD_OF_ARM = {"gold_card": "gold", "filler_card": "filler"}
FREEZE_PATH = HERE / "CALIBRATION-FREEZE-s1.json"
DEFAULT_CALLS = HERE / "results" / "calls_s1.jsonl"
DEFAULT_S0_CALLS = S0_DIR / "results" / "calls.jsonl"
DEFAULT_OUT_DIR = HERE / "results"
S0_FROZEN_MCNEMAR_P = 0.096  # S1-SPEC §5：报告必须并列 S0 v1.3 终值，防把 S1 误读为 orig 卡有效


# ---------------------------------------------------------------- 输入（流式）

def stream_calls(path: Path) -> tuple[list[dict], dict]:
    """逐行流式读 jsonl（不整文件载入）：每行 json.loads，同时流式算 sha256。

    坏行/撕裂行记入 unparsable（行号+原因），不猜——与 analyze_s0.load_calls 的
    "不猜" 口径一致，但本函数是流式实现（analyze_s0 一次 read_bytes，此处按行读）。
    """
    h = hashlib.sha256()
    rows: list[dict] = []
    unparsable: list[dict] = []
    n_lines = 0
    nbytes = 0
    with path.open("rb") as f:
        for lineno, raw in enumerate(f, 1):
            h.update(raw)
            nbytes += len(raw)
            s = raw.decode("utf-8", errors="replace").strip()
            if not s:
                continue
            n_lines += 1
            try:
                r = json.loads(s)
            except json.JSONDecodeError as e:
                unparsable.append({"line": lineno, "error": str(e)})
                continue
            if not isinstance(r, dict):
                unparsable.append({"line": lineno, "error": "not a json object"})
                continue
            rows.append(r)
    info = {"path": str(path), "sha256": h.hexdigest(), "bytes": nbytes,
            "n_lines": n_lines, "n_not_ok": sum(1 for r in rows if not r.get("ok")),
            "unparsable": unparsable}
    return rows, info


# ---------------------------------------------------------------- 判分（复用）

def grade_rows(rows: list[dict]) -> list[dict]:
    """run_s0.dedupe（同 key 留最早 ok）+ GRADERS["v1.3"] 判分。

    case_pass 语义与 run_s0.summarize_one 逐字一致：
      checks, st = g(r["text"]); passes = [v for v in checks.values() if v is not None]
      case_pass = bool(passes) and all(passes)
    void（空文本）4 check 全 None -> passes=[] -> case_pass=False，无需特判。
    """
    graded: list[dict] = []
    for r in run_s0.dedupe(rows):
        checks, st = GRADER(r["text"])
        passes = [v for v in checks.values() if v is not None]
        graded.append({**r, "checks": checks, "check_status": st,
                       "case_pass": bool(passes) and all(passes)})
    return graded


def by_instance(rows: list[dict]) -> dict:
    """instance_id -> 最早一条判分行（S0/S1 均一题一调用，rep 固定）。"""
    m: dict = {}
    for r in rows:
        m.setdefault(r["instance_id"], r)
    return m


def arm_summary(graded: list[dict]) -> dict:
    """单臂汇总：n_ok / case_pass / rate / Wilson 95%（复用 analyze_s0.wilson_ci）。"""
    n = len(graded)
    cp = sum(1 for r in graded if r["case_pass"])
    chk: dict = {}
    for k in CS:
        cnt = [r["checks"][k] for r in graded if r["checks"][k] is not None]
        chk[k] = {"counted": len(cnt), "pass": sum(1 for x in cnt if x),
                  "rate": round(sum(1 for x in cnt if x) / len(cnt), 4) if cnt else None}
    void = sum(1 for r in graded if all(r["checks"][k] is None for k in CS))
    return {"n_ok": n, "case_pass": cp,
            "rate": round(cp / n, 4) if n else None,
            "wilson_95": analyze_s0.wilson_ci(cp, n),
            "void": void, "checks": chk}


def count_ok_dup_keys(rows: list[dict]) -> int:
    """ok 行中重复 key 的出现次数（第 2 次起各计 1）。"""
    seen: set = set()
    dup = 0
    for r in rows:
        if not r.get("ok"):
            continue
        if r["key"] in seen:
            dup += 1
        seen.add(r["key"])
    return dup


def mcnemar_vs_no_card(arm_by: dict, nc_by: dict) -> dict:
    """arm 对 no_card 的 McNemar exact（描述性，复用 analyze_s0 实现）。"""
    common = sorted(set(nc_by) & set(arm_by))
    b = sum(1 for i in common if (not nc_by[i]["case_pass"]) and arm_by[i]["case_pass"])
    c = sum(1 for i in common if nc_by[i]["case_pass"] and (not arm_by[i]["case_pass"]))
    return {"n_common": len(common), "b_fail_to_pass": b, "c_pass_to_fail": c,
            "exact_p": analyze_s0.mcnemar_exact_two_sided_p(b, c)}


def arm_view(r: dict | None) -> dict | None:
    if r is None:
        return None
    return {"checks": {k: r["checks"][k] for k in CS}, "case_pass": r["case_pass"]}


# ---------------------------------------------------------------- Markdown

def _fmt_ci(w: dict) -> str:
    return "n/a" if w["lo"] is None else f"[{w['lo']:.3f}, {w['hi']:.3f}]"


def _fmt_checks(v: dict | None) -> str:
    if v is None:
        return "—"
    m = {True: "T", False: "F", None: "·"}
    return "".join(m[v["checks"][k]] for k in CS)


def _fmt_pass(v: dict | None) -> str:
    return "—" if v is None else ("T" if v["case_pass"] else "F")


def render_md(p: dict) -> str:
    L: list[str] = []
    L.append("# S1 gold/filler 阳性-阴性对照分析（analyze_s1）")
    L.append("")
    L.append(f"- 生成时间（--now 注入）：{p['now'] if p['now'] else '（未注入；输出不含时钟，逐字节可重现）'}")
    L.append(f"- 判分器：`run_s0.GRADERS[\"{GRADER_NAME}\"]`（逐字复用）；dedupe：`run_s0.dedupe`")
    L.append(f"- 状态：{p['status']}；**verdict：{p['verdict']}**"
             f"（gold={p['gold_verdict']}，filler={p['filler_verdict']}）")
    L.append("")
    L.append("## 输入")
    L.append("")
    L.append("| 输入 | sha256 | bytes | 行数 | not-ok | 坏行 |")
    L.append("|---|---|---|---|---|---|")
    for name in ("calls_s1", "s0_calls"):
        i = p["inputs"][name]
        L.append(f"| {name} | `{i['sha256']}` | {i['bytes']} | {i['n_lines']} | "
                 f"{i['n_not_ok']} | {len(i['unparsable'])} |")
    L.append("")
    L.append(f"- s0_calls sha256 与 FREEZE 一致：{p['integrity']['s0_calls_sha256_ok']}"
             f"（期望 `{p['integrity']['s0_calls_sha256_expected']}`）")
    L.append("")
    L.append("## 完整性（S1-SPEC §4.3）")
    L.append("")
    L.append("| arm | n_ok/期望 | 重复 key | prompt_version | card_sha256 一致 |")
    L.append("|---|---|---|---|---|")
    for arm in S1_ARMS:
        a = p["integrity"]["arms"][arm]
        L.append(f"| {arm} | {a['n_ok']}/{a['expected_n']} | {a['dup_keys']} | "
                 f"{'、'.join(a['prompt_versions']) or '—'} | {a['card_sha256_ok']} |")
    L.append("")
    L.append(f"- 完整性总判定：{'OK' if p['integrity']['ok'] else 'INCOMPLETE'}"
             "（不满足任一项 -> verdict=INCOMPLETE，补跑后再判）")
    L.append("")
    L.append("## 主表（per-arm，§5）")
    L.append("")
    L.append("| arm | n_ok | case_pass | rate | Wilson 95% CI | void |")
    L.append("|---|---|---|---|---|---|")
    for arm in ("no_card", "gold_card", "filler_card"):
        a = p["arms"][arm]
        L.append(f"| {arm} | {a['n_ok']} | {a['case_pass']} | {a['rate']} | "
                 f"{_fmt_ci(a['wilson_95'])} | {a['void']} |")
    L.append("")
    L.append("## S0 基线并列（防误读：S1 PASS 不证明 orig 卡有效）")
    L.append("")
    b = p["baseline_s0"]
    L.append(f"- 冻结终值：D={b['frozen']['d']}，R={b['frozen']['r']}，"
             f"McNemar p={b['frozen']['mcnemar_p']}（S0 v1.3）")
    L.append(f"- 本次复算：D={b['d_ids']}（d_pairs={b['d_pairs']}），R={b['r_ids']}"
             f"（r_pairs={b['r_pairs']}），paired={b['paired']}，"
             f"McNemar p={b['mcnemar_p_orig_vs_no_card']}")
    L.append(f"- D 复算 == 冻结值 {b['expected_d']}：{b['d_ok']}")
    L.append("")
    L.append("## 门槛（冻结，§4）")
    L.append("")
    g, fl = p["gates"]["gold"], p["gates"]["filler"]
    L.append(f"- **G1** = {g['G1']}（D 中 gold 翻 pass 的实例数，阈值 ≥{g['G1_threshold']}）"
             f" -> {'满足' if g['G1'] >= g['G1_threshold'] else '不满足'}")
    L.append(f"- **G2** = {g['G2']}（D 上 no_card False -> gold True 的 check 种类数，"
             f"阈值 ≥{g['G2_threshold']}）种类：{'、'.join(g['G2_flip_kinds']) or '—'}"
             f" -> {'满足' if g['G2'] >= g['G2_threshold'] else '不满足'}")
    L.append(f"- gold 判定：**{p['gold_verdict']}**")
    L.append(f"- **F1** = {fl['F1']}（全体实例 no_card fail -> filler pass 数，阈值 = 0）"
             f" -> {'满足' if fl['F1'] == 0 else '不满足'}"
             + (f"；翻动实例：{'、'.join(fl['F1_ids'])}" if fl["F1_ids"] else ""))
    L.append(f"- filler pass->fail（描述性，不触发 F1）：{len(fl['pass_to_fail_desc'])}"
             + (f"（{'、'.join(fl['pass_to_fail_desc'])}）" if fl["pass_to_fail_desc"] else ""))
    L.append(f"- filler 判定：**{p['filler_verdict']}**")
    L.append("")
    L.append("## McNemar exact（描述性，不作门槛）")
    L.append("")
    L.append("| 对照 | 共同实例 | b(fail->pass) | c(pass->fail) | exact p |")
    L.append("|---|---|---|---|---|")
    for name, key in (("gold vs no_card", "gold_vs_no_card"),
                      ("filler vs no_card", "filler_vs_no_card")):
        m = p["mcnemar_descriptive"][key]
        pp = "n/a" if m["exact_p"] is None else f"{m['exact_p']:.4f}"
        L.append(f"| {name} | {m['n_common']} | {m['b_fail_to_pass']} | "
                 f"{m['c_pass_to_fail']} | {pp} |")
    L.append("")
    L.append(f"## D 明细（{len(p['D_detail'])} 条）")
    L.append("")
    L.append("| instance_id | rep | no_card c1-c4 | pass | gold c1-c4 | pass | "
             "filler c1-c4 | pass | gold 翻转 check |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for d in p["D_detail"]:
        L.append(f"| {d['instance_id']} | {d['rep']} | {_fmt_checks(d['no_card'])} | "
                 f"{_fmt_pass(d['no_card'])} | {_fmt_checks(d['gold_card'])} | "
                 f"{_fmt_pass(d['gold_card'])} | {_fmt_checks(d['filler_card'])} | "
                 f"{_fmt_pass(d['filler_card'])} | {'、'.join(d['gold_flips']) or '—'} |")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- 主流程

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="analyze_s1",
        description="S1 gold/filler 阳性-阴性对照分析：流式读 calls，复用 run_s0.dedupe / "
                    "run_s0.GRADERS['v1.3'] / analyze_s0.wilson_ci / analyze_s0."
                    "mcnemar_exact_two_sided_p；判定 G1/G2/F1 与完整性，写 analysis_s1.json/.md。",
        epilog="exit 码：0 正常；2 缺 calls_s1（或 s0 calls）；3 复算 S0 D != 28。"
               "输出不含时钟；重复运行逐字节一致（时间须经 --now 注入）。")
    ap.add_argument("--calls", default=str(DEFAULT_CALLS),
                    help="S1 calls jsonl（gold_card/filler_card 两臂）")
    ap.add_argument("--s0-calls", default=str(DEFAULT_S0_CALLS),
                    help="S0 calls jsonl（no_card/orig_card 两臂，D 基线）")
    ap.add_argument("--out", default=str(DEFAULT_OUT_DIR),
                    help="输出目录（写 analysis_s1.json / analysis_s1.md）")
    ap.add_argument("--now", default=None,
                    help="生成时间注入（ISO 字符串）；不给则输出不含时钟，保证逐字节可重现")
    args = ap.parse_args(argv)

    calls = Path(args.calls)
    s0_calls = Path(args.s0_calls)
    out_dir = Path(args.out)
    if not calls.is_file():
        print(f"[analyze_s1] 缺 calls_s1：{calls}", file=sys.stderr)
        return 2
    if not s0_calls.is_file():
        print(f"[analyze_s1] 缺 s0 calls：{s0_calls}", file=sys.stderr)
        return 2

    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    expected_n = freeze["pool"]["instances"]
    expected_d = freeze["baseline"]["s0_d_v13"]

    s1_raw, s1_info = stream_calls(calls)
    s0_raw, s0_info = stream_calls(s0_calls)
    s0_sha_ok = s0_info["sha256"] == freeze["baseline"]["s0_calls"]["sha256"]

    s1_graded = grade_rows(s1_raw)
    s0_graded = grade_rows(s0_raw)

    nc_by = by_instance([r for r in s0_graded if r["arm"] == "no_card"])
    gold_by = by_instance([r for r in s1_graded if r["arm"] == "gold_card"])
    filler_by = by_instance([r for r in s1_graded if r["arm"] == "filler_card"])

    # D/R 复算：paired 语义与 run_s0.summarize_one 一致（(instance_id, rep) 双臂齐全）
    pairs: dict = {}
    for r in s0_graded:
        pairs.setdefault((r["instance_id"], r["rep"]), {})[r["arm"]] = r
    paired = {k: v for k, v in pairs.items() if "no_card" in v and "orig_card" in v}
    d_pairs = sorted(k for k, v in paired.items()
                     if (not v["no_card"]["case_pass"]) and v["orig_card"]["case_pass"])
    r_pairs = sorted(k for k, v in paired.items()
                     if v["no_card"]["case_pass"] and (not v["orig_card"]["case_pass"]))
    d_ids = sorted({k[0] for k in d_pairs})
    rep_by: dict = {}
    for iid, rep in d_pairs:
        rep_by.setdefault(iid, rep)
    d_ok = len(d_ids) == expected_d

    # 门槛：gold（G1 实例级 / G2 check 级，均在 D 上）
    g1_ids = [i for i in d_ids if i in gold_by and gold_by[i]["case_pass"]]
    flip_kinds: set = set()
    d_detail: list[dict] = []
    for i in d_ids:
        nc, gd, fl = nc_by.get(i), gold_by.get(i), filler_by.get(i)
        gf = [k for k in CS if nc and gd
              and nc["checks"][k] is False and gd["checks"][k] is True]
        ff = [k for k in CS if nc and fl
              and nc["checks"][k] is False and fl["checks"][k] is True]
        flip_kinds.update(gf)
        d_detail.append({"instance_id": i, "rep": rep_by.get(i),
                         "no_card": arm_view(nc), "gold_card": arm_view(gd),
                         "filler_card": arm_view(fl),
                         "gold_flips": gf, "filler_flips": ff})
    g1, g2 = len(g1_ids), len(sorted(flip_kinds))
    gold_pass = g1 >= 2 and g2 >= 2

    # 门槛：filler（F1 在全体实例上）
    common_nf = sorted(set(nc_by) & set(filler_by))
    f1_ids = [i for i in common_nf
              if (not nc_by[i]["case_pass"]) and filler_by[i]["case_pass"]]
    fpf_ids = [i for i in common_nf
               if nc_by[i]["case_pass"] and (not filler_by[i]["case_pass"])]
    f1 = len(f1_ids)
    filler_pass = f1 == 0

    # 完整性（§4.3）：每臂 120 ok、无重复 key、prompt_version 全 p2、card_sha256 与 FREEZE 一致
    arms_int: dict = {}
    for arm in S1_ARMS:
        arm_ok = [r for r in s1_raw if r.get("arm") == arm and r.get("ok")]
        n = len(by_instance([r for r in s1_graded if r["arm"] == arm]))
        dup = count_ok_dup_keys([r for r in s1_raw if r.get("arm") == arm])
        pvs = sorted({str(r.get("prompt_version")) for r in arm_ok})
        want_sha = freeze["cards"][CARD_OF_ARM[arm]]["sha256"]
        shas = sorted({str(r.get("card_sha256")) for r in arm_ok})
        ok = (n == expected_n) and dup == 0 and pvs == [run_s0.PROMPT_VERSION] \
            and shas == [want_sha]
        arms_int[arm] = {"n_ok": n, "expected_n": expected_n, "dup_keys": dup,
                         "prompt_versions": pvs, "card_sha256_values": shas,
                         "card_sha256_expected": want_sha,
                         "card_sha256_ok": shas == [want_sha], "ok": ok}
    integrity = {"expected_instances_per_arm": expected_n, "arms": arms_int,
                 "s0_calls_sha256_ok": s0_sha_ok,
                 "s0_calls_sha256_expected": freeze["baseline"]["s0_calls"]["sha256"],
                 "ok": all(arms_int[a]["ok"] for a in S1_ARMS) and s0_sha_ok}

    if not integrity["ok"]:
        verdict = "INCOMPLETE"
    elif gold_pass and filler_pass:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    payload = {
        "schema": "analysis_s1/v1",
        "now": args.now,
        "status": "ok" if d_ok else "d_mismatch",
        "grader": GRADER_NAME,
        "reused": {"dedupe": "run_s0.dedupe",
                   "case_pass_semantics": "run_s0.summarize_one",
                   "wilson_ci": "analyze_s0.wilson_ci",
                   "mcnemar_exact": "analyze_s0.mcnemar_exact_two_sided_p"},
        "inputs": {"calls_s1": s1_info, "s0_calls": s0_info,
                   "freeze_sha256": hashlib.sha256(
                       FREEZE_PATH.read_bytes()).hexdigest()},
        "integrity": integrity,
        "baseline_s0": {
            "paired": len(paired), "d_pairs": len(d_pairs), "r_pairs": len(r_pairs),
            "d_ids": len(d_ids), "r_ids": len({k[0] for k in r_pairs}),
            "mcnemar_p_orig_vs_no_card": analyze_s0.mcnemar_exact_two_sided_p(
                len(d_pairs), len(r_pairs)),
            "frozen": {"d": expected_d, "r": freeze["baseline"]["s0_r_v13"],
                       "mcnemar_p": S0_FROZEN_MCNEMAR_P},
            "expected_d": expected_d, "d_ok": d_ok},
        "arms": {"no_card": arm_summary(list(nc_by.values())),
                 "gold_card": arm_summary(list(gold_by.values())),
                 "filler_card": arm_summary(list(filler_by.values()))},
        "gates": {
            "gold": {"G1": g1, "G1_threshold": 2, "G1_ids": g1_ids,
                     "G2": g2, "G2_threshold": 2, "G2_flip_kinds": sorted(flip_kinds),
                     "pass": gold_pass, "verdict": "PASS" if gold_pass else "FAIL"},
            "filler": {"F1": f1, "F1_threshold": 0, "F1_ids": f1_ids,
                       "pass_to_fail_desc": fpf_ids,
                       "pass": filler_pass, "verdict": "PASS" if filler_pass else "FAIL"}},
        "mcnemar_descriptive": {
            "gold_vs_no_card": mcnemar_vs_no_card(gold_by, nc_by),
            "filler_vs_no_card": mcnemar_vs_no_card(filler_by, nc_by)},
        "verdict": verdict,
        "gold_verdict": "PASS" if gold_pass else "FAIL",
        "filler_verdict": "PASS" if filler_pass else "FAIL",
        "D_detail": d_detail,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis_s1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (out_dir / "analysis_s1.md").write_text(render_md(payload), encoding="utf-8")

    print(f"G1={g1} (need >=2)  G2={g2} (need >=2)  gold={payload['gold_verdict']}")
    print(f"F1={f1} (need ==0)  filler={payload['filler_verdict']}")
    print(f"integrity={'OK' if integrity['ok'] else 'INCOMPLETE'}  verdict={verdict}")
    print(f"wrote {out_dir / 'analysis_s1.json'} , {out_dir / 'analysis_s1.md'}")
    if not d_ok:
        print(f"[analyze_s1] D mismatch: expected {expected_d}, "
              f"observed d_ids={len(d_ids)} (d_pairs={len(d_pairs)}); "
              f"sample_ids={d_ids[:10]}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
