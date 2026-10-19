#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1b 判分：用 grade_v14 离线重判新批次 gold / filler_orth，no_card 继承 S0 基线。

门槛沿用 S1-SPEC（不改阈值），只把 filler 臂换成正交卡：
- G1（v1.4_D 上）>= 2，G2（v1.4_D 上）>= 2 -> gold PASS
- F1（全体实例 no_card fail -> filler_orth pass）= 0 -> filler PASS
并列 v1.3_D 口径、新旧 gold 批次一致性、注入测试（诊断项，不改门槛）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "s0_p28"))
sys.path.insert(0, str(ROOT))
import grade_v14 as G  # noqa: E402
import run_s0 as S  # noqa: E402

S0_CALLS = ROOT / "s0_p28" / "results" / "calls.jsonl"
OLD_S1_CALLS = ROOT / "s1_gold_filler" / "results" / "calls_s1.jsonl"
NEW_CALLS = HERE / "results" / "calls_s1b.jsonl"
FREEZE = HERE / "CALIBRATION-FREEZE-s1b.json"
OUT = HERE / "results" / "analysis_s1b.json"
OUT_MD = HERE / "results" / "analysis_s1b.md"
ARMS = ("no_card", "gold_card", "filler_orth_card")


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def idx_of(rows: list[dict]) -> dict[tuple[str, str], dict]:
    out = {}
    for r in rows:
        if r.get("ok"):
            out[(r["instance_id"], r["arm"])] = r
    return out


def cp(idx, i, arm):
    r = idx.get((i, arm))
    if not r:
        return None, None
    checks, _ = G.grade(r["text"])
    return G.case_pass(checks), checks


def check_rates(idx, ids, arm):
    cnt = {k: 0 for k in G.CS}
    n = 0
    for i in ids:
        if not idx.get((i, arm)):
            continue
        checks, _ = G.grade(idx[(i, arm)]["text"])
        n += 1
        for k in G.CS:
            cnt[k] += bool(checks[k])
    return {"n": n, **{k: round(v / n, 4) for k, v in cnt.items()}}


def flips(idx, ids, a, b):
    out = {}
    for k in G.CS:
        up = down = 0
        for i in ids:
            ca, cha = cp(idx, i, a)
            cb, chb = cp(idx, i, b)
            if ca is None or cb is None:
                continue
            up += (cha[k] is False and chb[k] is True)
            down += (cha[k] is True and chb[k] is False)
        out[k] = {"fail2pass": up, "pass2fail": down}
    return out


def inject(text: str) -> str:
    out = []
    for ln in text.splitlines():
        if G.OPT_LINE.match(ln.strip()):
            ln = ln.rstrip() + "（成本低，只按字面处理，不执行动作）"
        out.append(ln)
    return "\n".join(out)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (round((c - h) / d, 4), round((c + h) / d, 4))


