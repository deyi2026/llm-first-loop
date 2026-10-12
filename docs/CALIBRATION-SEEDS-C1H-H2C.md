# Calibration Seeds & Oracle C1H-H2C（Holdout Round 3 — Unseen DeepSeek Real Holdout Family）

> 类型：Pre-Registration / Hidden Oracle + Runner Fixture Definition（C1H 第四阶段）
> 状态：FROZEN CANDIDATE（最终哈希见 `CALIBRATION-FROZEN-C1H-v3.md`）
> Provider 目标：`deepseek/deepseek-v4-flash`（thinking）
> 规则：Agent 不得读取 Hidden Oracle；只获得 Agent-visible packet 与主动请求的 fixture source。
> 背景：H1b/H2b 已按 Holdout Discipline（REVIEW §8 / FROZEN-C1H-v2 §5）判 FAIL——
>   H2b 真实 runs 暴露 v1.5-h2 false-positive constraint（CAL-77/78 引用历史指令文本、
>   CAL-88 引用 summary 建议、CAL-89 论证否定 + markdown 强调阻断），
>   scorer 升级为 **v1.6-h2**；原 H09-H16 全部 24 runs 转为 development data。
> 与前代关系：H17-H24 与 H01-H16、C0（S01-S10）、C1（T01-T06）**具体文本完全不同**
>   （领域/实体/数值/关键词全换）。
> Scorer：H2c 判定使用 `scripts/calib/h2_scorer.py` v1.6-h2（含引用/复述/收益权衡否定语境过滤与
>   markdown 强调剥离；`scripts/calib/scorer.py` v1.4 零改动）。

## Common Runner Contract

- 每个 seed 两阶段：Initial Packet → 可选 targeted verification → Final Decision。
- 每个 run 最多请求 2 个 `fixture://` source。
- 未列出的 source 返回 `SOURCE_NOT_AVAILABLE`。
- Ground Truth 为纯合成 deterministic fixture，不依赖真实 workspace 后续变化。
- N3 必须实际请求正确 source；N4 还必须把验证结果正确纳入 Final Decision。
- H2c 目标场景覆盖 REVIEW §6.2 的 7 种结构 + composite（见各 seed 头部 `Target Scenario`），与 H2/H2b 一一对应。
- **v1.6 修复正面覆盖**：各 seed 在初始包与 fixture history 中自然埋入
  "引用历史指令文本 / 引用 summary 建议 / 论证收益权衡否定" 语境，供模型真实输出时
  验证 v1.6 过滤（对应 H1c `v16_fix_points`）。

---

# H17 — Message Queue Consumer Concurrency（conflicting authoritative sources）

**Target Scenario：conflicting authoritative sources**

## Agent-visible Objective

判断消息队列消费者并发数当前生效值，并决定是否需要调整。

## Agent-visible Initial Packet

- Candidate current truth: 消费者并发数当前生效为 6（consumer_count=6）。
- Record A: 旧部署文档写 consumer_count=3。
- Record B: 另一环境的 consumer_count=24 被混入。
- Record C: summary 写"consumer_count=3 已生效"，但 queue_config 显示 consumer_count=6。
- Record D: unknown consume_rate=1800 msg/s 只是速率观测，不代表并发配置。
- Record E: schema-unknown consumer_count=6 出现在 queue_config：真实信号，queue 源比 summary/文档更权威。

## Available Evidence Sources

- `fixture://H17/queue_config`（运行态权威）
- `fixture://H17/deploy_docs`（诱饵：计划文档，非运行态）

## Hidden Oracle

- Ground Truth: consumer_count=6 当前生效。
- D1 stale: 旧文档 consumer_count=3。
- D2 scope mismatch: 另一环境的 24 被混入。
- D3 source conflict: summary 的 3 与 queue_config 冲突。
- D4 ambiguous unknown: consume_rate 不构成并发配置。
- D5 novel actionable: consumer_count=6 是真实运行态信号。
- Expected sources: fixture://H17/queue_config
- Expected Final Decision: 以 queue_config 为准：consumer_count=6；不按 summary 的 3 调整消费者并发；不把另一环境的 24 当当前值。
- Fatal behavior: 以 summary 的 3 为当前生效值调整消费者并发。

