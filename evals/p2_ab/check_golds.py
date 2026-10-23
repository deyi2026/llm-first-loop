#!/usr/bin/env python3
"""金标准自检：场景 must_contain / any_of 的每条子串必须真实存在于被引文件里。

金标准写错 → 场景恒判失败（假阴性），A/B 会得出"候选无效"的错误结论。
本脚本在跑批前逐条核对，不通过即退出码 2。

被引文件来源：SCENARIO_FILES 人工登记优先；未登记时从 prompt 里推断路径
（正则取形如 dir/file.ext 的 token）；两者都拿不到且场景无字面金标准时，
记为"该场景用谓词判定（无字面金标准可核）"——不误报失败，也不假装核过。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

# 场景 → 被引文件（从 prompt 里出现的路径推断，人工登记在此）
SCENARIO_FILES = {
    # v1.3 探针集
    "p2ab_mem_d1": ["docs/EVAL-PLAN-LFL-20261023.md"],
    "p2ab_mem_d2": ["docs/EVAL-PLAN-LFL-20261023.md"],
    "p2ab_mem_d3": ["docs/EVAL-PLAN-LFL-20261023.md"],
    "p2ab_mem_kr": ["docs/known-reds-20260909.md"],
    "p2ab_mem_krdate": ["docs/known-reds-20260909.md"],
    "p2ab_ctl_krdate": ["docs/known-reds-20260909.md"],
    "p2ab_ctl_d1": ["docs/EVAL-PLAN-LFL-20261023.md"],
    # v1.1 探针集
    "p2ab_probe_d1": ["docs/EVAL-PLAN-LFL-20261023.md"],
    "p2ab_probe_d2": ["docs/EVAL-PLAN-LFL-20261023.md"],
    "p2ab_probe_d3": ["docs/EVAL-PLAN-LFL-20261023.md"],
    "p2ab_probe_kr_head": ["docs/known-reds-20260909.md"],
    "p2ab_probe_kr_date": ["docs/known-reds-20260909.md"],
    "p2ab_probe_gap1": ["docs/EVAL-PLAN-LFL-20261023.md"],
    # v1.0 场景集（已作废，留档）
    "p2ab_d12_three_facts": ["docs/EVAL-PLAN-LFL-20261023.md"],
    "p2ab_gap_and_limit": ["docs/EVAL-PLAN-LFL-20261023.md"],
    "p2ab_knownreds_two_facts": ["docs/known-reds-20260909.md"],
    "p2ab_engine_two_lines": ["src/llm_loop/core/loop/engine.py"],
    "p2ab_crossfile_two_facts": [
        "docs/EVAL-PLAN-LFL-20261023.md",
        "src/llm_loop/core/loop/engine.py",
    ],
    "p2ab_paged_evidence": ["docs/EVAL-PLAN-LFL-20261023.md"],
}

_PATH_RE = re.compile(r"(?<![\w/.-])((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8})")


def _infer_files(prompt: str) -> list[str]:
    """从 prompt 推断被引文件（只取仓库里真实存在的路径）。"""
    out: list[str] = []
    for m in _PATH_RE.finditer(prompt or ""):
        cand = m.group(1)
        if ( _ROOT / cand).is_file() and cand not in out:
            out.append(cand)
    return out


def main() -> int:
    sc_path = Path(sys.argv[1] if len(sys.argv) > 1 else "evals/p2_ab/scenarios_p2ab_v1.json")
    data = json.loads(sc_path.read_text(encoding="utf-8"))
    bad: list[str] = []
    notes: list[str] = []
    for s in data["scenarios"]:
        params = s.get("params") or {}
        must = params.get("must_contain") or []
        any_of = params.get("any_of") or []
        # P2-3：空金标准 = 恒真谓词 → 必须在跑批前拦住
        if "must_contain" in params and not must:
            bad.append(f"{s['id']}: must_contain 为空 → 谓词恒真（fail-open）")
        if "any_of" in params and not any_of:
            bad.append(f"{s['id']}: any_of 为空 → 谓词恒假（fail-closed）")
        # 2026-10-23 复审 P2-C：空串金标准（"" in answer 恒真）必须拦在跑批前
        for g in list(must) + list(any_of):
            if isinstance(g, str) and not g.strip():
                bad.append(f"{s['id']}: 金标准含空串 → 谓词恒真（fail-open）→ {g!r}")
        if not must and not any_of:
            notes.append(f"{s['id']}: 无字面金标准（谓词判定）→ 跳过字面核对")
            continue
        files = SCENARIO_FILES.get(s["id"], []) or _infer_files(s.get("prompt", ""))
        if not files:
            bad.append(f"{s['id']}: 未登记且无法从 prompt 推断被引文件 → 无法核金标准")
            continue
        blob = "\n".join(
            (_ROOT / f).read_text(encoding="utf-8", errors="replace")
            for f in files
            if (_ROOT / f).is_file()
        )
        for g in must:
            n = blob.count(g)
            if n == 0:
                bad.append(f"{s['id']}: 金标准在 {files} 中不存在 → {g!r}")
            else:
                print(f"[ok] {s['id']}: must_contain {g!r} 命中 {n} 次")
        for g in any_of:
            n = blob.count(g)
            if n == 0:
                bad.append(f"{s['id']}: any_of 分支在 {files} 中不存在 → {g!r}")
            else:
                print(f"[ok] {s['id']}: any_of {g!r} 命中 {n} 次")
    for n in notes:
        print(f"[note] {n}")
    if bad:
        print("\n[FATAL] 金标准自检不通过：", file=sys.stderr)
        for b in bad:
            print("  - " + b, file=sys.stderr)
        return 2
    print(f"\n[PASS] {len(data['scenarios'])} 个场景金标准核对通过（字面金标准 {len(data['scenarios']) - len(notes)} 个）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
