#!/usr/bin/env python3
"""held-out 强隔离核验（D-3）：held-out 任务**不得**出现在任何跑批产物里。

为什么要单独一个脚本：先前用 `grep heldout` 查 checkpoint 会误报 —— 被测模型在
场景里执行过 `ls evals/heldout/` 这类命令，文本里就出现了 "heldout" 字样。
**隔离要看的是任务 id 集合的交集，不是文本里有没有那个词。**

用法::

    python3 evals/heldout/v1/verify_isolation.py            # 查仓库内全部跑批产物
    python3 evals/heldout/v1/verify_isolation.py --results evals/results/foo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.resolve().parents[2]


def heldout_ids() -> set[str]:
    man = json.loads((_HERE / "manifest.json").read_text(encoding="utf-8"))
    tasks = man.get("tasks") or man.get("items") or []
    return {t.get("id") or t.get("task_id") for t in tasks if t.get("id") or t.get("task_id")}


def ran_scenario_ids(results_root: Path) -> set[str]:
    out: set[str] = set()
    for p in results_root.rglob("checkpoint*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = d.get("scenario_id") or d.get("case_id") or ""
            if sid:
                out.add(sid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, default=_ROOT / "evals" / "results")
    args = ap.parse_args()
    hid = heldout_ids()
    ran = ran_scenario_ids(args.results)
    overlap = sorted(hid & ran)
    print(f"held-out 任务 id：{len(hid)} 个")
    print(f"跑批产物里出现过的 scenario_id：{len(ran)} 个")
    if overlap:
        print(f"[FAIL] 交集 {len(overlap)} 个 → held-out 已被触碰：{overlap}")
        return 1
    print("[PASS] 交集为空 → held-out 未被跑过，D-3 强隔离成立")
    return 0


if __name__ == "__main__":
    sys.exit(main())
