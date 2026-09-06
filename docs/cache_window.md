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

## 当前压缩策略（2026-09-06 context-safe closure）

旧的 per-round `progressive_fold` / `PROGRESSIVE_FOLD_K` 与 `APPEND_COMPRESSION`
实验已经退休。原因不是“参数没调好”，而是它们会让程序持续重写旧 provider 前缀，
并把折叠时机/语义连续性变成第二套策略控制面。当前生产契约是：

1. **物理预算触发**：以当前路由模型窗口与显式 operator cap 为边界；`COMPACT_RATIO`
   默认 `1.0`，不因历史经验值提前压缩。
2. **机械 coarse compaction**：需要压缩时按最老端连续、协议原子组归档；provider 路径
   使用 versioned `cache_compacted_for`（含 model/effective-budget provenance），避免同一批内容
   每轮重复折叠。
3. **目标水位而非语义筛选**：默认 `COMPRESS_TARGET_RATIO=0.6`，只决定表示体积；程序
   不判断哪些事实“更重要”，不生成 Goal/当前决策、关键事实、推理结论或动态折叠提示。
4. **信息零丢失靠 durable recovery**：被移出 provider view 的原始消息进入 Archive/Evidence
   持久层，可通过显式 `search_archive` / EvidenceRef 精确恢复；折叠只改变表示，不改变事实。
5. **缓存代价显式化**：一次 coarse compaction 可能造成一次前缀重算，但之后前缀应重新
   稳定；禁止为了“平滑命中率”做每轮 K-fold 重写。

历史 event/report 中的 `progressive_fold` 字段继续按旧 schema 可读，仅用于考古与对账，
**不表示当前 runtime 仍有对应配置或执行分支**。

## 增长率 nudge（growth nudge，EVO-20260824-54d46549 镜像落地）

替换固定 80% 预警（每轮必警）为**双轨**（对齐 billion-context decideNudge）:

- **强制轨**：history 超预算×compact_ratio（当前默认 1.0）→ 必警（压缩在即, bypass 增长率）
- **增长率轨**：80% 准备态 + 距上次预警增长 ≥ 阈值（预算×5% 或 20K 字符）→ 才预警
  （重任务增长快早提示, 普通对话增长慢不打扰——不干扰执行）

nudge 现在是 **prompt-neutral observability**：只记录 `understand.compact_prep` action /
architecture status，不向 provider messages 追加提示文本，因此不会获得新的 prompt authority；
模型若查询这些事实，再自行决定是否需要整理/检索。

## 实现

- `src/llm_loop/core/cache_window.py`：纯函数 `describe_cache_window(messages, cached_tokens, prompt_tokens)`
- `src/llm_loop/core/history.py`：物理预算触发 + oldest-contiguous 原子组归档 + versioned provider marker
- `src/llm_loop/core/prompt_build/stages/history_budget_prep.py`：物理预算 / `COMPACT_RATIO` / prompt-neutral growth observability
- `src/llm_loop/core/prompt_build/stages/history_postprocess.py`：记录 `compaction_mode`、pre/post/drop 等机械事实
- `engine.py`：每轮响应后追加 `cache.window` 事件（fail-open）
- `factory.py`：`cache_health` 快照合并 `window` 维度
- 测试：`tests/unit/test_cache_window.py`、`tests/unit/test_cache_round_sim.py`、`tests/unit/test_history.py`
