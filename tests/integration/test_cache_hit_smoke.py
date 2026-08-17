"""缓存命中门禁（EVO-20260817-cef296f8 L3，2026-08-17）.

真实 provider 前缀缓存验证：同前缀连发 2 次，第二次命中率 ≥ 85%。
防"破坏前缀稳定"的改动在冒烟即失败（缓存破坏 = 成本放大 ~50 倍：
hit 0.05/M vs miss 1.5/M）。

实测阈值（2026-08-17）:
  - 91 tokens 前缀: 0%（太短不缓存）
  - 240 tokens 前缀: 53%（部分命中）
  - 453 tokens 前缀: 85%
  - 11.4K tokens 前缀: 99%
→ 用例用 ~2K tokens 长前缀，断言 ≥85%（稳定余量）。

跳过条件: 无真实 LLM key（DEEPSEEK_API_KEY/LLM_API_KEY）。
"""
import os

import pytest

from llm_loop.config import Settings
from llm_loop.llm.client import LLMClient


def _client() -> LLMClient:
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        pytest.skip("无真实 LLM key（DEEPSEEK_API_KEY/LLM_API_KEY）")
    base_url = (os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com/v1").strip()
    # 裸模型名（client 直连不接受 provider/ 前缀；registry 路由由上层负责）
    model = (os.environ.get("LLM_MODEL") or "deepseek-v4-flash").split("/")[-1].strip()
    return LLMClient(api_key=api_key, base_url=base_url, model=model)


@pytest.mark.real_llm
def test_cache_hit_rate_gate() -> None:
    """同前缀 2 连发，第二次命中率 ≥ 85%（防前缀稳定被破坏）."""
    client = _client()
    # ~2K tokens 长前缀（实测 453 tok→85%、11.4K→99%；短前缀命中率天然低不判）
    sys_prompt = "你是 llm-first-loop 测试助手。" + "缓存门禁测试前缀填充。" * 250
    msgs = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "用一句话说明前缀缓存的作用。"},
    ]
    r1 = client.chat(messages=msgs, tools=[])
    r2 = client.chat(messages=msgs, tools=[])
    ti = r2.prompt_tokens or 0
    hit = r2.prompt_cache_hit_tokens or 0
    rate = hit / ti * 100 if ti else 0.0
    print(
        f"[cache-gate] R1 in={r1.prompt_tokens} hit={r1.prompt_cache_hit_tokens} "
        f"| R2 in={ti} hit={hit} rate={rate:.1f}%"
    )
    assert rate >= 85.0, (
        f"缓存命中率 {rate:.1f}% < 85%——前缀稳定性被破坏？"
        "检查是否引入动态注入（system 消息每轮变化/经验提示重复注入/前缀分叉）"
    )
