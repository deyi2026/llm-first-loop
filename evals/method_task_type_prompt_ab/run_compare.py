"""EVO-20261010-994e30f4 上线前硬性检查(b): 弱模型档身份轮+任务轮行为对照.

对照面: method_manage 工具 schema 旧表面(ARM-A, 无 task_type) vs 新表面(ARM-B, 含
task_type 属性描述). 模型: cognilocal/qwen3.8-flash-next(本地).
机械判据(不做语义评分):
  G1 身份轮: 两臂自报身份关键要素一致 + 自报工具名单集合一致(允许子集, 不得幻觉新增)
  G2 任务轮-域已知: JSON 可解析 + record_qualification 调用参数过对应臂 schema 校验;
     ARM-B 须产出良构 task_type(非空字符串<=64); 不得携带臂外参数
  G3 任务轮-域未指明: 两臂可解析+参数合法; ARM-B 的 task_type 缺省或字符串均可,
     不得出现类型违规/臂外参数
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

VERDICT_ENUM = {"pass", "fail", "mixed", "insufficient", "not_evaluated"}

SYSTEM_TMPL = (
    "你是 llm-first-loop 运行环境中的模型。程序提供工具，你按当前用户指令调用工具完成任务。"
    "以下是本次环境中与 Method 学习相关的工具 schema（其余工具与本问题无关）:\n{tools_json}"
)

IDENTITY_PROMPT = (
    "请依次回答: 1) 你是什么模型、在什么运行环境/框架中工作？ 2) 列出你当前可用的全部工具名称（只要名字，逗号分隔，不要解释）。"
    "只依据本次上下文可见信息作答，不要猜测未提供的内容。"
)

TASK1_PROMPT = (
    "场景: 你刚在一个 code-edit 类任务中独立验证了 Method method:example-1 的有效性"
    "（机制与任务收益均 pass），现需用 method_manage 记录一次 qualification。"
    "请只输出你会发出的 method_manage 调用参数（一个 JSON 对象，不要其他文字）。"
)

TASK2_PROMPT = (
    "场景: 你刚验证了 Method method:example-2 的有效性并要记录 qualification，"
    "但本次任务没有明确的领域归类。请只输出你会发出的 method_manage 调用参数"
    "（一个 JSON 对象，不要其他文字）。"
)


def build_arms() -> tuple[list, list]:
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from llm_loop.introspection.registry_experience import _METHOD_MANAGE_TOOL_DEF

    arm_b = [copy.deepcopy(_METHOD_MANAGE_TOOL_DEF)]
    arm_a = copy.deepcopy(arm_b)
    # ARM-A: 剥离本次演进新增表面，还原旧 schema
    arm_a[0]["parameters"]["properties"].pop("task_type", None)
    return arm_a, arm_b


def call_model(system: str, user: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 2000,
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


def parse_tool_names(answer: str) -> tuple[set[str], set[str]]:
    """从身份轮回答抽取自报工具名（机械: 与已知工具名集合求交集/差集）."""
    known = ["method_manage", "refine_experience", "save_experience", "search_records",
             "search_evidence", "read_evidence", "task_create", "task_update"]
    found = {k for k in known if k in answer}
    words = set(re.findall(r"\b[a-z][a-z0-9_]{3,40}\b", answer))
    hallucinated = {w for w in words - set(known) if "_" in w and w not in
                    {"llm_first_loop", "evidence_refs", "task_type", "method_ref"}}
    return found, hallucinated


def valid_qualification_call(parsed, arm_props: set[str]) -> tuple[bool, bool, bool]:
    """返回 (valid_call, extra_params, task_type_wellformed_or_absent)."""
    if not isinstance(parsed, dict):
        return False, False, False
    extra = bool(set(parsed) - arm_props)
    valid = (
        parsed.get("action") == "record_qualification"
        and isinstance(parsed.get("method_ref"), str)
        and bool(parsed.get("method_ref"))
        and parsed.get("verdict") in VERDICT_ENUM
    )
    tt = parsed.get("task_type")
    tt_ok = tt is None or (isinstance(tt, str) and 0 < len(tt) <= 64)
    return valid, extra, tt_ok


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
        for arm_name, sysp, defs in (("A", sys_a, arm_a), ("B", sys_b, arm_b)):
            for round_name, prompt, kind in (
                ("identity", IDENTITY_PROMPT, "text"),
                ("task1_domain_known", TASK1_PROMPT, "json"),
                ("task2_domain_unspecified", TASK2_PROMPT, "json"),
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
                    row["arm_props"] = sorted(defs[0]["parameters"]["properties"])
                rows.append(row)
                print(f"[{rep}] {arm_name}/{round_name}: err={bool(err)} secs={row['secs']}")
                time.sleep(0.5)

    # ---- 机械判据 ----
    report = {"run_identity": args.confirm_run_identity, "model": MODEL, "n_reps": N_REPS,
              "generated_at": datetime.now().astimezone().isoformat(), "rows": rows, "gates": {}}

    def rows_of(arm, rnd):
        return [r for r in rows if r["arm"] == arm and r["round"] == rnd and not r["error"]]

    # G1 身份轮
    g1: dict = {}
    for arm in ("A", "B"):
        answers = [r["out"] for r in rows_of(arm, "identity")]
        tool_sets, hals = [], []
        for a in answers:
            found, hal = parse_tool_names(a)
            tool_sets.append(",".join(sorted(found)))
            hals.append(sorted(hal))
        g1[arm] = {"tool_sets": tool_sets, "hallucinated": hals,
                   "has_lfl_env": all(("llm-first-loop" in a or "llm_first_loop" in a) for a in answers)}
    g1["pass"] = bool(g1["A"]["tool_sets"] and g1["B"]["tool_sets"]
                      and all(s == g1["A"]["tool_sets"][0] for s in g1["A"]["tool_sets"])
                      and all(s == g1["B"]["tool_sets"][0] for s in g1["B"]["tool_sets"])
                      and g1["A"]["tool_sets"][0] == g1["B"]["tool_sets"][0]
                      and not any(g1["A"]["hallucinated"]) and not any(g1["B"]["hallucinated"]))
    report["gates"]["G1_identity"] = g1

    # G2 任务轮-域已知: ARM-B 须产出良构 task_type
    g2: dict = {}
    for arm in ("A", "B"):
        rs = rows_of(arm, "task1_domain_known")
        parse_ok = sum(1 for r in rs if r.get("parsed") is not None)
        valid = extra = tt_ok = 0
        tt_present_wellformed = 0
        for r in rs:
            v, e, t = valid_qualification_call(r.get("parsed"), set(r.get("arm_props", [])))
            valid += v
            extra += e
            tt_ok += t
            p = r.get("parsed")
            if isinstance(p, dict):
                tt = p.get("task_type")
                if isinstance(tt, str) and 0 < len(tt) <= 64:
                    tt_present_wellformed += 1
        g2[arm] = {"parse_ok": parse_ok, "total": len(rs), "valid_call": valid,
                   "extra_params": extra, "task_type_type_ok": tt_ok,
                   "task_type_present_wellformed": tt_present_wellformed}
    g2["no_degradation"] = bool(
        g2["B"]["parse_ok"] >= g2["A"]["parse_ok"]
        and g2["B"]["valid_call"] >= g2["A"]["valid_call"]
        and g2["B"]["extra_params"] == 0
    )
    g2["arm_b_uses_surface"] = g2["B"]["task_type_present_wellformed"] == g2["B"]["total"] > 0
    report["gates"]["G2_task_domain_known"] = g2

    # G3 任务轮-域未指明: 两臂参数合法; ARM-B 无类型违规/臂外参数
    g3: dict = {}
    for arm in ("A", "B"):
        rs = rows_of(arm, "task2_domain_unspecified")
        parse_ok = sum(1 for r in rs if r.get("parsed") is not None)
        valid = extra = tt_ok = 0
        for r in rs:
            v, e, t = valid_qualification_call(r.get("parsed"), set(r.get("arm_props", [])))
            valid += v
            extra += e
            tt_ok += t
        g3[arm] = {"parse_ok": parse_ok, "total": len(rs), "valid_call": valid,
                   "extra_params": extra, "task_type_type_ok": tt_ok}
    g3["no_degradation"] = bool(
        g3["B"]["parse_ok"] >= g3["A"]["parse_ok"]
        and g3["B"]["valid_call"] >= g3["A"]["valid_call"]
        and g3["B"]["extra_params"] == 0
        and g3["B"]["task_type_type_ok"] == g3["B"]["total"]
    )
    report["gates"]["G3_task_domain_unspecified"] = g3

    report["verdict"] = "PASS" if (g1["pass"] and g2["no_degradation"] and g2["arm_b_uses_surface"]
                                   and g3["no_degradation"]) else "FAIL"

    out_path = HERE / "results" / f"compare_{args.confirm_run_identity}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["gates"], ensure_ascii=False, indent=2))
    print(f"verdict={report['verdict']} -> {out_path}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
