# -*- coding: utf-8 -*-
"""本地模型工具调用加严基准 v2（真实 lms-chat 协议对齐 harness）
变量: 前缀 static/dynamic × 上下文 small/large（唯一变量原则）
指标: 格式成功率/工具选择/参数正确(含嵌套)/多工具判定/prefill耗时/推理耗时/首生成/总耗时
N=6 任务, 判定逻辑与 client.py _parse_text_tool_calls 逐字对齐
用法: python3 scripts/bench_local_toolcall_v2.py [--model qwen3.8-27b-mlx]
"""
import json, sys, time, urllib.request, argparse, re, http.client
from datetime import datetime

BASE = "http://localhost:1234/api/v1/chat"

# ── 10 工具（含嵌套参数与歧义对）──
TOOLS = [
    {"function": {"name": "web_search", "description": "搜索网络获取最新信息",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}}},
    {"function": {"name": "get_weather", "description": "查询城市当前天气情况",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
    {"function": {"name": "calculator", "description": "执行数学表达式计算",
     "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}},
    {"function": {"name": "set_reminder", "description": "设置定时提醒，到点通知用户",
     "parameters": {"type": "object", "properties": {"message": {"type": "string"}, "seconds": {"type": "integer"}}, "required": ["message", "seconds"]}}},
    {"function": {"name": "translate_text", "description": "将文本翻译为目标语言。必填参数: text, target_lang",
     "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "待翻译的原文内容"}, "target_lang": {"type": "string", "description": "目标语言代码，如 en/zh/ja"}}, "required": ["text", "target_lang"]}}},
    {"function": {"name": "summarize", "description": "对长文本生成摘要。必填参数: text",
     "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "待摘要的长文本"}, "max_words": {"type": "integer", "description": "摘要最大字数（可选）"}}, "required": ["text"]}}},
    {"function": {"name": "get_stock_price", "description": "查询股票当前价格。必填参数: symbol",
     "parameters": {"type": "object", "properties": {"symbol": {"type": "string", "description": "股票代码，如 AAPL/TSLA"}}, "required": ["symbol"]}}},
    {"function": {"name": "create_note", "description": "创建笔记并添加标签。必填参数: title, content",
     "parameters": {"type": "object", "properties": {"title": {"type": "string", "description": "笔记标题"}, "content": {"type": "string", "description": "笔记正文"}, "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表（可选）"}}, "required": ["title", "content"]}}},
    {"function": {"name": "list_files", "description": "列出目录下的文件",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"function": {"name": "send_email", "description": "发送邮件，支持定时发送。必填参数: to, subject, body；若指定定时发送则 schedule 必填",
     "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
       "schedule": {"type": "object", "properties": {"date": {"type": "string"}, "time": {"type": "string"}}}},
      "required": ["to", "subject", "body", "schedule"]}}},
]

# ── 6 任务：期望工具列表 + 参数检查（key 支持嵌套 "a.b"）──
TASKS = [
    {"id": "T1", "user": "帮我搜索最新的AI行业新闻",
     "expect_tools": ["web_search"], "expect_params": {"query": "AI"}},
    {"id": "T2", "user": "计算 17 乘以 23 等于多少",
     "expect_tools": ["calculator"], "expect_params": {"expression": "17"}},
    {"id": "T3", "user": "查一下北京明天会下雨吗",
     "expect_tools": ["get_weather"], "expect_params": {"city": "北京"}},
    {"id": "T4", "user": "给 zhang@example.com 发一封邮件，主题是季度汇报，正文写 见附件，安排在明天上午10点发送",
     "expect_tools": ["send_email"],
     "expect_params": {"to": "zhang", "subject": "季度", "body": "附件", "schedule.date": "2026", "schedule.time": "10"}},
    {"id": "T5", "user": "搜索最新的AI芯片新闻，顺便查一下深圳的天气",
     "expect_tools": ["web_search", "get_weather"], "expect_params": {"query": "芯片", "city": "深圳"}},
    {"id": "T6", "user": "把这段话翻译成英文：今天天气很好，我们出去散步吧",
     "expect_tools": ["translate_text"], "expect_params": {"text": "散步", "target_lang": "en"}},
]

# ── 大上下文：真实 harness 消息格式的 16 条历史 tail（与 _lms_msg_text 一致）──
def _hist_tail(n=8):
    pairs = []
    for i in range(n):
        pairs += [
            "[用户] 帮我看看项目里 client.py 有什么问题（历史对话，与当前请求无关）",
            f"[助手] [调用工具 read_file 参数 {{\"path\": \"src/llm_loop/llm/client.py\"}}]",
            f"[工具结果 read_file] 共 1058 行，第 {i*100} 行附近有截断提示",
        ]
    return "\n".join(pairs[:16])

LARGE_HIST = _hist_tail()

def tools_text(tools):
    lines = ["[可用工具]"]
    for t in tools:
        fn = t.get("function") or t
        desc = (fn.get("description") or "").strip().split("\n")[0][:120]
        params = fn.get("parameters") or {}
        props = params.get("properties") or {}
        skeleton = {k: {"type": v.get("type", "string")} for k, v in props.items()}
        lines.append(json.dumps({"name": fn.get("name",""), "description": desc,
            "parameters": {"type": "object", "properties": skeleton, "required": params.get("required", [])}},
            ensure_ascii=False))
    lines.append('需要调用工具时，仅输出一行 JSON: {"tool": "工具名", "args": {...}}；多个调用用换行分隔，不要输出其他内容。')
    return "\n".join(lines)

# 与 client.py _parse_text_tool_calls 逐字一致
def parse_text_tool_calls(text):
    out = []
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m: s = m.group(1).strip()
    for tm in re.finditer(r'"tool"\s*:\s*"[^"]+"', s):
        i = tm.start()
        while i > 0 and s[i] != "{": i -= 1
        if s[i] != "{": continue
        depth = 0; in_str = False; esc = False; j = i
        while j < len(s):
            ch = s[j]
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
            else:
                if ch == '"': in_str = True
                elif ch == "{": depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0: break
            j += 1
        if j >= len(s): continue
        try: d = json.loads(s[i:j+1])
        except ValueError: continue
        name = d.get("tool")
        if not name: continue
        args = d.get("args") or {}
        if isinstance(args, str):
            try: args = json.loads(args)
            except ValueError: args = {}
        out.append({"name": name, "arguments": args if isinstance(args, dict) else {}})
    return out

def call(model, content, timeout=300):
    """http.client 复用连接 + 完整读取（urllib 逐行迭代 SSE 会触发 LM Studio
    'Client disconnected' 判定导致交替 400，已实测 6/6 验证修复）."""
    payload = {"model": model, "input": [{"type": "text", "content": content}], "stream": True}
    body = json.dumps(payload).encode()
    conn = http.client.HTTPConnection("localhost", 1234, timeout=timeout)
    t0 = time.time()
    events = []  # (ts_rel, type)
    content_parts = []
    try:
        conn.request("POST", "/api/v1/chat", body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        if resp.status != 200:
            raw = resp.read().decode("utf-8", errors="replace")[:1500]
            raise RuntimeError(f"HTTP {resp.status}: {raw}")
        data = resp.read().decode("utf-8", errors="replace")
        for line in data.splitlines():
            line = line.strip()
            if not line.startswith("data:"): continue
            try: e = json.loads(line[5:].strip())
            except: continue
            t = e.get("type", "?")
            ts = time.time() - t0
            events.append((ts, t))
            if t == "prompt_processing.end":
                events.append((ts, "_PREFILL_END"))
            elif t == "reasoning.start":
                events.append((ts, "_REASON_START"))
            elif t == "reasoning.end":
                events.append((ts, "_REASON_END"))
            elif t == "message.delta":
                d = e.get("delta") or {}
                if isinstance(d, dict) and d.get("type") == "text":
                    content_parts.append(d.get("content") or "")
                elif e.get("content"):
                    content_parts.append(str(e["content"]))
                if not any(x[1] == "_FIRST_MSG" for x in events):
                    events.append((ts, "_FIRST_MSG"))
            elif t == "chat.end":
                events.append((ts, "_END"))
    finally:
        conn.close()
    total = time.time() - t0
    full = "".join(content_parts)
    return full, events, total

def stage(events, name):
    for ts, t in events:
        if t == name: return ts
    return None

def check(task, calls):
    got = [c["name"] for c in calls]
    fmt = len(calls) >= len(task["expect_tools"])
    tools_ok = set(task["expect_tools"]) <= set(got)
    params_ok = True; miss = []
    # P0: 必填完整性按 schema required 动态校验（声明=检查，消除假阳性）——
    # 对每个期望工具，从 TOOLS schema 取 required，逐个验证调用参数是否齐备
    for exp_tool in task["expect_tools"]:
        schema_required = []
        for t in TOOLS:
            fn = t.get("function") or t
            if fn.get("name") == exp_tool:
                schema_required = (fn.get("parameters") or {}).get("required", [])
                break
        for req_key in schema_required:
            found = False
            for c in calls:
                if c["name"] != exp_tool: continue
                v = c["arguments"]
                for kk in req_key.split("."):
                    if isinstance(v, dict) and kk in v: v = v[kk]
                    else: v = None; break
                if isinstance(v, str) and v:
                    found = True; break
                if isinstance(v, (int, float)) and v is not None:
                    found = True; break
                if isinstance(v, dict) and v:  # 嵌套对象非空即存在（如 schedule 整体）
                    found = True; break
            if not found: miss.append(f"required.{exp_tool}.{req_key}")
    # 值内容检查（expect_params 语义验证）
    for k, kw in task["expect_params"].items():
        found = False
        for c in calls:
            if c["name"] not in task["expect_tools"]: continue
            v = c["arguments"]
            for kk in k.split("."):
                if isinstance(v, dict) and kk in v: v = v[kk]
                else: v = None; break
            if isinstance(v, str) and kw in v:
                found = True; break
            if isinstance(v, (int, float)) and str(v).startswith(str(kw)):
                found = True; break
        if not found: miss.append(f"{k}~{kw}")
        params_ok = params_ok and found
    return fmt, tools_ok, params_ok, miss

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.8-27b-mlx")
    args = ap.parse_args()
    print(f"== v2 加严基准 模型={args.model} N={len(TASKS)} 组合=2x2 (真实lms-chat协议) ==", flush=True)
    results = []
    for task in TASKS:
        for pm in ("static", "dynamic"):
            for cm in ("small", "large"):
                ts = "2026-08-21 12:00:00" if pm == "static" else datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                sys_text = (f"你是工具调度助手。当前时间: {ts}。根据用户请求选择并调用最合适的工具。只输出工具调用，不输出额外解释。")
                parts = ["[系统] " + sys_text]
                parts.append(tools_text(TOOLS))
                if cm == "large":
                    parts.append(LARGE_HIST)
                parts.append("[用户] " + task["user"])
                content = "\n\n".join(parts)
                try:
                    full, events, total = call(args.model, content)
                    calls = parse_text_tool_calls(full)
                    fmt, t_ok, p_ok, miss = check(task, calls)
                    r = {"task": task["id"], "prefix": pm, "ctx": cm, "fmt": fmt, "tool": t_ok, "param": p_ok,
                         "miss": miss, "total": total, "calls": [c["name"] for c in calls],
                         "prefill": stage(events, "_PREFILL_END"), "reason": stage(events, "_REASON_END"),
                         "first_msg": stage(events, "_FIRST_MSG")}
                except Exception as e:
                    full = ""
                    calls = []
                    r = {"task": task["id"], "prefix": pm, "ctx": cm, "fmt": False, "tool": False, "param": False,
                         "miss": [str(e)], "total": None, "calls": [], "prefill": None, "reason": None, "first_msg": None}
                results.append(r)
                def _fmt(x):
                    return f"{x:.1f}" if x is not None else "-"
                print(f"{task['id']} [{pm}/{cm}] fmt={r['fmt']} tool={r['tool']} param={r['param']} "
                      f"calls={r['calls']} miss={r['miss']} | total={_fmt(r['total'])}s "
                      f"prefill={_fmt(r['prefill'])}s reason={_fmt(r['reason'])}s first_msg={_fmt(r['first_msg'])}s", flush=True)
                if not calls:
                    print(f"    ! 无工具调用, content前400: {full[:400]!r}", flush=True)
    print("\n== 汇总 ==")
    for pm in ("static", "dynamic"):
        for cm in ("small", "large"):
            rs = [r for r in results if r["prefix"] == pm and r["ctx"] == cm]
            n = len(rs)
            f = sum(r["fmt"] for r in rs); t = sum(r["tool"] for r in rs); p = sum(r["param"] for r in rs)
            tots = [r["total"] for r in rs if r["total"]]
            pre = [r["prefill"] for r in rs if r["prefill"] is not None]
            rea = [r["reason"] for r in rs if r["reason"] is not None]
            fm = [r["first_msg"] for r in rs if r["first_msg"] is not None]
            def avg(x): return sum(x)/len(x) if x else None
            print(f"[{pm}/{cm}] n={n} 格式={f}/{n} 工具={t}/{n} 参数={p}/{n} "
                  f"总耗时={avg(tots) and f'{avg(tots):.1f}s' or '-'} prefill={avg(pre) and f'{avg(pre):.1f}s' or '-'} "
                  f"推理={avg(rea) and f'{avg(rea):.1f}s' or '-'} 首生成={avg(fm) and f'{avg(fm):.1f}s' or '-'}")
    # 保存明细
    with open("data/audit/bench_v2_results.json", "w", encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=2)
    print("\n明细已存 data/audit/bench_v2_results.json")

if __name__ == "__main__":
    main()
