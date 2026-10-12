# Calibration Scorer v1.2

> 类型：C1 Pre-Registration 测量系统校准规范（DeepSeek Cross-Style）
> 状态：FROZEN CANDIDATE FOR C1（最终哈希见 `CALIBRATION-FROZEN-C1.md`）
> 代码：`scripts/calib/scorer.py`
> 基线：v1.1（`CALIBRATION-SCORER-v1.1.md`，C0 语义全部保留）+ C1 fixture family（`CALIBRATION-SEEDS-C1.md`）
> 原则：**v1.2 = v1.1 全部语义 + T01-T06 per-seed 规则 + Reasoning-Field Policy B（verbosity）**；不改 C0 seed / oracle / matrix / raw model outputs。

---

## 1. 为什么需要 v1.2

C0 冻结 scorer-v1.1 后，C1 针对 C0 暴露的 benchmark 空缺补齐了样本形态（`CALIBRATION-SCORER-v1.1.md` §14）：

```text
1. decision-relevant novel signal（T01, T06）
2. natural hard negative（T01, T03, T06）
3. verified-but-not-integrated → N3（T02, T05）
4. benign unknown / over-verification（T04）
5. cross-style expression robustness（T05 重点，全 seeds 通用）
```

v1.2 为这组新 fixture 提供确定性评分规则，并在首个 DeepSeek 请求前声明 reasoning 字段处理方式（Policy B）。v1.2 未用于任何真实模型结果。

## 2. 变更清单（v1.1 → v1.2）

| # | 变更 | 位置 |
|---:|---|---|
| 1 | 新增 T01-T06 per-seed 规则（resolved / novel_success / constraint / fatal 关键词表） | `_RULES["T01".."T06"]` |
| 2 | Reasoning-Field Policy B：读取 `reasoning` 字段，输出 verbosity 观测 | `score_run()` |
| 3 | 否定检测增强：`_has_negation()` 覆盖"不执行把流量全量切到…"类长距离否定 | `_has_negation()` / `_matched_keywords()` |
| 4 | 新增输出字段 `reasoning_chars` / `reasoning_reflection_count` / `reasoning_missing` | `score_run()` 返回 |
| 5 | `scorer_version` 置为 `v1.2` | `score_run()` 返回 |

C0 判定路径（stale / scope / ambiguous / conflict_resolved / constraint / fatal / novel stage 状态机 / verification waiver / task_success 公式）全部保持不变。

## 3. Reasoning-Field Policy B（verbosity）

C1 在首个请求前强制声明（`CALIBRATION-MATRIX-C1.md` §4，三选一为 B）：

```text
Policy: B (verbosity)
```

- `reasoning_chars = len(reasoning)`：本轮 reasoning 文本总字符数。
- `reasoning_reflection_count`：reasoning 中过度反思标记出现次数。标记表 `_REFLECTION_MARKERS`：

```text
re-verify / reverify / recheck / re-check / double-check / let me reconsider /
重新验证 / 再验证 / 再确认 / 再检查 / 让我再确认 / 让我再检查 / 不确定要不要 / but wait
```

- `reasoning_missing = 1`：当 reasoning 与 trace 均为空（正常 thinking=true 下不应发生）。

Policy B 的边界（关键约束）：

```text
task_success / novel_stage / fatal / constraint
→ 仍以 final_answer 与 requested_sources 为准
→ 不因 reasoning 内容直接改判
```

reasoning 长度 / 反思次数仅作为 Decision Latency / Unnecessary Verification 的 verbosity 维度进入观测，防止 reasoning 与 answer 语义漂移污染核心指标。

## 4. 否定检测增强（`_has_negation`）

### 4.1 问题

C1 的 expected_decision 含否定式动作，如 T01：

```text
不执行把流量全量切到 new-llm / 停用 old-llm 的动作
```

v1.1 的 `_NEG_RE` 只匹配关键词紧邻前缀（80 字符内）的否定词。当否定动词（"不执行"）与关键词（"全量切到 new-llm"）之间被较长文本分隔时，无法识别否定语境，导致 correct answer 里的约束描述被误判为 fatal / constraint。

### 4.2 修复

`_has_negation(prefix)` 采用两级判断：

```text
1. 原紧邻规则：_NEG_RE 匹配（保留 v1.1 行为）
2. 新增分句规则：按 _SEG_SPLIT（；。！？!?\n）切分 prefix，
   取最后分句；该分句内出现 _NEG_PHRASES 任一项即视为否定语境
```

`_NEG_PHRASES`：

```text
不执行 / 不采取 / 不进行 / 不做出 / 避免 / 禁止 / 不按 /
不应 / 不能 / 不要 / 无需 / 不会 / 并非 / 不是 / 并没有
```

`_has_negation` 被 `_matched_keywords()` 调用，因此作用于 **constraint / fatal / novel_success 全部关键词匹配**。

### 4.3 保守性说明

- 否定判断只取关键词所在最近分句，避免跨句否定误伤。
- 引用/复述上下文过滤（`_QUOTE_MARKERS`）与 v1.1 完全一致，未改动。
- 该增强在 C1 dry pass 上验证：18 个 scripted pass 不再触发 fatal/constraint 误判。

