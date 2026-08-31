#!/usr/bin/env python
"""R8.24-E E-4.2: CORE9 A/B 实验矩阵回放评估（fixture 回放口径，非镜像区实跑）.

三方案（E-D6，前置=C 包 capsule chars=0 已落地）:
- plan_i   现状 9 工具（CORE_TOOL_ORDER 基线）;
- plan_ii  缩减实验组（universal core = get_tool_schema + 最少 I/O:
           read_file/edit_file/execute_command; web/skill/search 按词法路由发现）;
- plan_iii 恢复三件套扩入方向（plan_i + read_evidence/search_evidence/list_evidence）
           另附半集合变体（plan_i + list_evidence）。

四指标: 任务完成率 / 错误工具率（词法误报调用占比）/ 发现工具耗时
（不可见工具的平均额外发现轮）/ 重复 schema lookup 次数。

回放模拟器（确定性规则，非 LLM）:
- 工具在可见面（方案 CORE ∪ 词法路由 task_names ∪ 协议上下文）→ 直接调用;
- 不可见但已注册 → get_tool_schema('?keyword'|name) 发现后调用（额外 1 轮 + 1 lookup）;
- 发现后同场景不再重复 lookup（会话内记忆）;
- 词法路由命中但不在 expected_chain → 误报调用（错误工具率计）;
- evidence 截断事实行在场 → 模型按 recovery_ref 意图查询 '?evidence'（路线 2）。

验证等级: fixture 回放替代镜像区实跑（tasks.md 5.4 口径，如实标注不虚报）。
产出: JSON 数据表 + markdown 矩阵（stdout / --out 文件）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from llm_loop.tools.eligibility import (  # noqa: E402
    CORE_TOOL_ORDER,
    TOOL_TASK_KEYWORDS,
    _task_relevant_names,
)

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "core_ab" / "scenarios.json"

PLANS: dict[str, tuple[str, ...]] = {
    "plan_i_status_quo": tuple(CORE_TOOL_ORDER),
    "plan_ii_reduced": (
        "get_tool_schema",
        "read_file",
        "edit_file",
        "execute_command",
    ),
    "plan_iii_recovery_full": tuple(
        CORE_TOOL_ORDER
    ) + ("read_evidence", "search_evidence", "list_evidence"),
    "plan_iii_recovery_half": tuple(CORE_TOOL_ORDER) + ("list_evidence",),
}

# 注册表全量名（R8.7 注册事实——回放以词表∪CORE∪fixture 期望并集近似）
_REGISTRY_UNIVERSE = set(CORE_TOOL_ORDER) | set(TOOL_TASK_KEYWORDS) | {
    "web_fetch", "read_image",
}


def _discoverable_via_schema_query(name: str) -> bool:
    """路线 2: get_tool_schema 按需发现——'?keyword' 搜索命中（工具名子串）."""
    probe = name.split("_")[-1]  # e.g. read_evidence → '?evidence'
    return name in _REGISTRY_UNIVERSE and probe in name


def run_plan(plan_core: tuple[str, ...], scenarios: list[dict]) -> dict:
    completed = 0
    total_calls = 0
    misdirected_calls = 0
    discovery_rounds = 0
    hidden_tools_seen = 0
    total_lookups = 0
    per_scenario: list[dict] = []

    for sc in scenarios:
        text = sc["task_text"]
        protocol = set(sc.get("protocol_tools") or [])
        chain = list(sc.get("expected_chain") or [])
        truncation = bool(sc.get("evidence_truncation"))

        visible = set(plan_core) | protocol
        routed = _task_relevant_names(text, _REGISTRY_UNIVERSE)
        visible |= routed

        sc_calls = 0
        sc_misdirected = 0
        sc_rounds = 0
        sc_lookups = 0
        ok = True
        for tool in chain:
            if tool in visible:
                sc_calls += 1
                continue
            if _discoverable_via_schema_query(tool):
                # 路线 2 按需发现: 截断场景模型有明确意图（recovery_ref 在场），
                # 非截断场景依赖模型主动探查（'?'+领域词）——均可发现，计 1 轮。
                sc_calls += 1
                sc_rounds += 1
                sc_lookups += 1
                hidden_tools_seen += 1
                continue
            ok = False  # 注册表外——不可发现（真实注册表不存在该工具）
        # 词法误报: 路由命中但任务不需要（模拟模型被小尾部诱导的调用）
        for _name in sorted(routed - set(chain) - set(plan_core)):
            sc_calls += 1
            sc_misdirected += 1
        if truncation and not (
            set(chain) & {"read_evidence", "search_evidence", "list_evidence"}
        ) & set(plan_core):
            # 截断事实行在场: 模型先查 '?evidence' 目录再取目标——路线 2 固有成本
            sc_lookups += 1  # 目标不在 CORE 时需目录查询（已在上面计 1 的不重复）
        if ok:
            completed += 1
        total_calls += sc_calls
        misdirected_calls += sc_misdirected
        discovery_rounds += sc_rounds
        total_lookups += sc_lookups
        per_scenario.append(
            {
                "id": sc["id"],
                "completed": ok,
                "calls": sc_calls,
                "misdirected": sc_misdirected,
                "discovery_rounds": sc_rounds,
                "lookups": sc_lookups,
            }
        )

    n = len(scenarios)
    hidden = max(hidden_tools_seen, 1)
    return {
        "completion_rate": round(completed / n, 4),
        "misdirected_tool_rate": round(misdirected_calls / max(total_calls, 1), 4),
        "avg_discovery_rounds_per_hidden_tool": round(discovery_rounds / hidden, 4),
        "total_schema_lookups": total_lookups,
        "core_size": len(plan_core),
        "completed": completed,
        "total_calls": total_calls,
        "misdirected_calls": misdirected_calls,
        "per_scenario": per_scenario,
    }


def evaluate(fixture: Path = FIXTURE) -> dict:
    scenarios = json.loads(fixture.read_text(encoding="utf-8"))["scenarios"]
    return {
        "verification_level": "fixture-replay（脱敏场景回放替代镜像区实跑; 环境不可用如实标注）",
        "fixture": str(fixture.relative_to(REPO_ROOT)),
        "n_scenarios": len(scenarios),
        "plans": {name: run_plan(core, scenarios) for name, core in PLANS.items()},
    }


def render_markdown(result: dict) -> str:
    lines = [
        "# CORE9 A/B 实验矩阵（E-4.2 数据表）",
        "",
        f"验证等级: {result['verification_level']}",
        f"场景数: {result['n_scenarios']}（fixture: {result['fixture']}）",
        "",
        "| 方案 | CORE 规模 | 任务完成率 | 错误工具率 | 发现耗时(轮/隐藏工具) | schema lookup 总数 |",
        "|---|---|---|---|---|---|",
    ]
    for name, m in result["plans"].items():
        lines.append(
            f"| {name} | {m['core_size']} | {m['completion_rate']:.2%} | "
            f"{m['misdirected_tool_rate']:.2%} | "
            f"{m['avg_discovery_rounds_per_hidden_tool']:.2f} | {m['total_schema_lookups']} |"
        )
    lines += [
        "",
        "判据（§13.2 硬门）: 缩减后 capability discovery 成功率不下降才可推广。",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="结果 JSON 写出路径（可选）")
    ap.add_argument("--markdown-out", default=None, help="markdown 矩阵写出路径（可选）")
    args = ap.parse_args()

    result = evaluate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()
    print(render_markdown(result))
    if args.out:
        Path(args.out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.markdown_out:
        Path(args.markdown_out).write_text(render_markdown(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
