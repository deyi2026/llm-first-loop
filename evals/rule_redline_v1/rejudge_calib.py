#!/usr/bin/env python3
"""离线重判校准样本的「自动谓词判定」（判据规格版本对齐用）。

背景（2026-10-23）：校准批次的 auto_verdict 是**跑批进程启动那一刻**加载的
判据代码 + 规格算出来的；之后若判据代码/规格升级，跑批产物的自动判定就与
当前冻结口径不一致。此脚本用**同一批 LLM 回答**（不改模型输出）按指定规格
离线重算自动判定，供独立审阅者做无偏一致率比对。

用法::

    # 先看差异（不写盘）
    python3 evals/rule_redline_v1/rejudge_calib.py --dir evals/results/redline_calibration_v3_20261023

    # 写回（保留原判定为 auto_verdict_prev，标注所用规格）
    python3 evals/rule_redline_v1/rejudge_calib.py --dir <dir> --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_HERE))

from llm_loop.eval.verdicts import run_verdict  # noqa: E402
import run_redline as rr  # noqa: E402


def case_params(case_id: str, spec: dict) -> tuple[str, dict]:
    """返回 (谓词名, 参数) —— 与 run_redline.build_scenarios 完全同构。"""
    index = {c["case_id"]: c for c in rr.load_index()}
    c = index[case_id]
    verdict = c["verdict"]
    params = {"rule": "REDLINE", "expect": c["expect"], "category": c["category"]}
    js = spec.get(case_id)
    if js:
        verdict = "redline_v2"
        params.update(js)
    return verdict, params


def main() -> int:
    ap = argparse.ArgumentParser(description="校准样本自动判定离线重判")
    ap.add_argument("--dir", required=True, help="校准批次输出目录")
    ap.add_argument("--spec", default="judge_spec_v4.json", help="判据规格文件名（相对 evals/rule_redline_v1/）")
    ap.add_argument("--apply", action="store_true", help="写回 calibration_items.json")
    args = ap.parse_args()

    out = Path(args.dir)
    items_path = out / "calibration_items.json"
    data = json.loads(items_path.read_text(encoding="utf-8"))
    spec = rr.load_judge_spec(args.spec)
    if not spec:
        print(f"[warn] 规格 {args.spec} 不存在或为空 → 只用 v1 旧口径", flush=True)

    changed: list[tuple[str, str, bool, bool]] = []
    for it in data["items"]:
        verdict, params = case_params(it["case_id"], spec)
        new = bool(run_verdict(verdict, it.get("trace") or [], it.get("answer") or "", params))
        old = bool(it.get("auto_verdict"))
        if new != old:
            changed.append((it["item_id"], it["case_id"], old, new))
        # v5.1（独立审查 P2-2）：二次 --apply 不能用"已重判过的值"覆盖原始判定
        # → auto_verdict_prev 只在第一次写，之后保持不变。
        it.setdefault("auto_verdict_prev", old)
        it["auto_verdict"] = new
        it["auto_verdict_spec"] = args.spec
        it["auto_verdict_predicate"] = verdict

    print(f"[rejudge] 规格={args.spec} 样本={len(data['items'])} 判定变化={len(changed)}", flush=True)
    for iid, cid, old, new in changed:
        print(f"  {iid} {cid}: {old} → {new}", flush=True)

    if args.apply:
        backup = out / "calibration_items.pre_rejudge.json"
        if not backup.exists():
            shutil.copy2(items_path, backup)
            print(f"[rejudge] 原判定已备份 → {backup}", flush=True)
        data["rejudged_with_spec"] = args.spec
        items_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[rejudge] 已写回 {items_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
