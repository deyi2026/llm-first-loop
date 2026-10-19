#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S0 离线分析：对 calls.jsonl 的只读快照重算判分并汇总（标准库 only，离线）。

纪律：
- 判分/去重/配对/每臂统计一律复用 run_s0：GRADERS、dedupe、summarize_one、ARMS、CS、C2_V13。
  本脚本不复制、不改写任何 grader 逻辑；长度分层与 c2 审计只做行子集切片后仍调
  summarize_one，或直接调用 GRADERS[g](text)——注意其返回 (checks, status) 二元组，
  不是 bool，绝不可写 bool(g(text))。
- 头条 paired/D/R 以 run_s0.summarize_one 为准；分层内部另做加和一致性校验。
- 闸门口径按 GATE-AMENDMENT-v2.md（终值前冻结）：新口径 = v1.3 D>=30 且
  v1.0/v1.1/v1.2 各自 D>=R；旧口径 gate_both（四版 D>=30）并列报告，不作主判据。
  三个标签逐字取自修正案 §2；全文不出现修正案 §2 表外的裁决性表述。

用法：
  python3 analyze_s0.py [--calls PATH] [--out PATH] [--require-complete]
                        [--markdown|--no-markdown] [--now ISO8601]
默认 calls = <script_dir>/results/calls.jsonl；默认 out = <script_dir>/results/analysis_s0.json。
退出码：0 正常；2 输入错误；3 --require-complete 且 paired < 120。
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # 只读纪律：import run_s0 也不写 __pycache__
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import run_s0 as S  # noqa: E402  复用 GRADERS / dedupe / summarize_one / ARMS / CS / C2_V13

AMENDMENT = HERE / "GATE-AMENDMENT-v2.md"
EXPECTED_PAIRS = 120
OLD_VERSIONS = ("v1.0", "v1.1", "v1.2")
Z95 = 1.959963984540054  # 标准正态 0.975 分位

# 标签逐字取自 GATE-AMENDMENT-v2.md §2（写死，禁止改写）
LABEL_POSITIVE = "S0 directional positive — pending S1"
LABEL_MIXED = "S0 mixed — revision flipped direction"
LABEL_NULL = "S0 no detectable effect under this instrument"

# c2 审计的分类注记（分析用正则，非 grader）：a/b 两个分支与 run_s0.C2_V13 的
# 两个 alternation 逐字对应；运行时校验 (a|b) 与 C2_V13 可互相推出（branch_split_consistent）。
A_RE = re.compile(r"(回复|回我|按|选|选择|挑)\s*[A-Ca-c1-3①-③]")
B_RE = re.compile(r"(要哪个|哪一个|你定|等你选|等你确认|请你选|告诉我)")
QMARK_RE = re.compile(r"[?？]")

C2_CLASSES = (
    ("a_option_choice", "a: 编号选择（C2_V13 分支1：(回复|回我|按|选|选择|挑)+[A-Ca-c1-3①-③]）"),
    ("b_handback", "b: 交回语（C2_V13 分支2：要哪个|哪一个|你定|等你选|等你确认|请你选|告诉我）"),
    ("c_qmark_201_300", "c: 问号落在第 201-300 字符尾窗（v1.0 尾窗 200 之外、v1.3 尾窗 300 之内）"),
    ("d_qmark_earlier", "d: 问号在更早位置（300 字符尾窗之前）"),
    ("e_other", "e: 其他（a-d 均未命中）"),
)

BIN_NAMES = ("[0,300)", "[300,600)", "[600,inf)")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_path(p: Path) -> str | None:
    try:
        return sha256_bytes(p.read_bytes())
    except OSError:
        return None


def wilson_ci(k: int, n: int, z: float = Z95) -> dict:
    """k/n 的 Wilson score 区间（95%）。n<=0 时未定义：记 None 并注明（不插补为 [0,1]）。"""
    if not n or n <= 0:
        return {"k": k or 0, "n": n or 0, "lo": None, "hi": None,
                "note": "n=0：Wilson 分母为 0，区间未定义；本脚本记 None（不插补为 [0,1]）"}
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return {"k": k, "n": n, "lo": round(max(0.0, center - half), 6),
            "hi": round(min(1.0, center + half), 6), "note": None}


