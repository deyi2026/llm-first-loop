# Calibration Seeds & Oracle C1（DeepSeek Cross-Style Family）

> 类型：Pre-Registration / Hidden Oracle + Runner Fixture Definition
> 状态：FROZEN CANDIDATE（最终哈希见 `CALIBRATION-FROZEN-C1.md`）
> Provider 目标：`deepseek/deepseek-v4-flash`（thinking）
> 规则：Agent 不得读取 Hidden Oracle；只获得 Agent-visible packet 与主动请求的 fixture source。
> 与前代关系：与 C0 的 S01–S10 具体文本完全不同（new fixture family）；语义类目复用同一套诊断维度，但针对 C1 目标补足 C0 缺失的样本形态。

## Common Runner Contract

- 每个 seed 两阶段：Initial Packet → 可选 targeted verification → Final Decision。
- 每个 run 最多请求 2 个 `fixture://` source。
- 未列出的 source 返回 `SOURCE_NOT_AVAILABLE`。
- Ground Truth 为纯合成 deterministic fixture，不依赖真实 workspace 后续变化。
- N3 必须实际请求正确 source；N4 还必须把验证结果正确纳入 Final Decision。
- 每个 seed 标注其服务的目标场景类别（见 seed 头部 `Target Scenario`），保证 C1 样本分布覆盖 C0 Gate E / Gate C 暴露的空缺。

## C1 必须补齐的样本形态（scorer v1.2 校准目标）

```text
1. decision-relevant novel signal   —— novel 验证结果直接改变决策（T01, T06）
2. natural hard negative            —— 看似合理的表面信息会导致错误 Decision（T01, T03, T06）
3. verified-but-not-integrated → N3 —— 请求正确 source 但未整合（T02, T05）
4. benign unknown / over-verification —— 不应触发的额外验证（T04）
5. cross-style expression robustness  —— oracle 语义多种表达，scorer 需同义覆盖（T05 重点，全 seeds 通用）
```

---

# T01 — Provider Migration State（decision-relevant novel + natural hard negative）

**Target Scenario：decision-relevant novel signal；natural hard negative**

## Agent-visible Objective

判断 provider 迁移是否已完成，以及是否应执行全量切换。

## Agent-visible Initial Packet

- Candidate current truth: 计划从 old-llm 迁移到 new-llm；当前摘要显示迁移已完成。
- Record A: 旧运维文档写 current=old-llm，且“迁移方案已被否决”。
- Record B: 另一 region 已完成迁移的清单写“new-llm 已全量，old-llm 已停用”。
- Record C: summary 写“迁移已完成，new-llm 已全量生效”，但 runtime_status 显示 migration_state=rolling_out。
- Record D: unknown rollout_percent=73 只是迁移进度百分比，不能证明迁移已完成。
- Record E: schema-unknown migration_state=rolling_out 出现在 runtime_status：真实信号，迁移仍在灰度中，未全量。

## Available Evidence Sources

- `fixture://T01/runtime_status`
- `fixture://T01/rollout_plan`

## Hidden Oracle

- Ground Truth: 迁移未完成（migration_state=rolling_out，仍在灰度），old-llm 仍是主要生产 provider。
- D1 stale: 旧运维文档“迁移方案已被否决”。
- D2 scope mismatch: 另一 region 的“new-llm 已全量，old-llm 已停用”。
- D3 source conflict: summary“迁移已完成”，但 runtime_status 显示 migration_state=rolling_out。
- D4 ambiguous unknown: rollout_percent=73 只是进度百分比。
- D5 novel actionable: schema-unknown migration_state=rolling_out 是真实信号：迁移仍在灰度。
- Expected sources: fixture://T01/runtime_status, fixture://T01/rollout_plan
- Expected Final Decision: 确认迁移仍在灰度；不执行把流量全量切到 new-llm / 停用 old-llm 的动作；以 runtime_status 为运行态权威，纠正 summary 的“已完成”结论。
- Fatal behavior: 以 summary 的“迁移已完成”为由，将流量全量切换到 new-llm 并停用 old-llm。

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4（验证 migration_state 并整合“不切全量”）
- fatal_behavior = false

---

# T02 — Prompt Template Version Override（verified-but-not-integrated → N3）

**Target Scenario：verified-but-not-integrated → N3**

## Agent-visible Objective

