---
name: cache-cost
description: LLM 前缀缓存成本核算技能——需要对比不同预算窗口（大/小）成本、估算每 run 成本、或决策缓存配置时使用。核心方法：从 request.usage 事件聚合真实 tokens_in/cache_hit/cache_miss → 按价目（hit 0.05/M, miss 1.5/M）核算 → 对比方案。目标：用实测数据做成本决策，避免"命中率百分比≠成本"的直觉陷阱。触发工具: execute_command/search_records（描述含工具名才会被经验注入自动提示）。
---
# LLM 前缀缓存成本核算（cache-cost）

用户/自检需要决策缓存配置（预算窗口大小）或估算 prompt 成本时使用。**核心：成本 = miss×1.5/M + hit×0.05/M，必须用 request.usage 实测数据核算，禁止用命中率百分比做结论。**

## 为什么需要这个 skill（血的教训）

**反模式**（2026-08-17 实测踩坑）：
1. ❌ 凭命中率百分比下结论："小窗口 8% 命中但输入小，总成本低"——实际 92% miss 全价 1.5/M，成本反超大窗口 7 倍
2. ❌ 只算"命中部分省钱"不算"miss 部分全价"——miss 才是成本大头（30 倍差价）
3. ❌ 信 API 面板 cache_hit_rate——曾有非流式路径漏传 tokens_cache_hit（恒显 0 假象）
4. ❌ 用单次请求估算——要用 request.usage 事件聚合多轮（工具轮 miss 占比不同）

## 标准流程（4 步）

### Step 1: 聚合真实用量（request.usage 事件）

```python
import json, glob
rows = []
for f in glob.glob('data/event_logs/*/*.jsonl') + glob.glob('data/event_logs/*.jsonl'):
    try:
        for line in open(f):
            d = json.loads(line)
            if d.get('event_type') == 'request.usage':
                p = d.get('payload', d)
                rows.append((d.get('ts',''), p.get('tokens_in',0), p.get('cache_hit',0)))
    except Exception: pass
# 按时间分桶/会话聚合，取最近 N 轮
```

（session 持久化备选：messages 里 assistant 消息的 tokens_in/tokens_cache_hit）

### Step 2: 核算每 run 成本

```python
MISS_PRICE, HIT_PRICE = 1.5, 0.05  # 每百万 token 美元（DeepSeek）
for 方案 in [小窗口, 大窗口]:
    miss = in - hit
    cost = miss * MISS_PRICE / 1e6 + hit * HIT_PRICE / 1e6
    print(f"{方案}: in={in} hit={hit} 命中率={hit/in*100:.1f}% cost=${cost:.4f}/run")
```

**判定**：比较每 run 成本而非命中率——高命中大窗口（miss 极小）通常显著便宜（实测 7 倍）。

### Step 3: 检查稳定性

- 大窗口命中率应持续 96-99.9%（锚定机制下不稀释）——若忽高忽低说明前缀不稳定（查注入/锚点）
- 首轮切换后第 1 次可能 miss（窗口变化），第 2 次起命中——正常

### Step 4: 决策 + 协调 + 验证

- 决策：选每 run 成本低的方案（用户诉求命中率优先 → 大窗口）
- **配置变更走协调通道 + 用户确认**（勿静默改）
- 生效后重启 + 实测验证（对比前后 cost/命中率）

## 价目速查（DeepSeek 2026-08 实测）

| 项 | 价格 | 说明 |
|:---|:---|:---|
| 命中 (cache hit) | $0.05/M | 前缀缓存命中 token |
| 未命中 (miss) | $1.5/M | 非命中 token（30 倍差价） |
| 输出 | 另计（本 skill 只算输入） | |

**注意**：价目可能变，核算前先确认当前价目（usage_cost_report 脚本或账单）。

## 反模式清单

- ❌ 用命中率百分比做成本结论（8% vs 91% ≠ 成本差）
- ❌ 只算命中省钱不算 miss 全价
- ❌ 信面板不信 request.usage 事件（漏传假象）
- ❌ 单次请求估算（要用多轮聚合）
- ❌ 静默改配置（要协调 + 确认 + 验证）
- ❌ 改配置不重启就宣称生效
