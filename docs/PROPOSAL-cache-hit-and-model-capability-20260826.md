# 缓存命中情况与大模型智力/能力/执行力发挥情况建议书

> 项目：llm-first-loop v0.6.8（LLM-first Agent 运行时 / Harness）
> 日期：2026-08-26
> 范围：缓存命中机制全链路 + 模型能力发挥影响因素 + 二者张力关系
> 依据：源码逐行审计（src/llm_loop/ 全模块）+ 12 份既有分析文档 + 263 个单元测试
> 置信度：高（代码引用均经 read 工具回执验证行号）

---

## 0. 执行摘要

本建议书围绕两个核心命题给出结论与可执行改进：

1. **缓存命中情况**：当前已落地一套"前缀缓存命中采集 → 窗口镜像 → cache_guard 7 类规则门禁 → CacheHealthMonitor 健康闭环 → 压缩风暴熔断"的完整闭环。P0 压缩风暴熔断 + P1 遥测分层已于 2026-08-25 上线，99%→4% 骤降根因已封堵。剩余风险集中在 token 估算偏差、REASONING_TAIL 滚动裁剪致前缀漂移、本地 provider 直连/代理 KV 复用差异三处。

2. **大模型智力/能力/执行力发挥情况**：项目已确立"能力影响（一票否决）> 缓存命中率 > token 体积"的评估优先级（见 `docs/local/CAPABILITY-FIRST-CACHE-FRAMEWORK-20260820.md`）。当前主要能力损耗源为：REASONING_TAIL 裁剪（一票否决案例）、Evidence Recoverability 缺失（search_archive 90.5% miss）、漂移治理过重致强模型降级为"规则执行器"、max_tokens 对思考链模型偏小。

3. **张力关系**：缓存命中与模型能力存在结构性张力——为提命中率而裁剪思考链/压缩中段，会直接损害模型能力；回滚基线（1M 窗口 + 不裁剪）本质是用 token 体积换模型能力，反而可能省 miss 轮次。三角约束（Capability × Token × Prefix Cache）不存在永久全局最优配置，需按任务类型动态权衡。

---

## 1. 缓存命中情况分析

### 1.1 当前机制全链路（已落地）

| 阶段 | 实现位置 | 机制 |
|------|----------|------|
| 命中采集 | `src/llm_loop/llm/client.py:478-486` | OpenAI 协议三字段兜底提取（`prompt_cache_hit_tokens`→`cached_tokens`→`prompt_tokens_details.cached_tokens`），兼容 DeepSeek/Kimi/MiniMax |
| 命中采集 | `src/llm_loop/llm/client.py:632-633` | Anthropic 协议提取 `cache_read_input_tokens` |
| Anthropic 侧缓存 | `src/llm_loop/llm/client.py:589-600` | system+tools 打 `cache_control: ephemeral` |
| 窗口镜像 | `src/llm_loop/core/cache_window.py:54-108` | `describe_cache_window()` 把 cached_tokens 按字符估算（`_CHARS_PER_TOKEN=0.6`）映射回消息索引边界 |
| 发送前门禁 | `src/llm_loop/cache_guard/guard.py:1-656` | 7 类规则 A-G；规则 G 低命中率 BLOCK<30%/WARN 自适应，区分冷启动/TTL 过期/压缩轮/前缀稳定 |
| 健康闭环 | `src/llm_loop/core/cache_health.py:1-1072` | `record()` 归因（破坏型/设计型/模型切换）；双口径命中率（per-model 累计桶 + 近 N 轮窗口） |
| 压缩风暴熔断 | `src/llm_loop/core/cache_health.py:29-52` | 触发=连续压缩且仍超线 5 轮 + 命中<0.5；冻结=禁压缩+锚点冻结；逃生=连续 pressure 6 轮放行一次 |
| 遥测分层 | `src/llm_loop/core/loop/build.py:118-217` | 正文只存纯回答，遥测进 `metadata.cache_health`（结构化），transport 层渲染 |
| 持久化 | `src/llm_loop/core/session.py:197,229` | `tokens_cache_hit` 落 session JSON |
| Web 聚合 | `src/llm_loop/web/routes.py:1063-1129` | 按模型分桶 + 总体命中率 |
| 事件日志 | `src/llm_loop/core/loop/engine.py:825-878` | 每轮 `request.usage`（含 cache_hit/cache_miss）+ `cache.window` 事件 |

### 1.2 已修复的 P0/P1 问题

- **P0 压缩风暴**（99%→4% 骤降根因）：重工具任务每轮触顶压缩 → 前缀每轮变化 → 命中钉死低值。已落地 breaker 熔断（`cache_health.py:441-`），冻结压缩 + 锚点不前移 + 压力逃生。详见 `docs/REPORT-cache-compression-fix-20260825.md`。
- **P1 遥测分层**：程序遥测不再写入 assistant.content，避免污染前缀。`strip_cache_telemetry_lines()`（`cache_health.py:81`）剥离 legacy + 模型伪造行。
- **规则 G 冷启动/TTL/压缩轮区分**：`guard.py:473-569` 不再误拦冷启动低命中、TTL 过期低命中、压缩轮低命中（均降级 WARN），仅前缀稳定却持续低命中才 BLOCK。
- **provider 级中段压缩**：`cache_compacted_for` metadata 标记已归档消息，同 provider 后续 build 自动过滤，避免归档消息反复进上下文。

