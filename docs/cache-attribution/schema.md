# Cache Attribution Report Schema — v1.0.0-draft2

> 状态：**待评审冻结**。冻结后版本号升为 `1.0.0`，此后任何字段变更必须升版本，禁止静默改语义。
> 范围：LFL provider 缓存 miss 的**机制归因**口径。它回答"miss 是哪条边界产生的、是否可控、置信度多少"，**不输出**"可修复 miss"这类黑盒总量。

## 0. 动机与不变量

本会话审计暴露过三类污染：

1. **活日志快照漂移** —— 分析期间事件仍在追加，两次读取得到不同总量；
2. **机制混桶** —— history compaction / tool working-set fold / provider eviction 被当成同一类"run 内重写"；
3. **事后猜测归因** —— 只看 input 跳变推机制，无法被 replay 验证。

因此 schema 的三条硬规则：

- **R-快照**：任何报表必须声明冻结快照（hash + seq watermark）。`freeze.py` 记录原始源文件 sha256/mtime，并生成不可变 `extract.jsonl`；scorer 只信任并校验 manifest 声明的 extract sha256 / event_count / seq watermark。源日志之后继续增长不改变已冻结结果。
- **R-证据**：`boundary.types` 只能由 LFL 原生事件/字段判定（分类规则 §4），不允许从 miss 大小反推机制。
- **R-分解**：每条请求的 miss 分解为 `observed_miss / expected_append_miss / boundary_excess_miss` 三元组 + `controllable` + `confidence`，三者来源与估算器版本显式声明。

## 1. 报表形态

JSONL，三种 record，靠 `record_type` 判别：

| record_type | 角色 | 数量 |
|---|---|---|
| `snapshot_header` | 快照身份 + 估算器参数 + surface 指纹 | 恰好 1 条，首行 |
| `request_attribution` | 每个已结算 provider 请求一条 | N 条，按 ts 升序 |
| `boundary_rollup` | 按 boundary 类型汇总 + storm 簇 | 恰好 1 条，末行 |

机器校验：JSON Schema（`schemas/cache_attribution_report.schema.json`，draft 2020-12）；rollup 必须与逐条记录**算术 reconcile**（§6）。

## 2. snapshot_header

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | 本 schema 版本 |
| `session_id` | string | |
| `log_snapshot_at` | date-time | 冻结时刻（水印） |
| `sources[]` | array of object | `{path, sha256, first_seq, last_seq, event_count}`，多文件日志逐个声明 |
| `generated_by` | `{scorer, version}` | 生成器标识 |
| `estimator` | object | 见 §5；含 `estimator_id` 与全部参数 |
| `surface` | object | `{provider, model, wire_protocol, tools_count, stable_prefix_fp, tool_prefix_fp?, provider_structure_fp?}` —— surface contract 指纹，P1 密度统计按此分组 |
| `notes` | string? | 自由文本 |

## 3. request_attribution

### 3.1 请求身份（全部 required）

`ts, seq, run_generation, round, attempt_kind, provider_call_id, provider, model, tokens_in, cache_hit, cache_miss, cache_hit_rate, stable_prefix_fp, prefix_changed, prefix_change_reason, gap_seconds_since_prev`（首请求可 null）。

`run_generation`：用户 run 单调递增序号（由 round 重置/gap 判定，映射 LFL `tail_user_run`）。
`cache_miss = tokens_in − cache_hit`；`cache_hit_rate = cache_hit / tokens_in`。

### 3.2 边界判定 `boundary`

```
boundary: {
  types: [<enum>...],        // 非空；可多值（同一窗口内多机制叠加）
  primary: <enum>,           // 归因主边界，按 §4 优先级取
  evidence_event_ids: [...], // 判定所依赖的事件 id / 字段路径，可审计
  classification_rule: str   // 命中的规则 id，如 "C3-compaction-in-window"
}
```

**边界枚举**（封闭集合，新增需升版本）：

`append_only` | `history_compaction` | `working_set_fold` | `provider_eviction` | `new_run_cold_start` | `route_switch` | `unknown`

> `route_switch` 是对既定六值的补充：provider/model/wire contract 变化导致的缓存冷却是既定行为，既非 eviction 也非 cold_start，实测会话中存在（ornith→glm）。

### 3.3 归因结果 `attribution`（全部 required）

