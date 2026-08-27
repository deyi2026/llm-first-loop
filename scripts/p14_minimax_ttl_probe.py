"""P14 TTL 探测实验（minimax，2026-08-21）.
目的: 定论 minimax 前缀缓存 TTL 区间（官方文档"5min/自动调整" vs 本地"24s 仍 miss"矛盾）。
方法: 同前缀定时重发，间隔递增，观测 cached_tokens 何时归零（命中消失）→ 反推 TTL 区间。
前缀: ~2.5K tokens 稳定前缀（官方 <512 不缓存，必须超阈值）。
"""
import os, sys, time, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv
load_dotenv()
from llm_loop.llm.client import LLMClient

def main():
    api_key = os.environ.get("MINIMAX_API_KEY")
    base_url = "https://api.minimax.chat/v1"
    model = "MiniMax-M3"  # 裸模型名（client 直连不接受 provider/ 前缀）
    c = LLMClient(api_key=api_key, base_url=base_url, model=model)
    sys_prompt = "你是 llm-first-loop TTL 探测助手。" + "TTL 探测稳定前缀填充。" * 350  # ~2.8K tok（>512 阈值）
    msgs = [{"role": "system", "content": sys_prompt},
            {"role": "user", "content": "用一句话确认收到。"}]
    # 间隔序列（秒）: 立即/30s/1min/2min/5min/10min —— 命中消失即停
    intervals = [0, 30, 60, 120, 300, 600]
    print("== P14 minimax TTL 探测 ==", flush=True)
    results = []
    for i, gap in enumerate(intervals):
        if i > 0:
            time.sleep(gap)
        r = c.chat(messages=msgs, tools=[], model=model)
        ti = r.prompt_tokens or 0
        hit = r.prompt_cache_hit_tokens or 0
        rate = hit / ti * 100 if ti else 0.0
        row = {"t": i, "gap_s": gap, "in": ti, "hit": hit, "rate": round(rate, 1)}
        results.append(row)
        print(f"  t{i} gap={gap:>4}s in={ti:>6} hit={hit:>6} rate={rate:5.1f}%", flush=True)
        if i > 0 and hit == 0:
            print(f"  → 命中消失于 gap={gap}s（TTL 区间: 上次{intervals[i-1]}s ~ {gap}s）", flush=True)
            break
    else:
        print("  → 10min 内未消失（TTL > 10min 或持续请求自动续期）", flush=True)
    json.dump(results, open("/tmp/p14_minimax_ttl_results.json", "w"), indent=2)

if __name__ == "__main__":
    main()