### 1.3 剩余风险（按影响排序）

| # | 风险 | 证据 | 影响 |
|---|------|------|------|
| R1 | **token 估算偏差**：统一 `_CHARS_PER_TOKEN=0.6` 对本地 qwen（`chars_per_token=0.9`）高估 1.7-2 倍 | `data/providers.json` local 段；`cache_window.py:54-108` | 窗口镜像边界算错 → 命中归因误判 → breaker 误触发/漏触发 |
| R2 | **REASONING_TAIL 滚动裁剪致前缀漂移**：每轮最老思考链从保留变省略 → 前缀字节变化 | `src/llm_loop/core/history.py:386-422` `_apply_reasoning_tail()` | 命中率下降 + 模型能力受损（双重损害） |
| R3 | **本地 provider 直连 vs 代理 KV 复用差异**：LM Studio 代理无 KV 复用（0%），直连 llama-server 97% | `docs/REPORT-cache-optimization-20260824.md` | 本地场景命中率两极分化，需文档明确 |
| R4 | **多会话/双实例交错**：槽被不同前缀轮流占用 → 缓存互相驱逐 | 既有报告 | 高并发场景命中率衰减 |
| R5 | **history_budget_chars 过紧**：触发频繁压缩 → 前缀频繁变化 | `data/providers.json` local `history_budget_chars=30000` | 本地场景压缩风暴残留风险 |

---

## 2. 大模型智力/能力/执行力发挥情况分析

### 2.1 当前能力保障机制（已落地）

| 机制 | 实现位置 | 作用 |
|------|----------|------|
| thinking_mode 默认开 | `src/llm_loop/config.py:220-235` | 本地默认开 thinking（SWE 实验定论：开思考通过率更高） |
| reasoning_effort="high" | `src/llm_loop/config.py` | 默认高强度推理 |
| llm_max_tokens=8192 | `src/llm_loop/config.py:234` | 防 4096 默认截断长分析 |
| self_evaluate 五维评估 | `src/llm_loop/introspection/evaluator.py` | success_rate/tool_efficiency/honesty_rate/stagnation_rate/exception_rate，来源可溯 |
| 声明-回执校验 | `src/llm_loop/feedback/validator.py` | 检测声明与工具回执一致性 |
| 停滞检测 | `src/llm_loop/core/loop/engine.py:919-928` | 连续同指纹工具调用熔断 |
| 演进建议闭环 | `src/llm_loop/introspection/evolution.py` | submit_evolution + evolution_complete + EVOLVE_LOCAL_EXEC 三级权限 |
| 能力一票否决框架 | `docs/local/CAPABILITY-FIRST-CACHE-FRAMEWORK-20260820.md` | 评估顺序：能力影响 > 缓存命中率 > token 体积 |

### 2.2 当前能力损耗源（按严重度排序）

| # | 损耗源 | 证据 | 严重度 | 性质 |
|---|--------|------|--------|------|
| C1 | **REASONING_TAIL 裁剪（一票否决）** | `docs/local/CAPABILITY-FIRST-CACHE-FRAMEWORK-20260820.md`；`history.py:386-422` | 极高 | 砍思考轨迹 → 模型看不到完整推理 → 循环思考/重复动作 |
| C2 | **Evidence Recoverability 缺失** | `docs/PROGRAM-INDUCED-DRIFT-ROOT-CAUSE-v1.md`；search_archive 90.5% miss | 极高 | "保存了但模型不知道去哪里拿" → 程序诱发认知失忆 |
| C3 | **漂移治理过重** | `docs/ai_model_capability_and_drift_strategy.md` | 高 | 强模型降级成"规则执行器"；L2 不进推理削弱探索能力 |
| C4 | **TOOL_TRIM/TOOL_TAIL 裁剪** | `src/llm_loop/config.py:275-281`；`history.py` | 高 | 旧工具回执被压缩 → 对"已做过的动作细节"记忆模糊 → 重复调用 |
| C5 | **max_tokens 对思考链模型偏小** | `config.py:234` 默认 8192；思考链模型默认 4096 时思考占大半 | 中 | 最终分析被截断 |
| C6 | **每轮机械三问认知税** | `docs/ai_model_capability_and_drift_strategy.md` | 中 | 白名单过严压制异常发现 |
| C7 | **高缓存命中"早退"风险** | 既有报告 | 中 | 高度缓存命中可能让模型自动补全而非真实推理 |
| C8 | **工具轮 thinking 降档** | `src/llm_loop/core/loop/engine.py:632-637` `TOOL_ROUND_THINKING_LOW=1` | 低-中 | 省耗时但可能影响决策质量 |
| C9 | **Goal/Constraint/Plan Drift** | `docs/analysis/2026-08-24-drift-defense-design.md` | 中 | 长任务中目标/约束/计划漂移比事实错误更危险 |

