#!/usr/bin/env python3
"""playwright_exec 验收基准（EVO-20260816-bfb9f215 阶段二 · 方法论评测纪律第 5 条首单）.

固定 5 个网关 Web E2E 任务 × 3 次重复，跑新形态 playwright_exec；旧形态
playwright_test 仅 goto+screenshot、无交互/断言能力（EVAL 报告 §一），不作为
对照执行项——基准聚焦"能力补齐"首要目标。token 消耗对照待真实 LLM 路径补测。

前置：网关 Web 在线（默认 http://localhost:8902，WEB_PORT 可覆盖）+ chromium 已安装。
用法: .venv/bin/python scripts/bench_playwright_exec.py [--base http://localhost:8902]
产出: data/e2e/bench/report_<ts>.json + 控制台对照表
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

REPEATS = 3

# 固定 5 任务（对网关 Web V2 真实路由的回归面；路由经 routes.py 核验 2026-08-16）
TASKS = [
    {"id": "home_render", "desc": "首页渲染：标题非空 + axtree 有内容",
     "code_tpl": '# 首页渲染检查\nt = goto("{base}/")\nassert t, "标题为空"\ntree = axtree_text()\nassert tree, "无障碍树为空"\nprint("TITLE:", t)\nprint("TREE_CHARS:", len(tree))'},
    {"id": "file_preview", "desc": "文件预览：/api/v1/files/preview 可达",
     "code_tpl": '# 文件预览 API\ngoto("{base}/")\nr = js("fetch(\'/api/v1/files/preview?path=README.md\').then(r=>r.status)")\nassert r in (200, 400, 404, 409), f"异常状态 {{r}}"\nprint("PREVIEW_API_STATUS:", r)'},
    {"id": "history_lazy", "desc": "历史会话：/api/v1/sessions 返回 200",
     "code_tpl": '# 会话列表接口\ngoto("{base}/")\nr = js("fetch(\'/api/v1/sessions\').then(r=>r.status)")\nassert r == 200, f"sessions {{r}}"\nprint("SESSIONS_STATUS:", r)'},
    {"id": "tool_card", "desc": "工具卡钩子：DOM 查询 tool 类节点可执行",
     "code_tpl": '# 工具卡钩子\ngoto("{base}/")\nn = js("document.querySelectorAll(\'[class*=tool]\').length")\nassert isinstance(n, int)\nprint("TOOL_NODES:", n)'},
    {"id": "feishu_card", "desc": "健康检查：/health 200 + service 字段",
     "code_tpl": '# 健康检查\ngoto("{base}/")\nr = js("fetch(\'/health\').then(r=>r.status)")\nassert r == 200, f"health {{r}}"\nbody = js("fetch(\'/health\').then(r=>r.json()).then(j=>j.service)")\nassert body, "service 字段为空"\nprint("HEALTH:", r, body)'},
]


def run_exec_task(base: str, task: dict, repeat: int) -> dict:
    """经 playwright_exec 子进程路径执行单任务."""
    from llm_loop.introspection.tools_playwright_exec import run_playwright_exec

    t0 = time.time()
    r = run_playwright_exec(None, None, {
        "code": task["code_tpl"].format(base=base),
        "session": f"bench/{task['id']}",
        "confirm": True,
        "timeout_s": 90,
    })
    return {
        "task": task["id"], "repeat": repeat,
        "status": r.status.value, "elapsed_s": round(time.time() - t0, 2),
        "tail": r.content[-300:],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8902")
    args = ap.parse_args()

    results = []
    for task in TASKS:
        for i in range(REPEATS):
            print(f"[{task['id']} #{i+1}] ...", flush=True)
            results.append(run_exec_task(args.base, task, i + 1))
            print(f"  -> {results[-1]['status']} ({results[-1]['elapsed_s']}s)", flush=True)

    ok = sum(1 for r in results if r["status"] == "success")
    report = {
        "base": args.base, "ts": time.time(),
        "total": len(results), "passed": ok, "pass_rate": round(ok / len(results), 3),
        "note": "playwright_test 旧形态对照: 仅 goto+screenshot，5 任务全部不可完成（能力缺失，见 EVAL 报告 §一）",
        "results": results,
    }
    out = Path("data/e2e/bench")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"report_{int(time.time())}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n== 通过率 {ok}/{len(results)} ({report['pass_rate']:.0%}) -> {path}")


if __name__ == "__main__":
    main()
