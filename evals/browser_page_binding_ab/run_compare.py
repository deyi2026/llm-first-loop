#!/usr/bin/env python3
"""EVO-20261007-11ae668f 弱模型档 prompt-surface A/B 对照。

演进模板硬性要求（进入 provider prompt 的 tool schema 策略文字变更）：
(b) cognilocal/qwen3.8-flash-next 身份轮 + 任务轮行为对照，无劣化才可上线。

arm-A_old_surface = git HEAD(a829e254a) 精确还原（旧描述 + 全量剥离 target_id）
arm-B_new_surface = 当前工作区代码导出（新描述 + target_id 属性）
判分全部机械（JSON 解析 + 关键字/键存在性），无语义打分。
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
import sys
import urllib.request

MODEL = os.environ.get("AB_MODEL", "qwen3.8-flash-next")
BASE_URL = os.environ.get("AB_BASE_URL", "http://localhost:8901/v1")
N_RUNS = 3
TEMP = 0.2
MAX_TOKENS = 1200  # qwen3.8 思考段占完成预算; 低值会触顶截断成空 content(harness 伪影, discipline 首跑已证实)
TIMEOUT_S = 120

OLD_PERCEIVE_DESC = (
    "Browser 只读感知：snapshot 读取 host 已绑定当前页面，hydrate 精确水合既有 ref，"
    "diff 比较两张 exact snapshot，wait 只读等待页面 ready/URL 或已观察对象 state/text。"
    "页面 wait 机械绑定当前 host-bound page；对象 wait 必须使用 exact grounding_ref。"
    "运行时拥有轮询节奏和默认超时；不导航、不 mutation、不 fuzzy/latest/rebind/retry，"
    "不判断 task completion，也不暴露 selector/坐标/CDP node id/AX index。"
    "method_ref=method:method-semantic-operation。"
)

FORBIDDEN_VENDOR_CLAIMS = ["chatgpt", "openai", "gpt-", "anthropic", "claude", "gemini", "文心", "bard"]


def _strip_target_id(node) -> None:
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict) and "target_id" in props:
            del props["target_id"]
        req = node.get("required")
        if isinstance(req, list) and "target_id" in req:
            req.remove("target_id")
        for v in node.values():
            _strip_target_id(v)
    elif isinstance(node, list):
        for v in node:
            _strip_target_id(v)


def build_arms() -> dict[str, list[dict]]:
    from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
    from llm_loop.tools.builtin.browser_semantic_operation import BrowserSemanticOperationTool

    def _def(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": copy.deepcopy(cls.parameters),
            },
        }

    arms: dict[str, list[dict]] = {
        "arm-B_new_surface": [_def(BrowserPerceiveTool), _def(BrowserSemanticOperationTool)]
    }
    old = copy.deepcopy(arms["arm-B_new_surface"])
    for t in old:
        _strip_target_id(t["function"]["parameters"])
        if t["function"]["name"] == "browser_perceive":
            t["function"]["description"] = OLD_PERCEIVE_DESC
    arms["arm-A_old_surface"] = old
    return arms


SYSTEM_TMPL = (
    "你是当前运行中的代理程序。本环境提供以下浏览器相关工具定义（其余工具与本问题无关）：\n{tools}"
)

IDENTITY_PROMPT = (
    "请只用一两句话介绍你自己：你是什么系统、由谁运行。"
    "然后列出你确定能使用的工具名；不确定就写“不确定”。"
)

TASK1_NORMAL = (
    "当前环境 host 已绑定唯一页面（正常单页状态）。用户要求：读取当前页面的语义对象快照。"
    "请直接输出你接下来会发起的工具调用参数：仅一个 JSON 对象，不要任何解释文字。"
)

TASK2_AMBIGUITY = (
    "你刚才调用了 browser_perceive，参数 {\"action\":\"snapshot\"}，收到如下 FAILURE 回执：\n"
    "{\"error\":\"multi_page_ambiguity\",\"pages\":["
    "{\"page_id\":\"page-A\",\"url\":\"https://passport.taobao.com/newlogin/login.htm\",\"title\":\"淘宝网-登录\"},"
    "{\"page_id\":\"page-B\",\"url\":\"https://www.taobao.com/\",\"title\":\"淘宝网 - 淘！我喜欢\"}],"
    "\"hint\":\"端点存在多个页面：显式传 target_id（取回执中的 page_id）绑定目标页后再发起动作。\"}\n"
    "用户目标在登录页（page-A）完成登录。请直接输出你接下来发起的 browser_perceive 调用参数："
    "仅一个 JSON 对象，不要任何解释文字。"
)


def chat(messages: list[dict]) -> str:
    payload = json.dumps(
        {"model": MODEL, "messages": messages, "temperature": TEMP, "max_tokens": MAX_TOKENS}
    ).encode()
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"] or ""


def extract_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def judge_identity(out: str) -> bool:
    low = out.lower()
    if not low.strip() or low.strip() in ("不确定", "无法回答"):
        return False
    if any(k in low for k in FORBIDDEN_VENDOR_CLAIMS):
        return False
    return True


def judge_task1(out: str) -> dict:
    obj = extract_json(out)
    ok = isinstance(obj, dict) and obj.get("action") == "snapshot"
    return {"parse_ok": ok, "spurious_target_id": bool(isinstance(obj, dict) and "target_id" in obj)}


def judge_task2(out: str) -> dict:
    obj = extract_json(out)
    parse_ok = isinstance(obj, dict) and obj.get("action") in ("snapshot", "wait", "hydrate")
    hit = parse_ok and obj.get("target_id") in ("page-A", "page-B")
    return {"parse_ok": parse_ok, "target_id_hit": bool(hit), "blind_retry": bool(parse_ok and "target_id" not in obj)}


def run(confirm: bool) -> int:
    arms = build_arms()
    results = {}
    for arm, tools in arms.items():
        system = SYSTEM_TMPL.format(tools=json.dumps(tools, ensure_ascii=False, indent=1))
        for label, prompt, judge in (
            ("G1_identity", IDENTITY_PROMPT, judge_identity),
            ("G2_task_normal", TASK1_NORMAL, judge_task1),
            ("G3_task_ambiguity", TASK2_AMBIGUITY, judge_task2),
        ):
            runs = []
            for i in range(N_RUNS):
                out = chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}])
                runs.append({"out": out, "judge": judge(out)})
                print(f"[{arm}] {label} run{i+1}: {json.dumps(judge(out), ensure_ascii=False)}")
            results.setdefault(arm, {})[label] = runs

    def _agg(arm, label, key):
        rr = results[arm][label]
        if isinstance(rr[0]["judge"], bool):
            return sum(1 for r in rr if r["judge"])
        return sum(1 for r in rr if r["judge"].get(key))

    def _avg(arm, label, key):
        return _agg(arm, label, key)

    gates = {}
    a, b = "arm-A_old_surface", "arm-B_new_surface"
    gates["G1"] = {
        "A_ok": _agg(a, "G1_identity", ""), "B_ok": _agg(b, "G1_identity", ""),
    }
    gates["G1"]["pass"] = gates["G1"]["A_ok"] >= N_RUNS - 1 and gates["G1"]["B_ok"] >= N_RUNS - 1 and gates["G1"]["B_ok"] >= gates["G1"]["A_ok"]
    gates["G2"] = {
        "A_parse": _avg(a, "G2_task_normal", "parse_ok"), "B_parse": _avg(b, "G2_task_normal", "parse_ok"),
        "A_spur": _avg(a, "G2_task_normal", "spurious_target_id"), "B_spur": _avg(b, "G2_task_normal", "spurious_target_id"),
    }
    gates["G2"]["pass"] = gates["G2"]["A_parse"] >= N_RUNS - 1 and gates["G2"]["B_parse"] >= N_RUNS - 1 and gates["G2"]["B_spur"] <= 1 and gates["G2"]["B_spur"] <= gates["G2"]["A_spur"] + 1
    gates["G3"] = {
        "A_parse": _avg(a, "G3_task_ambiguity", "parse_ok"), "B_parse": _avg(b, "G3_task_ambiguity", "parse_ok"),
        "A_hit": _avg(a, "G3_task_ambiguity", "target_id_hit"), "B_hit": _avg(b, "G3_task_ambiguity", "target_id_hit"),
    }
    gates["G3"]["pass"] = gates["G3"]["B_hit"] >= 2 and gates["G3"]["B_parse"] >= N_RUNS - 1
    overall = all(g["pass"] for g in gates.values())

    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"results_{ts}.json")
    with open(out_path, "w") as f:
        json.dump({"model": MODEL, "n_runs": N_RUNS, "gates": gates, "results": results, "overall_pass": overall}, f, ensure_ascii=False, indent=1)

    print("\n=== GATES ===")
    for g, v in gates.items():
        print(f"{g}: {json.dumps(v, ensure_ascii=False)}")
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    print(f"results -> {out_path}")
    return 0 if overall else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm-run-identity", action="store_true",
                    help="真实 LLM 调用确认（本地弱模型服务）")
    args = ap.parse_args()
    if not args.confirm_run_identity:
        print("refusing real LLM calls without --confirm-run-identity", file=sys.stderr)
        sys.exit(2)
    sys.exit(run(args.confirm_run_identity))
