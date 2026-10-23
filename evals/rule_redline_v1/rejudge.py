#!/usr/bin/env python3
"""红线批次的**离线重判**：同一批样本，换判据口径重算（不需要再跑 LLM）。

为什么需要它：2026-10-23 的判据迭代（v1→v2→v3）如果每次都重跑 108 条真实样本，
成本与时间都不可接受；而 run_eval.py 从 14:05 起已把 **answer_full** 落盘
（此前只留 200 字摘要 → 改判据就得重跑）。有了 answer_full 就能**离线重判**，
把"判据口径变了"与"模型表现变了"两件事分开。

用法::

    python3 evals/rule_redline_v1/rejudge.py \
        --checkpoint evals/results/rule_redline_v2_m31flash_20261023/checkpoint.jsonl \
        --spec judge_spec_v3.json --out evals/results/rejudge_v2batch_v3

    # 多口径并列
    python3 evals/rule_redline_v1/rejudge.py --checkpoint <ck> \
        --spec judge_spec_v2.json judge_spec_v3.json --out <dir>

口径（三口径，与 P1 域内一致）：
  · 主口径  rate        —— 截断样本计入分母（截断=没做到要求）
  · 参考口径 rate_scored —— 排除截断样本（只看真正答完的）
  · 截断率  truncated_rate
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.resolve().parents[1]  # evals/rule_redline_v1 -> 仓库根（**不是** parents[2]）
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

import llm_loop  # noqa: E402

# 2026-10-23 修：环境里装有**旧的** llm_loop（.releases/<sha>/src，非 editable），
# 一旦 sys.path 指错目录，就会静默 import 到旧包 → 'redline_v2' 判据不存在 →
# run_verdict 走"未知判据 → fail-closed" → **所有样本判不通过**（看起来像"全挂"）。
# 这里直接断言 import 到的是工作树代码，不对就当场报错，不让"静默用旧代码"发生。
if not str(Path(llm_loop.__file__).resolve()).startswith(str(_ROOT)):
    raise SystemExit(
        f"import 到的 llm_loop 不是工作树代码：{llm_loop.__file__}\n"
        f"期望前缀：{_ROOT}\n（用 .venv/bin/python 或修正 sys.path 后重跑）"
    )

from llm_loop.eval.verdicts import run_verdict, wilson_ci  # noqa: E402

_SPEC_KEYS = (
    "semantic_class",
    "forbidden",
    "context",
    "require",
    "legacy_verdict",
    "legacy_params",
    "allow_refusal_escape",
    "neg_scope",
)


def load_spec(name: str) -> dict:
    """取判据规格。特殊名 `recorded` → 空 spec → 全部用例沿用**批内记录判定**。

    `recorded` 这一档是"当时那批用的口径"（v1 旧判据 / v2 判据由批次当时加载的代码决定），
    用来和"用当前代码离线重判"做**同批同样本、只换判据**的对照。
    """
    if name == "recorded":
        return {}
    p = _HERE / name
    if not p.exists():
        raise SystemExit(f"判据规格不存在: {p}")
    return json.loads(p.read_text(encoding="utf-8")).get("cases", {})


def load_rows(checkpoint: Path) -> list[dict]:
    rows = []
    for line in checkpoint.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        d = rec.get("detail") or {}
        rows.append(
            {
                "case_id": rec.get("scenario_id", ""),
                "sample": rec.get("sample"),
                "answer": d.get("answer_full") or d.get("answer_head") or "",
                "has_full": "answer_full" in d,
                "trace": d.get("trace") or [],
                "recorded": bool(d.get("verdict")),
                "truncated": bool(d.get("truncated")),
                "rounds": d.get("rounds"),
            }
        )
    return rows


def judge(rows: list[dict], spec: dict, label: str) -> dict:
    per_case: dict[str, list[dict]] = defaultdict(list)
    judged: list[dict] = []
    for r in rows:
        c = spec.get(r["case_id"])
        if c is None:
            v = r["recorded"]  # 该用例未声明新口径 → 沿用批内记录判定
        else:
            params = {k: c[k] for k in _SPEC_KEYS if k in c}
            v = bool(run_verdict("redline_v2", r["trace"], r["answer"], params))
        r2 = dict(r)
        r2["verdict"] = v
        judged.append(r2)
        per_case[r["case_id"]].append(r2)
    rows = judged
    n = len(rows)
    n_trunc = sum(1 for r in rows if r["truncated"])
    n_pass = sum(1 for r in rows if r["verdict"])
    scored = [r for r in rows if not r["truncated"]]
    n_scored = len(scored)
    n_pass_scored = sum(1 for r in scored if r["verdict"])
    rate = n_pass / n if n else 0.0
    lo, hi = wilson_ci(n_pass, n) if n else (0.0, 0.0)
    rate_scored = n_pass_scored / n_scored if n_scored else 0.0
    slo, shi = wilson_ci(n_pass_scored, n_scored) if n_scored else (0.0, 0.0)
    return {
        "label": label,
        "n": n,
        "n_pass": n_pass,
        "rate": round(rate, 4),
        "rate_ci95": [round(lo, 3), round(hi, 3)],
        "n_truncated": n_trunc,
        "truncated_rate": round(n_trunc / n, 4) if n else 0.0,
        "n_scored": n_scored,
        "n_pass_scored": n_pass_scored,
        "rate_scored": round(rate_scored, 4),
        "rate_scored_ci95": [round(slo, 3), round(shi, 3)],
        "n_answer_full": sum(1 for r in rows if r["has_full"]),
        "per_case": {
            cid: {
                "n": len(rs),
                "n_pass": sum(1 for x in rs if x["verdict"]),
                "n_truncated": sum(1 for x in rs if x["truncated"]),
            }
            for cid, rs in sorted(per_case.items())
        },
        "rows": [
            {
                "case_id": r["case_id"],
                "sample": r["sample"],
                "verdict": r["verdict"],
                "truncated": r["truncated"],
            }
            for r in rows
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--spec", nargs="+", required=True, help="判据规格文件名（可多个）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", nargs="*", default=None)
    args = ap.parse_args()

    rows = load_rows(Path(args.checkpoint))
    if not rows:
        print("checkpoint 为空")
        return 2
    n_full = sum(1 for r in rows if r["has_full"])
    if n_full < len(rows):
        print(
            f"[WARN] {len(rows) - n_full}/{len(rows)} 条**没有 answer_full**（只有 200 字摘要）"
            f" → 重判只能看到摘要前 200 字，与原判定不完全可比（须在报告里注明）"
        )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for i, name in enumerate(args.spec):
        label = args.label[i] if args.label and i < len(args.label) else name.replace(".json", "")
        results.append(judge(rows, load_spec(name), label))
        r = results[-1]
        print(
            f"[{label}] n={r['n']} 通过={r['n_pass']} 主口径={r['rate']:.1%} "
            f"CI[{r['rate_ci95'][0]:.3f},{r['rate_ci95'][1]:.3f}] | 截断={r['n_truncated']} "
            f"({r['truncated_rate']:.1%}) | 参考口径 {r['rate_scored']:.1%} "
            f"({r['n_pass_scored']}/{r['n_scored']})"
        )
    (out / "rejudge.json").write_text(
        json.dumps({"checkpoint": args.checkpoint, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md = ["# 红线批次离线重判", "", f"批次：`{args.checkpoint}`　样本 {len(rows)} 条"
          f"（其中 {n_full} 条带 answer_full）", ""]
    for r in results:
        md += [
            f"## {r['label']}",
            "",
            f"- 主口径（截断计入分母）：**{r['rate']:.1%}**（{r['n_pass']}/{r['n']}）"
            f"　Wilson 95% CI [{r['rate_ci95'][0]:.3f}, {r['rate_ci95'][1]:.3f}]",
            f"- 截断率：{r['truncated_rate']:.1%}（{r['n_truncated']} 条）",
            f"- 参考口径（排除截断）：{r['rate_scored']:.1%}（{r['n_pass_scored']}/{r['n_scored']}）"
            f"　CI [{r['rate_scored_ci95'][0]:.3f}, {r['rate_scored_ci95'][1]:.3f}]",
            "",
            "| 用例 | n | 通过 | 截断 |",
            "|---|---|---|---|",
        ]
        for cid, s in r["per_case"].items():
            md.append(f"| {cid} | {s['n']} | {s['n_pass']} | {s['n_truncated']} |")
        md.append("")
    (out / "rejudge.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"报告 → {out / 'rejudge.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
