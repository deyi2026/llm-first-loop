#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 v1.4 grader 离线重判 S0 + S1（不重新调用模型）。

为什么离线重判：check 版本变化只影响判分，不影响已生成的 480 条回复文本；
重新生成会引入采样噪声、破坏配对。输入 sha 在 CALIBRATION-FREEZE-s1.json 中冻结。

输出：
- results/analysis_v14.json
- 控制台摘要（S0 D/R、S1 G1/G2/F1、与 v1.3 对照、注入测试）
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
S1_CALLS = HERE / "results" / "calls_s1.jsonl"
OUT = HERE / "results" / "analysis_v14.json"
ARMS = ("no_card", "gold_card", "filler_card")


def load() -> dict[tuple[str, str], dict]:
    s0 = S.dedupe([json.loads(l) for l in S0_CALLS.read_text(encoding="utf-8").splitlines() if l.strip()])
    s1 = S.dedupe([json.loads(l) for l in S1_CALLS.read_text(encoding="utf-8").splitlines() if l.strip()])
    idx = {}
    for r in s0 + s1:
        if r.get("ok"):
            idx[(r["instance_id"], r["arm"])] = r
    return idx


def cp(idx, i, arm):
    r = idx.get((i, arm))
    if not r:
        return None, None
    checks, st = G.grade(r["text"])
    return G.case_pass(checks), checks


def check_rates(idx, ids, arm):
    cnt = {k: 0 for k in G.CS}
    n = 0
    for i in ids:
        r = idx.get((i, arm))
        if not r:
            continue
        checks, _ = G.grade(r["text"])
        n += 1
        for k in G.CS:
            cnt[k] += bool(checks[k])
    return {"n": n, **{k: round(v / n, 4) for k, v in cnt.items()}}


def flips(idx, ids, a, b):
    out = {}
    for k in G.CS:
        up = down = 0
        for i in ids:
            ca, _ = cp(idx, i, a)
            cb, chb = cp(idx, i, b)
            if ca is None or cb is None:
                continue
            _, cha = cp(idx, i, a)
            if cha[k] is False and chb[k] is True:
                up += 1
            elif cha[k] is True and chb[k] is False:
                down += 1
        out[k] = {"fail2pass": up, "pass2fail": down}
    return out


def inject(text: str) -> str:
    """在每条编号项行尾注入成本/边界短语，检验 c3 是否只认措辞。"""
    out = []
    for ln in text.splitlines():
        if G.OPT_LINE.match(ln.strip()):
            ln = ln.rstrip() + "（成本低，只按字面处理，不执行动作）"
        out.append(ln)
    return "\n".join(out)


