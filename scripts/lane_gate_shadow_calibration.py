"""S1 影子期校准：18 个场景，机检判定 vs 人工判定逐条对照。

人工判定依据 docs/design/DESIGN-20261105-main-lane-parallel-delivery-v1.md
§4.4.1 十条机检表 + 三级授权语义，**先于机检结果独立写定**，避免自证。

判定口径分两列：
- verdict     : 十条机检是否全过（文档要求"全满足才自动"，skip≠pass）
- allowed     : 是否应自动执行（开关关时即使全过也不自动，回落 S0）
漏拦 = 人工判 fail 而机检 verdict=pass（一票否决项）
误拦 = 人工判 pass 而机检 verdict=fail（安全但降低效率）
"""
import json

from llm_loop.introspection.lane_gate import GateConfig, S1Evidence, evaluate_s1_gate

MAIN = "939be9a04fcfac737916722cf2e35f4c88d1984d"
OLD = "c72be2c4840c731dd18a3694d3a39afb178063db"
HEAD = "aaa111bbb222ccc333ddd444eee555fff6667778"
PATCH = "sha256:patch-abc"
NOW = "2026-11-05T12:55:00+08:00"
CREATED = "2026-11-05T12:00:00+08:00"


def ev(**over):
    e = {
        "lane": {"lane_id": "lane-cal", "branch": "fix/cal", "head_sha": HEAD,
                 "base_main_sha": MAIN, "paths": ["src/llm_loop/x.py"], "verify_ref": "vf-1"},
        "main": {"head_sha": MAIN, "broken": False, "deploy_window": False},
        "verify": {"receipt_id": "vf-1", "patch_digest": PATCH, "base_sha": MAIN,
                   "result": "pass", "scope": "full", "impacted_result": "",
                   "created_at": CREATED, "contract_hit": False},
        "current_patch_digest": PATCH,
        "review": {"verdict": "pass", "bound_sha": HEAD, "created_at": CREATED},
        "deployment": {"target_sha": MAIN, "rollback_sha": OLD, "ts": CREATED,
                       "phase": "service_control:web"},
        "merge_precheck": {"source": "merge-tree", "conflicts": 0},
        "batch": {"members": [{"lane_id": "lane-cal", "kind": "normal"}], "changed_files_total": 1},
        "help_requests": [],
        "claim_overlaps": [],
        "merge_plan": {"no_ff": True, "parent_sha": MAIN},
        "changed_files": ["src/llm_loop/x.py"],
        "now_iso": NOW,
    }
    for k, v in over.items():
        if k in ("lane", "main", "verify", "review", "deployment",
                 "merge_precheck", "batch", "merge_plan"):
            e[k] = {**e[k], **v}
        else:
            e[k] = v
    return S1Evidence(**e)


CFG = GateConfig(lane_auto_merge=True, auto_merge_allowlist=("src/llm_loop",))
CFG_RULES = GateConfig(lane_auto_merge=True, auto_merge_allowlist=("src/llm_loop", "rules"))

