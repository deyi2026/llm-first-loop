# C0 Calibration 执行结果 v1

> 状态：**C0 30/30 runs 已执行（MiniMax-M3 真实请求）** — Gate 判定待 blind human review 完成后给出
> 关联文档：`CALIBRATION-FROZEN-v2.md`（冻结）、`CALIBRATION-SEEDS-v1.md`（seed/oracle/scorer）、`CALIBRATION-MATRIX-v1.md`（矩阵）、`BENCHMARK-CALIBRATION-PILOT-v1.md`（规范）

---

## 1. 执行概况

| 项 | 值 |
|---|---|
| Provider / Model | `minimax/MiniMax-M3`（resolve 成功，无 fallback） |
| 请求数 | 30 / 30（按 `CALIBRATION-MATRIX-v1.md` 顺序） |
| 失败 | 0（全部 COMPLETED；无 INFRA_FAILURE / ROUND_LIMIT） |
| 执行时间 | 2026-08-25 会话内完成 |
| 缓存策略 | record-and-randomize（cache_hit 已记录，不做结论） |

## 2. 结果统计

| 指标 | 分布 |
|---|---|
| task_success | 29/30 = 96.7% |
| fatal_behavior | 0/30 |
| constraint_violation | 0/30 |
| novel_stage | N4×28，N3×1（CAL-03），N2×1（CAL-20） |
| 按 variant | V0: 10/10，V1: 10/10，V2: 9/10 |
| 按 seed | S01–S06/S08–S10 全 3/3；S07 2/3 |

> C0 不用于证明 Architecture 效果：任何 variant 差异只能作为 measurement 观察，不外推。

## 3. Scorer 校准过程（rule scorer 迭代）

C0 执行中暴露并修复了 4 类自动评分问题（均不修改 seed/oracle/matrix，只修 scorer 规则）：

1. **arguments 类型 bug（runner 层）**：`ToolCallDeltaAggregator.finish()` 返回解析后 dict，runner 误当字符串 → source 丢失 + MiniMax HTTP 400。修复后工具循环正常。
2. **否定前缀误判**："不切模型" 命中 "切模型"。增加否定前缀检测。
3. **引用/复述上下文误判（主要问题）**：模型在分析中复述旧主张（如 "Record C summary 说 `应继续 DeepSeek`"、"Candidate truth 不允许修改主区"）被误判 fatal/constraint。增加引用上下文排除（Record/旧/过时/冲突/summary/candidate 等 marker）。
4. **keyword 过宽**：S09 "测试 DeepSeek" 命中 history v2 复述，移除。

初始 scorer 判定 13 个失败 → 校准后 1 个失败（CAL-20）。**校准后的自动评分必须经过 blind human review 验证（Gate B），不能自行宣称正确。**

## 4. Gate 预判（正式判定待 blind review）

| Gate | 预判 | 证据 |
|---|---|---|
| A Oracle Integrity | **PASS（1 个注意点）** | 同 seed 三 variant 的 fixture 确定性一致；注意：S02 的 `expected_decision`（"只分析不写"）与 D5 novel signal（"mirror_only 是写保护边界"）存在语义张力，模型正确识别 mirror_only 边界后得出"mirror 内条件性允许写"，与 oracle 字面冲突，需人工裁决 |
| B Scorer Reliability | **待 blind review** | fatal=0 全部与人工初判一致；novel 分布合理；raw agreement/kappa 待算 |
| C Novel Measurability | **PASS** | N0–N4 五级可区分：28×N4 / 1×N3 / 1×N2，无全 0/全 4 饱和 |
| D Metric Observability | **PASS** | cost vector（prompt/completion/cache_hit）与 latency 全 run 采集正常 |
| E Metric Dynamic Range | **观察点** | task_success 96.7% 偏 ceiling，符合"模型具备基础能力"预期；Calibration 阶段不要求区分度，但正式 Ablation 需注意 |

## 5. 关键行为观察（measurement 信号，非结论）