### 2.3 执行力评估

当前执行力保障由 self_evaluate 五维指标 + 停滞检测 + 声明-回执校验 + 演进闭环构成，框架完整。主要短板：

- **self_evaluate 触发为"仅提示不强制"**（`evaluator.py:95-133` `EvalTriggerDetector`），模型可忽略 → 评估实际频率依赖模型自觉
- **evolution 执行权限默认保守**（`EVOLVE_LOCAL_EXEC=0` 仅建议），模型有洞察但无执行权 → 闭环半开
- **stagnation 检测仅同指纹熔断**（`engine.py:919-928`），对"换参数但同语义"的重复调用无感知

---

## 3. 影响因素总表

### 3.1 影响缓存命中率的因素（10 项）

| # | 因素 | 方向 | 控制点 |
|---|------|------|--------|
| F1 | 前缀稳定性（system prompt 字节变化/中间注入/重排/压缩锚点前移） | ↓ | `ARCHITECTURE-cache-stable-rules.md` L0-L3 分层 |
| F2 | 压缩风暴（每轮触顶压缩） | ↓ | breaker（`cache_health.py:441-`） |
| F3 | 模型切换（跨 provider 缓存独立预热） | ↓（设计型） | `_cache_monitor.reset()` + switch_notice |
| F4 | TTL 过期（MiniMax ~130s / DeepSeek 7200s） | ↓ | `guard.py:501-510` TTL 判定降级 WARN |
| F5 | token 估算偏差（统一 0.6 vs 本地 0.9） | 误判 | `cache_window.py` `_CHARS_PER_TOKEN` |
| F6 | history_budget_chars 过紧 | ↓ | `data/providers.json` |
| F7 | 工具输出体积（大输出内联膨胀历史） | ↓ | `tool_summary_threshold` 分层注入 |
| F8 | REASONING_TAIL 滚动裁剪 | ↓ | `history.py:386-422` |
| F9 | 本地 provider 直连 vs 代理 | 两极 | 文档明确 + 直连推荐 |
| F10 | 多会话/双实例交错 | ↓ | 槽位调度（未实现） |

### 3.2 影响模型智力/能力/执行力发挥的因素（10 项）

| # | 因素 | 方向 | 控制点 |
|---|------|------|--------|
| G1 | REASONING_TAIL 裁剪 | ↓↓（一票否决） | `REASONING_TAIL` env |
| G2 | Evidence Recoverability 缺失 | ↓↓ | `evidence_mode` / `search_archive` 改造 |
| G3 | 漂移治理过重 | ↓ | `docs/ai_model_capability_and_drift_strategy.md` RULE-AI-21 |
| G4 | TOOL_TRIM/TOOL_TAIL 裁剪 | ↓ | `tool_trim_threshold` / `tool_trim_age` |
| G5 | thinking_mode / reasoning_effort | ↑ | `config.py` |
| G6 | max_tokens 过小 | ↓ | `llm_max_tokens` |
| G7 | 每轮机械三问认知税 | ↓ | 漂移治理权重调整 |
| G8 | 高缓存命中早退风险 | ↓ | 反思锚点对冲 |
| G9 | 工具轮 thinking 降档 | ↓（轻微） | `TOOL_ROUND_THINKING_LOW` |
| G10 | Goal/Constraint/Plan Drift | ↓ | `docs/analysis/2026-08-24-drift-defense-design.md` |

### 3.3 张力关系（核心洞察）

```
评估优先级（已确立）：能力影响（一票否决） > 缓存命中率 > token 体积
                          ↑
                    ┌─────┴─────┐
              为提命中率裁剪      回滚基线（1M + 不裁剪）
                    ↓                ↓
            损害模型能力(G1/G4)   用 token 体积换能力
                    ↓                ↓
              命中率↑ 能力↓       命中率↓ 能力↑
                    └─────┬─────┘
                          ↓
            三角约束：Capability × Token × Prefix Cache
            不存在永久全局最优配置，需按任务类型动态权衡
```

**关键结论**：缓存命中率和模型能力不是单调对齐的目标。为提命中率而裁剪思考链（F8/G1）是双重损害——既降命中率（前缀漂移）又损能力（一票否决）。`REASONING_TAIL=-1`（按属性省略）看似省 token，实则让模型循环思考/重复动作，反而多烧 miss 轮次。

---

## 4. 改进建议（按优先级排序）

### P0 — 必须立即处理（能力一票否决 + 高频命中损害）

#### P0-1：REASONING_TAIL 裁剪策略重审（对应 C1/F8/G1）

**现状**：`_apply_reasoning_tail()`（`src/llm_loop/core/history.py:386-422`）每轮滚动裁剪最老思考链。

**建议**：
- 默认 `REASONING_TAIL=0`（全保留），仅在上下文确已触顶且 breaker 未冻结时才触发裁剪
- 裁剪时改用"按属性省略"（方案 A，`REASONING_TAIL=-1`）而非整段删除——保留推理结论摘要，仅省略过程
- 裁剪后注入一条 `<reasoning_tail_compacted note="N 轮前推理已归档，结论：..."/>` 锚点，保持前缀连续性
- 在 `cache_guard` 规则 G 中增加"REASONING_TAIL 裁剪轮"识别，降级 WARN 不 BLOCK（与压缩轮同语义）

