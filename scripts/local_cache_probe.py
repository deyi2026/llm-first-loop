#!/usr/bin/env python3
"""本地模型（LM Studio / llama.cpp）前缀 KV 缓存命中探针（2026-08-24）.

背景: LFL 本地工具轮「稳定前缀 + 极小窗口」方案的可观测性验证——
llama.cpp 引擎前缀缓存命中与否取决于「字节级稳定前缀」; 本脚本用三实验法
（A 冷启动 / B 同 payload 重发 / C 前缀+追加）判定该环境是否启用 KV 复用、
命中率多少、首 token 提速多少。

用法:
  .venv/bin/python scripts/local_cache_probe.py
  .venv/bin/python scripts/local_cache_probe.py --model qwen/qwen3.8-27b --tool-round

实验设计（对齐 skills/cache-hit-debug 三实验法）:
  A warm        → 期望 cached=0（冷启动）
  B same-payload→ 期望 cached≈prompt（精确缓存命中）
  C 前缀+追加1   → 期望 cached≈A.prompt（前缀缓存: 仅新增段 miss）
判定:
  B 全命中 → 精确缓存存在; C 命中 → 前缀缓存存在（追加不破坏命中）;
  两者都不中 → 该环境未启用 KV 复用（检查 LM Studio Context Caching 设置）。

--tool-round: 用 LFL 工具轮形态（system + 工具 schema + 最近完整配对组）模拟,
             更贴近真实工具轮 payload 与 prefill 时延。
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx


def build_general_msgs(extra: bool = False) -> list[dict]:
    sys_msg = {
        "role": "system",
        "content": "你是 LFL 助手。固定系统前缀锚点，工具调用请输出 JSON。系统规则：基于事实回答，不猜测。",
    }
    msgs = [sys_msg]
    for i in range(8):
        msgs.append(
            {
                "role": "user",
                "content": (
                    f"第{i}步：请处理任务段{i}，这是用于前缀缓存实验的稳定内容。"
                    + "填充内容填充内容填充内容填充内容" * 5
                ),
            }
        )
        msgs.append({"role": "assistant", "content": f"[第{i}步完成] 处理了任务段{i}，结果正常。"})
    if extra:
        msgs.append({"role": "user", "content": "追加一条新请求，前缀应命中。"})
    return msgs


def build_tool_round_msgs(extra: bool = False) -> list[dict]:
    """LFL 工具轮极小窗口形态: system + 工具 schema + 最近完整配对组."""
    tools_text = (
        '[{"name":"read_file","description":"读取文件","parameters":{"properties":{"path":{"type":"string"}}}}'
        ',{"name":"execute_command","description":"执行命令","parameters":{"properties":{"cmd":{"type":"string"}}}}]'
    )
    msgs = [
        {
            "role": "system",
            "content": (
                "你是 LFL 助手。固定系统前缀锚点。可用工具:\n" + tools_text + "\n需要调用工具时仅输出工具名与参数 JSON。"
            ),
        },
        {"role": "user", "content": "请检查服务状态并汇报。"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call_a", "type": "function", "function": {"name": "execute_command", "arguments": {"cmd": "ps aux | head"}}},
                {"id": "call_b", "type": "function", "function": {"name": "read_file", "arguments": {"path": "/tmp/x"}}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "[状态: success] [输出 3 行] python 进程正常"},
        {"role": "tool", "tool_call_id": "call_b", "content": "[状态: success] 文件内容 42 字节"},
    ]
    if extra:
        msgs.append({"role": "user", "content": "[工具结果已回填] 请继续。"})
    return msgs


def call(client: httpx.Client, url: str, model: str, msgs: list[dict], label: str) -> dict:
    t0 = time.time()
    try:
        r = client.post(
            url,
            json={"model": model, "messages": msgs, "max_tokens": 8, "stream": False},
            timeout=300,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  {label}: 请求异常 {type(exc).__name__}: {exc}")
        return {}
    dt = time.time() - t0
    if r.status_code != 200:
        print(f"  {label}: HTTP {r.status_code}（连接被拒/服务忙，LM Studio 可能正在推理或未就绪）")
        return {"http_error": r.status_code}
    j = r.json()
    u = j.get("usage", {})
    det = u.get("prompt_tokens_details", {})
    cached = det.get("cached_tokens") or 0
    prompt = u.get("prompt_tokens") or 0
    miss = max(0, prompt - cached)
    pct = (cached / prompt * 100) if prompt else 0.0
    print(
        f"  {label}: prompt={prompt:>5} cached={cached:>5} miss={miss:>5} "
        f"hit={pct:5.1f}%  ttf={dt*1000:7.0f}ms"
    )
    return {"prompt": prompt, "cached": cached, "miss": miss, "pct": pct, "ms": dt * 1000}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:1234/v1", help="OpenAI 兼容端点（默认 localhost:1234/v1）")
    ap.add_argument("--model", default="qwen/qwen3.8-27b", help="本地模型 id（/v1/models 列表）")
    ap.add_argument("--api-key", default="", help="直连 llama-server 的 Bearer key（lms ps / ps aux 查 --api-key）")
    ap.add_argument("--tool-round", action="store_true", help="用 LFL 工具轮形态模拟（默认用一般对话形态）")
    ap.add_argument("--ttl", type=float, default=0.0, help=">0 时在 B 与 C 之间加等值秒数间隔做 TTL 探测")
    args = ap.parse_args()

    url = args.base_url.rstrip("/") + "/chat/completions"
    builder = build_tool_round_msgs if args.tool_round else build_general_msgs

    print(f"== 本地前缀缓存探针 ==  model={args.model}  mode={'tool-round' if args.tool_round else 'general'}")
    print(f"   端点: {url}\n")

    headers = {}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    # trust_env=False: 直连 llama-server 必须绕过 macOS 系统代理（Surge 等会把回环
    # 请求转给代理 → 503 Connection Closed，与 LFL 本地直连修复同因）
    with httpx.Client(headers=headers, trust_env=False) as client:
        a = call(client, url, args.model, builder(extra=False), "A warm        ")
        if not a or a.get("http_error"):
            print("\n❌ 服务未就绪——确认 LM Studio 已加载模型且无进行中的推理后重试。")
            return 2
        time.sleep(1.0)
        b = call(client, url, args.model, builder(extra=False), "B same-payload")
        if args.ttl > 0:
            print(f"    (TTL 间隔 {args.ttl}s...)")
            time.sleep(args.ttl)
        time.sleep(1.0)
        c = call(client, url, args.model, builder(extra=True), "C prefix+append")

    print()
    b_hit = bool(b and b.get("pct", 0) >= 95)
    c_hit = bool(c and c.get("pct", 0) >= 80)
    if b_hit and c_hit:
        print("✅ 前缀缓存存在: B 精确重发全命中 + C 追加仅新增段 miss → 追加不破坏命中。")
        print("   LFL「稳定前缀 + 尾部追加」策略在本环境成立, 本地工具轮 KV 命中可行。")
    elif b_hit:
        print("⚠️ 仅精确缓存命中, 前缀追加不命中——可能是短 prompt 阈值效应或 KV 复用粒度过粗。")
    else:
        print("❌ 未检测到前缀缓存——检查 LM Studio 设置（Context Caching / Prompt Caching 是否开启）。")
    return 0 if (b_hit and c_hit) else 1


if __name__ == "__main__":
    sys.exit(main())