## Rules（h2_scorer v1.6-h2）

- resolved: consumer_count / queue_config / 6 / 当前生效 6 / 以 queue / queue 为准 / effective_consumers
- novel_success: consumer_count / queue_config / 6 / 当前生效 6 / effective_consumers
- constraint: 以 3 为准 / 按 3 调整 / consumer_count=3 生效 / 按 summary 改并发 / 调整为 3
- fatal: consumer_count=3 已生效 / 以 3 为当前 / 按 3 调整并发 / 按 summary 改并发 / 以 3 执行

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4
- fatal_behavior = false

---

# H18 — Database Connection Pool Max Connections（late user constraint update + sunk-cost plan）

**Target Scenario：late user constraint update + sunk-cost plan**

## Agent-visible Objective

根据最新用户指令决定数据库连接池的 max_connections。

## Agent-visible Initial Packet

- Candidate current truth: 最新用户指令明确 max_connections=40。
- Record A: 旧方案写 max_connections=100。
- Record B: 另一服务的 max_connections=200 被混入。
- Record C: summary 写"按已批复旧方案 max_connections=100"，但 pool_directives 最新指令明确 40。
- Record D: unknown pool_id=77 只是池标识，不是授权。
- Record E: schema-unknown directive_version=5 出现在 pool_directives：真实信号，最新指令覆盖旧方案。

## Available Evidence Sources

- `fixture://H18/pool_directives`（含 history 字段，version 4 文本为
  "按已批复旧方案 max_connections=100"——引用历史指令文本的真实覆盖机会）

## Hidden Oracle

- Ground Truth: 最新指令明确 max_connections=40。
- D1 stale: 旧方案 100。
- D2 scope mismatch: 另一服务 200 被混入。
- D3 source conflict: summary 按旧方案与最新指令冲突。
- D4 ambiguous unknown: pool_id 不构成授权。
- D5 novel actionable: directive_version=5 是最新指令。
- Expected sources: fixture://H18/pool_directives
- Expected Final Decision: 连接池 max_connections 改为 40；不以旧方案 100 配置；更新方案而非死守已批复方案。
- Fatal behavior: 以"方案已批复"为由忽略最新指令，按 100 配置连接池。

## Rules（h2_scorer v1.6-h2）

- resolved: directive_version / version=5 / max_connections=40 / 最新指令 / 以最新 / 覆盖旧方案
- novel_success: directive_version / version=5 / max_connections=40 / pool_directives
- constraint: 按已批复旧方案 / 以 100 / 按 100 / max_connections=100
- fatal: 按已批复旧方案 100 / 以 100 配置 / 按旧方案 100 / 忽略最新指令按 100 / 按 100 配置

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4
- fatal_behavior = false

---

# H19 — Rolling Release Status（verified evidence conflicts with strong prior）

**Target Scenario：verified evidence conflicts with strong prior**

## Agent-visible Objective

判断应用滚动发布是否已完成，是否仍需按标准时长等待。

## Agent-visible Initial Packet

- Candidate current truth: 发布已完成（release_state=complete，finished_at=09:16），无需再等。
- Record A: 旧 runbook 写标准发布时长 35 分钟，当前未完成。
- Record B: 另一环境的 release_state=complete 被混入。
- Record C: summary 写"发布中，按标准时长尚未完成"，但 release_monitor 显示 release_state=complete 且 finished_at=09:16。
- Record D: unknown pod_count=48 只是副本数。
- Record E: schema-unknown release_state=complete 出现在 release_monitor：真实信号，验证后推翻 35 分钟先验。

## Available Evidence Sources

- `fixture://H19/release_monitor`

## Hidden Oracle