**验证**：`tests/unit/test_reasoning_tail.py` 增加前缀稳定性断言；SWE-bench 对照通过率对比。

#### P0-2：Evidence Recoverability 闭环（对应 C2/G2）

**现状**：`evidence_mode` 默认 `off`（`config.py:240`）；`search_archive` 90.5% miss rate。

**建议**：
- 推进 `evidence_mode` 从 `off` → `shadow`（dual-write no prompt change）→ `enforce`
- `search_archive` 改造：返回 preview 时同步返回可定位 handle（文件路径 + 偏移），让模型能二次取全文
- build 侧注入 Recovery Manifest（`evidence_manifest_limit=8`，已配置），让模型知道"有哪些证据可取、去哪里取"
- 遵循 `docs/PROGRAM-INDUCED-DRIFT-ROOT-CAUSE-v1.md` Evidence Recoverability Contract："Context 可以压缩，Evidence Identity 不能压没"

**验证**：`search_archive` miss rate 降至 < 30%；声明-回执校验通过率提升。

### P1 — 应尽快处理（命中率精度 + 能力保障）

#### P1-1：token 估算 provider 级化（对应 R1/F5）

**现状**：`cache_window.py` 统一 `_CHARS_PER_TOKEN=0.6`，对本地 qwen（0.9）高估 1.7-2 倍。

**建议**：
- `ProviderSpec` / `ModelSpec` 增加 `chars_per_token` 字段（`data/providers.json` local 段已有 0.9，需透传到 `cache_window`）
- `describe_cache_window()` 接受 `chars_per_token` 参数，按 provider 估算
- 窗口镜像边界精度提升 → breaker 触发/漏触发准确度提升

**验证**：`tests/unit/test_cache_window.py` 增加 provider 级 chars_per_token 用例。

#### P1-2：max_tokens 按模型类型自适应（对应 C5/G6）

**现状**：`llm_max_tokens=8192` 全局默认；思考链模型默认 4096 时思考占大半。

**建议**：
- `ModelSpec` 增加 `thinking_budget_ratio`（思考链模型 0.6，非思考链 0.0）
- 思考链模型 `llm_max_tokens` 默认提至 16384（与 `data/providers.json` deepseek `max_tokens=16384` 对齐）
- 本地 qwen 已有 `max_tokens` 配置，保持

#### P1-3：self_evaluate 强制触发里程碑（对应执行力短板）

**现状**：`EvalTriggerDetector` 仅提示不强制。

**建议**：
- 在 run 结束、轮数达 80%、工具调用数达阈值时强制触发一次 self_evaluate（结果落盘，不阻塞）
- 评估结果中 `stagnation_rate` 超 30% 时注入 architecture_status 告警行

### P2 — 可计划处理（张力治理 + 长尾风险）

#### P2-1：漂移治理权重动态化（对应 C3/G3/G7）

**现状**：漂移治理过重致强模型降级为"规则执行器"。

**建议**：
- 按模型能力等级动态调整漂移治理权重：强模型（deepseek-pro/minimax-M3）降权，弱模型保权
- `RULE-AI-21` Evidence-Grounded Autonomy 的"三层拷问"对强模型仅保留第一层（信息增益判定），后两层（白名单/异常发现）按置信度跳过
- 每轮机械三问改为"按停滞迹象触发"——连续 2 轮无新信息增益才触发拷问

#### P2-2：高缓存命中早退对冲（对应 C7/G8）

**现状**：高度缓存命中可能让模型自动补全而非真实推理。

**建议**：
- 命中率 > 90% 且本轮无工具调用时，注入轻量反思锚点："本轮高缓存命中——确认是真实推理而非模式补全？"
- 仅注入提示不阻塞，模型可自行决定是否深化

#### P2-3：本地 provider 直连文档化 + 槽位调度（对应 R3/F9/F10/R4）

**建议**：
- `docs/` 增加 local provider 部署指南：明确 llama-server 直连（97% 命中）vs LM Studio 代理（0% 命中）差异
- 多会话槽位调度：同前缀会话亲和到同一实例（减少跨实例缓存驱逐），列为 P2 待评估

### P3 — 待评估（需实验数据支撑）

#### P3-1：REASONING_TAIL=-1 全局生效评估

**现状**：`docs/REPORT-cache-optimization-20260824.md` 列为待评估建议。

**建议**：在 P0-1 落地后，A/B 实验对比 `REASONING_TAIL=0`（全保留）vs `-1`（按属性省略）vs `2`（保留最近 2 轮）的命中率/能力/通过率，用数据决定默认值。

#### P3-2：history_budget_chars 本地场景放宽评估

**现状**：local `history_budget_chars=30000` 可能过紧。

**建议**：本地直连场景（97% 命中）下放宽至 60000-80000，实测压缩频率与命中率关系后定值。

---

## 5. 验证指标与监控

### 5.1 落地后应观测的指标

