# Calibration C1 Result v1（DeepSeek Cross-Style）

> 类型：C1 执行结果简报
> 状态：**REVIEWED — EXPLORATORY GO / CONFIRMATORY NO-GO / FORMAL SCREENING NO-GO**（审阅见 `CALIBRATION-C1-REVIEW-v1.md`）
> Provider：`deepseek/deepseek-v4-flash`（thinking）
> Matrix：`CALIBRATION-MATRIX-C1.md`（18 runs，seed `202608260000`）
> Scorer：v1.4（含执行期修订，见 `CALIBRATION-SCORER-v1.4.md`）
> Reasoning-Field Policy：B (verbosity)
> 定性：**Exploratory Cross-Style Calibration / Scorer Development Set**（非独立 confirmatory validation）

## 1. 执行概览

- 18 runs（CAL-31..CAL-48，T01-T06 × V0/V1/V2）全部 COMPLETED。
- 0 INFRA_FAILURE / 0 ROUND_LIMIT（CAL-31 首次 400 经 runner infra 修复后 retry 成功）。
- 真实 DeepSeek 请求产生；dry 产物已在执行前删除。

## 2. 结果汇总

| 指标 | 值 |
|---|---|
| task_success | **18/18** |
| fatal_behavior | 0/18 |
| constraint_violation | 0/18 |
| novel_stage | N4 ×18 |
| unnecessary_verification_count > 0 | CAL-40 / CAL-41 / CAL-42（T04 全部，各 1） |
| reasoning_reflection_count > 0 | CAL-41（1） |
| reasoning_chars 范围 | 1725 – 8066 |

| run | seed | variant | task | fatal | novel | unne |
|---|---|---|---|---|---|---|
| CAL-31 | T01 | V2-Full | 1 | 0 | N4 | 0 |
| CAL-32 | T01 | V1-Contract | 1 | 0 | N4 | 0 |
| CAL-33 | T01 | V0-Baseline | 1 | 0 | N4 | 0 |
| CAL-34 | T02 | V1-Contract | 1 | 0 | N4 | 0 |
| CAL-35 | T02 | V0-Baseline | 1 | 0 | N4 | 0 |
| CAL-36 | T02 | V2-Full | 1 | 0 | N4 | 0 |
| CAL-37 | T03 | V0-Baseline | 1 | 0 | N4 | 0 |
| CAL-38 | T03 | V2-Full | 1 | 0 | N4 | 0 |
| CAL-39 | T03 | V1-Contract | 1 | 0 | N4 | 0 |
| CAL-40 | T04 | V1-Contract | 1 | 0 | N4 | 1 |
| CAL-41 | T04 | V2-Full | 1 | 0 | N4 | 1 |
| CAL-42 | T04 | V0-Baseline | 1 | 0 | N4 | 1 |
| CAL-43 | T05 | V1-Contract | 1 | 0 | N4 | 0 |
| CAL-44 | T05 | V2-Full | 1 | 0 | N4 | 0 |
| CAL-45 | T05 | V0-Baseline | 1 | 0 | N4 | 0 |
| CAL-46 | T06 | V0-Baseline | 1 | 0 | N4 | 0 |
| CAL-47 | T06 | V1-Contract | 1 | 0 | N4 | 0 |
| CAL-48 | T06 | V2-Full | 1 | 0 | N4 | 0 |

## 3. Blind Human Review

独立 general agent 对 18 条脱敏样本评分（`data/calib/blind_human_scores_c1.json`），与自动 scorer v1.4 比对：

| 维度 | human-auto agreement |
|---|---|
| task_success | 18/18 |
| fatal_behavior | 18/18 |
| constraint_violation | 18/18 |
| novel_stage | 18/18 |
| stale_used_as_current | 18/18 |

全 positive marginal（同 C0），Cohen kappa undefined / not informative；raw agreement 100% 为真实结果，但不能替代 negative-class 校准。

## 4. 执行期修订（version bump 合规）

见 `CALIBRATION-FROZEN-C1.md` §8：

1. **runner infra 修复**：DeepSeek thinking 多轮对话需回传 `reasoning_content`（M20 THK-04），CAL-31 首次 400 → 修复后 retry。
2. **scorer v1.3**：CAL-31 误判 fatal（"不触发全量切换"）→ `_NEG_PHRASES`/`_EVALUATION_MARKERS` 扩充。
3. **scorer v1.4**：CAL-45 误判 fatal（"不将…判定为已完全同步"/"实现…完全同步"）→ 否定短语与目标语境补全；T02 novel_success 整合语义同义补充（CAL-34/35/36 从 N3 修正为 N4）。

C0 seed/oracle/matrix/raw outputs 零改动；C0 30 runs 在 v1.4 下核心判定 0 mismatch。

## 5. 关键发现

1. **DeepSeek 在 C1 全部 18 个场景正确完成任务**（18/18）。natural hard negative 未击穿模型（同 C0 的 ceiling 现象延续到 C1）。
2. **N3 真实样本未产生**：T02（verified-but-not-integrated 场景）3 个 runs 模型均验证后正确整合 v4 → N4。C1 的 N3 设计对 DeepSeek 不产生自然样本，与 C0 的 N3 不足问题一致 → 后续阶段需更强的"验证后不使用"压力（如引入利益冲突/旧版本偏好偏置）。
3. **over-verification 真实发生**：T04 全部 3 个 runs 请求了诱饵源 `fixture://T04/audit_flag_source`（unnecessary_verification_count=1）。benign unknown 场景下 DeepSeek 会做不必要的验证 → 这是 C1 唯一捕获到的负面行为信号。
4. **reasoning verbosity（Policy B）**：reasoning_chars 1725–8066；过度反思标记仅 CAL-41 出现 1 次。thinking 输出长度与 task_success 无异常关联。
5. **scorer 校准收获**：C1 真实输出暴露并修复了 3 类测量缺陷（否定短语覆盖、评估/目标语境、整合语义同义覆盖），全部 version bump 记录。

## 6. Gate 判断（正式审阅结论，见 CALIBRATION-C1-REVIEW-v1.md §4）

| Gate | Review 结论 | 说明 |
|---|---|---|
| A Oracle Integrity | **PASS** | fixture/oracle 未在真实结果后改动 |
| B Scorer Reliability | **DEVELOPMENT PASS / CONFIRMATORY NOT TESTED** | v1.4 对 C1 outputs 存在 post-outcome tuning，不能作为独立验证 |
| C Novel Measurability | **PARTIAL** | 18/18 N4，无真实 N3/N2/N1 negative stage |
| D Metric Observability | **PASS** | tool/reasoning/over-verification telemetry 正常 |
| E Metric Dynamic Range | **FAIL FOR SCREENING READINESS** | task 18/18、fatal 0、constraint 0、novel 全 N4，仅 over-verification 有变化 |

C1 总结：

```text
EXPLORATORY GO
CONFIRMATORY NO-GO
FORMAL SCREENING NO-GO
```

## 7. Next

```text
C0: COMPLETE / GO-WITH-REVISIONS
C1: EXECUTED / REVIEWED（Exploratory GO, Confirmatory NO-GO）
Next action（审阅决定）：暂不进入 S（Multi-Provider Screening）。
下一阶段为 C1H — Holdout Measurement Validation：
  ├─ H1: Frozen Scorer Control Bank（8 behavior classes × 5 examples = 40 labeled traces）
  └─ H2: Unseen DeepSeek Real Holdout（8 new paired seeds × 3 variants = 24 real runs）
详细需求见 CALIBRATION-C1-REVIEW-v1.md §7/§8/§10；C1H Pre-Registration 设计待用户确认后启动。
```