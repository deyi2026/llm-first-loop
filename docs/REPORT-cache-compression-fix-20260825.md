# 压缩缓存修复（P0 breaker + P1 遥测分层 + provider 中段稳定压缩）审批材料

> 日期: 2026-08-25 ｜ 镜像协议: MIRROR-workspace-protocol.md §5 ｜ 状态: 待审批
> 镜像: `llm-first-loop-mirror`（本工作区，端口 8903）｜ 主区: `llm-first-loop`（未接触）

## 1. 改了什么

### 1.1 本次改动文件清单（相对于镜像既有 WIP 的增量）

| 文件 | 本次增量 | 核心内容 |
|---|---|---|
| `src/llm_loop/core/cache_health.py` | ~+230 行 | P0 压缩风暴熔断（模块常量 + `_BreakerState` + `note_build_result`/`breaker_active_for`/`breaker_freeze_compression`/`context_pressure_decision`/`note_context_pressure`/进出场/审计）；P1 遥测行剥离 `strip_cache_telemetry_lines` |
| `src/llm_loop/core/history.py` | 扩展 | `freeze_compression`；provider 级 `cache_compacted_for` 状态；固定 head + 中段归档；同 provider 下轮过滤已归档中段；provider 模式压到 `COMPRESS_TARGET_RATIO` 深水位，避免每轮重复压缩 |
| `src/llm_loop/core/loop/build.py` | 扩展 | `_breaker_pressure_block`、`_post_run_cache_health`、build 后 `note_build_result`；提交视图剥离 legacy 遥测；provider 可见历史口径；常规 fold 恢复固定 head（仅 emergency 禁用）；中段归档状态写 event-log |
| `src/llm_loop/core/loop/events.py` | 小改 | 消息定位优先对象 identity，避免重复正文消息归档事件错位；新增 provider 中段折叠状态事件写入辅助 |
| `src/llm_loop/event_log/model.py` / `replay.py` | 小改 | 新增 `message.cache_compacted`；event-log replay 可重建 `metadata.cache_compacted_for`，保证 JSON / event-log 读路径一致 |
| `src/llm_loop/core/loop/engine.py` | ~-30 净 | 接线 `_breaker_pressure_block` + `_post_run_cache_health`（遥测不再写回正文）；guard context 传 `breaker_active` |
| `src/llm_loop/cache_guard/guard.py` | ~+60 | 规则 F/G 与 breaker 协调降级；压缩轮（`compress_count>0`）规则 G BLOCK→WARN；`breaker_active` 进 meta |
| `src/llm_loop/llm/client.py` | +1 字段 | `GuardRequestContext.breaker_active` 透传 |
| `src/llm_loop/feishu/cross_sync.py` | +5 | transport 层按 `metadata.cache_health` 渲染 canonical 遥测 |
| `.env` | +1 行 | `PROGRESSIVE_FOLD_K=3`（作为压缩入口；provider 中段模式不再受 K 的 95% 停折语义限制，而是压到目标水位） |
| `CHANGELOG.md` | +46 | 变更记录 |
| `tests/unit/test_cache_breaker.py` | 新增/扩展 | 风暴检测/隔离/hysteresis/逃生/审计、provider 中段固定 head、不重复归档、provider 隔离、规则 F·G 协调、遥测剥离 |
| `tests/unit/test_cache_breaker_engine.py` | 新增/扩展 | breaker 接线、冻结/pressure/escape、遥测 metadata-only reload、真实 LoopEngine 中段标记 JSON↔event-log replay 一致性 |
| `tests/unit/test_cache_round_sim.py` | 扩展 | 压缩轮共同前缀验证 + 40 轮重工具离线压力测试（压缩频率/共同前缀/工具协议配对） |
| `tests/unit/test_model_aware_budget.py` | +3 | 钉住 `PROGRESSIVE_FOLD_K=0`（该测试口径=一次性大裁路径） |
| `scripts/smoke_breaker_test.py` | 新增 ~200 行 | 压测脚本（`--model` 可选，验收：连续压缩轮/breaker 事件/逐 request 曲线/遥测隔离） |

### 1.2 核心 diff 摘要（语义）

