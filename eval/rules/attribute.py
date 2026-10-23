#!/usr/bin/env python3
"""Terminal-Bench v2 基线失败归因器（只读、可复算）。

用途：把 `results.json` 中笼统的 `unknown_agent_error` 拆解到具体根因子类，
      使基线可用性判断（D6 纪律）有可审计依据，而不是只报一个失败计数。

用法：
    python3 eval/rules/attribute.py \
        --run-dir eval/results/baseline_v0_terminus2_glm53_full/2026-10-14__20-23-44 \
        --log eval/logs/baseline_v0_full.log

判据来源（全部为机械可复算证据，不含模型判断）：
  A_docker_build   日志含 `Harness execution failed for <task>: Command '['docker'...`
                   → 逐任务确定性判据。
  B_errno24        日志含 `Harness execution failed for <task>: [Errno 24]`
                   → 逐任务确定性判据。注意：日志命中数可能比归因数多，
                     差值为未产生 results.json 条目的任务（如 path-tracing）。
  C_llm_api_5xx    **残差归因（证据等级弱于 A/B）**：该任务既无 A 也无 B，
                   且 LLM 交互阶段出现 5xx 错误块
                   （`Unknown Error in LLM interaction: RetryError[... InternalServerError]`）。
                   ⚠️ 该判据**非逐任务确定性**：日志中 5xx 错误块仅约半数上下文带 task_id，
                   无法逐任务绑定；C 组由排除法 + 全局日志证据推出。
                   → 故脚本同时输出 `robustness` 字段：剔除 C 组后的环境侧占比，
                     用于证明"不可用基线"结论不依赖 C 组。
  D_agent_side:*   其余：agent 真实运行后的失败模式（test_timeout / agent_timeout /
                   parse_error / unset），归 LFL harness/agent 侧，可用于能力比较。

退出码非 0 表示输入不可用（例如 results.json 缺失）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

DOCKER_BUILD_RE = re.compile(
    r"Harness execution failed for \S*/([A-Za-z0-9._-]+): Command '\['docker'"
)
ERRNO24_RE = re.compile(
    r"Harness execution failed for \S*/([A-Za-z0-9._-]+): \[Errno 24\]"
)
LLM_ERROR_RE = re.compile(
    r"Unknown Error in LLM interaction: RetryError\[.*raised InternalServerError\]"
)
AGENT_TIMEOUT_RE = re.compile(
    r"Agent timed out after [\d.]+s for task ([A-Za-z0-9._-]+)\.?"
)
TEST_TIMEOUT_RE = re.compile(
    r"Test command timed out after [\d.]+s for task ([A-Za-z0-9._-]+)\.?"
)

INFRA_GROUPS = ("A_docker_build", "B_errno24", "C_llm_api_5xx")


def classify(results: list[dict], log_text: str) -> dict[str, list[str]]:
    build = set(DOCKER_BUILD_RE.findall(log_text))
    emfile = set(ERRNO24_RE.findall(log_text))
    llm_err_present = bool(LLM_ERROR_RE.search(log_text))

    groups: dict[str, list[str]] = defaultdict(list)
    for r in results:
        tid = r["task_id"]
        if r.get("is_resolved"):
            groups["RESOLVED"].append(tid)
            continue
        fm = r.get("failure_mode", "NA")
        if fm == "unknown_agent_error":
            if tid in build:
                groups["A_docker_build"].append(tid)
            elif tid in emfile:
                groups["B_errno24"].append(tid)
            elif llm_err_present:
                groups["C_llm_api_5xx"].append(tid)
            else:
                groups["C_llm_api_5xx"].append(tid)  # 兜底：仍属环境类
        else:
            groups[f"D_agent_side:{fm}"].append(tid)
    return dict(groups)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args()

    results_path = os.path.join(args.run_dir, "results.json")
    if not os.path.exists(results_path):
        print(f"[FAIL] results.json 不存在: {results_path}", file=sys.stderr)
        return 2
    with open(results_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    results = doc["results"]
    with open(args.log, encoding="utf-8", errors="replace") as fh:
        log_text = fh.read()

    groups = classify(results, log_text)
    infra = [t for g in INFRA_GROUPS for t in groups.get(g, [])]
    # 稳健性：剔除证据等级较弱的 C 组（残差归因）后的环境侧占比
    infra_ab = [t for g in ("A_docker_build", "B_errno24") for t in groups.get(g, [])]
    agent_side = [
        t
        for g, ts in groups.items()
        if g.startswith("D_agent_side:")
        for t in ts
    ]
    n_resolved = len(groups.get("RESOLVED", []))
    n_agent_comparable = n_resolved + len(agent_side)
    n_unresolved = len(results) - n_resolved

    out = {
        "run_dir": args.run_dir,
        "n_results": len(results),
        "n_resolved": n_resolved,
        "n_unresolved": n_unresolved,
        "n_infra_failures": len(infra),
        "n_agent_comparable": n_agent_comparable,
        "raw_accuracy": n_resolved / len(results) if results else 0.0,
        "agent_comparable_accuracy": (
            n_resolved / n_agent_comparable if n_agent_comparable else 0.0
        ),
        "infra_share_of_failures": (
            len(infra) / n_unresolved if n_unresolved else 0.0
        ),
        "robustness": {
            "note": "剔除 C_llm_api_5xx（残差归因）后的环境侧占比；"
                    "用于证明『不可用基线』结论不依赖证据等级较弱的 C 组",
            "n_infra_excluding_C": len(infra_ab),
            "share_excluding_C": (
                len(infra_ab) / n_unresolved if n_unresolved else 0.0
            ),
        },
        "groups": {k: sorted(v) for k, v in sorted(groups.items())},
    }

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"run_dir: {args.run_dir}")
    print(f"results: {out['n_results']}  resolved: {n_resolved}  unresolved: {n_unresolved}")
    print()
    for g, ts in sorted(out["groups"].items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(ts):3d}  {g}")
    print()
    print(f"原口径（全部判定）      : {n_resolved}/{out['n_results']} = {out['raw_accuracy']*100:.2f}%")
    print(f"归因后（agent 可比集）  : {n_resolved}/{n_agent_comparable} = {out['agent_comparable_accuracy']*100:.2f}%")
    print(f"环境类失败占失败比      : {len(infra)}/{n_unresolved} = {out['infra_share_of_failures']*100:.1f}%")
    print(f"  稳健性（剔除残差归因 C）: {out['robustness']['n_infra_excluding_C']}/{n_unresolved} = {out['robustness']['share_excluding_C']*100:.1f}%")
    print()
    if out["infra_share_of_failures"] > 0.30:
        print("[D6] 环境类失败 > 30% → 该基线标为『不可用基线』，禁止进入能力比较。")
    else:
        print("[D6] 环境类失败 ≤ 30% → 基线可用于能力比较（仍须并列报原口径）。")
    if out["robustness"]["share_excluding_C"] > 0.30:
        print("[稳健性] 剔除 C 组后仍 > 30% → 结论不依赖证据等级较弱的残差归因。")
    else:
        print("[稳健性][警告] 剔除 C 组后 ≤ 30% → 结论部分依赖 C 组，引用时必须标注。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