def mcnemar_exact_two_sided_p(b: int, c: int) -> float | None:
    """McNemar 精确双侧：discordant n=b+c，X~Bin(n,0.5)，
    p = sum_{k: P(k) <= P(min(b,c))} P(k)（与 scipy.stats.binomtest 两侧口径同族）。
    n=0（无不一致对）→ None。"""
    n = b + c
    if n == 0:
        return None
    denom = 2.0 ** n
    pmf = [math.comb(n, k) / denom for k in range(n + 1)]
    p_obs = pmf[min(b, c)]
    return min(1.0, sum(x for x in pmf if x <= p_obs * (1.0 + 1e-12)))


def load_calls(path: Path) -> tuple[list[dict], dict]:
    """读入快照（一次读字节，哈希与行解析同源）。末行若被并发写撕裂记 unparsable，不猜。"""
    raw = path.read_bytes()
    info: dict = {"sha256": sha256_bytes(raw), "bytes": len(raw)}
    rows: list[dict] = []
    unparsable: list[dict] = []
    n_lines = 0
    for i, ln in enumerate(raw.decode("utf-8").split("\n"), 1):
        s = ln.strip()
        if not s:
            continue
        n_lines += 1
        try:
            rows.append(json.loads(s))
        except json.JSONDecodeError:
            unparsable.append({"line_no": i, "head_chars": s[:120]})
    info["lines_total"] = n_lines
    info["lines_ok"] = sum(1 for r in rows if r.get("ok"))
    info["lines_fail"] = sum(1 for r in rows if not r.get("ok"))
    info["lines_unparsable"] = len(unparsable)
    info["unparsable"] = unparsable
    return rows, info


def pair_map(rows: list[dict]) -> dict[tuple, dict[str, dict]]:
    m: dict[tuple, dict[str, dict]] = {}
    for r in rows:
        m.setdefault((r["instance_id"], r["rep"]), {})[r["arm"]] = r
    return m


def len_bin(n_chars: int) -> str:
    if n_chars < 300:
        return BIN_NAMES[0]
    if n_chars < 600:
        return BIN_NAMES[1]
    return BIN_NAMES[2]


def c2_negative_audit(rows: list[dict]) -> tuple[dict, bool]:
    """每臂 dedupe 后的 ok 行：v1.0 c2=False 的集合内，分类 v1.3 c2=True 的原因
    （优先级 a>b>c>d>e，一个文本命中多类取先命中者）；v1.0=False 且 v1.3=False 计零标记。
    返回 (各臂结果, (a|b) 与 run_s0.C2_V13 是否逐行等价)。"""
    arms_out: dict[str, dict] = {}
    split_consistent = True
    for arm in S.ARMS:
        classes = {cid: {"desc": desc, "count": 0, "first10_ids": []} for cid, desc in C2_CLASSES}
        zero = {"desc": "v1.0 c2=False 且 v1.3 c2=False（零标记）", "count": 0, "first10_ids": []}
        n_audit = 0
        n_flip = 0
        for r in rows:
            if r["arm"] != arm:
                continue
            text = r.get("text") or ""
            c10 = S.GRADERS["v1.0"](text)[0]["c2"]  # (checks, status) 二元组，取 checks["c2"]
            c13 = S.GRADERS["v1.3"](text)[0]["c2"]
            hit_ab = (A_RE.search(text) is not None) or (B_RE.search(text) is not None)
            if hit_ab != (S.C2_V13.search(text) is not None):
                split_consistent = False
            if c10 is None or c10:
                continue  # void 或 v1.0 已判 True：不在负向审计集
            n_audit += 1
            if c13:
                n_flip += 1
                n = len(text)
                t3, t2 = max(0, n - 300), max(0, n - 200)
                if A_RE.search(text):
                    cid = "a_option_choice"
                elif B_RE.search(text):
                    cid = "b_handback"
                elif QMARK_RE.search(text[t3:t2]):
                    cid = "c_qmark_201_300"
                elif QMARK_RE.search(text[:t3]):
                    cid = "d_qmark_earlier"
                else:
                    cid = "e_other"
                classes[cid]["count"] += 1
                if len(classes[cid]["first10_ids"]) < 10:
                    classes[cid]["first10_ids"].append(r["key"])
            else:
                zero["count"] += 1
                if len(zero["first10_ids"]) < 10:
                    zero["first10_ids"].append(r["key"])
        arms_out[arm] = {
            "n_v1_0_c2_false": n_audit,
            "flipped_to_v1_3_true": n_flip,
            "stayed_false": n_audit - n_flip,
            "classes": classes,
            "zero_marker": zero,
        }
    return arms_out, split_consistent