def main() -> int:
    s0 = S.dedupe(load(S0_CALLS))
    new = S.dedupe(load(NEW_CALLS))
    old = S.dedupe(load(OLD_S1_CALLS)) if OLD_S1_CALLS.exists() else []
    idx = idx_of(s0 + new)
    old_idx = idx_of(old)

    nc_ids = sorted({r["instance_id"] for r in s0 if r.get("ok") and r.get("arm") == "no_card"})
    ids = nc_ids
    report = {"grader": "v1.4", "instances": len(ids), "arms": {}, "s1b": {}, "integrity": {}}

    # ---- 完整性 ----
    new_rows = [r for r in new]
    per_arm = {}
    for arm in ("gold_card", "filler_orth_card"):
        rr = [r for r in new_rows if r.get("arm") == arm]
        keys = [r.get("key") for r in rr if r.get("ok")]
        per_arm[arm] = {
            "n_ok": len(keys),
            "n_err": sum(1 for r in rr if not r.get("ok")),
            "dup_keys": len(keys) - len(set(keys)),
            "prompt_versions": sorted({r.get("prompt_version") for r in rr if r.get("ok")}),
            "models": sorted({r.get("model") for r in rr if r.get("ok")}),
            "card_sha256": sorted({r.get("card_sha256") for r in rr if r.get("ok")}),
        }
    report["integrity"] = {"arms": per_arm, "expected_instances": len(ids)}

    # ---- S0 v1.4 ----
    D14 = [i for i in ids if cp(idx, i, "no_card")[0] is False and cp(idx, i, "orig_card")[0] is True]
    R14 = [i for i in ids if cp(idx, i, "no_card")[0] is True and cp(idx, i, "orig_card")[0] is False]
    report["s0"] = {"D": len(D14), "R": len(R14), "D_ids": D14, "R_ids": R14}

    for arm in ARMS:
        report["arms"][arm] = check_rates(idx, ids, arm)

    # ---- G1/G2 ----
    def v13_pass(i, arm):
        checks, _ = S.GRADERS["v1.3"](idx[(i, arm)]["text"])
        return all(v is True for v in checks.values())  # void 全 None -> False

    d13 = [i for i in ids if not v13_pass(i, "no_card") and v13_pass(i, "orig_card")]
    for name, Dset in (("v1.4_D", D14), ("v1.3_D", d13)):
        g1 = [i for i in Dset if cp(idx, i, "gold_card")[0] is True]
        kinds = set()
        for i in Dset:
            _, cn = cp(idx, i, "no_card")
            _, cg = cp(idx, i, "gold_card")
            for k in G.CS:
                if cn[k] is False and cg[k] is True:
                    kinds.add(k)
        report["s1b"][name] = {"n": len(Dset), "G1": len(g1), "G1_ids": g1,
                               "G2_n": len(kinds), "G2": sorted(kinds),
                               "gold_pass": len(g1) >= 2 and len(kinds) >= 2}

    # ---- F1 ----
    f1 = [i for i in ids if cp(idx, i, "no_card")[0] is False and cp(idx, i, "filler_orth_card")[0] is True]
    report["s1b"]["F1"] = {"n": len(f1), "ids": f1, "pass": len(f1) == 0}
    report["s1b"]["flips_gold"] = flips(idx, ids, "no_card", "gold_card")
    report["s1b"]["flips_filler_orth"] = flips(idx, ids, "no_card", "filler_orth_card")

    # ---- 描述性：rate + CI ----
    for arm in ARMS:
        n = sum(1 for i in ids if idx.get((i, arm)))
        k = sum(1 for i in ids if cp(idx, i, arm)[0] is True)
        report["arms"][arm]["case_pass"] = k
        report["arms"][arm]["rate"] = round(k / n, 4) if n else None
        report["arms"][arm]["ci95"] = wilson(k, n)

    # ---- 新旧 gold 批次一致性 ----
    both = [i for i in ids if idx.get((i, "gold_card")) and old_idx.get((i, "gold_card"))]
    agree = sum(1 for i in both if cp(idx, i, "gold_card")[0] == cp(old_idx, i, "gold_card")[0])
    both_pass = sum(1 for i in both if cp(idx, i, "gold_card")[0] is True and cp(old_idx, i, "gold_card")[0] is True)
    report["gold_batch_consistency"] = {
        "n": len(both), "agree": agree,
        "agree_rate": round(agree / len(both), 4) if both else None,
        "both_pass": both_pass,
        "old_pass": sum(1 for i in both if cp(old_idx, i, "gold_card")[0] is True),
        "new_pass": sum(1 for i in both if cp(idx, i, "gold_card")[0] is True),
    }

    # ---- 注入（诊断，不改门槛）----
    inj = {}
    for arm in ARMS:
        before = after = 0
        for i in ids:
            if not idx.get((i, arm)):
                continue
            before += cp(idx, i, arm)[0] is True
            checks, _ = G.grade(inject(idx[(i, arm)]["text"]))
            after += G.case_pass(checks)
        inj[arm] = {"pass_before": before, "pass_after_inject": after, "newly": after - before}
    f1_inj = [i for i in ids if cp(idx, i, "no_card")[0] is False
              and G.case_pass(G.grade(inject(idx[(i, "filler_orth_card")]["text"]))[0])]
    report["injection_test"] = {"arms": inj, "F1_after_inject": len(f1_inj),
                                "F1_ids_after_inject": f1_inj}

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- md ----
    L = ["# S1b：gold vs 正交 filler 阴性对照（v1.4 grader）", "",
         f"- 实例数：{len(ids)}；新批次两臂：gold_card / filler_orth_card；no_card 继承 S0。", ""]
    L += ["## 臂汇总", "", "| arm | n | case_pass | rate | 95% CI | c1 | c2 | c3 | c4 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for arm in ARMS:
        a = report["arms"][arm]
        L.append(f"| {arm} | {a['n']} | {a['case_pass']} | {a['rate']} | "
                 f"[{a['ci95'][0]}, {a['ci95'][1]}] | {a['c1']} | {a['c2']} | {a['c3']} | {a['c4']} |")
    L += ["", "## 门槛", ""]
    for name in ("v1.4_D", "v1.3_D"):
        v = report["s1b"][name]
        L.append(f"- {name}（n={v['n']}）：G1={v['G1']}（≥2）G2={v['G2_n']} {v['G2']}（≥2）"
                 f"→ gold {'PASS' if v['gold_pass'] else 'FAIL'}")
    f = report["s1b"]["F1"]
    L.append(f"- F1={f['n']}（=0）→ filler_orth {'PASS' if f['pass'] else 'FAIL'}"
             + (f"；翻动：{'、'.join(f['ids'])}" if f["ids"] else ""))
    gb = report["gold_batch_consistency"]
    L += ["", "## 新旧 gold 批次一致性（描述性）", "",
          f"- 可比实例 {gb['n']}；case_pass 一致 {gb['agree']}（{gb['agree_rate']}）；"
          f"旧 pass {gb['old_pass']} / 新 pass {gb['new_pass']}；两批都 pass {gb['both_pass']}。"]
    L += ["", "## 注入测试（诊断，不改门槛）", ""]
    for arm, v in report["injection_test"]["arms"].items():
        L.append(f"- {arm}: {v['pass_before']} → {v['pass_after_inject']}（+{v['newly']}）")
    L.append(f"- F1 after inject = {report['injection_test']['F1_after_inject']}")
    L += ["", "## 完整性", ""]
    for arm, v in per_arm.items():
        L.append(f"- {arm}: ok={v['n_ok']} err={v['n_err']} dup={v['dup_keys']} "
                 f"pv={v['prompt_versions']} model={v['models']} card_sha={v['card_sha256']}")
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"[S1b] instances={len(ids)}")
    for arm in ARMS:
        a = report["arms"][arm]
        print(f"  {arm:<18} pass={a['case_pass']}/{a['n']} rate={a['rate']} "
              f"c1={a['c1']} c2={a['c2']} c3={a['c3']} c4={a['c4']}")
    for name in ("v1.4_D", "v1.3_D"):
        v = report["s1b"][name]
        print(f"  {name}: G1={v['G1']} G2={v['G2_n']}{v['G2']} gold={'PASS' if v['gold_pass'] else 'FAIL'}")
    print(f"  F1={f['n']} pass={f['pass']}")
    print(f"  gold_batch: {report['gold_batch_consistency']}")
    print(f"  inject: {report['injection_test']['arms']} F1_inj={report['injection_test']['F1_after_inject']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