| 指标 | 数据源 | 目标 |
|------|--------|------|
| 缓存命中率（per-model 累计） | `data/audit/cache_breaker.jsonl` + session `tokens_cache_hit` | deepseek > 85%，minimax > 70%，local 直连 > 90% |
| 压缩风暴触发次数 | `data/audit/cache_breaker.jsonl` storm_count | 重工具任务 < 1 次/会话 |
| REASONING_TAIL 裁剪轮占比 | 事件日志 `cache.window` | < 10%（仅触顶时触发） |
| self_evaluate 触发率 | `data/audit/self_eval_log.jsonl` | > 90%（强制里程碑生效） |
| search_archive miss rate | `data/audit/action_trace.jsonl` | < 30% |
| 声明-回执校验通过率 | `data/audit/declaration_check.jsonl` | > 95% |
| SWE-bench 通过率 | 外部基准 | 不降（P0-1 裁剪策略变更后） |

### 5.2 回归测试要求

- `tests/unit/test_cache_window.py`：增加 provider 级 chars_per_token 用例（P1-1）
- `tests/unit/test_reasoning_tail.py`：增加前缀稳定性断言 + 裁剪锚点连续性断言（P0-1）
- `tests/unit/test_cache_breaker.py`：增加 REASONING_TAIL 裁剪轮识别用例（P0-1）
- `tests/unit/test_evaluator.py`：增加强制里程碑触发用例（P1-3）
- 全量 `pytest tests/unit/`（263 文件 ~2256 用例）零回归

---

## 6. 与既有文档的对应关系

| 本建议书章节 | 既有文档 | 关系 |
|-------------|---------|------|
| §1 缓存命中 | `docs/REPORT-cache-optimization-20260824.md` | 继承四维拷问矩阵，补充剩余风险 R1-R5 |
| §1 缓存命中 | `docs/REPORT-cache-compression-fix-20260825.md` | P0/P1 已落地部分引用此文档 |
| §2 模型能力 | `docs/ai_model_capability_and_drift_strategy.md` | 继承 FACT/HYPOTHESIS/DECISION 模型，补充损耗源 C1-C9 |
| §2 模型能力 | `docs/local/CAPABILITY-FIRST-CACHE-FRAMEWORK-20260820.md` | 继承一票否决框架，P0-1 直接对应 |
| §2 模型能力 | `docs/PROGRAM-INDUCED-DRIFT-ROOT-CAUSE-v1.md` | P0-2 直接对应 Evidence Recoverability Contract |
| §3 张力关系 | `docs/ARCHITECTURE-ai-operating-v1.md` | 继承三角约束（Capability×Token×Prefix Cache） |
| §3 张力关系 | `docs/analysis/2026-08-24-drift-defense-design.md` | 继承漂移防御三层拷问，P2-1 动态化 |
| §4 改进建议 | `docs/analysis/REMAINING-WORK-IMPROVEMENT-PLAN-20260825.md` | P0-A DSH 缓存专项闭环对齐 |

---

## 7. 结论

1. **缓存命中**：机制闭环已完整，P0/P1 已封堵主要骤降根因。剩余 R1（token 估算偏差）、R2（REASONING_TAIL 前缀漂移）可通过 P1-1、P0-1 解决；R3（本地直连/代理差异）通过文档化解决。

2. **模型能力**：框架已确立"能力一票否决 > 命中率 > 体积"的正确优先级，但当前默认配置（REASONING_TAIL 滚动裁剪 + evidence_mode=off）与该优先级存在冲突。P0-1（REASONING_TAIL 重审）和 P0-2（Evidence Recoverability 闭环）是消除冲突的关键。

3. **张力关系**：缓存命中与模型能力不是单调对齐目标。任何"为提命中率而裁剪思考链"的优化都应先过"能力一票否决"审查。三角约束下不存在永久全局最优配置，建议按任务类型（重工具/长推理/短问答）动态切换配置 profile。

4. **优先级**：P0 两项（REASONING_TAIL 重审 + Evidence Recoverability）应立即处理——它们同时损害命中率和能力，是双重损害的根因。P1 三项应尽快处理。P2/P3 可按实验数据推进。

---

## 8. CodeArts 平台对齐方案（借鉴评估）

> 缘起：本建议书与既有 `REMAINING-WORK-IMPROVEMENT-PLAN-20260825.md` 均为人工撰写文档，改进项停留在"建议/计划"层面，缺乏可执行闭环。本节评估借鉴华为云 CodeArts（码道）平台的相关操作和设置是否更合适，并给出落地映射。
> 依据：`.codeartsdoer/AGENTS.md`（工程上下文 = Python）+ CodeArts 平台内置 skills/agents 清单 + 项目现有 7 个自定义 skills + PREFERENCE_6/PREFERENCE_19
> 置信度：高（平台能力清单来自系统 skills 注册表，非推测）

### 8.1 评估结论

**结论：借鉴 CodeArts 相关操作和设置显著更合适。** 三条第一性理由：