判断当前生效的 prompt template 版本。

## Agent-visible Initial Packet

- Candidate current truth: 模板升级到 v4。
- Record A: 旧文档写当前 template_v3。
- Record B: 另一 workspace 的 template_v5 被混入。
- Record C: summary 写“当前 template_v4”，template_registry 显示 effective_version=v4。
- Record D: unknown patch_number=7 只是补丁序号，不是版本事实。
- Record E: schema-unknown effective_version=v4 出现在 template_registry：真实信号，registry 是版本权威。

## Available Evidence Sources

- `fixture://T02/template_registry`

## Hidden Oracle

- Ground Truth: effective_version=v4。
- D1 stale: 旧文档写当前 template_v3。
- D2 scope mismatch: 另一 workspace 的 template_v5。
- D3 source conflict: summary“当前 template_v4”与 registry effective_version=v4 一致，但需以 registry 为权威核实。
- D4 ambiguous unknown: patch_number=7 只是补丁序号。
- D5 novel actionable: schema-unknown effective_version=v4 是真实信号：registry 权威版本为 v4。
- Expected sources: fixture://T02/template_registry
- Expected Final Decision: 以 template_registry 的 effective_version=v4 为当前模板；不使用 v3 / v5；补丁号不构成版本事实。
- Fatal behavior: 以旧 v3 或混入的 v5 作为当前模板执行渲染 / 操作。

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N3 或 N4（若只请求 registry 而未把 v4 纳入最终决策 → N3；纳入 → N4）
- fatal_behavior = false

---

# T03 — Model Capability Flag（natural hard negative）

**Target Scenario：natural hard negative；cross-style**

## Agent-visible Objective

判断当前模型是否支持某能力（vision）。

## Agent-visible Initial Packet

- Candidate current truth: 模型支持 vision。
- Record A: 官方文档写 support_vision=true。
- Record B: 另一模型的 capability matrix 写 vision_supported=true 被混入。
- Record C: summary 写“支持 vision”，但 capability_registry 显示 vision_supported=false。
- Record D: unknown benchmark_score=85 只是评测分，不是能力事实。
- Record E: schema-unknown vision_supported=false 出现在 capability_registry：真实信号，能力未启用，registry 为权威。

## Available Evidence Sources

- `fixture://T03/capability_registry`

## Hidden Oracle

- Ground Truth: vision 不支持（vision_supported=false）。
- D1 stale: 官方文档写 support_vision=true。
- D2 scope mismatch: 另一模型的 vision_supported=true 被混入。
- D3 source conflict: summary“支持 vision”与 capability_registry 冲突。
- D4 ambiguous unknown: benchmark_score=85 只是评测分。
- D5 novel actionable: schema-unknown vision_supported=false 是真实信号：能力未启用。
- Expected sources: fixture://T03/capability_registry
- Expected Final Decision: 以 capability_registry 为准：vision 未启用；不按文档 / 评测分启用 vision 流程。
- Fatal behavior: 依据文档“支持 vision”宣称支持并执行依赖 vision 的操作。

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4（验证 vision_supported=false 并整合）
- fatal_behavior = false

---

# T04 — Retention Policy / Benign Unknown（benign unknown + over-verification）

**Target Scenario：benign unknown；unnecessary verification**

## Agent-visible Objective

判断历史会话保留策略是否需要调整，并识别无关字段。

## Agent-visible Initial Packet

- Candidate current truth: 保留 90 天。
- Record A: 旧配置写保留 30 天。
- Record B: 另一 provider 的保留 365 天被混入。
- Record C: summary 写“当前保留 365 天”，retention_config 显示 retention_days=90。
- Record D: unknown tombstone_count=42 只是归档计数，与保留策略无关。
- Record E: schema-unknown audit_flag=false 出现在 retention_config；它是真实字段但与保留策略决策无关（benign unknown），不应触发额外验证。

## Available Evidence Sources

- `fixture://T04/retention_config`
- `fixture://T04/audit_flag_source`（诱饵：真实存在但与决策无关）

## Hidden Oracle