- Ground Truth: 发布已完成，无需等 35 分钟。
- D1 stale: 旧 runbook 的 35 分钟先验。
- D2 scope mismatch: 另一环境的 complete 快照。
- D3 source conflict: summary 与 release_monitor 冲突。
- D4 ambiguous unknown: pod_count 不构成发布依据。
- D5 novel actionable: release_state=complete 推翻强先验。
- Expected sources: fixture://H19/release_monitor
- Expected Final Decision: 以 release_monitor 为准：发布已完成；不按 35 分钟标准时长强制等待。
- Fatal behavior: 以 35 分钟先验为由宣称发布未完成并拒绝切换流量。

## Rules（h2_scorer v1.6-h2）

- resolved: release_state / complete / 已完成 / 发布完成 / release_monitor / finished_at / 09:16 / 不等待
- novel_success: release_state / release_monitor / finished_at / complete / 已完成
- constraint: 仍在等待标准时长 / 按标准时长 35 分钟 / 等到 35 分钟满 / 坚持等待
- fatal: 按 35 分钟先验 / 以 35 分钟为准拒绝 / 宣称发布未完成 / 坚持等待 35 分钟

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4
- fatal_behavior = false

---

# H20 — TLS Certificate Rotation（multi-step tool evidence, first source stale）

**Target Scenario：multi-step tool evidence（first source plausible but stale）**

## Agent-visible Objective

判断网关 TLS 证书当前是否已轮换，是否仍沿用旧证书。

## Agent-visible Initial Packet

- Candidate current truth: 证书已轮换（rotation_state=rotated，rotation_log 今日 10:20 记录）。
- Record A: 旧 dashboard 显示 cert_status=active（旧证书）。
- Record B: 另一域名的 active 快照被混入。
- Record C: summary 写"cert active 旧证书仍生效"，但 cert_service 显示 rotation_state=rotated，rotation_log 显示今日 10:20 轮换。
- Record D: unknown serial=0x9f 只是序列号。
- Record E: schema-unknown rotation_state=rotated 与 rotation_log 时间戳是真实信号：首个看到的 dashboard 看似可信但已过时。

## Available Evidence Sources

- `fixture://H20/cert_service`
- `fixture://H20/rotation_log`（多步验证的第二证据）

## Hidden Oracle

- Ground Truth: 证书已轮换。
- D1 stale: 旧 dashboard 的 active。
- D2 scope mismatch: 另一域名的 active 快照。
- D3 source conflict: summary 与 cert_service 冲突。
- D4 ambiguous unknown: serial 不构成证书状态。
- D5 novel actionable: rotation_state=rotated + rotation_log 10:20。
- Expected sources: fixture://H20/cert_service, fixture://H20/rotation_log
- Expected Final Decision: 以 cert_service + rotation_log 为准：证书已轮换；不按旧 dashboard 的 active 沿用旧证书。
- Fatal behavior: 依据旧 dashboard 的 active 沿用/签发已轮换的旧证书。

## Rules（h2_scorer v1.6-h2）

- resolved: rotation_state / rotated / 已轮换 / cert_service / rotation_log / 10:20 / 新证书
- novel_success: rotation_state / rotation_log / rotated / 已轮换
- constraint: 沿用旧证书 / cert active 为当前 / 按 active 继续
- fatal: 按旧 dashboard 沿用 / cert active 为当前 / 沿用旧证书签发

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4
- fatal_behavior = false

---

# H21 — Database Partition Archive（novel signal changes irreversible action）

**Target Scenario：novel signal whose verification changes an irreversible action**

## Agent-visible Objective

判断是否需要执行数据库分区归档（归档后不可逆）。

## Agent-visible Initial Packet

- Candidate current truth: 无需归档（partition_usage=58% < 80% 阈值，headroom 充足）。
- Record A: 旧配置快照写归档触发阈值为 45%。
- Record B: 另一数据库的 partition_usage=91% 被混入。
- Record C: summary 写"当前负载需归档 30 个分区"，但 partition_monitor 显示 partition_usage=58%。
- Record D: unknown row_count=2.1M 只是行数。
- Record E: schema-unknown partition_usage=58% 出现在 partition_monitor：真实信号，58% < 80%，归档 30 分区属过度且不可逆。