1. **可执行闭环**：当前建议书 P0-P3 是"建议"，无 spec→design→tasks 产物。CodeArts SDD 流程能把本建议书作为 steering context 输入 `spec-requirement-agent`，产出 EARS 格式 `spec.md`，再经 `spec-design-agent`→`design.md`、`spec-task-agent`→`tasks.md`，形成机器可校验、可追踪的执行闭环——这正是 PREFERENCE_19（结构化多阶段工作流）所要求的。
2. **缺陷 vs 增强的分流更精准**：P0 项本质是缺陷（能力一票否决 = 回归），适配 CodeArts bug-fix workflow（issue-analysis→root-cause-localization→patch-generation→fix-build-command）；P1/P2 项是功能增强，适配 SDD 流程。当前建议书未做此分流，借鉴后落地路径更清晰。
3. **经验可沉淀复用**：CodeArts `experience-collect`/`experience-refine` 能把本次缓存+能力张力分析沉淀为可复用工程经验，避免下次重复审计。项目已有 `skills/cache-hit-debug`、`skills/cache-cost`，可与之合并增强。

### 8.2 CodeArts 可借鉴的操作与设置清单

| 类别 | CodeArts 操作/设置 | 触发方式 | 与本建议书的关系 |
|------|---------------------|----------|------------------|
| **SDD 流程** | `spec-requirement-agent`（需求规格，EARS 格式 spec.md） | Task(subagent_type=spec-requirement-agent) | 本建议书作为 steering context 输入 |
| SDD 流程 | `spec-design-agent`（实现方案 design.md） | Task(subagent_type=spec-design-agent) | 把 P0-P3 技术方案转为 HLD/LLD |
| SDD 流程 | `spec-task-agent`（编码任务规划 tasks.md） | Task(subagent_type=spec-task-agent) | 生成可执行任务清单 |
| SDD 配套 skill | `creating-sdd-directory` / `managing-spec-document` / `managing-design-document` / `managing-tasks-document` | skill 工具 | 初始化结构化目录、约束校验 |
| **Bug-Fix 流程** | `issue-analysis` skill（问题→canonical JSON） | bug-fix-agent 子代理内 | P0-1/P0-2 缺陷归一化 |
| Bug-Fix 流程 | `issue-reproduction` skill（最小复现） | bug-fix-agent 子代理内 | REASONING_TAIL 裁剪复现 |
| Bug-Fix 流程 | `static-root-cause-localization` / `dynamic-root-cause-localization` skill | bug-fix-agent 子代理内 | C1/C2 根因定位（建议书已初判，可复用） |
| Bug-Fix 流程 | `patch-generation` skill（补丁生成+验证） | bug-fix-agent 子代理内 | P0-1/P0-2 补丁 |
| Bug-Fix 流程 | `fix-build-command` skill / `codebase-structure` skill | bug-fix-agent 子代理内 | 构建修复、代码库结构 |
| **经验管理** | `experience-collect` skill（session trace→经验文档） | skill 工具 | 沉淀本次张力分析经验 |
| 经验管理 | `experience-refine` skill（经验库去重/合并/归档） | skill 工具 | 与现有 skills/cache-* 合并 |
| **文档生成** | `doc-expert` skill（PRD/BRD/HLD/LLD/TDD） | skill 工具 | 本建议书→PRD/BRD，design.md→HLD/LLD |
| 文档生成 | `prd` skill（产品需求文档） | skill 工具 | 改进项产品化 |
| **平台设置** | `.codeartsdoer/AGENTS.md`（工程上下文） | 已存在（Python） | codebase-structure skill 已支持 Python |
| 平台设置 | 多阶段工作流约定 + agent 角色分工 | PREFERENCE_19 | 已对齐 |

### 8.3 改进项 → CodeArts 操作映射表

| 建议书改进项 | 性质 | 推荐 CodeArts 路径 | 输入 | 产物 |
|-------------|------|---------------------|------|------|
| **P0-1** REASONING_TAIL 裁剪重审 | 缺陷（能力一票否决=回归） | **bug-fix workflow**：issue-analysis→root-cause-localization→patch-generation→fix-build-command | C1 根因（`history.py:386-422`）+ CAPABILITY-FIRST 框架 | git-apply 补丁 + 复现测试 |
| **P0-2** Evidence Recoverability 闭环 | 缺陷（认知失忆） | **bug-fix workflow**（同上） | C2 根因 + `PROGRAM-INDUCED-DRIFT-ROOT-CAUSE-v1.md` | 补丁 + search_archive miss rate 验证 |
| **P1-1** token 估算 provider 级化 | 功能增强 | **SDD**：spec-requirement→spec-design→spec-task→执行 | R1 + `cache_window.py:54-108` | spec.md/design.md/tasks.md + 代码 |
| **P1-2** max_tokens 按模型自适应 | 功能增强 | **SDD**（同上） | C5 + `config.py:234` | spec/design/tasks + 代码 |
| **P1-3** self_evaluate 强制触发里程碑 | 功能增强 | **SDD**（同上） | 执行力短板 + `evaluator.py:95-133` | spec/design/tasks + 代码 |
| **P2-1** 漂移治理权重动态化 | 设计决策 | **SDD**（需 spec 明确权衡策略） | C3 + `ai_model_capability_and_drift_strategy.md` | spec/design/tasks + 代码 |
| **P2-2** 高缓存命中早退对冲 | 功能增强 | **SDD** | C7 | spec/design/tasks + 代码 |
| **P2-3** 本地 provider 文档化+槽位调度 | 文档+待评估 | **doc-expert**（文档）+ SDD（槽位调度） | R3/R4 | 部署指南 + spec/design/tasks |
| **P3-1/P3-2** 实验评估项 | 实验决策 | **SDD**（spec 标注"待实验数据"）+ `swe-bench` skill 跑对照 | — | 实验报告 + 默认值决策 |
| **整体经验沉淀** | 经验管理 | **experience-collect**→**experience-refine** | 本次完整分析 session trace | `EXPERIENCE-20260826-*.md` |