**P0 compression-storm breaker**（规格 1:1）
- 触发 = 连续 (context.compressed 且压缩后仍超压缩线) 达 `BREAKER_TRIGGER_RUNS`(5) + 命中共信号（独立滚动窗口 < `BREAKER_HIT_THR` 0.5——防渐进折叠误判）
- 冻结 = 禁程序压缩 + 锚点冻结（`freeze_compression` 进 `build_history_messages`）；冻结期超安全水位（预算×0.95 = 规则 F BLOCK 阈值）→ `context_pressure` 前置拦截（不提交）；规则 F/G 在 breaker 期降级 WARN（防双拦死锁）
- 退出 = cooldown 下限 + 水位（预算×0.8）+ 连续稳定（hysteresis，非仅时间）
- 逃生 = 连续 pressure 达 `BREAKER_PRESSURE_ESCAPE_MAX`(6) → 放行一次受控压缩（烧损有界）
- 审计 = `data/audit/cache_breaker.jsonl`（storm_count/anchor/enter/exit/pressure/escape）
- 水位口径 = 锚定视图字符（实际提交量；锚点压缩不删会话消息）

**P1 遥测内容/传输分层**
- `assistant.content` = 纯回答；权威遥测 → `metadata.cache_health`（结构化）
- build 提交视图剥离 legacy ⚡ 行 + 模型伪造行；transport（web 返回值 / 飞书 cross_sync）渲染 canonical 一份
- 程序统计源不变（`request.usage`/`run.end` 的 provider 上报值）

**provider 中段稳定压缩（第二阶段，目标=压缩轮也保持结构稳定）**
- 初始 K=3 修复先解决了致命问题：旧 `head_keep + fold` 没有持久化“中段已经归档”的状态，导致同一批消息重复归档、规则 F 永久 BLOCK；阶段一用“禁用 head + 锚点前移”止住风暴，但压缩轮仍会从历史开头断前缀。
- 最终路径改为 provider 级中段状态：归档消息写 `metadata.cache_compacted_for=[provider]`；同 provider 后续 build 自动过滤这些消息，其他 provider 仍可见，避免跨模型串缓存命名空间。
- 因为“中段已归档”现在可持久化，常规 provider fold 可以保留固定 head、锚点不动；删除断点位于 head 之后，压缩轮共同前缀不再只剩 system。
- provider 模式不再“折 K 组后 ≤95% 就停”，而是一次压到 `COMPRESS_TARGET_RATIO`（生产当前 0.5）目标水位；这是 hysteresis，避免重工具会话每轮刚越 90% 又压一次。无 provider 的直接调用仍保留原 K=3 兼容语义。
- 中段状态双轨持久化：Session JSON 写 metadata，同时 `message.cache_compacted` 事件按原消息序号落 event-log；replay 重建相同 metadata，切换 event-log 读路径/重启不会让中段“复活”。
- breaker 仍保留为最后保险；规则 F/G 协调逻辑不依赖中段优化是否成功。

## 2. 验证了什么

### 2.1 单测（全量）
- `tests/unit/` 当前 **2256 collected**，完整运行到 **100% / exit 0**；既有 skip 保持，只有 `lark_oapi/pkg_resources` 第三方弃用 warning。
- 缓存/历史/event-log/read-path/协议边界 focused 矩阵 **118 项全部 PASS**。
- 本轮触及生产模块 focused Ruff **All checks passed**；focused pyright **0 errors / 0 warnings**；最终全 `pyright src` 同样 **0 errors / 0 warnings**；`git diff --check` PASS；`engine.py` 1138 行（≤1172 门限）。

### 2.2 行为实测（真实 API，镜像 8903）

**MiniMax 压缩缓存命中压测（阶段一 breaker/fold 修复时的真实 API 证据）**（`minimax/MiniMax-M3`，临时预算 30-60K 后还原）：
- 稳态命中 83-94%（24 轮长会话合计 89.1%）；冷启动 1% → 3 轮回温 78%+
- 阶段一（当时仍禁用 head）压缩轮约 1%；**阶段一修复已做到压缩轮可提交、下一轮即回温 81-92%**（对比 8/24 deepseek 事故：压缩后永不回温、钉死 3-4% 40+ 轮）。该 1% 数字不代表当前最终的 provider 固定-head 中段模式。
- 无风暴形态（压缩轮分散，中间有正常轮；旧形态=22+ 轮连续压缩）