def main() -> int:
    idx = load()
    ids = sorted({i for (i, _) in idx})
    report = {"grader": "v1.4", "instances": len(ids), "arms": {}, "s0": {}, "s1": {}}

    # ---- S0: 主判据 v1.4 D>=30 + 方向一致性（旧版各自 D>=R，用原 grader）----
    D14 = [i for i in ids if cp(idx, i, "no_card")[0] is False and cp(idx, i, "orig_card")[0] is True]
    R14 = [i for i in ids if cp(idx, i, "no_card")[0] is True and cp(idx, i, "orig_card")[0] is False]
    report["s0"]["v1.4"] = {"D": len(D14), "R": len(R14), "D_ids": D14, "R_ids": R14,
                            "pass_D_ge_30": len(D14) >= 30}
    # 旧版方向（逐字复用冻结 grader）
    for gname in ("v1.0", "v1.1", "v1.2", "v1.3"):
        g = S.GRADERS[gname]
        d = r = 0
        for i in ids:
            a, b = idx.get((i, "no_card")), idx.get((i, "orig_card"))
            if not a or not b:
                continue
            ca = all(v is True for v in g(a["text"])[0].values())
            cb = all(v is True for v in g(b["text"])[0].values())
            d += (not ca) and cb
            r += ca and (not cb)
        report["s0"][gname] = {"D": d, "R": r}
    old_ok = all(report["s0"][g]["D"] >= report["s0"][g]["R"] for g in ("v1.0", "v1.1", "v1.2"))
    report["s0"]["directional_consistency_old"] = old_ok
    if len(D14) >= 30 and old_ok:
        label = "S0 directional positive — pending S1"
    elif len(D14) >= 30:
        label = "S0 mixed — revision flipped direction"
    else:
        label = "S0 no detectable effect under this instrument"
    report["s0"]["label"] = label

    # ---- S1 ----
    for arm in ARMS:
        report["arms"][arm] = check_rates(idx, ids, arm)
    gold_pass = [i for i in ids if cp(idx, i, "gold_card")[0] is True]
    filler_pass = [i for i in ids if cp(idx, i, "filler_card")[0] is True]
    report["s1"]["gold_case_pass"] = len(gold_pass)
    report["s1"]["filler_case_pass"] = len(filler_pass)
    for name, Dset in (("v1.3_D", [i for i in ids if S.GRADERS["v1.3"](idx[(i, "no_card")]["text"])[0] and not all(S.GRADERS["v1.3"](idx[(i, "no_card")]["text"])[0].values()) and all(S.GRADERS["v1.3"](idx[(i, "orig_card")]["text"])[0].values())]), ("v1.4_D", D14)):
        g1 = [i for i in Dset if cp(idx, i, "gold_card")[0]]
        kinds = set()
        for i in Dset:
            _, cn = cp(idx, i, "no_card")
            _, cg = cp(idx, i, "gold_card")
            for k in G.CS:
                if cn[k] is False and cg[k] is True:
                    kinds.add(k)
        report["s1"][name] = {"n": len(Dset), "G1": len(g1), "G1_ids": g1, "G2": sorted(kinds),
                             "G2_n": len(kinds), "gold_pass": len(g1) >= 2 and len(kinds) >= 2}
    f1 = [i for i in ids if cp(idx, i, "no_card")[0] is False and cp(idx, i, "filler_card")[0] is True]
    report["s1"]["F1"] = {"n": len(f1), "ids": f1, "pass": len(f1) == 0}
    report["s1"]["flips_gold"] = flips(idx, ids, "no_card", "gold_card")
    report["s1"]["flips_filler"] = flips(idx, ids, "no_card", "filler_card")

    # ---- 注入测试：F1 是否只靠措辞 ----
    inj = {}
    for arm in ("no_card", "filler_card", "gold_card"):
        before = after = 0
        for i in ids:
            r = idx.get((i, arm))
            if not r:
                continue
            before += cp(idx, i, arm)[0] is True
            checks, _ = G.grade(inject(r["text"]))
            after += G.case_pass(checks)
        inj[arm] = {"pass_before": before, "pass_after_inject": after, "newly": after - before}
    f1_inj = [i for i in ids if cp(idx, i, "no_card")[0] is False
              and G.case_pass(G.grade(inject(idx[(i, "filler_card")]["text"]))[0])]
    report["injection_test"] = {"arms": inj, "F1_after_inject": len(f1_inj), "F1_ids_after_inject": f1_inj}

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[S0 v1.4] D={len(D14)} R={len(R14)} D>=30:{len(D14)>=30} label={label}")
    for g in ("v1.0", "v1.1", "v1.2", "v1.3"):
        print(f"   {g}: D={report['s0'][g]['D']} R={report['s0'][g]['R']}")
    print(f"[S1 v1.4] gold_pass={len(gold_pass)}/120 filler_pass={len(filler_pass)}/120")
    for name in ("v1.3_D", "v1.4_D"):
        v = report["s1"][name]
        print(f"   {name}: G1={v['G1']} G2={v['G2']} ({v['G2_n']}) gold={'PASS' if v['gold_pass'] else 'FAIL'}")
    print(f"   F1={report['s1']['F1']['n']} pass={report['s1']['F1']['pass']}")
    print(f"[inject] {report['injection_test']['arms']}  F1_after_inject={len(f1_inj)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