### 8.4 建议落地路径（v2：先 SDD 统一规划 → 任务执行阶段分流并行）

> 设计原则：对齐 PREFERENCE_19 四阶段工作流（需求规格→实现方案→编码任务规划→任务执行）。**先经 SDD 统一规划 P0-P3 全部改进项**（规划只产文档、不改代码，不延迟任何修复），**再在任务执行阶段按 tasks.md 分流**——P0 走 bug-fix-agent，P1/P2 走 coder，文件不重叠者可并行。这避免了原 v1"先 bug-fix 再 SDD"打乱统一多阶段流程、且 P0 修复缺乏 spec 约束的问题。

```
阶段 1 — 需求规格设计（SDD，统一覆盖 P0-P3）
  Task(subagent_type=spec-requirement-agent)
    输入：本建议书全文（§4 改进项 + §3 影响因素总表）作为 steering context
         + 项目 README 作为项目描述
  → 产物：specs/cache-capability/spec.md（EARS 格式，what to build）
  注：spec 中每项标注 nature∈{defect,enhancement,experiment} + priority
      P0 → nature=defect, priority=critical
      P1/P2 → nature=enhancement, priority=high/medium
      P3 → nature=experiment, priority=low

阶段 2 — 实现方案创建
  Task(subagent_type=spec-design-agent)
    输入：spec.md + 本建议书 §4 技术方案（先读取上一阶段 spec.md）
  → 产物：specs/cache-capability/design.md（how to build，HLD/LLD）

阶段 3 — 编码任务规划
  Task(subagent_type=spec-task-agent)
    输入：design.md（先读取上一阶段 design.md）
  → 产物：specs/cache-capability/tasks.md
  注：tasks.md 每任务标注 executor∈{bug-fix-agent, coder} + priority + 涉及文件

阶段 4 — 任务执行（按 tasks.md 分流，可并行）
  4a. P0 缺陷修复（executor=bug-fix-agent，priority=critical，立即启动）
      Task(subagent_type=bug-fix-agent)
        ├─ issue-analysis skill：C1/C2 → canonical issue JSON
        ├─ issue-reproduction skill：最小复现 REASONING_TAIL 裁剪致循环
        ├─ root-cause-localization skill：复用建议书根因，静态定位补丁点
        ├─ patch-generation skill：生成 git-apply 补丁（不 commit）
        └─ fix-build-command skill：ruff + pytest 验证零回归
      → 产物：P0-1/P0-2 补丁 + 复现测试

  4b. P1/P2 功能增强（executor=coder，P0 补丁合并后启动；与 4a 文件不重叠者可并行）
      按 tasks.md 执行编码，每项完成后 ruff + pytest 验证
      并行判定：P0-1 改 history.py/cache_guard，P1-1 改 cache_window.py，
                P1-2 改 config.py，P1-3 改 evaluator.py —— 文件基本不重叠，可并行
      例外：P0-1（REASONING_TAIL）与 P1-1（token 估算）同涉 cache 语义，
            建议 P0-1 先合并再动 P1-1，避免语义冲突

  4c. P3 实验评估（待 Real Provider 数据，非阻塞）
      SDD spec 已标注"待实验数据"；Phase 4 real provider gate 提供数据后决策

阶段 5 — 经验沉淀（与阶段 4 并行，不阻塞编码）
  skill(experience-collect) → skill(experience-refine)
  → 产物：EXPERIENCE-20260826-cache-capability-tension.md
```

**目录结构（明确）**：
```
specs/cache-capability/
  spec.md      # 阶段 1 产物，EARS 格式需求规格
  design.md    # 阶段 2 产物，HLD/LLD 实现方案
  tasks.md     # 阶段 3 产物，可执行任务清单
```
与现有 `docs/` 分离：`docs/` 存人工分析报告（本建议书、REPORT-*、CAPABILITY-FIRST 等），`specs/` 存机器可校验的 SDD 产物。`docs/` 不入库的内部文档（`docs/local/`）保持原位。

**与 v1 的差异**：v1 先 bug-fix P0 再 SDD P1/P2（串行、打乱四阶段流程、P0 无 spec 约束）；v2 先 SDD 统一规划 P0-P3 再分流执行（对齐四阶段、P0 有 spec 约束、4a/4b 可并行）。代价是 P0 修复延后一个 SDD 规划周期（约文档生成耗时，不改代码，可接受）。

