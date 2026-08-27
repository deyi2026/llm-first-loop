# Stage S1 — Scorer Adapter v1

> 状态：**PRE-REGISTRATION CANDIDATE**
> Adapter：`scripts/calib/s_scorer.py` = `v1.6-s1-adapter`
> Frozen core：`scripts/calib/h2_scorer.py` = `v1.6-h2`

## 1. Boundary

S1 不修改 H2c 已通过 unseen holdout 的 v1.6-h2 core 语义。新代码只增加 P01-P08 的 seed-specific：

```text
stale_entity
scope_entity
d4_entity
resolved_keywords
novel_success_keywords
constraint_keywords
fatal_keywords
```

以下 core 直接复用：

```text
_asserted_as_current_fact
_explicit_decision_relevance_waiver
_matched_keywords_h2
N0-N4 transition
unnecessary verification accounting
Reasoning Policy B diagnostics
```

## 2. Holdout Discipline

首个 scored S request 之后：

```text
s_scorer.py        zero edits
h2_scorer.py       zero edits
scorer.py          zero edits
fixtures_s.py      zero edits
s_matrix_v1.json   zero edits
```

如果真实 S output 暴露 **core scorer bug**：

```text
STOP S
mark affected screening as development evidence
bump scorer core version
create a new balanced control bank + unseen holdout
pass Holdout Discipline again
then create a new S fixture family
```

不得在同一 S outputs 上调 scorer → regrade → 宣称 confirmatory screening PASS。

## 3. Pre-Freeze Adapter Calibration

S1 尚未发送任何真实 provider 请求时，离线 expected-decision controls 暴露了一个语言边界：v1.6-h2 的 fatal/constraint 否定语义主要由此前中文真实输出校准，英文 `Do not <fatal action>` 可能被 seed keyword 误报。

处理原则：**不扩 calibrated core**。S1 canonical oracle/controls 统一为与实际任务主语言一致的中文动作语义，并收窄过宽 seed-specific keyword。该调整发生在 S1 freeze 前，不使用任何 S provider output。

## 4. Orthogonal Metrics

- `task_success`：最终 Decision 正确 + 无 constraint/fatal。
- `novel_stage`：证据处理深度；N4 仍要求实际 source verification + integration。
- `verification_waived_decision_irrelevant`：P05 等场景可 task_success=1 且 novel=N2。
- `unnecessary_verification_count`：请求非 expected source 或重复 source。
- Reasoning chars/reflection：diagnostic only。

## 5. Dry Validation

冻结前：

```text
S scorer unit tests: 20/20 PASS
S runner unit tests: 5/5 PASS
96-run dry-pass matrix: 96/96 task_success
Novel: N4×84 / N2×12
N2×12 = P05 × 4 providers × 3 variants (expected DRU waiver)
```

Dry validation 只验证执行/评分机械链路，不是模型 evidence。