S = [
    ("C01", "全绿+开关开+allowlist 覆盖", ev(), CFG, "pass", True, "十条全满足→自动"),
    ("C02", "main.broken=true", ev(main={"broken": True}), CFG, "fail", False, "第1条"),
    ("C03", "部署窗口内", ev(main={"deploy_window": True}), CFG, "fail", False, "第1条"),
    ("C04", "merge-tree 冲突=2", ev(merge_precheck={"conflicts": 2}), CFG, "fail", False, "第2条"),
    ("C05", "patch_digest 不匹配", ev(current_patch_digest="sha256:other"), CFG, "fail", False, "第3条"),
    ("C06", "base 旧+impacted 级复验 pass", ev(verify={"base_sha": OLD, "scope": "impacted", "impacted_result": "pass"}), CFG, "pass", True, "第3条：需 scope=impacted 且复验 pass"),
    ("C07", "base 旧且无 impacted 复验", ev(verify={"base_sha": OLD, "impacted_result": ""}), CFG, "fail", False, "第3条"),
    ("C08", "审查 verdict=fail", ev(review={"verdict": "fail"}), CFG, "fail", False, "第4条"),
    ("C09", "审查绑定 sha 不匹配", ev(review={"bound_sha": OLD}), CFG, "fail", False, "第4条"),
    ("C10", "改动路径不在 allowlist", ev(), GateConfig(lane_auto_merge=True, auto_merge_allowlist=("src/other",)), "fail", False, "第5条"),
    ("C11", "改动路径命中 sealed(rules)", ev(changed_files=["rules/x.md"], lane={"paths": ["rules"]}), CFG_RULES, "fail", False, "第6条"),
    ("C12", "批次超 K=3", ev(batch={"members": [{"lane_id": f"l{i}", "kind": "normal"} for i in range(4)]}), CFG, "fail", False, "第7条"),
    ("C13", "有 need=block 协助请求", ev(help_requests=[{"id": "h1", "need": "block"}]), CFG, "fail", False, "第8条"),
    ("C14", "其他 lane 持重叠 claim", ev(claim_overlaps=[{"lane_id": "lane-b", "paths": ["src/llm_loop/x.py"]}]), CFG, "fail", False, "第9条"),
    ("C15", "merge_plan.no_ff=false", ev(merge_plan={"no_ff": False}), CFG, "fail", False, "第10条"),
    ("C16", "merge_plan.parent 非 main head", ev(merge_plan={"parent_sha": OLD}), CFG, "fail", False, "第10条"),
    ("C17", "协助/claim 数据源未接入(None)", ev(help_requests=None, claim_overlaps=None), CFG, "fail", False, "skip≠pass，依赖不可用不放行"),
    ("C18", "空 allowlist（默认）", ev(), GateConfig(), "fail", False, "第5条：默认空=全不自动→path_not_allowed"),
    ("C19", "开关关但 allowlist 已配", ev(), GateConfig(lane_auto_merge=False, auto_merge_allowlist=("src/llm_loop",)), "pass", False, "全过但不自动，回落 S0"),
]

rows = []
for cid, desc, evidence, cfg, h_verdict, h_allowed, why in S:
    out = evaluate_s1_gate(evidence, cfg)
    m_verdict = out.get("verdict")
    m_allowed = bool(out.get("auto_merge_allowed"))
    rows.append({
        "id": cid, "desc": desc, "human_verdict": h_verdict, "machine_verdict": m_verdict,
        "human_allowed": h_allowed, "machine_allowed": m_allowed,
        "verdict_match": m_verdict == h_verdict,
        "allowed_match": m_allowed == h_allowed,
        "false_allow": h_verdict == "fail" and m_verdict == "pass",
        "false_deny": h_verdict == "pass" and m_verdict == "fail",
        "auto_denied": out.get("auto_denied"),
        "decision_reason": out.get("decision_reason"),
        "rule": why,
    })

total = len(rows)
v_ok = sum(1 for r in rows if r["verdict_match"])
a_ok = sum(1 for r in rows if r["allowed_match"])
both = sum(1 for r in rows if r["verdict_match"] and r["allowed_match"])
leak = sum(1 for r in rows if r["false_allow"])
over = sum(1 for r in rows if r["false_deny"])

print(f"{'id':<4} {'scenario':<30} {'人判':<6} {'机判':<6} {'人auto':<6} {'机auto':<6} {'denied'}")
for r in rows:
    print(
        f"{r['id']:<4} {r['desc'][:30]:<30} {r['human_verdict']:<6} {r['machine_verdict']:<6} "
        f"{r['human_allowed']:<6} {r['machine_allowed']:<6} {','.join(r['auto_denied'] or [])}"
    )
print()
print(json.dumps({
    "total": total, "verdict_match": v_ok, "allowed_match": a_ok,
    "both_match": both, "consistency_rate": round(both / total, 4),
    "false_allow_leak": leak, "false_deny": over,
    "pass_criteria": "consistency 100% and leak 0",
    "meets_criteria": both == total and leak == 0,
}, ensure_ascii=False, indent=2))
with open("work/shadow_calibration_result.json", "w", encoding="utf-8") as fh:
    json.dump(rows, fh, ensure_ascii=False, indent=2)
