---
name: cache-hit-debug
description: LLM 前缀缓存命中排查技能——缓存命中率异常低（~1%）、怀疑缓存不生效、或想优化 prompt 成本时使用。核心方法：三实验法（缓存类型区分/TTL 排除/预算链定位）+ request.meta 真相源验证。目标：系统性定位根因而非猜测（实测从误判到根因 5 步内）。触发工具: architecture_status/execute_command/search_records/search_archive（描述含工具名才会被经验注入自动提示）。
---
# LLM 前缀缓存命中排查（cache-hit-debug）

用户/自检发现缓存命中率异常低（面板 cache_hit_rate ~1% 级别）或想降低 prompt 成本时，按以下流程系统排查。**核心：先实验验证机制，再查配置链，最后改+重启验证。**

## 为什么需要这个 skill（血泪教训）

**反模式**（实测踩坑）：
1. ❌ 凭先验下结论："这 provider 没有缓存"——短实验（131 token）不命中就误判无前缀缓存，实际是短 prompt 阈值效应
2. ❌ 只查 .env 单层配置——预算有多层 min 链（全局/provider/模型窗口），真实压制点在 provider 级
3. ❌ 以为 .env LLM_MODEL 就是实际运行模型——session model_override 会覆盖（配额降级残留）
4. ❌ refresh_config 后以为预算已生效——provider 级 history_budget_chars 热重载不作用于运行中引擎，必须重启
5. ❌ 忽略时间戳时区——event_logs 是 UTC，本地是 CST(+8)，统计先对齐

## 标准流程（5 步）

### Step 1: 缓存类型区分实验（先验证机制）

用**长 prompt（>3000 token，建议 20+ 条消息）**发 3 个请求：
- A. warm（初始序列）→ 期望 0 命中
- B. 完全同 payload 重发 → 验证**精确缓存**
- C. 前缀 + 追加 1 条 → 验证**前缀缓存**（关键！追加命中率应 ~97%）

```python
# 非流式 + usage 完整字段（流式需 stream_options.include_usage）
r = httpx.post(url, json={"model": model, "messages": msgs}, timeout=120)
u = r.json().get("usage", {})
print(u.get("cached_tokens"), u.get("prompt_tokens"))
```

**判定**：B 全命中 = 精确缓存存在；C 命中（仅新增部分未命中）= **前缀缓存存在**——追加不破坏命中，**修改已提交序列（压缩/重排）必断点**。

### Step 2: TTL 排除实验（排除次要因素）

同 payload 间隔 30s/60s/120s/180s/300s 重发，看 cached_tokens：
- 全部命中 → TTL ≥ 5 分钟，排除 TTL 因素（会话内调用间隔通常 <60s）
- 超时后 miss → TTL 是因素，需控制调用节奏

### Step 3: 预算链定位（查真实生效值）

```
effective_budget = min(全局 HISTORY_MAX_CHARS, provider 级 history_budget_chars, 模型窗口 × 系数)
```

**真相源是 event_logs 的 request.meta**（每轮含 model/budget/history_chars），不是 .env：
```python
# 查每轮真实 budget
reqs = [(json.loads(l)['ts'], json.loads(l)['payload']) for l in open(log) if 'request.meta' in l]
for ts, p in reqs[-5:]: print(ts[11:19], p.get('model'), p.get('budget'), p.get('history_chars'))
```

**注意**：request.meta 里 model 字段才是实际运行模型（可能被 session model_override 覆盖）；budget 才是真正生效预算（min 链结果）。先查 model 再查对应 provider 的预算配置。

### Step 4: 修复（三层都要改）

1. `data/providers.json`：目标 provider 的 `history_budget_chars`（当前会话实际用的 provider！）
2. `.env`：`HISTORY_MAX_CHARS`（全局）
3. `adjust_strategy history_budget`：运行时参数（仅当前进程）

**历史量估算**：session 总字符 vs 预算——预算要 > 历史总量（否则每轮压缩=每轮断点）；且 < 模型窗口（1M token 窗口 ≈ 200 万字符，留安全边际）。

### Step 5: 重启 + 验证

`bash scripts/restart_system.sh restart`（回 y 确认）→ 触发一次调用 → **request.meta budget 变为新值**才算生效（热重载对 provider 预算无效）。

## 压缩友好策略（根因修复）

命中率 = 稳定期占比（压缩轮必 miss 一次，物理必然）。优化方向：
- **留缓冲**：压缩目标从"裁到预算 100%"改为"预算×0.6-0.7"（留 40% 增长空间 → 稳定期从几轮延长到几十轮）
- **锚定**：system + 注入不参与压缩（前缀稳定锚）
- **放大预算**：预算 > 会话历史总量 → 不压缩 → 纯追加（命中 ~97%）

## 反模式清单

- ❌ 短 prompt 实验（<3000 token）下缓存结论
- ❌ 只改 .env 不查 provider 级/只改 provider 级不查实际运行 model
- ❌ refresh 后不重启就宣称生效
- ❌ 压缩轮被断点就断言"缓存坏了"——这是物理必然，看稳定期占比
- ❌ 统计事件时忽略 UTC vs 本地时区

## 实测参考（2026-08-16 本环境）

| 项 | 值 |
|---|---|
| 前缀追加命中率 | 97.3%（9472/9735） |
| 修复前命中率 | ~1%（每轮压缩） |
| 修复后 | 99.2%（长 run 稳定期） |
| TTL | ≥300s（实测 5 分钟全命中） |
| 模型 | kimi/k3、deepseek-v4-flash（窗口均 1M token） |
