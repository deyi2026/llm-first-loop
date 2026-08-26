# 缓存窗口镜像（Cache Window Mirror，2026-08-24）

把服务端每轮上报的 `cached_tokens`（前缀命中 token 数）映射回**提交载荷的消息级窗口**，
让"缓存里到底有什么"可见、可审计——与 llama.cpp / DeepSeek 的前缀缓存管理逻辑对齐。

## 核心概念

```
提交载荷 = [system + 工具 schema] + [历史/配对组/注入]      ← LFL 组装
             └── 缓存区（KV 前缀命中, 零额外 prefill）──┘│── 新增区（miss, 需 prefill）──┘
             ↑ 边界 = cached_tokens × 2 字符（字符估算, 与 runtime 同源）
```

- **缓存区**：本次请求与上次请求的公共字节前缀（服务端 KV 已算好, 引用其中信息 = 免费）
- **新增区**：本轮新增内容（新消息/新工具结果/新注入——每次都要 prefill）
- **边界消息**：落在边界中间的消息标记 `partial: true`

## 落点

1. **事件日志**：每轮 `cache.window` 事件（event_logs/<session_id>.jsonl），含
   `cached_tokens/prompt_tokens/hit_ratio/boundary_chars/boundary_msg_index/cached_msgs/new_msgs/summary`
   ——完整、可回放、按轮审计。
2. **architecture_status**：`context_usage.cache_health.window` 快照（含 `summary` 单行摘要
   与最近 8 条缓存/新增消息下标），AI 每轮可自查。

## 怎么读 / 怎么用（信息补充决策, RULE-AI-00: 程序给事实, AI 决策）

| 观察 | 含义 | 决策含义 |
|---|---|---|
| 边界在消息 #k | 缓存覆盖到 #k, 之后为新增 | 引用 #k 之前信息零成本; 引用 #k 之后信息 = 本次已付 |
| `new_msgs` 增长快 | 每轮新增内容多（如零历史工具轮配对组每轮变化） | 新增内容不可避免; 保持尾部追加即可 |
| 命中率骤降 + 边界前移 | 前缀被破坏（压缩/注入漂移/模型切换） | 查 cache_guard 归因（anchor_moved/gate_drift/cold_start）|
| 载荷内无缓存区（cached=0）| 冷启动/断前缀 | 物理必然, 非异常 |

**信息补充三原则**（对齐前缀缓存语义）：
1. **补充 = 尾部追加**：新增信息放载荷尾部 → 前缀字节不变 → miss 仅新增段（最便宜）
2. **引用缓存区内信息 = 免费**：AI 可放心引用已在载荷内的早期内容（KV 已算好）
3. **中插/重排/压缩 = 断前缀**：当次全量 miss——信息价值必须大于断点代价才做

## 已知形态（实测/推演）

- **回答轮（追加历史）**：命中率 ~95%+，边界在倒数第 1-2 条消息——追加不破坏命中
- **零历史工具轮**：公共前缀仅 system+工具 schema（配对组每轮变化属新增区）——
  缓存命中率低但 miss 量小（~100-200 tokens ≈ 0.5-1s prefill），"快"靠的是载荷小
- **多会话/双实例交错**：槽被不同前缀轮流占用 → 缓存互相驱逐 → 命中率自然衰减
- **进程重启/模型重载**：KV 全清 → 全部会话冷启动（物理现实）

## 渐进压缩（progressive_fold，EVO-20260824-54d46549 镜像落地）

billion-context 拷问产出（2026-08-24）: **字节级前缀缓存下"小范围折叠保前缀"宣传不成立**
（DeepSeek/OpenAI 前缀缓存按字节比较——折叠点之后全量失效, 折 5 条与折 50 条当轮 miss 范围相同）。
故渐进折叠的价值**不是省 token**，而是:

1. **命中率曲线平滑**：每次只折最老 K 个配对组（K 小, 建议 3-5）→ 命中率小幅下降不崩盘
   （对比一次性大裁: 99%×几十轮 + 崩到 4%×1 轮）→ cache_guard 规则 G（<30% BLOCK）
   **不触发** → 执行不被打断（渐进压缩最强理由）。
2. **智力无断崖**：每次只丢几组, AI 可逐步适应/检索；一次性大裁当轮突然看不到 20-90 条中段事实。
3. **折叠标注注入**：折叠后注入 `[渐进折叠] 本轮仅折叠最老 N 个配对组…可 search_archive 检索`
   → AI 有感知, 减少"刚引用的内容已被折掉"的推理落空。

**保命兜底**：折满 K 组后提交仍 >95% 预算 → 突破 K 继续归档（防 guard 规则 F BLOCK / 提交超限 400）。
**配对原子性**：渐进折叠按配对组整体归档（声明↔回执同折, 无孤儿 → 协议 400 不出现）。

**启用**：`PROGRESSIVE_FOLD_K=3`（env；0=一次性大裁现有行为, 零回归）。

## 增长率 nudge（growth nudge，EVO-20260824-54d46549 镜像落地）

替换固定 80% 预警（每轮必警）为**双轨**（对齐 billion-context decideNudge）:

- **强制轨**：history 超预算×compact_ratio（90% 默认）→ 必警（压缩在即, bypass 增长率）
- **增长率轨**：80% 准备态 + 距上次预警增长 ≥ 阈值（预算×5% 或 20K 字符）→ 才预警
  （重任务增长快早提示, 普通对话增长慢不打扰——不干扰执行）

nudge 是**尾部注入/审计动作**（不碰已提交前缀）→ 缓存命中零影响；AI 感知走
`understand.compact_prep` action + architecture_status，决策归 AI（RULE-AI-00）。

## 实现

- `src/llm_loop/core/cache_window.py`：纯函数 `describe_cache_window(messages, cached_tokens, prompt_tokens)`
- `src/llm_loop/core/history.py`：`build_history_messages(progressive_fold=K)` 渐进折叠（归档循环 K 上限 + 95% 保命兜底 + 折叠标注）
- `src/llm_loop/core/loop/build.py`：`_growth_nudge_kind()` 纯函数（双轨判定）+ PROGRESSIVE_FOLD_K 接线
- `engine.py`：每轮响应后追加 `cache.window` 事件（fail-open）
- `factory.py`：`cache_health` 快照合并 `window` 维度
- 测试：`tests/unit/test_cache_window.py`、`tests/unit/test_progressive_fold.py`、`tests/unit/test_growth_nudge.py`