| 字段 | 说明 |
|---|---|
| `observed_miss` | `= cache_miss`，冗余存储便于单行阅读 |
| `expected_append_miss` | 反事实：无该边界、纯追加世界下的期望 miss（§5） |
| `boundary_excess_miss` | `= max(0, observed_miss − expected_append_miss)` |
| `clamped_negative_tokens` | 负值截断量（观测好于期望时 >0） |
| `controllable` | `yes / no / partial / unknown`，按 §4.2 映射表 |
| `confidence` | `high / medium / low`，按 §4.3 |
| `estimator_id` | 冗余声明，防混读 |

**禁止**在 v1 输出任何"可修复 miss"单值汇总；rollup 只给分桶和 `controllable_*` 分解。

### 3.4 机制明细块（可选，按 boundary 出现）

**`history_compaction_detail`**：

| 字段 | 来源 |
|---|---|
| `compaction_epoch, pre_chars, post_chars, trigger` | 现有 `history.compaction` 事件 |
| `archived_messages, archived_groups` | 现有（`message.cache_compacted` 计数归到这里，**它不是独立机制**） |
| `low_water_target, growth_guard, convergence_ok` | **P2 产出**；schema 冻结为 nullable，`pending_fields` 标注 |
| `rounds_until_next_compaction` | 事后派生 |

**`working_set_detail`**：

| 字段 | 来源 |
|---|---|
| `raw_tool_chars, projected_tool_chars, folded_results, folded_groups, fold_trigger, net_gain_chars` | 现有 `request.meta.influence.ingress.tool_working_set` |
| `working_set_projection_epoch, previous_projection_fp` | **P3 产出**；nullable + pending |

**`provider_eviction_detail`**（仅当 `provider_eviction` 在 types 中）：

```
{ stable_prefix_unchanged: true,     // 常量 true —— 这是判定前提
  no_local_projection_boundary: true, // 常量 true
  full_miss: bool, hit_drop_ratio: number?, gap_seconds: number, ttl_suspected: bool }
```

**铁律：`provider_eviction` 的 excess 计入 `uncontrollable` 桶，永远不得计入 LFL 可修复 miss。**

### 3.5 `context_sizes`（required，nullable）

`{history_chars, provider_visible_chars}` —— P1 密度观测的原料；`chars_per_token = provider_visible_chars / tokens_in`，与归因同源同快照。

## 4. 分类规则（封闭优先级）

同一请求窗口 `(prev_ts, ts]` 内按序评估，命中者全部进 `types`；`primary` 按最高优先级取：

| 规则 | 判定 | 边界 | 优先级 |
|---|---|---|---|
| C1 | `model` 或 `provider` ≠ 上一请求（**注意：`provider_structure_fp` 是逐请求指纹，不是路由判据，禁止进入 C1**） | `route_switch` | 1 |
| C2 | `run_generation` 变化（round 重置） | `new_run_cold_start` | 2 |
| C3 | 窗口内存在 `history.compaction` 事件或 `compaction_epoch` 增长 | `history_compaction` | 3 |
| C4 | 窗口内 working-set 折叠证据（`folded_results` 增量 >0；P3 后：`working_set_projection_epoch` 变化） | `working_set_fold` | 4 |
| C5 | `stable_prefix_fp` 未变 ∧ 无 C3/C4 证据 ∧ `prefix_changed=false` ∧ (`cache_hit=0` ∨ `cache_hit < 0.5 × stable_prefix_tokens`) | `provider_eviction`（suspected） | 5 |
| C6 | 无任何边界证据 ∧ `tokens_in ≥ prev_tokens_in − tolerance` | `append_only` | 6 |
| C7 | 证据矛盾（如 input 回缩但无 C3/C4 证据；`prefix_changed=true` 但无 C1） | `unknown` + 告警 tag | 7 |

### 4.1 共现（P3 的直接验收指标）

`types` 多值合法。v1 的 excess **只归 `primary`**，不做数值拆分（拆分留给 scorer v2）。报表必须能回答：**fold 与 compaction 同窗口共现率**——P3"收敛到同一 projection boundary"的验收就看它的下降。

### 4.2 controllable 映射