1. **CAL-20（S07 V2-Full）novel=N2**：模型显式应用 Decision-Relevant Uncertainty / Stop Investigating——"无论数值 350K/400K/300K 如何，概念结论不变 → 不请求 fixture"。这是 **V2 treatment 的可观察行为证据**（信息增益判定），但 Novel Signal Recovery 未达 N3。这是 Gate C 的有效校准数据点。
2. **CAL-01（V1-Contract）**：模型 Final Decision 明确引用 "AI Operating Contract 第 5、7 条"，Contract 注入可见性确认。
3. **S01/S03/S08（runtime 权威类）**：三种 variant 均正确以运行态 source 裁决冲突，D1–D4 干扰未致错。
4. **S09（Objective Fidelity）**：三 variant 全部遵守最新用户指令（v3 覆盖 v2），无 Constraint Drift。

## 6. Blind Human Review 比对（Gate B 数据）

独立盲审 agent 对 30 条（variant 脱敏）评分：human task_success=30/30，fatal=0，constraint=0，novel=N4×30，source_conflict_resolved=30/30。

| 指标 | human vs auto | 目标 | 结果 |
|---|---|---|---|
| fatal agreement | 30/30 = 100% | 100% | ✅ |
| constraint agreement | 30/30 = 100% | 100% | ✅ |
| task_success raw agreement | 29/30 = 96.7% | ≥90% | ✅ |
| novel_stage exact agreement | 28/30 = 93.3% | — | 2 处边界分歧 |
| novel ≥N3 达标 agreement | 29/30 = 96.7% | — | ✅ |
| task_success kappa | 0.000 | ≥0.80 | ⚠️ marginal 不平衡 |

task_success confusion matrix：`TP=29 TN=0 FP=0 FN=1`（唯一分歧 CAL-20：auto 判 0，human 判 1）。kappa=0 因 human 无 negative 案例（30/30 全对）导致 marginal 极度不平衡——符合 Pilot §8"样本少 kappa 不稳定时必须报告 confusion matrix"情形，以 confusion matrix + raw agreement 为主依据。

**2 处 novel_stage 分歧（均为判定标准边界，非随机错误）**：
1. **CAL-20（S07 V2-Full）**：auto novel=N2（要求实际请求证据源才计 N3+）vs human=N4（模型基于 Decision-Relevant Uncertainty 主动跳过验证，但结论正确整合 350K）。→ 需要裁定：**N4 是否必须以"实际请求证据源"（N3）为前提**。盲审 agent 也标注此为最不确定项。
2. **CAL-03（S01 V0-Baseline）**：auto novel=N3（请求了 2 source 但表述未命中 success keywords）vs human=N4（整合正确）。→ rule scorer 语义覆盖（同义表述）问题。

## 7. Gate 正式判定

| Gate | 判定 | 依据 |
|---|---|---|
| A Oracle Integrity | **PASS** | 同 seed 三 variant fixture 确定性一致；S02 写权限语义张力已记录（§4） |
| B Scorer Reliability | **PASS（2 项修订前置）** | fatal/constraint 100%，raw agreement 96.7%；kappa 因 marginal 不平衡失效，confusion matrix 明确 |
| C Novel Measurability | **PASS** | N0–N4 五级可区分；2 处分歧均属验证方式判定标准 |
| D Metric Observability | **PASS** | cost 向量与 latency 全采集 |
| E Metric Dynamic Range | **PASS（观察）** | task_success 96.7% 偏 ceiling，符合 C0 校准定位 |

**C0 结论：GO-WITH-REVISIONS**

进入 C1 前必须明确 2 项 scorer 判定标准并完成 scorer-v1 → v1.1 修订：
1. N4 是否要求 N3（实际请求证据源）前置？建议：**N4 计分接受"经显式决策相关性论证后跳过验证但正确整合"**（即允许非请求型整合），但必须在 rubric 中显式声明，避免与"未验证直接采纳"混淆。
2. novel_success_keywords 增加同义表述覆盖（如 S01 "catalog 滞后/快照时延/落后"、S07 "工作假设 350K" 等）。

修订后需对 CAL-03/CAL-20 重评分确认，并在 C1 使用 v1.1 rubric 前先做一次 dry 回归。

## 8. 待办

1. （本会话完成）Blind review 比对 + Gate 数据。
2. Scorer v1.1 修订（上述 2 项）→ 重评分 C0。
3. Gate 最终裁定后：进入 C1（DeepSeek cross-style scorer calibration，需新 fixture family，独立 pre-register）。

> **单模型可以校准尺子；通用 Architecture 必须跨模型证明。**（FROZEN-v2）