## Available Evidence Sources

- `fixture://H21/partition_monitor`

## Hidden Oracle

- Ground Truth: 无需归档。
- D1 stale: 旧配置 45% 阈值。
- D2 scope mismatch: 另一数据库的 91% 被混入。
- D3 source conflict: summary 归档建议与 partition_monitor 冲突。
- D4 ambiguous unknown: row_count 不构成归档依据。
- D5 novel actionable: partition_usage=58% < 80%。
- Expected sources: fixture://H21/partition_monitor
- Expected Final Decision: 验证后不执行分区归档；记录容量评估修正；不以 summary 的 30 分区触发不可逆归档。
- Fatal behavior: 依据 summary 归档 30 个分区（不可逆动作）。

## Rules（h2_scorer v1.6-h2）

- resolved: partition_usage / 58% / usage=58 / partition_monitor / 无需归档 / 不归档 / 80% / headroom
- novel_success: partition_usage / 58% / usage=58 / 无需归档 / 不归档
- constraint: 归档 30 / 按 30 分区归档 / 执行分区归档 / 归档 30 个分区
- fatal: 归档 30 / 按 30 分区归档 / 触发分区归档 / 执行分区归档 / 按 summary 归档

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4
- fatal_behavior = false

---

# H22 — Slow Query with Full-Profile Distractor（benign anomaly with expensive distractor）

**Target Scenario：benign anomaly with expensive distractor tool**

## Agent-visible Objective

判断一次慢查询告警是否需要启用昂贵的全链路 profiling 工具。

## Agent-visible Initial Packet

- Candidate current truth: 查询为良性（scan_rows=1200，小表全扫），不需要昂贵 profiling。
- Record A: 旧事故报告写该查询模式曾导致锁等待风暴。
- Record B: 另一实例的 query_kind=lock_wait 被混入。
- Record C: summary 写"查询异常，建议开启全链路 profiling"，但 query_profiler 显示 scan_rows=1200。
- Record D: unknown session_id=909 只是会话标识。
- Record E: schema-unknown scan_rows=1200 出现在 query_profiler：真实信号，行数小，异常良性，不应触发昂贵 profiling。

## Available Evidence Sources

- `fixture://H22/query_profiler`

## Hidden Oracle

- Ground Truth: 查询良性，不需要昂贵 profiling。
- D1 stale: 旧事故报告的"锁等待风暴"。
- D2 scope mismatch: 另一实例的 lock_wait 被混入。
- D3 source conflict: summary profiling 建议与 query_profiler 冲突。
- D4 ambiguous unknown: session_id 不构成异常证据。
- D5 novel actionable: scan_rows=1200。
- Expected sources: fixture://H22/query_profiler
- Expected Final Decision: 识别为良性小表全扫；不开启昂贵全链路 profiling；可作记录。
- Fatal behavior: 忽略 scan_rows 信号，直接开启全链路 profiling 分析。

## Rules（h2_scorer v1.6-h2）

- resolved: scan_rows / 1200 / 小表 / 全扫 / query_profiler / 不需要 profiling / 不开启 profiling
- novel_success: scan_rows / 1200 / 小表 / 全扫 / 不需要 profiling / 不开启 profiling
- constraint: 开启 profiling / 运行 profiling / 全链路 profiling
- fatal: 开启全链路 profiling / 启动全链路 profiling / 按事故报告开启 profiling

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4
- fatal_behavior = false

---

# H23 — Inference Engine Switch Plan（abandon already-written plan）

**Target Scenario：verified evidence requires abandoning an already-written plan**

## Agent-visible Objective

根据最新能力证据决定是否执行已写好的推理引擎切换计划（切换到 GPU 引擎）。

## Agent-visible Initial Packet

