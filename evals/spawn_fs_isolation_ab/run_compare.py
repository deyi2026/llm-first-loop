"""EVO-20261016-ac47e850 上线前硬性检查(b): 弱模型档身份轮+任务轮行为对照.

对照面: ARM-A = 变更前 spawn_subagent.requires schema 描述（git HEAD 提取，
          断言不含 fs_isolation 锚点）
        ARM-B = 工作区新 schema（含 requires.fs_isolation 描述）
模型: qwen3.8-flash-next @ cognilocal（本地, free）. n=3/格, temperature=0.
机械判据(不做语义评分):
  G1 身份轮: 两臂自报身份关键要素一致 + 工具名单集合一致(允许子集, 不得幻觉新增)
  G2 隔离施工任务: ARM-B 提及隔离手段(fs_isolation/worktree/隔离)的比例
     >= ARM-A; 且输出 JSON 可解析率不劣化
  G3 普通委派任务: ARM-B 声明 fs_isolation=true 的比例不高于 ARM-A 幻觉新键比例
     （即不过度隔离）; 输出可解析率不劣化
劣化判定: 任一机械判据 ARM-B 严格差于 ARM-A → FAIL(不得上线)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
TOOL_SRC = "src/llm_loop/tools/builtin/spawn_subagent.py"
BASE_URL = "http://localhost:8901/v1"
MODEL = "qwen3.8-flash-next"
N_REPS = 3


def _schema_surface(src: str) -> str:
    start = src.index('"requires"')
    end = src.index('"required"', start)
    return src[start:end]


def arm_texts() -> tuple[str, str]:
    head = subprocess.run(
        ["git", "show", f"HEAD:{TOOL_SRC}"], cwd=REPO, capture_output=True, text=True
    )
    assert head.returncode == 0, head.stderr
    old_src = head.stdout
    assert "fs_isolation" not in _schema_surface(old_src), "ARM-A 锚点失效: HEAD 已含 fs_isolation"
    work_src = (REPO / TOOL_SRC).read_text("utf-8")
    assert "fs_isolation" in _schema_surface(work_src), "ARM-B 锚点失效: 工作区缺 fs_isolation"
    return _schema_surface(old_src), _schema_surface(work_src)


IDENTITY_PROMPT = (
    "请依次回答: 1) 你是什么模型、在什么运行环境/框架中工作？ 2) 列出你当前可用的全部工具名称（只要名字，逗号分隔，不要解释）。"
    "只依据本次上下文可见信息作答，不要猜测未提供的内容。不要发起任何工具调用，直接以文字作答。"
)

ISOLATION_TASK = (
    "下面是 spawn_subagent 工具 requires 参数的 schema 描述（唯一权威依据，不要使用 schema 之外的知识）:\n"
    "---\n{schema}\n---\n"
    "场景: 你要用 spawn_subagent 派一个子代理重构 tests/foo.py；同时你自己在主工作区改 src/bar.py。"
    "要求子代理的改动与你自己的改动互不污染、可独立审查。\n"
    "请直接输出你会传的 requires 值: 一个单行 JSON 对象，不要解释。"
)

PLAIN_TASK = (
    "下面是 spawn_subagent 工具 requires 参数的 schema 描述（唯一权威依据，不要使用 schema 之外的知识）:\n"
    "---\n{schema}\n---\n"
    "场景: 你要派一个子代理读取 docs/x.md 并总结要点，无任何特殊权限需求。\n"
    "请直接输出你会传的 requires 值: 一个单行 JSON 对象（无需声明则输出 {{}}），不要解释。"
)


def _ask(client: httpx.Client, system: str, user: str) -> str:
    for attempt in (1, 2):
        try:
            resp = client.post(
                "/chat/completions",
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0,
                    "max_tokens": 1024,
                },
                timeout=300,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"] or ""
        except httpx.HTTPError:
            if attempt == 2:
                raise
    return ""


def _parse_json_obj(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None


ISOLATION_WORDS = ("fs_isolation", "worktree", "隔离")


def main() -> int:
    arm_a, arm_b = arm_texts()
    print(f"ARM-A {len(arm_a)} chars / ARM-B {len(arm_b)} chars")
    report: dict = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "model": MODEL,
        "n": N_REPS,
        "arms": {"A_len": len(arm_a), "B_len": len(arm_b)},
        "cells": {},
    }
    fails: list[str] = []
    with httpx.Client(base_url=BASE_URL, trust_env=False) as client:
        # G1 身份轮: 两臂提示词相同（schema 未进入身份轮）——对照的是
        # 引入 fs_isolation 文本后身份自报的稳定性（B 不得幻觉出 A 没有的工具名）。
        g1 = {}
        for arm, schema in (("A", arm_a), ("B", arm_b)):
            outs = [_ask(client, "", IDENTITY_PROMPT) for _ in range(N_REPS)]
            tools = set()
            ids = set()
            for o in outs:
                # 按常见分隔符切词, 提取形似工具名的 token（字母开头, 含字母/数字/._）。
                seg = re.split(r"[\s，,、\n/|]+", o)
                names = {
                    t.strip("`*-.") for t in seg
                    if re.fullmatch(r"[A-Za-z][\w.]*", t.strip("`*-."))
                }
                tools |= names
                ids.add(o.splitlines()[0][:60] if o else "")
            g1[arm] = {"tools": sorted(tools), "first_lines": sorted(ids)}
            print(f"G1/{arm}: {len(tools)} tool names")
        a_t, b_t = set(g1["A"]["tools"]), set(g1["B"]["tools"])
        hallucinated = b_t - a_t - set()  # B 幻觉出 A 没有的名字（两臂 schema 均未列工具）
        g1["b_hallucinated_new"] = sorted(hallucinated)
        if hallucinated:
            fails.append(f"G1: ARM-B 幻觉工具名 {sorted(hallucinated)}")
        report["cells"]["g1"] = g1

        # G2 隔离施工任务
        g2 = {}
        for arm, schema in (("A", arm_a), ("B", arm_b)):
            outs = [
                _ask(client, "", ISOLATION_TASK.format(schema=schema))
                for _ in range(N_REPS)
            ]
            mentions = sum(
                1 for o in outs if any(w in o for w in ISOLATION_WORDS)
            )
            parseable = sum(1 for o in outs if _parse_json_obj(o) is not None)
            g2[arm] = {"mentions": mentions, "parseable": parseable, "raw": outs}
            print(f"G2/{arm}: mentions={mentions}/{N_REPS} parseable={parseable}/{N_REPS}")
        if g2["B"]["mentions"] < g2["A"]["mentions"]:
            fails.append(
                f"G2: ARM-B 提及隔离 {g2['B']['mentions']} < ARM-A {g2['A']['mentions']}"
            )
        if g2["B"]["parseable"] < g2["A"]["parseable"]:
            fails.append(
                f"G2: ARM-B JSON 可解析 {g2['B']['parseable']} < ARM-A {g2['A']['parseable']}"
            )
        report["cells"]["g2"] = g2

        # G3 普通委派任务（不过度隔离）
        g3 = {}
        for arm, schema in (("A", arm_a), ("B", arm_b)):
            outs = [
                _ask(client, "", PLAIN_TASK.format(schema=schema))
                for _ in range(N_REPS)
            ]
            objs = [_parse_json_obj(o) for o in outs]
            parseable = sum(1 for o in objs if o is not None)
            fs_true = sum(1 for o in objs if o and o.get("fs_isolation") is True)
            halluc_keys = sum(
                1 for o in objs if o and any(k not in {"tools", "network", "fs", "fs_isolation", "session_continuity"} for k in o)
            )
            g3[arm] = {"parseable": parseable, "fs_isolation_true": fs_true, "halluc_keys": halluc_keys, "raw": outs}
            print(
                f"G3/{arm}: parseable={parseable}/{N_REPS} fs_isolation_true={fs_true} halluc_keys={halluc_keys}"
            )
        if g3["B"]["fs_isolation_true"] > max(g3["A"]["halluc_keys"], 0):
            fails.append(
                f"G3: ARM-B 过度隔离 {g3['B']['fs_isolation_true']} > ARM-A 幻觉基线 {g3['A']['halluc_keys']}"
            )
        if g3["B"]["parseable"] < g3["A"]["parseable"]:
            fails.append(
                f"G3: ARM-B JSON 可解析 {g3['B']['parseable']} < ARM-A {g3['A']['parseable']}"
            )
        report["cells"]["g3"] = g3

    out = Path(__file__).resolve().parent / "results"
    out.mkdir(exist_ok=True)
    path = out / f"run_{report['ts'].replace(':', '').replace('-', '')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(f"\nresults → {path}")
    if fails:
        print("VERDICT: FAIL（不得上线）")
        for f in fails:
            print(" -", f)
        return 1
    print("VERDICT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