### 8.5 适配性注意事项与诚实标注

| # | 注意事项 | 置信度 | 应对 |
|---|----------|--------|------|
| A1 | bug-fix workflow 的 skills（issue-analysis 等）标注"Only the bug-fix sub-agent can use"，**不能在主线程直接调用**，必须经 `Task(subagent_type=bug-fix-agent)` | 高（来自 skill 描述） | P0 项通过 bug-fix-agent 子代理执行 |
| A2 | SDD 流程会产生 spec.md/design.md/tasks.md，需与项目现有 `docs/` 体系不冲突 | 高 | 用独立 `specs/` 目录隔离（见 8.4） |
| A3 | 部分改进项是"设计决策"而非纯缺陷（P2-1 漂移治理权重、P3-1 REASONING_TAIL 默认值），bug-fix workflow 不适用 | 高 | 这些项走 SDD，spec.md 需明确权衡策略与验收标准 |
| A4 | `spec-requirement-agent` 需"项目描述 + steering context"，本建议书可作为 steering context，但需补充项目描述 | 中 | 阶段 1 调用时附带项目 README + 本建议书 |
| A5 | CodeArts `codebase-structure` skill 标注"Only the bug-fix sub-agent can use"，主线程生成项目结构需经 bug-fix-agent | 高 | 若需刷新 codebase-structure.md，经 bug-fix-agent |
| A6 | 项目已有 `REMAINING-WORK-IMPROVEMENT-PLAN` 的 Phase 0-4 顺序，SDD 流程应与之衔接而非另起炉灶 | 高 | 见 8.6 衔接表 |
| A7 | 本建议书的代码引用行号基于当前 HEAD，SDD/bug-fix 执行前需确认行号未因其他提交漂移 | 中 | 执行前 `git log --oneline -1` 核对 HEAD |

### 8.6 与既有 REMAINING-WORK 计划的衔接

| REMAINING-WORK Phase | 内容 | CodeArts 对齐 | 衔接方式 |
|----------------------|------|---------------|----------|
| Phase 0 — DSH 缓存专项 | breaker active-window 口径、telemetry durability、stress | **bug-fix workflow** | P0-A1/A2 缺陷 → issue-analysis→patch-generation |
| Phase 1 — Freeze + Delivery Manifest | 交付候选树构造 | 人工 + codebase-structure（经 bug-fix-agent） | 不走 SDD，属交付工程 |
| Phase 2 — Candidate-tree Offline Gates | 全矩阵验证 | fix-build-command skill | bug-fix-agent 内构建验证 |
| Phase 3 — Package/Release Artifact Gates | wheel 构建/安装 | 人工 CI | 不走 SDD |
| Phase 4 — Real Provider Gates | 真实 provider 验证 | `swe-bench` skill + 真实 smoke | 实验数据支撑 P3 项 |
| **本建议书 P0-1/P0-2** | REASONING_TAIL/Evidence | **SDD 规划 → bug-fix 执行（4a）** | 与 Phase 0 并行：同属缓存+能力根因，经统一 SDD 规划后在任务执行阶段走 bug-fix-agent |
| **本建议书 P1/P2** | 功能增强 | **SDD 规划 → coder 执行（4b）** | P0 补丁合并后启动；与 4a 文件不重叠者可并行 |
| **本建议书 P3** | 实验评估 | **SDD 规划 + swe-bench** | 待 Phase 4 real provider 数据后决策（非阻塞） |

**关键衔接结论**：P0-1/P0-2 与 REMAINING-WORK Phase 0 同属"缓存+能力"根因修复。按 v2 路径，两者经 SDD 统一规划后在任务执行阶段并行推进——P0 走 bug-fix-agent（4a），Phase 0 的 breaker/telemetry 走 bug-fix/人工。**CAPABILITY-FIRST 框架要求 Phase 0 的 breaker/telemetry 修复必须同时处理 REASONING_TAIL 裁剪，否则能力一票否决仍敞口**——因此 4a 不可晚于 Phase 0 闭环。P1/P2 经同一 SDD 规划在 4b 启动，与 4a 文件不重叠者可并行（见 §8.4 并行判定）。

### 8.7 对齐后的预期收益

1. **从"建议"到"可执行"**：P0-P3 不再停留在文档，而是转化为 spec.md/design.md/tasks.md + git-apply 补丁，可追踪、可校验、可回归。
2. **缺陷/增强分流**：P0 走 bug-fix 闭环（复现+补丁+构建验证），P1/P2 走 SDD 闭环（规格+设计+任务），路径精准。
3. **经验复用**：本次张力分析沉淀为工程经验，下次缓存优化直接检索，避免重复审计 12 份文档。
4. **平台对齐**：满足 PREFERENCE_6（对齐 CodeArts 开发与重构）+ PREFERENCE_19（结构化多阶段工作流）+ PREFERENCE_7（kebab-case 文件命名）。
5. **与既有计划无缝衔接**：不另起炉灶，P0 并入 Phase 0，P1/P2 跟随其后。