def analyze(rows_all: list[dict], calls_info: dict, calls_path: Path,
            now_iso: str, now_injected: bool) -> dict:
    fail_rows = [{"key": r.get("key"), "error": (r.get("error") or "")[:300],
                  "latency_s": r.get("latency_s")} for r in rows_all if not r.get("ok")]
    ok_rows_raw = [r for r in rows_all if r.get("ok")]
    occ: dict[str, int] = {}
    for r in ok_rows_raw:
        occ[r["key"]] = occ.get(r["key"], 0) + 1
    dup_keys = {k: v for k, v in sorted(occ.items()) if v > 1}

    rows = S.dedupe(rows_all)  # 权威去重：同 key 保留最早一条 ok
    pairs = pair_map(rows)
    complete = {k: v for k, v in pairs.items() if len(v) == 2}
    missing = sorted(f"{iid}|r{rep} (only: {'+'.join(sorted(v))})"
                     for (iid, rep), v in pairs.items() if len(v) < 2)

    # ---- 每版 grader：头条数字全部来自 run_s0.summarize_one（权威） ----
    graders: dict[str, dict] = {}
    for g in S.GRADERS:
        r = dict(S.summarize_one(rows, g))
        r["D_minus_R"] = r["D_case_level"] - r["R_case_level"]
        for arm, a in r["arms"].items():
            a["case_pass_wilson95"] = wilson_ci(a["case_pass"], a["n"])
        pv = mcnemar_exact_two_sided_p(r["D_case_level"], r["R_case_level"])
        r["mcnemar_exact"] = {
            "b_D": r["D_case_level"], "c_R": r["R_case_level"],
            "n_discordant": r["D_case_level"] + r["R_case_level"],
            "p_two_sided": None if pv is None else round(pv, 6),
            "method": "exact binomial two-sided: X~Bin(D+R,0.5), p=sum P(X=k) for P(k)<=P(min(D,R))",
            "note": None if pv is not None else "D+R=0（无不一致对）→ p 未定义",
        }
        graders[g] = r

    # ---- c3 长度分层：按 no_card 回复字符数；子集仍调 summarize_one 保证同源 ----
    by_bin: dict[str, list] = {b: [] for b in BIN_NAMES}
    for k, v in complete.items():
        by_bin[len_bin(len(v["no_card"]["text"]))].append(k)

    bins_out: dict[str, dict] = {}
    for b in BIN_NAMES:
        ks = sorted(by_bin[b])
        sub = sorted((v for k in ks for v in complete[k].values()), key=lambda r: r["key"])
        e: dict = {"n_pairs": len(ks), "per_grader": {}, "v1_3_arms_case_pass": None}
        for g in S.GRADERS:
            sg = S.summarize_one(sub, g)
            e["per_grader"][g] = {"paired": sg["paired"], "D": sg["D_case_level"],
                                  "R": sg["R_case_level"]}
            if g == "v1.3":
                e["v1_3_arms_case_pass"] = {
                    arm: (None if arm not in sg["arms"] else {
                        "n": sg["arms"][arm]["n"],
                        "case_pass": sg["arms"][arm]["case_pass"],
                        "case_pass_rate": sg["arms"][arm]["case_pass_rate"]})
                    for arm in S.ARMS}
        bins_out[b] = e

    # ---- 四分位切点（no_card 长度；D/R 只报 v1.3） ----
    lens_sorted = sorted(len(v["no_card"]["text"]) for v in complete.values())
    if len(lens_sorted) >= 2:
        cuts = statistics.quantiles(lens_sorted, n=4)  # 默认 method='exclusive'
        qmembers: list[list] = [[] for _ in range(4)]
        for k, v in complete.items():
            qmembers[bisect.bisect_left(cuts, len(v["no_card"]["text"]))].append(k)
        qs = []
        for qi in range(4):
            ks = sorted(qmembers[qi])
            sub = sorted((v for k in ks for v in complete[k].values()), key=lambda r: r["key"])
            sg = S.summarize_one(sub, "v1.3")
            ls = sorted(len(complete[k]["no_card"]["text"]) for k in ks)
            qs.append({"quartile": f"Q{qi + 1}", "n_pairs": len(ks),
                       "len_min": ls[0] if ls else None, "len_max": ls[-1] if ls else None,
                       "D": sg["D_case_level"], "R": sg["R_case_level"],
                       "paired": sg["paired"]})
        quart = {"cut_points_q1_q2_q3": [round(x, 4) for x in cuts],
                 "method": "statistics.quantiles(n=4, method='exclusive')（R type-7 同族）",
                 "assignment": "bisect_left(cuts, L)：L<=q1→Q1；q1<L<=q2→Q2；q2<L<=q3→Q3；L>q3→Q4",
                 "quartiles": qs}
    else:
        quart = {"cut_points_q1_q2_q3": None,
                 "method": "statistics.quantiles(n=4, method='exclusive')",
                 "assignment": "bisect_left(cuts, L)（同上）", "quartiles": [],
                 "note": f"配对数 {len(lens_sorted)} < 2，无法给四分位切点（不插补）"}

    cons: dict = {"pairing_structure_matches_summarize_one":
                  all(graders[g]["paired"] == len(complete) for g in S.GRADERS)}
    for g in S.GRADERS:
        cons[g] = {
            "bin_paired_sum_equal": (sum(bins_out[b]["per_grader"][g]["paired"] for b in BIN_NAMES)
                                     == graders[g]["paired"]),
            "bin_D_sum_equal": (sum(bins_out[b]["per_grader"][g]["D"] for b in BIN_NAMES)
                                == graders[g]["D_case_level"]),
            "bin_R_sum_equal": (sum(bins_out[b]["per_grader"][g]["R"] for b in BIN_NAMES)
                                == graders[g]["R_case_level"]),
        }
    if quart["quartiles"]:
        cons["quartiles_v1_3"] = {
            "D_sum_equal": sum(q["D"] for q in quart["quartiles"]) == graders["v1.3"]["D_case_level"],
            "R_sum_equal": sum(q["R"] for q in quart["quartiles"]) == graders["v1.3"]["R_case_level"],
            "pairs_sum_equal": (sum(q["n_pairs"] for q in quart["quartiles"])
                                == graders["v1.3"]["paired"]),
        }

    # ---- c2 负向审计 ----
    c2_arms, split_ok = c2_negative_audit(rows)

    # ---- 两套闸门并列（标签逐字取自 GATE-AMENDMENT-v2.md §2） ----
    per_g_gate = {g: bool(graders[g]["gate_pass_D_ge_30"]) for g in S.GRADERS}
    dir_cons = {g: {"D": graders[g]["D_case_level"], "R": graders[g]["R_case_level"],
                    "D_ge_R": graders[g]["D_case_level"] >= graders[g]["R_case_level"]}
                for g in OLD_VERSIONS}
    main_ok = graders["v1.3"]["D_case_level"] >= 30
    dir_ok = all(x["D_ge_R"] for x in dir_cons.values())
    label = LABEL_NULL if not main_ok else (LABEL_POSITIVE if dir_ok else LABEL_MIXED)
    gates = {
        "old_gate_both": {
            "definition": "旧口径：四版同时 D_case_level>=30（即 run_s0.summarize 的 gate_both；并列报告，不作主判据）",
            "per_grader": per_g_gate,
            "gate_both": all(per_g_gate.values()),
        },
        "new_gate_frozen": {
            "source": AMENDMENT.name + "（终值前冻结；sha256 见 meta.amendment_sha256）",
            "main_criterion": "v1.3 D_case_level >= 30",
            "v1_3_D": graders["v1.3"]["D_case_level"],
            "main_satisfied": main_ok,
            "direction_consistency_v1_0_v1_1_v1_2": dir_cons,
            "all_old_versions_D_ge_R": dir_ok,
            "label": label,
            "v1_0_direction_deviation": {"D": graders["v1.0"]["D_case_level"],
                                         "R": graders["v1.0"]["R_case_level"]},
        },
        "label_rule": ("主判据满足且三旧版均 D>=R → 第1个标签；主判据满足但任一旧版 D<R → 第2个；"
                       "主判据不满足 → 第3个。标签逐字取自修正案 §2，不得出现表外裁决语。"),
    }

    meta = {
        "generated_at": now_iso,
        "now_injected": now_injected,
        "analyzer": "analyze_s0.py",
        "calls_path": str(calls_path),
        "calls_sha256": calls_info["sha256"],
        "calls_bytes": calls_info["bytes"],
        "lines_total": calls_info["lines_total"],
        "lines_ok": calls_info["lines_ok"],
        "lines_fail": calls_info["lines_fail"],
        "lines_unparsable": calls_info["lines_unparsable"],
        "unparsable_details": calls_info["unparsable"],
        "paired": graders["v1.3"]["paired"],
        "expected_pairs_complete": EXPECTED_PAIRS,
        "missing_paired_keys": missing,  # 只列缺失配对键，不插补
        "amendment_file": AMENDMENT.name,
        "amendment_sha256": sha256_path(AMENDMENT),
        "provenance_sha256": {
            "run_s0.py": sha256_path(HERE / "run_s0.py"),
            "build_pool_p28.py": sha256_path(HERE / "build_pool_p28.py"),
            "pool_p28.jsonl": sha256_path(HERE / "pool_p28.jsonl"),
        },
        "graders_used": list(S.GRADERS.keys()),
        "dedupe_rule": "run_s0.dedupe：同 key 保留最早一条 ok",
        "snapshot_note": "calls.jsonl 为读入时刻的快照（该文件可能仍在被追加；本分析不回写任何数据文件）",
    }
    data_quality = {
        "fail_rows": {"count": len(fail_rows), "rows": fail_rows[:50],
                      "note": ("仅列前 50 条" if len(fail_rows) > 50 else None)},
        "duplicate_ok": {"keys_with_multiple_ok": len(dup_keys),
                         "extra_rows_dropped": (sum(dup_keys.values()) - len(dup_keys)) if dup_keys else 0,
                         "per_key_occurrences": dup_keys},
        "missing_paired_keys": missing,
    }
    return {
        "meta": meta,
        "graders": graders,
        "c3_length_strata": {
            "bin_definition": "按配对中 no_card 回复字符数固定分层 [0,300)/[300,600)/[600,inf)",
            "bins": bins_out,
            "quartiles_v1_3": quart,
            "consistency": cons,
        },
        "c2_negative_audit": {
            "definition": ("每臂 dedupe 后 ok 行中 v1.0 c2=False 的集合：分类 v1.3 c2=True 的原因"
                           "（优先级 a>b>c>d>e）；v1.0=False 且 v1.3=False 计零标记"),
            "arms": c2_arms,
            "branch_split_consistent_with_C2_V13": split_ok,
        },
        "gates": gates,
        "data_quality": data_quality,
    }


