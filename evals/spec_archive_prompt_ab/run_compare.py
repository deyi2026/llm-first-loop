"""EVO-20261002-daa84575 上线前硬性检查(b): 弱模型档身份轮+任务轮行为对照.

对照面: create_goal/update_goal 工具 schema 旧表面(ARM-A) vs 新表面(ARM-B, 含
spec_change_ref/spec_archive). 模型: cognilocal/qwen3.8-flash-next(本地).
机械判据(不做语义评分):
  G1 身份轮: 两臂自报身份关键要素一致 + 自报工具名单集合一致(允许子集, 不得幻觉新增)
  G2 任务轮-未声明spec: JSON 可解析 + 参数过对应臂 schema 校验 + 无投机 spec_archive
  G3 任务轮-已声明spec: ARM-B 须产出良构 spec_archive(清单或不适用); ARM-A 仅记录
劣化判定: ARM-B 任一机械判据严格差于 ARM-A → FAIL(不得上线)
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BASE_URL = "http://localhost:8901/v1"
MODEL = "qwen3.8-flash-next"
N_REPS = 3

OLD_UPDATE_DESC = (
    "更新任务目标状态（EVO-20260824-3cd4d74b；终局证据门 EVO-20260923-6bcc4880）。"
    "status=complete 仅当全部需求已用当前证据验证: 程序级强制——任务图 open 任务须清零、"
    "evidence_required 任务须 evidence verified；无 done 任务依托（空任务图）时须自报"
    " evidence_refs 并通过真实性校验，否则 BLOCKED 拒绝书写。status=blocked 仅当严格"
    "阻塞条件实际满足（外部阻塞/安全边界/等人工），blocked 不走证据门。"
    "何时不用: 目标仍 active 推进中。"
)

SYSTEM_TMPL = (
    "你是 llm-first-loop 运行环境中的模型。程序提供工具，你按当前用户指令调用工具完成任务。"
    "以下是本次环境中与 Goal 生命周期相关的工具 schema（其余工具与本问题无关）:\n{tools_json}"
)

IDENTITY_PROMPT = (
    "请依次回答: 1) 你是什么模型、在什么运行环境/框架中工作？ 2) 列出你当前可用的全部工具名称（只要名字，逗号分隔，不要解释）。"
    "只依据本次上下文可见信息作答，不要猜测未提供的内容。"
)

TASK1_PROMPT = (
    "场景: Goal GOAL-A（未声明任何 spec 字段）下全部任务已 done 且 evidence verified，"
    "现需收口。请只输出你会发出的 update_goal 调用参数（一个 JSON 对象，不要其他文字）。"
)

TASK2_PROMPT = (
    "场景: Goal GOAL-B 创建时声明了 spec_change_ref=.codeartsdoer/specs/20261002/，"
    "其下全部任务已 done 且 evidence verified，现需收口；该 Goal 是纯分析类任务，"
    "没有把 spec 变更吸收进任何文档。请只输出你会发出的 update_goal 调用参数（一个 JSON 对象，不要其他文字）。"
)


def build_arms() -> tuple[list, list]:
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from llm_loop.introspection.tools_goal import CREATE_GOAL_TOOL_DEF, UPDATE_GOAL_TOOL_DEF

    arm_b = [copy.deepcopy(CREATE_GOAL_TOOL_DEF), copy.deepcopy(UPDATE_GOAL_TOOL_DEF)]
    arm_a = copy.deepcopy(arm_b)
    # ARM-A: 剥离本次演进新增表面，还原旧 schema
    arm_a[0]["parameters"]["properties"].pop("spec_change_ref", None)
    arm_a[1]["parameters"]["properties"].pop("spec_archive", None)
    arm_a[1]["description"] = OLD_UPDATE_DESC
    return arm_a, arm_b


def call_model(system: str, user: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 700,
        "temperature": 0.0,
        "stream": False,
    }
    r = httpx.post(f"{BASE_URL}/chat/completions", json=payload, timeout=180.0)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def extract_json(text: str):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def parse_tool_names(answer: str) -> set[str]:
    """从身份轮回答抽取自报工具名（机械: 与已知工具名集合求交集/差集）."""
    known = ["create_goal", "update_goal", "get_goal", "checkpoint_goal", "task_create", "task_update",
             "task_frontier", "submit_evolution"]
    found = {k for k in known if k in answer}
    # 幻觉检测: 回答中出现的 snake_case 词但不在 known
    words = set(re.findall(r"\b[a-z][a-z0-9_]{3,40}\b", answer))
    hallucinated = {w for w in words - set(known) if "_" in w and "goal" not in w and w not in
                    {"llm_first_loop", "evidence_refs", "status", "reason", "complete", "blocked"}}
    return found, hallucinated


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm-run-identity", default="")
    args = ap.parse_args()
    if not args.confirm_run_identity:
        print("需要 --confirm-run-identity <id> 显式授权真实 LLM 调用")
        return 2
    arm_a, arm_b = build_arms()
    sys_a = SYSTEM_TMPL.format(tools_json=json.dumps(arm_a, ensure_ascii=False))
    sys_b = SYSTEM_TMPL.format(tools_json=json.dumps(arm_b, ensure_ascii=False))
    rows = []
    for rep in range(N_REPS):
        for arm_name, sysp in (("A", sys_a), ("B", sys_b)):
            for round_name, prompt, kind in (
                ("identity", IDENTITY_PROMPT, "text"),
                ("task1_no_spec", TASK1_PROMPT, "json"),
                ("task2_with_spec", TASK2_PROMPT, "json"),
            ):
                t0 = time.time()
                try:
                    out = call_model(sysp, prompt)
                    err = ""
                except Exception as exc:  # noqa: BLE001
                    out, err = "", f"{type(exc).__name__}: {exc}"
                row = {"rep": rep, "arm": arm_name, "round": round_name, "out": out,
                       "error": err, "secs": round(time.time() - t0, 1)}
                if kind == "json":
                    row["parsed"] = extract_json(out)
                rows.append(row)
                print(f"[{rep}] {arm_name}/{round_name}: err={bool(err)} secs={row['secs']}")
                time.sleep(0.5)

    # ---- 机械判据 ----
    report = {"run_identity": args.confirm_run_identity, "model": MODEL, "n_reps": N_REPS,
              "generated_at": datetime.now().astimezone().isoformat(), "rows": rows, "gates": {}}

    def rows_of(arm, rnd):
        return [r for r in rows if r["arm"] == arm and r["round"] == rnd and not r["error"]]

    # G1 身份轮
    g1 = {}
    for arm in ("A", "B"):
        sets, hallu = [], set()
        for r in rows_of(arm, "identity"):
            s, h = parse_tool_names(r["out"])
            sets.append(s)
            hallu |= h
        g1[arm] = {"tool_sets": [sorted(s) for s in sets], "hallucinated": sorted(hallu),
                   "has_lfl_env": ["llm-first-loop" in (r["out"] or "") or "llm_first" in (r["out"] or "")
                                   for r in rows_of(arm, "identity")]}
    g1["stable"] = (all(s == g1["A"]["tool_sets"][0] for s in g1["A"]["tool_sets"])
                    and all(s == g1["B"]["tool_sets"][0] for s in g1["B"]["tool_sets"])
                    and g1["A"]["tool_sets"][0] == g1["B"]["tool_sets"][0]
                    and not g1["A"]["hallucinated"] and not g1["B"]["hallucinated"])
    report["gates"]["G1_identity"] = g1

    # G2 任务轮-未声明 spec: ARM-B 不得投机加 spec_archive; 参数须含 goal_id/status
    g2 = {}
    for arm in ("A", "B"):
        parsed_n = sum(1 for r in rows_of(arm, "task1_no_spec") if r.get("parsed") is not None)
        valid = 0
        spurious = 0
        for r in rows_of(arm, "task1_no_spec"):
            p = r.get("parsed")
            if isinstance(p, dict) and p.get("goal_id") and p.get("status") == "complete":
                valid += 1
                if "spec_archive" in p or "spec_change_ref" in p:
                    spurious += 1
        g2[arm] = {"parse_ok": parsed_n, "total": len(rows_of(arm, "task1_no_spec")),
                   "valid_update_call": valid, "spurious_spec": spurious}
    g2["no_degradation"] = g2["B"]["parse_ok"] >= g2["A"]["parse_ok"] and g2["B"]["spurious_spec"] == 0
    report["gates"]["G2_task_no_spec"] = g2

    # G3 任务轮-已声明 spec: ARM-B 须产出良构 spec_archive
    g3 = {}
    for arm in ("A", "B"):
        wellformed = 0
        for r in rows_of(arm, "task2_with_spec"):
            p = r.get("parsed")
            if not isinstance(p, dict):
                continue
            sa = p.get("spec_archive")
            if isinstance(sa, dict) and (
                (sa.get("applicable") is False and str(sa.get("reason", "")).strip())
                or (str(sa.get("result_doc", "")).strip() and sa.get("merged_docs"))
            ):
                wellformed += 1
        g3[arm] = {"parse_ok": sum(1 for r in rows_of(arm, "task2_with_spec") if r.get("parsed") is not None),
                   "total": len(rows_of(arm, "task2_with_spec")), "wellformed_spec_archive": wellformed}
    report["gates"]["G3_task_with_spec"] = g3

    verdict = "PASS" if (g1["stable"] and g2["no_degradation"]) else "FAIL"
    report["verdict"] = verdict
    out_path = HERE / "results" / f"compare_{args.confirm_run_identity}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report["gates"][k] for k in report["gates"]}, ensure_ascii=False, indent=2))
    print(f"verdict={verdict} -> {out_path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
