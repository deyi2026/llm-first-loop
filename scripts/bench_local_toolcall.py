"""本地模型工具调用基准：前缀静态化 × 上下文大小 对格式成功率/参数正确率/耗时的影响
用法: python3 scripts/bench_local_toolcall.py [--model qwen3.8-27b-mlx]
输出: 逐任务明细 + 汇总表
"""

import argparse
import json
import time
import urllib.request
from datetime import datetime

BASE = "http://localhost:1234/v1/chat/completions"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜索网络获取最新信息",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "执行数学计算",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "数学表达式"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "设置定时提醒",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}, "seconds": {"type": "integer"}},
                "required": ["message", "seconds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询城市天气",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
]

TASKS = [
    {
        "id": "T1",
        "user": "帮我搜索最新的AI行业新闻",
        "expect_tool": "web_search",
        "expect_params": {"query": "AI"},
    },
    {
        "id": "T2",
        "user": "计算一下 17 乘以 23 等于多少",
        "expect_tool": "calculator",
        "expect_params": {"expression": "17"},
    },
    {
        "id": "T3",
        "user": "5分钟后提醒我去开周会",
        "expect_tool": "set_reminder",
        "expect_params": {"message": "周会", "seconds": "300"},
    },
    {
        "id": "T4",
        "user": "帮我查一下北京明天的天气怎么样",
        "expect_tool": "get_weather",
        "expect_params": {"city": "北京"},
    },
    {
        "id": "T5",
        "user": "搜索一下 2025 年大模型落地应用案例，顺便看看杭州和深圳的天气",
        "expect_tool": "web_search",
        "expect_params": {"query": "大模型"},
    },
]

# 无关上下文填充（模拟长历史/大信息量）
LARGE_CTX = (
    "项目背景：本系统为 LLM-first 架构的自主运行平台，核心原则是程序作为感官和手脚、模型作为大脑。"
    "系统包含工具调用循环、记忆注入、经验沉淀、缓存优化、演进建议等多个模块。当前正在进行本地大模型工具调用性能优化专项。"
    "历史会话摘要：此前验证了前缀稳定对缓存命中的影响，确认 system prompt 中的动态内容会破坏前缀缓存。"
    "这是一段与当前请求无关的历史对话记录，用于测试大上下文对工具调用格式遵循的影响。"
) * 100


def call(model, messages, tools, timeout=240):
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": 512,
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        BASE,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    dt = time.time() - t0
    msg = body.get("choices", [{}])[0].get("message", {})
    usage = body.get("usage", {})
    return msg, dt, usage


def check(msg, task):
    """返回 (格式成功, 工具选择正确, 参数正确, 说明)"""
    tcs = msg.get("tool_calls") or []
    if not tcs:
        return (False, False, False, f"无tool_calls, content={msg.get('content', '')[:80]!r}")
    tc = tcs[0]
    name = tc.get("function", {}).get("name", "")
    try:
        args = json.loads(tc.get("function", {}).get("arguments", "{}"))
        args_ok = True
    except json.JSONDecodeError:
        args = {}
        args_ok = False
    fmt_ok = True
    tool_ok = name == task["expect_tool"]
    if not args_ok:
        return (
            False,
            tool_ok,
            False,
            f"参数JSON解析失败: {tc.get('function', {}).get('arguments', '')[:100]!r}",
        )
    # 参数正确性：期望 key 存在且值包含关键词
    for k, kw in task["expect_params"].items():
        v = str(args.get(k, ""))
        if not v or (kw not in v and not v.startswith(kw)):
            return (fmt_ok, tool_ok, False, f"参数{k}={v!r} 不匹配期望 {kw!r} (工具={name})")
    return (fmt_ok, tool_ok, True, f"OK 工具={name} 参数={json.dumps(args, ensure_ascii=False)}")


def run_case(model, task, prefix_mode, ctx_mode):
    ts = (
        "2026-08-21 12:00:00"
        if prefix_mode == "static"
        else datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    )
    sys_prompt = (
        f"你是工具调度助手。当前时间: {ts}。根据用户请求选择并调用最合适的工具。"
        "只输出工具调用，不输出额外解释。"
    )
    if ctx_mode == "large":
        sys_prompt = LARGE_CTX + "\n\n" + sys_prompt
    msgs = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": task["user"]}]
    try:
        msg, dt, usage = call(model, msgs, TOOLS)
        fmt, tool_ok, param_ok, note = check(msg, task)
        return {
            "fmt": fmt,
            "tool": tool_ok,
            "param": param_ok,
            "dt": dt,
            "tokens": usage.get("total_tokens", 0),
            "note": note,
        }
    except Exception as e:
        return {
            "fmt": False,
            "tool": False,
            "param": False,
            "dt": None,
            "tokens": None,
            "note": f"调用异常: {type(e).__name__}: {e}",
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.8-27b-mlx")
    args = ap.parse_args()
    print(f"== 本地工具调用基准 模型={args.model} 任务数={len(TASKS)} 组合=2x2 ==", flush=True)
    results = []
    for task in TASKS:
        for pm in ("static", "dynamic"):
            for cm in ("small", "large"):
                r = run_case(args.model, task, pm, cm)
                r.update({"task": task["id"], "prefix": pm, "ctx": cm})
                results.append(r)
                print(
                    f"{task['id']} [{pm}/{cm}] fmt={r['fmt']} tool={r['tool']} param={r['param']} "
                    f"dt={r['dt']:.1f}s tok={r['tokens']} | {r['note'][:80]}",
                    flush=True,
                )
    # 汇总
    print("\n== 汇总 ==")
    for pm in ("static", "dynamic"):
        for cm in ("small", "large"):
            rs = [r for r in results if r["prefix"] == pm and r["ctx"] == cm]
            n = len(rs)
            f = sum(r["fmt"] for r in rs)
            t = sum(r["tool"] for r in rs)
            p = sum(r["param"] for r in rs)
            dts = [r["dt"] for r in rs if r["dt"]]
            print(
                f"[{pm}/{cm}] n={n} 格式成功率={f}/{n} 工具正确={t}/{n} 参数正确={p}/{n} "
                f"平均耗时={sum(dts) / len(dts):.1f}s"
                if dts
                else f"[{pm}/{cm}] n={n} 格式成功率={f}/{n} 无耗时数据"
            )
    # 前缀缓存观察：static 组合第2次起是否更快（同前缀重复）
    print("\n== 静态前缀耗时序列（观察前缀缓存）==")
    for task in TASKS:
        s = [
            r
            for r in results
            if r["task"] == task["id"] and r["prefix"] == "static" and r["ctx"] == "small"
        ]
        dts = [f"{r['dt']:.1f}" for r in s if r["dt"]]
        print(f"{task['id']}: " + " → ".join(dts))


if __name__ == "__main__":
    main()