def _f(x, nd: int = 4) -> str:
    return "NA" if x is None else f"{x:.{nd}f}"


def print_markdown(res: dict) -> None:
    m = res["meta"]
    gnames = list(res["graders"].keys())
    print("# S0 offline analysis — read-only snapshot")
    print(f"- generated_at: {m['generated_at']} (now_injected={m['now_injected']})")
    print(f"- calls: {m['calls_path']} sha256={m['calls_sha256']}")
    print(f"- lines: total={m['lines_total']} ok={m['lines_ok']} fail={m['lines_fail']} "
          f"unparsable={m['lines_unparsable']}")
    dq = res["data_quality"]
    print(f"- duplicate ok keys: {dq['duplicate_ok']['keys_with_multiple_ok']} "
          f"(extra rows dropped: {dq['duplicate_ok']['extra_rows_dropped']})")
    print(f"- paired: {m['paired']}/{m['expected_pairs_complete']}  "
          f"missing pairs: {len(m['missing_paired_keys'])} (keys → JSON meta.missing_paired_keys)")
    print(f"- amendment: {m['amendment_file']} sha256={m['amendment_sha256']}")
    print()
    print("## per-grader paired results（D/R 以 run_s0.summarize_one 为准）")
    print("| grader | paired | D | R | D-R | both_pass | both_fail | identical | mcnemar_exact_p | D>=30 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for g in gnames:
        r = res["graders"][g]
        p = r["mcnemar_exact"]["p_two_sided"]
        ptxt = "NA" if p is None else f"{p:.6g}"
        print(f"| {g} | {r['paired']} | {r['D_case_level']} | {r['R_case_level']} | {r['D_minus_R']} | "
              f"{r['both_pass']} | {r['both_fail']} | {r['identical_texts']} | {ptxt} | "
              f"{r['gate_pass_D_ge_30']} |")
    print()
    print("## per-arm（case_pass 的 Wilson 95% CI）")
    print("| grader | arm | n | case_pass | rate | wilson95 | c1 | c2 | c3 | c4 | median_chars |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for g in gnames:
        for arm, a in res["graders"][g]["arms"].items():
            w = a["case_pass_wilson95"]
            wtxt = "NA" if w["lo"] is None else f"[{w['lo']:.4f},{w['hi']:.4f}]"
            ch = " ".join(f"{c}={_f(a['checks'][c]['rate'])}" for c in S.CS)
            print(f"| {g} | {arm} | {a['n']} | {a['case_pass']} | {_f(a['case_pass_rate'])} | "
                  f"{wtxt} | {ch} | {a['median_reply_chars']} |")
    st = res["c3_length_strata"]
    print()
    print("## c3 length strata（按 no_card 回复字符数；每层四版 D/R）")
    print("| bin | n_pairs | " + " | ".join(f"{g} D/R" for g in gnames) + " |")
    print("|---|---|" + "---|" * len(gnames))
    for b in BIN_NAMES:
        e = st["bins"][b]
        cells = " | ".join(f"{e['per_grader'][g]['D']}/{e['per_grader'][g]['R']}" for g in gnames)
        print(f"| {b} | {e['n_pairs']} | {cells} |")
    print()
    print("v1.3 各层两臂 case_pass：")
    print("| bin | n_pairs | arm(v1.3) | case_pass | rate |")
    print("|---|---|---|---|---|")
    for b in BIN_NAMES:
        e = st["bins"][b]
        va = e["v1_3_arms_case_pass"] or {}
        for arm in S.ARMS:
            x = va.get(arm)
            if x:
                print(f"| {b} | {e['n_pairs']} | {arm} | {x['case_pass']} | {_f(x['case_pass_rate'])} |")
    q = st["quartiles_v1_3"]
    print()
    print(f"## no_card 长度四分位（v1.3；cuts={q['cut_points_q1_q2_q3']}；{q['method']}）")
    print("| quartile | len_min | len_max | n_pairs | D | R |")
    print("|---|---|---|---|---|---|")
    for x in q["quartiles"]:
        print(f"| {x['quartile']} | {x['len_min']} | {x['len_max']} | {x['n_pairs']} | {x['D']} | {x['R']} |")
    au = res["c2_negative_audit"]
    print()
    print("## c2 负向审计（v1.0 c2=False 集合内 v1.3 c2=True 的原因分类；每类前 10 id → JSON）")
    print("| arm | v1.0 c2=False | flipped→v1.3 True | a | b | c | d | e | zero_marker(两版均False) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for arm in S.ARMS:
        e = au["arms"].get(arm) or {}
        cl = e.get("classes") or {}
        print(f"| {arm} | {e.get('n_v1_0_c2_false')} | {e.get('flipped_to_v1_3_true')} | "
              f"{cl.get('a_option_choice', {}).get('count')} | {cl.get('b_handback', {}).get('count')} | "
              f"{cl.get('c_qmark_201_300', {}).get('count')} | {cl.get('d_qmark_earlier', {}).get('count')} | "
              f"{cl.get('e_other', {}).get('count')} | {e.get('zero_marker', {}).get('count')} |")
    print(f"- (a|b) 与 run_s0.C2_V13 逐行等价: {au['branch_split_consistent_with_C2_V13']}")
    gt = res["gates"]
    print()
    print("## gates（两套口径并列；标签逐字取自 GATE-AMENDMENT-v2.md §2）")
    og = gt["old_gate_both"]
    print(f"- 旧口径 gate_both（四版 D>=30）: {og['gate_both']}  per-grader: "
          + ", ".join(f"{g}={og['per_grader'][g]}" for g in gnames))
    ng = gt["new_gate_frozen"]
    dc = ng["direction_consistency_v1_0_v1_1_v1_2"]
    print(f"- 新冻结口径: v1.3 D={ng['v1_3_D']}（>=30: {ng['main_satisfied']}）；方向一致性 D>=R: "
          + ", ".join(f"{g} {dc[g]['D']}/{dc[g]['R']}→{dc[g]['D_ge_R']}" for g in dc))
    print(f"- label: {ng['label']}")
    print()
    print("## data quality")
    print(f"- fail rows: {dq['fail_rows']['count']} "
          f"{[r['key'] for r in dq['fail_rows']['rows']][:5]}")
    print(f"- duplicate ok keys: {dq['duplicate_ok']['keys_with_multiple_ok']} "
          f"{dq['duplicate_ok']['per_key_occurrences']}")
    mq = dq["missing_paired_keys"]
    print(f"- missing paired keys ({len(mq)}): {mq[:8]}{' ...' if len(mq) > 8 else ''}")
    print(f"- strata consistency: {st['consistency']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="S0 offline analysis（只读快照；判分/去重/配对复用 run_s0）")
    ap.add_argument("--calls", default=None,
                    help="calls.jsonl 路径（默认 <script_dir>/results/calls.jsonl）")
    ap.add_argument("--out", default=None,
                    help="输出 JSON 路径（默认 <script_dir>/results/analysis_s0.json）")
    ap.add_argument("--require-complete", action="store_true",
                    help=f"paired < {EXPECTED_PAIRS} 时退出码 3")
    ap.add_argument("--markdown", dest="markdown", action="store_true", default=True,
                    help="向 stdout 打印 markdown 表格（默认开启）")
    ap.add_argument("--no-markdown", dest="markdown", action="store_false",
                    help="关闭 stdout 表格")
    ap.add_argument("--now", default=None,
                    help="注入 ISO8601 时间戳（确定性自检用；默认当前时间，只写入 meta）")
    a = ap.parse_args(argv)

    calls_path = Path(a.calls) if a.calls else HERE / "results" / "calls.jsonl"
    out_path = Path(a.out) if a.out else HERE / "results" / "analysis_s0.json"
    if not calls_path.exists():
        print(f"[error] calls file not found: {calls_path}", file=sys.stderr)
        return 2
    rows, info = load_calls(calls_path)
    now_iso = a.now if a.now else datetime.now(timezone.utc).isoformat()
    res = analyze(rows, info, calls_path, now_iso, bool(a.now))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(res, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    if a.markdown:
        print_markdown(res)
    print(f"[out] {out_path}")
    if a.require_complete and res["meta"]["paired"] < EXPECTED_PAIRS:
        print(f"[require-complete] paired={res['meta']['paired']} < {EXPECTED_PAIRS} → exit 3",
              file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
