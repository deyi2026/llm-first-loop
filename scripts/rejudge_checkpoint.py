#!/usr/bin/env python3
"""按当前判定口径**离线重判**已落盘的跑批 checkpoint（不重跑 LLM）。

为什么需要（2026-10-23 真实发现）：
  域内 v2 跑批实测 22 样本中 5 个 verdict=False，其中 **4 个是 truncated=True**
  （达到最大轮数被中断）。原口径把截断样本计进分母 → 系统性低估通过率，
  把「执行预算不足」误报为「被测能力失败」。

本脚本：
  - 读 checkpoint.jsonl（每行 {scenario_id, sample, detail}）
  - 用**当前** verdicts.py 重算每个样本的 verdict（纯函数，不触网）
  - 按**当前**统计口径重算：passed / failed / truncated / scored / rate / Wilson CI
  - 输出 JSON + Markdown 到指定目录；**不覆盖**原 checkpoint（原样保留作原始证据）

用法:
    uv run --no-sync python scripts/rejudge_checkpoint.py \
        --checkpoint evals/results/eval_v2_m31flash_20261023/checkpoint.jsonl \
        --scenarios tests/eval_sets/scenarios_v2.json \
        --output evals/results/eval_v2_m31flash_20261023/rejudged
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.eval.verdicts import is_truncated_answer, run_verdict, wilson_ci  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args(argv)

    scen_doc = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in scen_doc["scenarios"]}

    rows = []
    for line in Path(args.checkpoint).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    per_scenario: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        sid = str(r["scenario_id"])
        d = r.get("detail", {})
        sc = by_id.get(sid)
        if sc is None:
            print(f"[warn] 未知场景 {sid}，跳过", file=sys.stderr)
            continue
        trace = d.get("trace") or []
        # 答复只存了前 200 字（answer_head）→ 截断识别用 is_truncated_answer 兜底
        answer_head = d.get("answer_head") or ""
        trunc = bool(d.get("truncated")) or is_truncated_answer(answer_head)
        verdict = run_verdict(
            sc["verdict"], trace, answer_head, sc.get("params"), truncated=trunc
        )
        per_scenario[sid].append(
            {
                "sample": d.get("sample"),
                "verdict": bool(verdict),
                "truncated": trunc,
                "rounds": d.get("rounds"),
                "tokens_in": d.get("tokens_in", 0),
                "tokens_out": d.get("tokens_out", 0),
                "original_verdict": d.get("verdict"),
                "original_truncated": d.get("truncated"),
            }
        )

    results = []
    for sid, items in per_scenario.items():
        sc = by_id[sid]
        n = len(items)
        n_trunc = sum(1 for i in items if i["truncated"])
        n_pass_all = sum(1 for i in items if i["verdict"])
        n_pass_scored = sum(1 for i in items if i["verdict"] and not i["truncated"])
        n_fail = sum(1 for i in items if not i["verdict"] and not i["truncated"])
        n_scored = n_pass_scored + n_fail
        lo, hi = wilson_ci(n_pass_all, n) if n else (0.0, 0.0)
        lo_s, hi_s = wilson_ci(n_pass_scored, n_scored) if n_scored else (0.0, 0.0)
        changed = sum(
            1 for i in items if i["verdict"] != bool(i["original_verdict"])
        )
        results.append(
            {
                "id": sid,
                "name": sc["name"],
                "verdict": sc["verdict"],
                "samples": n,
                "passed": n_pass_all,
                "failed": n_fail,
                "truncated": n_trunc,
                "scored": n_scored,
                "rate": (n_pass_all / n) if n else 0.0,
                "rate_scored": (n_pass_scored / n_scored) if n_scored else 0.0,
                "truncated_rate": (n_trunc / n) if n else 0.0,
                "ci": [round(lo, 3), round(hi, 3)],
                "ci_scored": [round(lo_s, 3), round(hi_s, 3)],
                "verdict_changed_vs_original": changed,
                "samples_detail": items,
            }
        )

    tot_n = sum(r["samples"] for r in results)
    tot_pass = sum(r["passed"] for r in results)
    tot_fail = sum(r["failed"] for r in results)
    tot_trunc = sum(r["truncated"] for r in results)
    tot_scored = sum(r["scored"] for r in results)
    tot_pass_scored = sum(r["passed"] - 0 for r in results)  # 占位，下面按场景累加
    tot_pass_scored = 0
    for r in results:
        tot_pass_scored += sum(
            1 for i in r["samples_detail"] if i["verdict"] and not i["truncated"]
        )
    lo, hi = wilson_ci(tot_pass, tot_n) if tot_n else (0.0, 0.0)
    lo_s, hi_s = wilson_ci(tot_pass_scored, tot_scored) if tot_scored else (0.0, 0.0)
    summary = {
        "scenarios": len(results),
        "samples": tot_n,
        "passed": tot_pass,
        "failed": tot_fail,
        "truncated": tot_trunc,
        "scored": tot_scored,
        "rate": (tot_pass / tot_n) if tot_n else 0.0,
        "rate_scored": (tot_pass_scored / tot_scored) if tot_scored else 0.0,
        "truncated_rate": (tot_trunc / tot_n) if tot_n else 0.0,
        "ci": [round(lo, 3), round(hi, 3)],
        "ci_scored": [round(lo_s, 3), round(hi_s, 3)],
        "note": "主口径 = 通过/全部样本（保守，截断计入分母）；参考率 = 通过/(通过+真失败)",
    }

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rejudged.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    md = [
        "# 离线重判报告（按截断分离口径）",
        "",
        f"> 输入 checkpoint: `{args.checkpoint}`",
        f"> 判定口径：{summary['note']}",
        "",
        "| 场景 | 通过/全部 | 截断 | 真失败 | 主口径率 | 参考率(排除截断) | Wilson 95% CI(主) | 与原判定不同的样本数 |",
        "|:---|:---|:---|:---|:---|:---|:---|:---|",
    ]
    for r in results:
        md.append(
            f"| {r['name']} | {r['passed']}/{r['samples']} | {r['truncated']} | {r['failed']} "
            f"| {r['rate']:.2f} | {r.get('rate_scored', 0.0):.2f} "
            f"| [{r['ci'][0]:.3f}, {r['ci'][1]:.3f}] | {r['verdict_changed_vs_original']} |"
        )
    md.append("")
    md.append(
        f"**合计**：主口径 {summary['passed']}/{summary['samples']} 通过"
        f"（率 {summary['rate']:.3f}，CI [{summary['ci'][0]:.3f}, {summary['ci'][1]:.3f}]）；"
        f"参考率（排除截断）{summary.get('rate_scored', 0.0):.3f}"
        f"（CI [{summary.get('ci_scored', [0, 0])[0]:.3f}, {summary.get('ci_scored', [0, 0])[1]:.3f}]）；"
        f"截断 {summary['truncated']}/{summary['samples']}"
        f"（{summary['truncated_rate']:.3f}）；真失败 {summary['failed']}。"
    )
    md.append("")
    md.append("> 纪律：样本不足如实标注；CI 区间重叠即不宣称统计显著；负结果同等呈现。")
    (out_dir / "rejudged.md").write_text("\n".join(md), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[重判] 已写出 {out_dir}/rejudged.json 与 rejudged.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
