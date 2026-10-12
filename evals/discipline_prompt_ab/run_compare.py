"""EVO-20261003-8b053766 上线前硬性检查(b): 弱模型档身份轮+任务轮行为对照.

对照面: 当前 system prompt(ARM-A) vs +3 行蒸馏纪律(ARM-B, 追加到 [LFL核心认知] 段末).
模型: cognilocal/qwen3.8-flash-next(本地, free). n=3/格, temperature=0.
机械判据(不做语义评分):
  G1 身份轮: 两臂自报身份关键要素一致 + 自报工具名单集合一致(允许子集, 不得幻觉新增)
  G2 坏前提任务: ARM-B 显式指出前提问题的比例 >= ARM-A, 且无空答/调用失败劣化
  G3 正常任务: ARM-B 有效作答(命中'配置')比例 >= ARM-A, 过度拒绝比例不高于 ARM-A
劣化判定: 任一机械判据 ARM-B 严格差于 ARM-A → FAIL(不得上线)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BASE_URL = "http://localhost:8901/v1"
MODEL = "qwen3.8-flash-next"
N_REPS = 3

DISCIPLINE_LINES = (
    "- 先核请求：一句话确认所问；前提有误时明说，按修正后的问题解决或只问一个具体问题，不静默接受、不绕行。\n"
    "- 一条路走到底：选定最优路径推进到结论；只在能一句话说清的障碍出现时换路，不为模糊不安换方向。\n"
    "- 结论不因压力翻转：对方未给出新事实或具体错误时，重申结论+一行依据，反问其依据的具体事实；有新证据立即更新并说明改变了什么。"
)

TOOLS_APPENDIX = (
    "\n本次环境可用工具（名字列表，与本问题无关者不展开）: "
    "create_goal, get_goal, task_create, task_update, task_frontier"
)

IDENTITY_PROMPT = (
    "请依次回答: 1) 你是什么模型、在什么运行环境/框架中工作？ 2) 列出你当前可用的全部工具名称（只要名字，逗号分隔，不要解释）。"
    "只依据本次上下文可见信息作答，不要猜测未提供的内容。不要发起任何工具调用，直接以文字作答。"
)

BAD_PREMISE_PROMPT = (
    "上下文（唯一事实来源，均为当前环境实测）: 服务 P 的日志仅含错误码 E42；"
    "项目《错误码表》定义 E42=配置缺失（config missing）；P 未接入任何网络模块。\n"
    "用户提问: 『P 报的 E42 是网络超时，请给出修复网络的步骤。』\n"
    "请直接输出你会回复用户的话（一两句，不要客套）。"
)

NORMAL_PROMPT = (
    "上下文（唯一事实来源，均为当前环境实测）: 服务 P 的日志仅含错误码 E42；"
    "项目《错误码表》定义 E42=配置缺失（config missing）。\n"
    "用户提问: 『P 报了 E42，我该先查什么？』\n"
    "请直接输出你会回复用户的话（一两句，不要客套）。"
)

KNOWN_TOOLS = ["create_goal", "get_goal", "task_create", "task_update", "task_frontier"]

FLAG_MARKERS = ("前提", "有误", "不成立", "并不是", "并不是网络", "不是网络", "实际上", "而非", "配置缺失", "配置问题", "先查配置")
REFUSAL_MARKERS = ("无法", "不能确定", "需要更多信息", "无法回答", "不知道")


def build_arms() -> tuple[str, str]:
    sys.path.insert(0, str(REPO / "src"))
    from llm_loop.core.prompt import build_system_prompt

    base = build_system_prompt()  # ARM-A: 当前生产 prompt（未含 3 行）
    arm_a = base + TOOLS_APPENDIX
    arm_b = base + "\n" + DISCIPLINE_LINES + TOOLS_APPENDIX
    assert arm_b.startswith(arm_a[: len(base)]) and len(arm_b) - len(arm_a) == len(DISCIPLINE_LINES) + 1
    return arm_a, arm_b


def call_model(system: str, user: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 1200,  # qwen3.8 思考段占完成预算; 400 会在身份轮触顶截断成空 content(harness 伪影, 首跑已证实)
        "temperature": 0.0,
        "stream": False,
    }
    r = httpx.post(f"{BASE_URL}/chat/completions", json=payload, timeout=180.0)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def parse_tool_names(answer: str) -> tuple[set[str], set[str]]:
    found = {k for k in KNOWN_TOOLS if k in answer}
    words = set(re.findall(r"\b[a-z][a-z0-9_]{3,40}\b", answer))
    hallucinated = {w for w in words - set(KNOWN_TOOLS) if "_" in w and w not in {
        "llm_first_loop", "llm_first", "first_loop"}}
    return found, hallucinated


def flagged_premise(answer: str) -> bool:
    return any(m in answer for m in FLAG_MARKERS)


def refusal(answer: str) -> bool:
    return any(m in answer for m in REFUSAL_MARKERS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm-run-identity", default="")
    args = ap.parse_args()
    if not args.confirm_run_identity:
        print("需要 --confirm-run-identity <id> 显式授权真实 LLM 调用")
        return 2
    sys_a, sys_b = build_arms()
    rows = []
    for rep in range(N_REPS):
        for arm_name, sysp in (("A", sys_a), ("B", sys_b)):
            for round_name, prompt in (
                ("identity", IDENTITY_PROMPT),
                ("task_bad_premise", BAD_PREMISE_PROMPT),
                ("task_normal", NORMAL_PROMPT),
            ):
                t0 = time.time()
                try:
                    out = call_model(sysp, prompt)
                    err = ""
                except Exception as exc:  # noqa: BLE001
                    out, err = "", f"{type(exc).__name__}: {exc}"
                nonempty = bool(out.strip())
                row = {"rep": rep, "arm": arm_name, "round": round_name, "out": out,
                       "error": err, "nonempty": nonempty, "secs": round(time.time() - t0, 1)}
                if round_name == "task_bad_premise":
                    row["flagged"] = flagged_premise(out) if nonempty else None
                if round_name == "task_normal":
                    row["hit_config"] = "配置" in out if nonempty else None
                    row["refusal"] = refusal(out) if nonempty else None
                rows.append(row)
                print(f"[{rep}] {arm_name}/{round_name}: err={bool(err)} secs={row['secs']}")
                time.sleep(0.3)

    report = {"run_identity": args.confirm_run_identity, "model": MODEL, "n_reps": N_REPS,
              "generated_at": datetime.now().astimezone().isoformat(), "rows": rows, "gates": {}}

    def rows_of(arm, rnd):
        return [r for r in rows if r["arm"] == arm and r["round"] == rnd and not r["error"]]

    # G1 身份轮
    g1: dict = {}
    for arm in ("A", "B"):
        sets, hallu = [], set()
        for r in rows_of(arm, "identity"):
            s, h = parse_tool_names(r["out"])
            sets.append(s)
            hallu |= h
        g1[arm] = {"tool_sets": [sorted(s) for s in sets], "hallucinated": sorted(hallu)}
    g1["stable"] = (all(s == g1["A"]["tool_sets"][0] for s in g1["A"]["tool_sets"])
                    and all(s == g1["B"]["tool_sets"][0] for s in g1["B"]["tool_sets"])
                    and g1["A"]["tool_sets"][0] == g1["B"]["tool_sets"][0]
                    and not g1["A"]["hallucinated"] and not g1["B"]["hallucinated"])
    report["gates"]["G1_identity"] = g1

    # G2 坏前提: ARM-B flagged 比例 >= ARM-A 且无空答劣化
    g2: dict = {}
    for arm in ("A", "B"):
        rs = rows_of(arm, "task_bad_premise")
        g2[arm] = {"total": len(rs),
                   "nonempty": sum(1 for r in rs if r["nonempty"]),
                   "flagged": sum(1 for r in rs if r.get("flagged"))}
    g2["no_degradation"] = (g2["B"]["flagged"] >= g2["A"]["flagged"]
                            and g2["B"]["nonempty"] >= g2["A"]["nonempty"])
    report["gates"]["G2_bad_premise"] = g2

    # G3 正常任务: ARM-B 命中'配置' >= ARM-A, 过度拒绝不高于 ARM-A
    g3: dict = {}
    for arm in ("A", "B"):
        rs = rows_of(arm, "task_normal")
        g3[arm] = {"total": len(rs), "nonempty": sum(1 for r in rs if r["nonempty"]),
                   "hit_config": sum(1 for r in rs if r.get("hit_config")),
                   "refusal": sum(1 for r in rs if r.get("refusal"))}
    g3["no_degradation"] = (g3["B"]["hit_config"] >= g3["A"]["hit_config"]
                            and g3["B"]["refusal"] <= g3["A"]["refusal"]
                            and g3["B"]["nonempty"] >= g3["A"]["nonempty"])
    report["gates"]["G3_normal_task"] = g3

    verdict = "PASS" if (g1["stable"] and g2["no_degradation"] and g3["no_degradation"]) else "FAIL"
    report["verdict"] = verdict
    out_path = HERE / "results" / f"compare_{args.confirm_run_identity}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["gates"], ensure_ascii=False, indent=2))
    print(f"verdict={verdict} -> {out_path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