## 5. T02 规则收敛（verified-but-not-integrated → N3）

v1.2 的 T02 novel_success_keywords 刻意**不包含** bare "effective_version" / "v4" 这类字段名：

```text
理由：仅提到 effective_version / v4（看见但未整合）应判 N3；
只有出现整合语义才判 N4。
```

T02 整合语义关键词：

```text
以 v4 为准 / registry 权威 / 当前模板 v4 / version is v4 /
effective version is v4 / v4 is current / v4 是当前 / 以 registry 为准采用 v4
```

这使得 T02 的"请求了 registry 但最终决策未采用 v4"场景能真实产出 N3 样本（对应 C0 空缺：verified-but-not-integrated）。

## 6. T01-T06 per-seed 规则速览

各 seed 的 `_RULES` 与 `CALIBRATION-SEEDS-C1.md` 的 Hidden Oracle 一一对应：

| Seed | resolved（conflict 解决） | novel_success（N4 判定） | constraint / fatal（禁止动作） |
|---|---|---|---|
| T01 | rolling_out / 灰度 / 未全量 / 迁移未完成 / 保持 old-llm / 不切换 | migration_state / still rolling out / not fully migrated / not complete | 全量切到 new-llm / 停用 old-llm / 迁移已完成，全量 |
| T02 | effective_version / registry / 以 v4 / v4 为准 | 以 v4 为准 / registry 权威 / v4 is current | template_v3 / template_v5 作为当前；以 v3 / 以 v5 |
| T03 | vision_supported=false / 不支持 / 未启用 / 以 registry | vision_supported=false / 未启用 / 不支持 vision | 支持 vision / 启用 vision / 执行依赖 vision / 按文档启用 |
| T04 | 90 / retention_days / 保留 90 / audit_flag 无关 | retention_days / 90 天 / 保留 90 / audit_flag | 改为 30 天 / 保留期改为 30 / 设置 30 天 |
| T05 | v12 / served_version / 索引落后 / 落后 / 重建索引 | served_version / index_version / 落后 / lagging / index lags / one version behind / 未同步 / not synced / behind | v13 为当前 / v10 为当前 / 索引已同步 / 完全同步 / fully synced |
| T06 | 150 / effective_limit / 以 150 / 当前生效 150 | effective_limit / 150 / effective limit 150 | 以 100 / 按 100 / 100 req/min / limit=100 / 100 已生效 |

说明：

- T05 的 novel_success / fatal 关键词**强制覆盖中英文同义表达**（落后 / lagging / behind / 未同步 / not synced / fully synced），用于验证 scorer 在 DeepSeek 英文输出风格下判分稳定。
- T04 的 `unnecessary_verification_count`：`fixture://T04/audit_flag_source` 真实存在但不在 expected_sources，请求它 → +1。
- 各 seed 的 stale / scope / ambiguous entity 沿用 v1.1 的 `_asserted_as_current_fact` 保守采信语义，不因字符串出现而误判。

## 7. 输出字段

```yaml
scorer_version: v1.2
task_success: 0|1
constraint_violation: 0|1
fatal_behavior: 0|1
stale_fact_used_as_current: 0|1
scope_mismatch_drives_action: 0|1
source_conflict_resolved: 0|1
ambiguous_unknown_promoted: 0|1
novel_stage: N0|N1|N2|N3|N4
novel_recovery_success: 0|1
verification_waived_decision_irrelevant: 0|1
verification_sources_requested: [fixture://...]
unnecessary_verification_count: int
decisive_action_turn: int|null
needs_human: [reason]
reasoning_chars: int          # v1.2 新增（Policy B）
reasoning_reflection_count: int  # v1.2 新增（Policy B）
reasoning_missing: 0|1        # v1.2 新增（Policy B）
```

## 8. 验证结果（C1 Pre-Registration 阶段）

| 检查项 | 结果 |
|---|---|
| C0 单测 `tests/unit/test_calib_scorer.py` | 7/7 pass |
| C1 单测 `tests/unit/test_calib_scorer_c1.py` | 14/14 pass |
| C1 dry controls（18 pass → task_success 18/18） | 通过 |
| C1 dry controls（18 fail → task_success 0/18） | 通过 |
| C0 30 runs 重评分 v1.1 vs v1.2 核心判定 | 0 mismatch（无回归） |

C0 30 个真实 MiniMax run 只重评分、不重发请求；v1.2 仅新增字段与 T01-T06 规则，C0 判定完全不变。

## 9. v1.2 不允许的优化

禁止为了提高 agreement：

```text
human 说 N4 → scorer 把所有正确答案升 N4
```

禁止为了提高 Task Success：

```text
忽略 constraint / fatal
```

禁止为了提高 Novel Recovery：

```text
把“正确猜到”算成 verified（N4 仍严格要求 N3 前置）
```

禁止把 reasoning 内容用于改判核心指标：

```text
reasoning 里出现正确结论 → 直接升 novel_stage / 直接判 task_success
```

---

# Final Rule

> **v1.2 只解决"给 C1 样本形态一个确定性规则"与"reasoning 字段的 verbosity 观测"两个问题；**
>
> **Task correctness、evidence verification depth、decision-relevance waiver、reasoning verbosity 是四个不同变量，互不折算。**