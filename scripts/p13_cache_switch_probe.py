"""P1-3 (EVO-0dbdf702): 同 provider 跨模型缓存共享实测（只读，不预设结论）.
flash 建前缀 → flash 复测（对照组） → 切 pro 同前缀（关键）.
hit>0 → DeepSeek 池内跨模型共享（切换成本低于预期）; hit=0 → 按模型隔离（确认现状）.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from llm_loop.llm.client import LLMClient  # noqa: E402


def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
    base_url = (os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com/v1").strip()
    flash = "deepseek-v4-flash"
    pro = "deepseek-v4-pro"
    c = LLMClient(api_key=api_key, base_url=base_url, model=flash)
    sys_prompt = (
        "你是 llm-first-loop 缓存实测助手。" + "跨模型缓存共享探测前缀填充。" * 300
    )  # ~2.4K tok
    msgs = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "用一句话说明前缀缓存的机制。"},
    ]
    r1 = c.chat(messages=msgs, tools=[], model=flash)
    r2 = c.chat(messages=msgs, tools=[], model=flash)
    r3 = c.chat(messages=msgs, tools=[], model=pro)

    def row(name, r):
        ti = r.prompt_tokens or 0
        hit = r.prompt_cache_hit_tokens or 0
        rate = hit / ti * 100 if ti else 0
        print(f"  {name:16s} in={ti:6d} hit={hit:6d} rate={rate:5.1f}%")
        return hit

    print("== P1-3 跨模型缓存共享实测 ==")
    print(f"base_url={base_url}")
    row("R1 flash 建前缀", r1)
    h2 = row("R2 flash 复测", r2)
    h3 = row("R3 pro 同前缀", r3)
    print("== 结论 ==")
    if h2 < 1700:
        print("⚠ R2 flash 复测命中率异常低——前缀未建立或池内未热，本组数据不可靠")
    if h3 > 0:
        print(
            f"✅ 跨模型共享成立: pro 命中 flash 前缀 {h3} tokens → 切换成本低于预期，可优化锚点策略"
        )
    else:
        print("❌ 按模型隔离: pro 对 flash 前缀 hit=0 → 确认现状（首轮全量 miss 属实），关闭该项")


if __name__ == "__main__":
    main()