**deepseek 冒烟**（生产配置 300K budget）：
- 修复前：guard F 连续 BLOCK 循环（提交 286K 恒值——即 fold 重复归档 bug），2M+ tokens 空转
- 修复后：breaker 第 3 轮进入 → `[上下文压力]` 拦截（不再提交 286K 请求，零烧损）→ 6 轮 pressure 后逃生轮武装 → 审计事件完整（`breaker_enter`/`context_pressure`×6/`escape_armed`）
- 遥测分层：会话正文无 ⚡ 行（伪造 93.6% 行被剥离）、`metadata.cache_health` 存在、返回仅一条 canonical

### 2.3 当前最终代码的离线结构压力验收

固定生产目标参数 `COMPRESS_TARGET_RATIO=0.5`，构造 40 轮重工具会话（每轮 user → tool declaration → 3.5K tool result → assistant，60K history budget，12K head_keep，provider=deepseek）：

- 仅 **5 个压缩轮**：第 **12 / 18 / 24 / 30 / 36** 轮；`max_consecutive_compactions=1`（旧 K=3/95% 停折仿真曾达到 29 轮连续压缩）。
- 压缩轮相对上一轮的**最小共同前缀 10,015 chars**，证明断点已经推到固定 head 之后，而不是 system 后立即断。
- 压后载荷约 **33,044–34,077 chars / 60K budget**，有明确增长缓冲；下一次压缩约隔 6 轮。
- 40 轮全过程工具声明↔tool receipt 配对完整，无孤儿 tool 回执；同 provider 已归档中段不重复归档。
- 真实 API 的“最终 provider 固定-head 中段模式”尚未重新付费冒烟；这里把它与阶段一真实 API 证据明确分开，避免把旧 1% 压缩轮数据误当成最终行为。

### 2.3 审计样例（data/audit/cache_breaker.jsonl）
```
breaker_enter    storm_streak=8  chars=624596 reason=storm_streak=8
context_pressure ×6              chars=685423..686523 reason=over_safety_cap
escape_armed                     reason=pressure_runs>=6
```

## 3. 影响面

- **涉及机制**：缓存前缀/压缩/归档（核心缓存路径）——变更集中在 breaker/freeze、provider 中段过滤/折叠、event-log 状态重放、guard 协调；无压缩会话不进入中段标记路径（全 unit + focused 矩阵覆盖）。
- **涉及运行中会话**：镜像存量会话（如 507c5bf0/c9fa090c 测试会话）不受影响（breaker 按会话隔离）；主区**零接触**
- **配置变化**：`.env` 保持 `PROGRESSIVE_FOLD_K=3`；生产 `COMPRESS_TARGET_RATIO=0.5` 作为中段模式回落目标；测试期间的临时 LLM_MODEL/base_url/HISTORY_MAX_CHARS 改动已还原。
- **回滚方案**：breaker/guard 可独立回滚；provider 中段模式需成组回滚 `history.py` + `build.py/events.py` + `event_log/model.py/replay.py` 的状态写入/重放逻辑，并删除对应新测试；`.env` 删 `PROGRESSIVE_FOLD_K` 可关闭入口。不要只删 replay 或只删 metadata 过滤，否则 JSON/event-log 会再次出现状态不一致。

## 4. 遗留 / 建议

- 未做：budget 调 150-200K（按规格保持 300K 不动——防风暴靠 hysteresis+breaker，不靠缩预算）
- 未做：tool result/memory 尾部减量（健康态 97%→更高的第二阶段优化，规格明确放后）
- 未做：最终 provider 固定-head 中段模式的真实 API 复测（避免未经明确意图消耗 provider 凭据/费用）；当前证据为阶段一真实 API + 最终代码离线结构 stress + 全 unit。
- 建议：审批/promotion 前先在镜像用 `scripts/smoke_breaker_test.py` 对 DeepSeek 做一次最终真实冒烟，重点验收压缩轮命中不再跌到阶段一的 ~1%、且压缩轮间隔与离线 hysteresis 方向一致；通过后再 promotion。