| 边界 | controllable |
|---|---|
| `history_compaction` / `working_set_fold` | `yes` |
| `new_run_cold_start` / `route_switch` | `partial` |
| `append_only` / `provider_eviction` | `no` |
| `unknown` | `unknown` |

### 4.3 confidence 映射

`high`：有直接事件证据（C1/C3/C4）；`medium`：结构性推断（C2/C5/C6）；`low`：C7 或估算器走了 fallback 参数。

## 5. 估算器 v1（`v1-linear-append`）

| 场景 | `expected_append_miss` |
|---|---|
| `append_only` | `max(0, tokens_in − prev_tokens_in) + block_allowance` |
| 边界轮且 input 回缩 | `growth_fallback + block_allowance`（反事实：不压也会自然增长） |
| 边界轮且 input 增长 | `max(0, tokens_in − prev_tokens_in) + block_allowance`（增长部分本就是新内容） |
| `new_run_cold_start` | `tokens_in − stable_prefix_tokens` |
| `provider_eviction` | 同 `append_only` 公式（excess 落入 uncontrollable 桶） |

参数（header 声明）：`block_allowance_tokens=64`（provider 缓存块粒度）；`growth_fallback_tokens=512`（同 run 正增量的窗口中位数，缺省回落值）；`stable_prefix_tokens` —— **优先用 LFL 侧实测**（system+tools+memory 的 token 计量）；无计量时回落"冷启动观测 hit 最小值"，此时该轮 confidence 降 `medium` 并在 `estimator.params.stable_prefix_source` 标注 fallback。

**保守方向声明**：边界轮的 excess 是"实际未命中 − 反事实追加期望"。保留区字节若实际重新命中，会自然缩减 observed_miss，不会虚增 excess；因此 excess 是**实际损失的上界、下界不低于保留区真实重填量**。方向单向、可 replay。

**版本策略**：估算公式改动必须升 `estimator_id`（v2-…），旧报表不重算、新旧不可直接对比，除非声明换算。

## 6. boundary_rollup 与 reconcile

rollup 必须满足（scorer 自检 + 外部可验）：

```
Σ by_boundary.observed_miss_sum      == totals.observed_miss      == Σ request.observed_miss
Σ by_boundary.expected_append_miss_sum == totals.expected_append_miss
Σ by_boundary.boundary_excess_miss_sum == totals.boundary_excess_miss
controllable_excess_miss = Σ( excess | controllable= yes )
uncontrollable_excess_miss = Σ( excess | controllable= no )
partial_excess_miss = Σ( excess | controllable= partial )
unknown_excess_miss = Σ( excess | controllable= unknown )
```

`by_boundary[].controllable` 汇总同一 primary 的请求；若同一 primary 因共现机制出现多个 controllability 值，则为 `mixed`，禁止沿用第一条记录的标签。

`storm_clusters[]`：`{boundary, start_ts, end_ts, transactions, excess_miss_sum, definition}`。v1 定义：**180s 窗口内 ≥2 次 history.compaction 事务**。storm 簇的 excess_miss_sum 只计入簇内请求级 excess，样本窗口未覆盖的簇成员必须在 `notes` 声明。

## 7. P1/P2/P3 消费接口（本 schema 的下游契约）

- **P1 密度统计**：原料 = 每条 `request_attribution.context_sizes × tokens_in`，按 `header.surface`（provider+model+wire/tool contract）分组；EWMA lower bound / 保守低分位 + **更新迟滞**；**禁止单轮反馈控制**。token 是 authority，char 仅作 projector bridge。
- **P2 低水位**：`low_water_target / growth_guard / convergence_ok / rounds_until_next_compaction` 就位后，storm_clusters 应归零；`P90(growth)×3` 作为 qualification hypothesis 被 A/B（2/3/4-round guard），不写死。
- **P3 共现率**：`types` 含 `[history_compaction, working_set_fold]` 的请求占比与 `previous_projection_fp` 变更频率是验收指标。
- **验收语言**：从此不再用总命中率替代机制归因；总命中率只作背景量。

## 8. 样例与校验

- 样例：`schemas/examples/51da0a7a-attribution.sample.jsonl`（真实会话数据 + 1 条显式标注的 synthetic `route_switch` 记录演示枚举完备性；rollup 仅聚合真实记录）。
- 校验：样例必须通过 JSON Schema；rollup 必须与逐条记录 reconcile。CI 中两者都跑。
