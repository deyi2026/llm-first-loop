#!/usr/bin/env python3
"""DeepSeek API 前缀缓存探针（2026-08-25，对齐 local_cache_probe 三实验法）.

背景: LFL 镜像区当前装配 deepseek-v4-flash（官方 V4-Flash-0731, api.deepseek.com）。
DeepSeek 的 Context Caching 是服务端自动前缀缓存（磁盘缓存, 命中 token 按折扣价计费）。
本脚本用 A 冷启动 / B 同 payload 重发 / C 前缀+追加 判定:
  - 前缀缓存是否生效（B 全命中）
  - 追加是否破坏命中（C 命中 ≈ A.prompt）
  - 缓存 TTL 表现（--ttl 间隔后重发, 看命中是否保留）

用法:
  .venv/bin/python scripts/deepseek_cache_probe.py                 # flash 三实验
  .venv/bin/python scripts/deepseek_cache_probe.py --ttl 120      # 加 120s TTL 探测
  .venv/bin/python scripts/deepseek_cache_probe.py --model deepseek-v4-pro

环境: DEEPSEEK_API_KEY（.env 已配）; --base-url 默认 https://api.deepseek.com/v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

SYSTEM = (
    "你是 LFL 助手。固定系统前缀锚点。系统规则：基于事实回答，不猜测；"
    "需要调用工具时仅输出工具名与参数 JSON。" + "稳定前缀填充内容" * 40
)
TOOLS_TEXT = (
    '[{"name":"read_file","description":"读取文件","parameters":{"properties":{"path":{"type":"string"}}}}'
    ',{"name":"execute_command","description":"执行命令","parameters":{"properties":{"cmd":{"type":"string"}}}}]'
)


def build_msgs(extra: bool = False) -> list[dict]:
    """LFL 工具轮形态: system + 工具 schema + 最近完整配对组 + 历史段."""
    msgs: list[dict] = [
        {"role": "system", "content": SYSTEM + "\n可用工具:\n" + TOOLS_TEXT},
        {"role": "user", "content": "请检查服务状态并汇报。"},
        {
            "role": "assistant",
            "tool_calls": [
                # DeepSeek API: function.arguments 必须是 JSON 字符串（本地 llama.cpp 才接受对象）
                {"id": "call_a", "type": "function", "function": {"name": "execute_command", "arguments": json.dumps({"cmd": "ps aux | head"})}},
                {"id": "call_b", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": "/tmp/x"})}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "[状态: success] [输出 3 行] python 进程正常"},
        {"role": "tool", "tool_call_id": "call_b", "content": "[状态: success] 文件内容 42 字节"},
    ]
    # 历史段: 模拟多轮回答历史（稳定前缀的一部分）
    for i in range(6):
        msgs.append({"role": "user", "content": f"第{i}步：处理任务段{i}。" + "填充内容" * 30})
        msgs.append({"role": "assistant", "content": f"[第{i}步完成] 处理了任务段{i}，结果正常。"})
    if extra:
        msgs.append({"role": "user", "content": "[工具结果已回填] 请继续完成剩余步骤。"})
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
        print(f"  {label}: HTTP {r.status_code} {r.text[:200]}")
        return {"http_error": r.status_code}
    j = r.json()
    u = j.get("usage", {})
    # DeepSeek: prompt_cache_hit_tokens / prompt_cache_miss_tokens; 兜底 cached_tokens
    cached = int(u.get("prompt_cache_hit_tokens") or u.get("cached_tokens") or 0)
    prompt = int(u.get("prompt_tokens") or 0)
    miss = max(0, prompt - cached)
    pct = (cached / prompt * 100) if prompt else 0.0
    print(
        f"  {label}: prompt={prompt:>5} hit={cached:>5} miss={miss:>5} "
        f"hit_rate={pct:5.1f}%  ttf={dt*1000:7.0f}ms"
    )
    return {"prompt": prompt, "cached": cached, "miss": miss, "pct": pct, "ms": dt * 1000}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="https://api.deepseek.com/v1")
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--ttl", type=float, default=0.0, help=">0 时在 B 与 C 之间加等值秒数间隔做 TTL 探测")
    args = ap.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        print("❌ 未找到 DEEPSEEK_API_KEY / LLM_API_KEY（.env 未加载？）")
        return 2
    url = args.base_url.rstrip("/") + "/chat/completions"
    print(f"== DeepSeek 前缀缓存探针 ==  model={args.model}")
    print(f"   端点: {url}")

    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(headers=headers, timeout=300) as client:
        a = call(client, url, args.model, build_msgs(extra=False), "A cold          ")
        if not a or a.get("http_error"):
            print("\n❌ 请求失败——检查网络（代理）/ key / 模型名。")
            return 2
        time.sleep(1.0)
        b = call(client, url, args.model, build_msgs(extra=False), "B same-payload ")
        if args.ttl > 0:
            print(f"    (TTL 间隔 {args.ttl}s...)")
            time.sleep(args.ttl)
        time.sleep(1.0)
        c = call(client, url, args.model, build_msgs(extra=True), "C prefix+append")

    print()
    # DeepSeek 缓存为块粒度（实测载荷尾部 ~64-128 tokens 不入缓存），故阈值放宽:
    # B 命中 ≥80% 即精确重发命中; C 需同时满足 命中率≥80% 且 命中token数不较 B 回退（前缀未被破坏）
    b_hit = bool(b and b.get("pct", 0) >= 80)
    c_hit = bool(
        c and c.get("pct", 0) >= 80
        and b and c.get("cached", 0) >= b.get("cached", 0) * 0.95
    )
    if b_hit and c_hit:
        append_miss = (c.get("miss", 0) - b.get("miss", 0)) if b else 0
        append_tok = (c.get("prompt", 0) - b.get("prompt", 0)) if b else 0
        print("✅ 前缀缓存生效: B 同载荷重发高命中 + C 追加后命中 token 不缩水"
              f"（新增 miss {append_miss} ≈ 追加 {append_tok} tokens）→ 尾部追加不破坏命中。")
        print("   LFL「稳定前缀 + 尾部追加」策略在 DeepSeek 成立, 缓存省钱可观测。")
    elif b_hit:
        print("⚠️ 精确重发高命中, 但前缀追加后命中回退——检查载荷差异（前缀字节是否被改动）。")
    else:
        print("❌ 未检测到缓存命中——检查 model id / 载荷前缀稳定性 / 账户缓存策略。")
    return 0 if (b_hit and c_hit) else 1


if __name__ == "__main__":
    sys.exit(main())