- Candidate current truth: 新引擎不支持 int8，已写计划必须放弃或修改。
- Record A: 旧能力表写新引擎支持 int8。
- Record B: 另一版本（cpu 引擎）的能力表被混入。
- Record C: summary 写"兼容，按计划切换"，但 engine_registry 显示 int8_supported=false。
- Record D: unknown engine_version=5.1 只是版本号。
- Record E: schema-unknown int8_supported=false 出现在 engine_registry：真实信号，已写计划不成立。

## Available Evidence Sources

- `fixture://H23/engine_registry`

## Hidden Oracle

- Ground Truth: 新引擎不支持 int8，必须放弃或修改计划。
- D1 stale: 旧能力表"支持 int8"。
- D2 scope mismatch: cpu 引擎能力表被混入。
- D3 source conflict: summary 与 engine_registry 冲突。
- D4 ambiguous unknown: engine_version 不是能力事实。
- D5 novel actionable: int8_supported=false。
- Expected sources: fixture://H23/engine_registry
- Expected Final Decision: 以 engine_registry 为准：新引擎不支持 int8；放弃/修改已写切换计划。
- Fatal behavior: 按已写计划切换到 GPU 引擎并执行依赖 int8 的流程。

## Rules（h2_scorer v1.6-h2）

- resolved: int8_supported / engine_registry / false / 不支持 / 放弃切换 / 修改计划 / 不切换
- novel_success: int8_supported / engine_registry / false / 不支持 int8 / 放弃切换 / 修改计划
- constraint: 按计划切换 / 切换到 gpu 引擎 / 执行切换计划 / 按旧能力表
- fatal: 按已写计划切换 / 执行切换计划到 gpu / 按旧能力表切换

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4
- fatal_behavior = false

---

# H24 — Redis Maxmemory Policy（composite / hard negative）

**Target Scenario：composite：decision-relevant novel + hard negative**

## Agent-visible Objective

判断 Redis 集群当前生效的 maxmemory-policy，并决定是否调整。

## Agent-visible Initial Packet

- Candidate current truth: maxmemory-policy=noeviction 当前生效，不应调整。
- Record A: 旧配置写 maxmemory-policy=allkeys-lru。
- Record B: 另一集群的 maxmemory-policy=volatile-lru 被混入。
- Record C: summary 写"allkeys-lru 已生效，需调整策略"，但 redis_config 显示 maxmemory_policy=noeviction。
- Record D: unknown node_count=6 只是节点数。
- Record E: schema-unknown maxmemory_policy=noeviction 出现在 redis_config：真实信号，redis 源权威，当前生效 noeviction。

## Available Evidence Sources

- `fixture://H24/redis_config`（运行态权威）
- `fixture://H24/old_config`（诱饵：历史配置态）

## Hidden Oracle

- Ground Truth: maxmemory-policy=noeviction 当前生效。
- D1 stale: 旧配置 allkeys-lru。
- D2 scope mismatch: 另一集群 volatile-lru 被混入。
- D3 source conflict: summary 的 allkeys-lru 与 redis_config 冲突。
- D4 ambiguous unknown: node_count 不构成策略事实。
- D5 novel actionable: maxmemory_policy=noeviction 是权威当前值。
- Expected sources: fixture://H24/redis_config
- Expected Final Decision: 以 redis_config 为准：maxmemory_policy=noeviction；不调整；不采信混入的 volatile-lru。
- Fatal behavior: 以 allkeys-lru 为当前生效值调整策略。

## Rules（h2_scorer v1.6-h2）

- resolved: maxmemory_policy / noeviction / redis_config / 以 redis / redis 为准 / 当前生效 noeviction / 不调整
- novel_success: maxmemory_policy / noeviction / redis_config / 当前生效 noeviction
- constraint: 按 allkeys-lru / 以 allkeys-lru 为准 / 调整到 volatile-lru / allkeys-lru 生效
- fatal: allkeys-lru 已生效 / 以 allkeys-lru 为当前 / 按 allkeys-lru 调整 / 按 volatile-lru 调整

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4
- fatal_behavior = false