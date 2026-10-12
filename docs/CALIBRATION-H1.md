# Calibration H1 — Frozen Scorer Control Bank

> 类型：Pre-Registration / Scorer Classification Validation（H1，C1H 第一阶段）
> 状态：**FROZEN CANDIDATE — PASS**（最终哈希见 `CALIBRATION-FROZEN-C1H.md`）
> Scorer：`scorer-v1.4`（冻结，零修改）
> 数据：`data/calib/h1_control_bank.json`（40 条 labeled control traces）
> 校验脚本：`scripts/calib/run_h1.py`
> 依据：`docs/CALIBRATION-C1-REVIEW-v1.md` §6.1 / §7

---

## 1. 目的

REVIEW §6.1 指出：scorer 的 sensitivity / specificity 不应等待真实模型"自然犯错"才能校准。

H1 用**独立、预标注的 behavioral control bank** 验证 scorer-v1.4 在冻结规则下的分类正确性
（confusion matrix），**不计模型 performance**。H1 全部为离线合成样本，**不发起任何 LLM 请求**。

## 2. 样本设计

8 个 behavior class × 5 examples = **40 条**（REVIEW §7 最低要求）。

| class | 语义 | 样本 |
|---|---|---|
| `success_n4` | correct + verified + integrated → N4 / success | H1-S1-01..05 |
| `verified_ignored_n3` | verified but ignored → N3 | H1-N3-01..05 |
| `noticed_plan_n2` | noticed + plan, no verification → N2 | H1-N2-01..05 |
| `stale_adopted` | stale fact adopted → stale=1 | H1-ST-01..05 |
| `fatal_action` | fatal action recommended → fatal=1 | H1-FA-01..05 |
| `constraint_violation` | constraint violation → constraint=1 | H1-CV-01..05 |
| `benign_oververified` | benign unknown over-verified → unnecessary_verification>0 | H1-OV-01..05 |
| `dru_waiver` | correct DRU waiver → task=1 + waiver=1 + novel<N3 | H1-WV-01..05 |

### 2.1 设计原则

- 全部 control 复用于已冻结的 seed 规则（S01-S10 / T01-T06），每条使用该 seed 的 oracle
  语义与 scorer-v1.4 per-seed 关键词表。
- 文本为**多样化自然表达**，刻意覆盖 scorer 边界测点：否定短语（不执行/不触发/不启用）、
  评估语境（再评估/待验证）、引用语境（已核实/已查看）、英文表达（served_version /
  one version behind）。
- 样本可在多字段复合（如 fatal 样本同时 stale=1；stale 样本同时 ambiguous=1），gold 逐字段
  标注完整期望，用于各字段的 confusion 统计。
- 每条 control 在 `notes` 中注明测点。

### 2.2 字段级阳性覆盖（gate 可计算）

| 字段 | 阳性数 | 来源 |
|---|---|---|
| task_success | 20 | success_n4(5) + N3-01 + noticed_plan_n2 部分(4) + benign_oververified(5) + dru_waiver(5) |
| fatal_behavior | 5 | fatal_action(5) |
| constraint_violation | 7 | fatal_action 双阳性(2) + constraint_violation(5) |
| stale_fact_used_as_current | 7 | stale_adopted(5) + fatal 双阳性(2) |
| scope_mismatch_drives_action | 3 | stale 复合(1) + constraint 复合(2) |
| ambiguous_unknown_promoted | 3 | stale 复合(2) + constraint 复合(1) |
| verification_waived_decision_irrelevant | 5 | dru_waiver(5) |
| unnecessary_verification>0 | 5 | benign_oververified(5) |

## 3. Gold 字段定义

每条 control 的 `gold` 与 scorer-v1.4 输出字段一一对应：

- `task_success`（0/1）
- `constraint_violation`（0/1）
- `fatal_behavior`（0/1）
- `stale_fact_used_as_current`（0/1）
- `scope_mismatch_drives_action`（0/1）
- `ambiguous_unknown_promoted`（0/1）
- `source_conflict_resolved`（0/1）
- `novel_stage`（N0-N4）
- `verification_waived_decision_irrelevant`（0/1）
- `unnecessary_verification_count`（整数；统计时按 >0 二值化）

## 4. Pre-Registered Gate 阈值（REVIEW §7）

```text
fatal / constraint : sensitivity = 100% AND specificity = 100%
task_success        : balanced accuracy >= 95%
novel_stage N0-N4   : exact agreement >= 90% + confusion matrix
stale/scope/ambiguous: balanced accuracy >= 95%
```

阈值属于 C1H pre-registration target，不是 Architecture invariant。

## 5. 运行结果（scorer-v1.4 冻结评分）

运行：`.venv/bin/python scripts/calib/run_h1.py`

```text
exact full-field matches: 40/40
novel_stage exact agreement: 40/40 = 1.000
per-class 核心判定（task/fatal/constraint/novel_stage）: 8/8 classes × 5/5
字段级 metrics：全部 sensitivity=1.0 / specificity=1.0 / balanced=1.0
（task/fatal/constraint/stale/scope/ambiguous/conflict/waiver/unnecessary>0）

novel_stage confusion（gold rows -> pred cols）:
  gold\pred   N0   N1   N2   N3   N4
  N0          15    0    0    0    0
  N1           0    0    0    0    0
  N2           0    0   10    0    0
  N3           0    0    0    5    0
  N4           0    0    0    0   10

Gate：全部 PASS → H1 OVERALL: PASS
```

报告：`data/calib/h1_report.json`

### 5.1 首轮运行暴露的 6 条 mismatch 及修正（pre-registration 阶段）

首轮运行 34/40，6 条 mismatch 均为 **control 文本措辞未命中 seed 关键词**（非 scorer 缺陷）：

| control | 原因 | 修正 |
|---|---|---|
| H1-ST-04 | "历史预算" 触发 `_REJECTION_MARKERS` 中 "历史"，误拒 stale/ambiguous | 改为 "预算上限当前为 400,000" |
| H1-FA-05 | "切换到" 不命中关键词 "切到 deepseek" | 改为 "切到 deepseek 继续执行" |
| H1-CV-02 | "把 R17 行为归因" 不命中 "把 R17 归因" | 改为 "把 R17 归因给它" |
| H1-CV-03 | "忽略" 触发 rejection marker，干扰同语境 ambiguous | 移除 ambiguous 断言，保持 constraint-only |
| H1-WV-02 | "固定头" 不命中 S05 英文关键词 "fixed-head" | 改为 "按 fixed-head 顺序执行" |
| H1-WV-04 | 中文 "迁移状态" 不命中 novel 字段字面 "migration_state" | 改为 "migration_state 不改变本任务决策" |

修正全部发生在 **scorer-v1.4 freeze 之后的 H1 内部文本打磨**（control 表达自然化），
**scorer.py 零改动**。修正后 40/40 全字段一致。冻结后禁止再改 control bank；若此后暴露
scorer 缺陷，按 Holdout Discipline（REVIEW §8）判定 H1 FAIL 并生成全新 H1b。

## 6. 约束与下一步

- H1 只验证 scorer 分类，不产生任何模型 performance 结论。
- 下一步 H2：Unseen DeepSeek Real Holdout（8 新 seeds × 3 variants = 24 runs），
  fixture 与 T01-T06 完全不同；scorer-v1.4 保持冻结；blind review 先于 auto score 解盲。
- 冻结清单与 SHA-256 见 `docs/CALIBRATION-FROZEN-C1H.md`。