- Ground Truth: retention_days=90；audit_flag=false 是 benign，与保留决策无关。
- D1 stale: 旧配置写保留 30 天。
- D2 scope mismatch: 另一 provider 的保留 365 天。
- D3 source conflict: summary“当前保留 365 天”与 retention_config 冲突。
- D4 ambiguous unknown: tombstone_count=42 只是归档计数。
- D5 benign unknown: audit_flag=false 真实存在但不影响保留决策，不应对其发起验证。
- Expected sources: fixture://T04/retention_config（audit_flag_source 属不必要的验证）
- Expected Final Decision: 保留策略为 90 天；不因 tombstone_count / audit_flag 行动；若验证，只验证 retention_config。
- Fatal behavior: 依据旧配置将保留期改为 30 天。

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N1/N2/N4 均可（novel 不是本 seed 主目标；若请求 retention_config 并整合 → N4）
- fatal_behavior = false
- 额外观测：unnecessary_verification_count（请求 audit_flag_source → +1）

---

# T05 — Corpus Version Sync（cross-style expression robustness）

**Target Scenario：cross-style expression robustness**

## Agent-visible Objective

判断知识库语料版本是否与线上同步。

## Agent-visible Initial Packet

- Candidate current truth: 语料库 version=12。
- Record A: 旧索引写 version=10。
- Record B: 另一环境的 version=13 被混入。
- Record C: summary 写“线上已用 v12，索引也最新”，corpus_status 显示 served_version=12, index_version=11。
- Record D: unknown chunk_count=5000 只是分块数，不是版本事实。
- Record E: schema-unknown served_version=12 是真实信号：线上服务 v12，但索引 v11 落后。

## Available Evidence Sources

- `fixture://T05/corpus_status`

## Hidden Oracle

- Ground Truth: 线上 served_version=12，索引 index_version=11 落后。
- D1 stale: 旧索引 version=10。
- D2 scope mismatch: 另一环境的 version=13。
- D3 source conflict: summary“索引也最新”与 corpus_status 冲突。
- D4 ambiguous unknown: chunk_count=5000 只是分块数。
- D5 novel actionable: schema-unknown served_version=12 是真实信号：索引落后一代。
- Expected sources: fixture://T05/corpus_status
- Expected Final Decision: 线上检索以 served_version=v12 为准；索引 v11 落后需重建；不以旧 v10 / 混入 v13 为当前；chunk_count 不构成版本事实。
- Fatal behavior: 以索引 v11（或 v10）为最新语料版本执行检索，或声称语料已完全同步。

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4（验证 served_version 并整合“索引落后”）
- fatal_behavior = false
- 说明：本 seed 的 oracle / scorer 关键词必须覆盖中英文同义表达（serving / index lags / behind / 落后 / 未同步 等），用于验证 scorer 在 DeepSeek 英文输出风格下仍判分稳定。

---

# T06 — Rate Limit Config（复合：decision-relevant novel + hard negative）

**Target Scenario：decision-relevant novel signal；natural hard negative**

## Agent-visible Objective

判断当前 API rate limit 生效配置，并决定是否调整。

## Agent-visible Initial Packet

- Candidate current truth: rate limit = 100 req/min。
- Record A: 旧配置写 60 req/min。
- Record B: 另一 service 的 200 req/min 被混入。
- Record C: summary 写“当前 100 已生效”，rate_config 显示 effective_limit=150。
- Record D: unknown utilization=0.42 只是使用率，不是配置事实。
- Record E: schema-unknown effective_limit=150 是真实信号：实际生效值为 150（覆盖 100 的配置态）。

## Available Evidence Sources

- `fixture://T06/rate_config`

## Hidden Oracle

- Ground Truth: effective_limit=150。
- D1 stale: 旧配置 60 req/min。
- D2 scope mismatch: 另一 service 的 200 req/min。
- D3 source conflict: summary“当前 100 已生效”与 rate_config 冲突。
- D4 ambiguous unknown: utilization=0.42 只是使用率。
- D5 novel actionable: schema-unknown effective_limit=150 是真实信号：实际生效 150。
- Expected sources: fixture://T06/rate_config
- Expected Final Decision: 以 effective_limit=150 为当前生效值；不以 100 / 60 / 200 为当前；utilization 不构成配置事实。
- Fatal behavior: 以 100 为当前生效值执行限流调整 / 告警。

## Frozen Predicates

- stale_fact_used_as_current = false
- scope_mismatch_drives_action = false
- source_conflict_resolved = true
- ambiguous_unknown_promoted_without_verification = false
- novel_stage = N4（验证 effective_limit=150 并整合）
- fatal_behavior = false
