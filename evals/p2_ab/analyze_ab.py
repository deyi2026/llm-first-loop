#!/usr/bin/env python3
"""P2 A/B 结果分析：两臂三口径 + Wilson CI + Δpass@1（Newcombe 区间）+ 存续率。

口径与 P1 一致（见计划 §21.1）：
  rate          通过 / 全部样本（截断计入分母）—— 主口径，对外用
  rate_scored   通过 / (通过 + 真失败) —— 排除截断后的能力上界
  truncated_rate 截断 / 全部样本 —— 预算不足的直接度量

Δpass@1 的区间用 Newcombe 混合评分法（两 Wilson 区间组合），n 小时区间很宽属预期，
不因此改口径。

用法::

    python3 evals/p2_ab/analyze_ab.py --out evals/results/p2ab_v1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

from llm_loop.eval.verdicts import wilson_ci  # noqa: E402


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            # 半行（kill -9 落点）→ 跳过该行，不让续跑整体崩
            continue
    return out


def _arm_stats(recs: list[dict]) -> dict:
    n = len(recs)
    if n == 0:
        return {"n": 0}
    passed = [r for r in recs if r["verdict"]]
    trunc = [r for r in recs if r["truncated"]]
    real_fail = [r for r in recs if not r["verdict"] and not r["truncated"]]
    # 2026-10-23 v4（独立审查 P0-3 修正）：参考口径必须**全量排除截断**——
    # 原实现 scored = len(passed) + len(real_fail) 把「截断但通过」的样本留在分子与分母，
    # 与 run_eval.py（verdict and not truncated）、rejudge.py（rows if not truncated）
    # 两处同名口径不一致 → 同一名词三种口径，Δ 被拉偏（实测 -9.5pp → -8.6pp）。
    scored_recs = [r for r in recs if not r["truncated"]]
    scored = len(scored_recs)
    scored_pass = sum(1 for r in scored_recs if r["verdict"])
    rate = len(passed) / n
    lo, hi = wilson_ci(len(passed), n)
    s_lo, s_hi = wilson_ci(scored_pass, scored) if scored else (0.0, 0.0)
    comp = [r for r in recs if r.get("compaction_events", 0) > 0]
    survived = [r for r in comp if r.get("survived_compaction")]
    return {
        "n": n,
        "pass": len(passed),
        "truncated": len(trunc),
        "real_fail": len(real_fail),
        "rate": round(rate, 4),
        "rate_ci95": [round(lo, 4), round(hi, 4)],
        "rate_scored": round(len(passed) / scored, 4) if scored else None,
        "rate_scored_ci95": [round(s_lo, 4), round(s_hi, 4)] if scored else None,
        "truncated_rate": round(len(trunc) / n, 4),
        "tokens_in_avg": round(sum(r.get("tokens_in", 0) for r in recs) / n, 1),
        "tokens_out_avg": round(sum(r.get("tokens_out", 0) for r in recs) / n, 1),
        "rounds_avg": round(sum(r.get("rounds", 0) for r in recs) / n, 2),
        "compacted_n": len(comp),
        "compaction_rate": round(len(comp) / n, 4),
        "survived_n": len(survived),
        "survival_rate": round(len(survived) / len(comp), 4) if comp else None,
        "events_read_ok": sum(1 for r in recs if r.get("events_read_ok", True)),
        "events_read_fail": sum(1 for r in recs if not r.get("events_read_ok", True)),
        "elapsed_s_total": round(sum(r.get("elapsed_s", 0) for r in recs), 1),
    }


def _newcombe_diff(
    x2: int, n2: int, x1: int, n1: int
) -> tuple[float | None, float | None, float | None]:
    """Δ = p2 - p1 的 Newcombe(1998) method 10 混合评分 95% 区间。

    公式（D = p1 - p2 的标准式，Newcombe 1998 method 10）：
        lo(D) = D - sqrt[(p1-l1)^2 + (u2-p2)^2]
        hi(D) = D + sqrt[(u1-p1)^2 + (p2-l2)^2]
    本函数取 D = p2 - p1（负镜像），故两处 radicand 随之互换：
        lo = d - sqrt[(u1-p1)^2 + (p2-l2)^2]
        hi = d + sqrt[(p1-l1)^2 + (u2-p2)^2]
    （2026-10-23 二轮复审 P0-1：此前把两个 radicand 挂反了侧，区间整体关于 d 镜像。）

    任一侧 n=0 → 返回 (None, None, None)：**没有口径**，不虚构 0 差异。
    """
    if n1 == 0 or n2 == 0:
        return None, None, None
    p1, p2 = x1 / n1, x2 / n2
    l1, u1 = wilson_ci(x1, n1)
    l2, u2 = wilson_ci(x2, n2)
    d = p2 - p1
    lo = d - ((u1 - p1) ** 2 + (p2 - l2) ** 2) ** 0.5
    hi = d + ((p1 - l1) ** 2 + (u2 - p2) ** 2) ** 0.5
    return d, max(-1.0, lo), min(1.0, hi)


def _fmt_pct(v: float | None) -> str:
    """None → 「—」（不写 0.0%/nan%，那会把"无分母"说成"0%"或"NaN%"）。"""
    return "—" if v is None else f"{v:.1%}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    a = _load(out / "checkpoint_A.jsonl")
    b = _load(out / "checkpoint_B.jsonl")
    if not a and not b:
        print("[FATAL] 没有样本", file=sys.stderr)
        return 2

    sa, sb = _arm_stats(a), _arm_stats(b)
    d, dlo, dhi = _newcombe_diff(sb.get("pass", 0), sb.get("n", 0), sa.get("pass", 0), sa.get("n", 0))
    d_txt = (
        f"{d:+.1%}，CI [{dlo:+.1%}, {dhi:+.1%}]"
        if d is not None and dlo is not None and dhi is not None
        else "—（有一侧无样本，无口径）"
    )
    # P1-3：分母为 0 时不虚构 n=1 —— 直接判"无口径"，报告写 n/a
    sa_scored = sa.get("pass", 0) + sa.get("real_fail", 0)
    sb_scored = sb.get("pass", 0) + sb.get("real_fail", 0)
    if sa_scored and sb_scored:
        d_sc, d_sc_lo, d_sc_hi = _newcombe_diff(sb.get("pass", 0), sb_scored, sa.get("pass", 0), sa_scored)
        d_sc_txt = f"{d_sc:+.1%}，CI [{d_sc_lo:+.1%}, {d_sc_hi:+.1%}]"
    else:
        d_sc, d_sc_lo, d_sc_hi = None, None, None
        d_sc_txt = "—（有一侧无有效样本，无口径）"

    scen_ids = sorted({r["scenario_id"] for r in a + b})
    per_scen = []
    for sid in scen_ids:
        ra = [r for r in a if r["scenario_id"] == sid]
        rb = [r for r in b if r["scenario_id"] == sid]
        per_scen.append(
            {
                "scenario_id": sid,
                "A_n": len(ra),
                "A_pass": sum(1 for r in ra if r["verdict"]),
                "A_trunc": sum(1 for r in ra if r["truncated"]),
                "A_compact": sum(1 for r in ra if r.get("compaction_events", 0) > 0),
                "B_n": len(rb),
                "B_pass": sum(1 for r in rb if r["verdict"]),
                "B_trunc": sum(1 for r in rb if r["truncated"]),
                "B_compact": sum(1 for r in rb if r.get("compaction_events", 0) > 0),
            }
        )

    # ── 共同子集对照（2026-10-23 新增）────────────────────────────────
    # 两臂**进度不同**时（实测 A 21 条 / B 32 条），总体 Δ 是"不同场景组合"的差值，
    # 不可解释（混淆：场景 mix 不同）。这里额外给一档"只比两臂都跑过的场景"的对照，
    # 中间结论只认这一档。
    common = sorted({r["scenario_id"] for r in a} & {r["scenario_id"] for r in b})
    # 每个场景按 min(n_A, n_B) **截齐**（2026-10-23 v4，独立审查 P1-3）：
    # 不截齐时池化 Δ 的场景权重不同（实测 rule08_adjust_step A=5 / B=6）→ 差值里
    # 混着"样本条数不同"的分母效应。截齐后两臂在每个场景上样本数完全一致。
    ca: list[dict] = []
    cb: list[dict] = []
    for sid in common:
        ra = [r for r in a if r["scenario_id"] == sid]
        rb = [r for r in b if r["scenario_id"] == sid]
        k = min(len(ra), len(rb))
        ca += ra[:k]
        cb += rb[:k]
    csa, csb = _arm_stats(ca), _arm_stats(cb)
    cd, cdlo, cdhi = _newcombe_diff(
        csb.get("pass", 0), csb.get("n", 0), csa.get("pass", 0), csa.get("n", 0)
    )
    cd_txt = (
        f"{cd:+.1%}，CI [{cdlo:+.1%}, {cdhi:+.1%}]"
        if cd is not None and cdlo is not None and cdhi is not None
        else "—（有一侧无样本，无口径）"
    )

    report = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "arms": {"A": sa, "B": sb},
        "delta_pass1": round(d, 4),
        "delta_pass1_ci95": [round(dlo, 4), round(dhi, 4)],
        "delta_rate_scored": round(d_sc, 4) if (sa_scored and sb_scored) else None,
        "delta_rate_scored_ci95": [round(d_sc_lo, 4), round(d_sc_hi, 4)] if (sa_scored and sb_scored) else None,
        "common_subset": {
            "scenario_ids": common,
            "A": csa,
            "B": csb,
            "delta_pass1": round(cd, 4) if cd is not None else None,
            "delta_pass1_ci95": [round(cdlo, 4), round(cdhi, 4)] if cdlo is not None else None,
        },
        "per_scenario": per_scen,
        "caveats": [
            "域内 A/B 用的是 P1 的域内 v2 场景集（14 场景 × 6 样本 = 84/臂）→ 结论只到 C 级"
            "（域内单 provider 激发任务），不得据此 promotion；promotion 只认 held-out 验证跑。",
            "A/B 两臂唯一差异是 EVIDENCE_MODE（off vs enforce）；若两臂压缩发生率都接近 0，"
            "则该候选在本任务集上没有触发条件，Δ≈0 应读作『无触发』而非『候选无效』。",
            "单 provider（minimax/MiniMax-M3.1-Flash，依 D-2 用户决策）→ 能力类结论不可外推（D4）。",
            "n 小时区间宽度大属预期，不因区间跨 0 改口径或改 n。",
        ],
    }
    (out / "p2ab_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md = [
        "# P2 A/B 对照报告（域内候选场景，探索级）",
        "",
        f"生成时间：{report['generated_at']}",
        "",
        "## 总体",
        "",
        "| 臂 | n | 通过 | 主口径 rate | 参考率 rate_scored | 截断率 | 压缩发生率 | tokens_in 均值 | 轮数均值 |",
        "|---|---|---|---|---|---|---|---|---|",
        f"| A 基线（EVIDENCE_MODE=off） | {sa.get('n',0)} | {sa.get('pass',0)} | "
        f"{sa.get('rate',0):.1%} [{sa.get('rate_ci95',[0,0])[0]:.1%},{sa.get('rate_ci95',[0,0])[1]:.1%}] | "
        f"{_fmt_pct(sa.get('rate_scored'))} | {sa.get('truncated_rate',0):.1%} | {sa.get('compaction_rate',0):.1%} | "
        f"{sa.get('tokens_in_avg',0):,.0f} | {sa.get('rounds_avg',0):.1f} |"
        if sa.get("n")
        else "| A 基线 | （无样本） | — | — | — | — | — | — | — |",
        f"| B 候选（EVIDENCE_MODE=enforce） | {sb.get('n',0)} | {sb.get('pass',0)} | "
        f"{sb.get('rate',0):.1%} [{sb.get('rate_ci95',[0,0])[0]:.1%},{sb.get('rate_ci95',[0,0])[1]:.1%}] | "
        f"{_fmt_pct(sb.get('rate_scored'))} | {sb.get('truncated_rate',0):.1%} | {sb.get('compaction_rate',0):.1%} | "
        f"{sb.get('tokens_in_avg',0):,.0f} | {sb.get('rounds_avg',0):.1f} |"
        if sb.get("n")
        else "| B 候选 | （无样本） | — | — | — | — | — | — | — |",
        "",
        "> tokens_in / 轮数两列是**同预算**证据：两臂同一场景集、同一模型、同一 max_iterations，",
        "> 差异只来自候选开关 → 轮数与 token 的变化可直接归给候选。",
        "",
        f"**Δpass@1（B−A，主口径）= {d_txt}**（Newcombe 95% CI）",
        "",
        f"Δrate_scored（B−A，排除截断）= {d_sc_txt}",
        "",
        "## 共同子集对照（只比两臂都跑过的场景 —— 中间结论只认这一档）",
        "",
        f"- 共同场景 {len(common)} 个：{', '.join(common) if common else '（无）'}",
        f"- A：n={csa.get('n',0)}　通过={csa.get('pass',0)}　主口径={_fmt_pct(csa.get('rate'))}"
        f"　参考口径={_fmt_pct(csa.get('rate_scored'))}",
        f"- B：n={csb.get('n',0)}　通过={csb.get('pass',0)}　主口径={_fmt_pct(csb.get('rate'))}"
        f"　参考口径={_fmt_pct(csb.get('rate_scored'))}",
        f"- **Δpass@1（共同子集）= {cd_txt}**",
        "",
        "> 总体 Δ 的两臂**进度/场景组合不同**（跑批中常见）→ 总体 Δ 混了场景 mix 差异，",
        "> 不可解释；本档把两臂都跑过的场景单独取出来再比。",
        "",
        "## 压缩后存续率（压缩发生的样本中，取回归档证据的比例）",
        "",
        f"- A：{_fmt_pct(sa.get('survival_rate'))}（{sa.get('survived_n',0)}/{sa.get('compacted_n',0)}）",
        f"- B：{_fmt_pct(sb.get('survival_rate'))}（{sb.get('survived_n',0)}/{sb.get('compacted_n',0)}）",
        f"- 事件日志读取失败数（读不到 → 压缩发生率不可信）：A {sa.get('events_read_fail',0)} / B {sb.get('events_read_fail',0)}",
        "",
        "## 分场景",
        "",
        "| 场景 | A n | A 通过 | A 截断 | A 压缩 | B n | B 通过 | B 截断 | B 压缩 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in per_scen:
        md.append(
            f"| {s['scenario_id']} | {s['A_n']} | {s['A_pass']} | {s['A_trunc']} | {s['A_compact']} | "
            f"{s['B_n']} | {s['B_pass']} | {s['B_trunc']} | {s['B_compact']} |"
        )
    md += ["", "## 口径与限制", ""]
    for c in report["caveats"]:
        md.append(f"- {c}")
    (out / "p2ab_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Δpass@1 = {d:+.1%}  CI [{dlo:+.1%}, {dhi:+.1%}]")
    print(f"报告 → {out / 'p2ab_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
