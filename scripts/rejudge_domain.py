#!/usr/bin/env python3
"""域内场景批次的**离线重判**（判据版本变更后，用同一批模型回答重算判定）。

用法::

    .venv/bin/python scripts/rejudge_domain.py \
      --checkpoint evals/results/eval_v2_m31flash_20261023/checkpoint.jsonl \
      --scenarios tests/eval_sets/scenarios_v2.json \
      --out evals/results/rejudge_domain_v5

说明：
- **不重跑模型**：只重算判定（trace + 回答都已落盘）。
- 批次里若只有 ``answer_head``（200 字摘要）而无 ``answer_full``，
  则按摘要重判，并在输出里标注 ``answer_source=head`` —— 结论按"近似"对待。
- 场景 params 里的 ``${MODEL}`` 用**该样本实际使用的模型**注入
  （model_used），保证判据针对"本次被测模型"。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from llm_loop.eval.verdicts import run_verdict, wilson_ci  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="域内批次离线重判")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--label", default="rejudge")
    args = ap.parse_args()

    sc_data = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
    scenarios = {s["id"]: s for s in sc_data["scenarios"]}
    rows = [json.loads(line) for line in Path(args.checkpoint).read_text(encoding="utf-8").splitlines() if line.strip()]

    by_scn: dict[str, list[dict]] = defaultdict(list)
    diffs: list[dict] = []
    head_only = 0
    # v5.1（独立审查 P2-3）：样本缺 model_used 时**不能**把 expected 置空
    # （那会静默削弱 identity 判据）→ 用本批次的**主导模型**兜底并告警。
    used_models = [str((r.get("detail") or {}).get("model_used") or "").strip() for r in rows]
    dominant = max(set(m for m in used_models if m), key=lambda m: used_models.count(m), default="")
    missing_model = 0
    for r in rows:
        sid = r["scenario_id"]
        d = r.get("detail") or {}
        sc = scenarios.get(sid)
        if sc is None:
            print(f"[warn] 场景集里没有 {sid}，跳过", flush=True)
            continue
        params = dict(sc.get("params") or {})
        if params.get("expected") == "${MODEL}":
            model_ref = (d.get("model_used") or "").strip() or dominant
            if not (d.get("model_used") or "").strip():
                missing_model += 1
            if not model_ref:
                # v5.2（独立审查第 2 轮 P2-3）：expected 置空会让 identity 判据
                # 静默退化成"只看未核验措辞" → 必须显式失败，不静默降级。
                raise SystemExit(
                    "[fatal] 样本缺 model_used 且本批没有主导模型 → 无法重判 identity 场景"
                )
            params["expected"] = model_ref
        answer = d.get("answer_full")
        src = "full"
        if not answer:
            answer = d.get("answer_head") or ""
            src = "head"
            head_only += 1
        verdict = bool(run_verdict(sc["verdict"], d.get("trace") or [], answer, params))
        old = bool(d.get("verdict"))
        by_scn[sid].append({"verdict": verdict, "old": old, "truncated": bool(d.get("truncated")), "src": src})
        if verdict != old:
            diffs.append({
                "scenario_id": sid, "sample": d.get("sample"), "old": old, "new": verdict,
                "answer_source": src, "rounds": d.get("rounds"),
            })

    if missing_model:
        print(f"[warn] {missing_model} 条样本缺 model_used → 用本批主导模型 {dominant!r} 兜底", flush=True)
    total = sum(len(v) for v in by_scn.values())
    passed = sum(1 for v in by_scn.values() for x in v if x["verdict"])
    trunc = sum(1 for v in by_scn.values() for x in v if x["truncated"])
    lo, hi = wilson_ci(passed, total)
    lines = [
        f"# 域内批次离线重判（{args.label}）",
        "",
        f"- checkpoint：`{args.checkpoint}`",
        f"- 场景集：`{args.scenarios}`",
        f"- 样本 {total} 条；判定通过 {passed} = {passed / total:.1%}（Wilson 95% CI [{lo:.3f}, {hi:.3f}]）",
        f"- 截断 {trunc} 条 = {trunc / total:.1%}",
        f"- 判定变化 {len(diffs)} 条"
        + (f"（{head_only}/{total} 条样本只有 200 字摘要，按摘要重判 → 近似）" if head_only else ""),
        "",
        "| 场景 | 判定 | 旧判定 | 新判定 | 截断 |",
        "|---|---|---|---|---|",
    ]
    for sid, items in by_scn.items():
        n = len(items)
        p = sum(1 for x in items if x["verdict"])
        t = sum(1 for x in items if x["truncated"])
        o = sum(1 for x in items if x.get("old"))
        lines.append(f"| {sid} | {p}/{n} | {o}/{n} | {p}/{n} | {t} |")
    lines += ["", "## 判定变化明细", ""]
    if diffs:
        lines += ["| 场景 | 样本 | 旧 | 新 | 回答来源 | 轮数 |", "|---|---|---|---|---|---|"]
        for d in diffs:
            lines.append(
                f"| {d['scenario_id']} | {d['sample']} | {'PASS' if d['old'] else 'FAIL'} "
                f"| {'PASS' if d['new'] else 'FAIL'} | {d['answer_source']} | {d['rounds']} |"
            )
    else:
        lines.append("（无变化）")
    text = "\n".join(lines) + "\n"
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.label}.md").write_text(text, encoding="utf-8")
        (out / f"{args.label}.json").write_text(
            json.dumps({"total": total, "passed": passed, "ci": [lo, hi], "truncated": trunc,
                        "diffs": diffs, "head_only": head_only}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(text)
        print(f"[rejudge] 已写出 {out / (args.label + '.md')}", flush=True)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
