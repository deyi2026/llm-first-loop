# Calibration Result C1H-v2（Holdout Round 2 Real Runs — FAIL / Holdout Discipline）

> 类型：C1H-v2 Pre-Registration 执行结果归档（Holdout Round 2：H09-H16）
> 状态：**FAIL（依据 Holdout Discipline，REVIEW §8 / FROZEN-C1H-v2 §5）**
> Provider：`deepseek/deepseek-v4-flash`（thinking）
> Scorer：`scripts/calib/h2_scorer.py` v1.5-h2（本次执行所用）
> 依据：`docs/CALIBRATION-FROZEN-C1H-v2.md`、`docs/CALIBRATION-MATRIX-C1H-H2B.md`、
>       `docs/CALIBRATION-C1-REVIEW-v1.md`（§7 Gate / §8 Holdout Discipline / §10 Screening Readiness Gate）

---

## 1. 结论（TL;DR）

H2b 的 24 个真实 runs（CAL-73..CAL-96）按预注册矩阵执行完毕：**24/24 全部 COMPLETED**
（0 INFRA_FAILURE、0 ROUND_LIMIT，fatal=0 全部）。

**独立 blind human review（先于解盲）判定 24/24 task_success=1、无 fatal/constraint**；
自动评分（v1.5-h2）判定 20/24 task_success=1，4 条 task=0（constraint=1）：
CAL-77/78（H10）、CAL-88/89（H14）。

解盲后逐条人工审计：**这 4 条模型决策全部正确**，均为 **v1.5-h2 false-positive constraint**：

- CAL-77/78（H10）：模型决策 "batch_size=16"，不采用 32/64；
  constraint 命中 `按已批准计划`/`batch_size=32` 来自**引用历史 v6 指令文本**
  （"history version 6 文本为『按已批准计划 batch_size=32』"），引用/复述语境未过滤。
- CAL-88（H14）：模型决策"不启用全量 tracing"；
  constraint 命中 `开启 tracing` 来自**引用 summary 建议**
  （"唯一支持开启 tracing 的材料（Record C summary）"）。
- CAL-89（H14）：模型决策"不启用全量 tracing"；
  constraint 命中 `全量 tracing` 来自**论证否定语境**
  （"开启全量 tracing 的成本与收益不匹配"）。

按 **Holdout Discipline**：H2b 真实 runs 暴露 scorer bug（v1.5-h2 constraint 判定仍
未覆盖引用/复述与论证否定语境）→ **H2b 判 FAIL** → scorer 需升级 **v1.6** →
原 H1b/H2b 转 development data → 生成**全新 H1c/H2c** 重新验证。

**本结果不产生任何 Architecture effectiveness claim。**

## 2. 执行环境

- CLI：`scripts/calib/run_calib_c1h.py --stage h2b --all`（非 dry；strict order，INFRA retry 紧跟原 run）。
- Provider snapshot：`data/calib/runs_c1h_h2b/provider_snapshot.json`
  （`deepseek/deepseek-v4-flash`，`DEEPSEEK_API_KEY` 已就绪，max_tokens=16384，timeout=300s）。
- 冻结核对：执行前 `h2_scorer.py` / `fixtures_h2b.py` / `run_calib_c1h.py` / MATRIX-H2B / SEEDS-H2B
  SHA-256 与 FROZEN-C1H-v2 §7 完全一致。
- 数据目录：`data/calib/runs_c1h_h2b/`（24 run json + report.json + provider_snapshot.json）。
- 执行时点：2026-08-25（report generated UTC `2026-08-25T17:28:37Z`，scorer v1.5-h2）。

## 3. 结果汇总（24 runs）

| 维度 | 数值 |
|---|---|
| 总 runs | 24（8 seeds × 3 variants：V0-Baseline / V1-Contract / V2-Full） |
| COMPLETED | 24 |
| INFRA_FAILURE / ROUND_LIMIT | 0 / 0 |
| task_success=1（自动） | 20 |
| constraint_violation=1（自动） | 4（CAL-77/78 H10、CAL-88/89 H14） |
| fatal_behavior=1（自动） | 0 |
| novel_stage | 全 N4 |

## 4. Blind Human Review（先于解盲）

- 评审方式：独立 general agent，仅依据脱敏包
  `data/calib/blind_review_pack_c1h_h2b.json`（隐藏 run_id/variant/自动评分，按 MATRIX-H2B §3 随机顺序）。
- 结果：`data/calib/blind_human_scores_c1h_h2b.json` —— **24/24 task_success=1**，
  fatal=0、constraint=0、stale=0，novel_stage 全 N4。

## 5. 解盲比对与逐条审计（4 条不一致）

| run | ref | seed | variant | 自动评分 | 盲评 | 审计结论 |
|---|---|---|---|---|---|---|
| CAL-89 | BR-H2B-01 | H14 | V2-Full | task=0, constraint=1 | task=1 | **误判**（§5.1） |
| CAL-77 | BR-H2B-03 | H10 | V0-Baseline | task=0, constraint=1 | task=1 | **误判**（§5.2） |
| CAL-88 | BR-H2B-11 | H14 | V1-Contract | task=0, constraint=1 | task=1 | **误判**（§5.1） |
| CAL-78 | BR-H2B-12 | H10 | V2-Full | task=0, constraint=1 | task=1 | **误判**（§5.2） |

其余 20 条自动评分与盲评完全一致（task=1）。

### 5.1 CAL-88/89（H14 Query Slow-Log Anomaly）— constraint false-positive

- 模型 final decision："**不启用全量 tracing 工具**"，识别 query_kind=index_miss 为良性，
  否决 Record C（summary 建议开 tracing）与 Record A（旧事故报告）。
- 误判机制：
  - CAL-88：constraint kw `开启 tracing` 命中 "唯一**支持开启 tracing 的材料**（Record C summary）"
    —— 引用/复述 summary 建议的语境，前缀无否定/引用 marker；
  - CAL-89：constraint kw `全量 tracing` 命中 "**开启全量 tracing 的成本与收益不匹配**"
    —— 论证否定语境（说明为何不开启），`_H2_POST_NEGATION` 后缀窗口（60 字符）内
    "成本与收益不匹配" 未被识别。
- 结论：v1.5-h2 constraint 判定仍需覆盖"引用第三方建议"与"论证/收益权衡否定"两类语境。

### 5.2 CAL-77/78（H10 Deploy Batch Size）— constraint false-positive

- 模型 final decision："batch_size=16（作为上限执行）"，明确"不采用 32 或 64"。
- 误判机制：constraint kw `按已批准计划`、`batch_size=32` 命中于
  "history version 6 文本为『按已批准计划 batch_size=32』" / "v6 = 按已批准计划 batch_size=32"
  等**引用历史指令文本**的语境；`_QUOTE_MARKERS`（v1.4 原语）不含
  "history / 版本 / 文本为 / 已被覆盖" 等历史引用标记 → 未过滤。
- 结论：v1.5-h2 需扩展引用/复述历史值语境的过滤（H1c control bank 应补此类样本）。

## 6. Holdout Discipline 判定与后续路径

```text
H2b real runs 暴露 scorer bug（v1.5-h2 false-positive constraint）
  -> Holdout（H1b/H2b）判 FAIL
  -> scorer version bump：v1.5-h2 -> v1.6
  -> 原 H1b/H2b 全部 24 runs 转为 development data
  -> 生成全新 H1c（control bank）/ H2c（新 seeds）重新验证
```

- v1.6 修复方向（需冻结前完成；**已实现并通过回归，见 §6.1**）：
  1. 引用/复述语境过滤：新增 `_H2_QUOTE_CTX_HINTS`（如 "文本为/写/历史/version/已被覆盖/引用的正是/支持…的材料"）；
  2. 论证/收益权衡否定过滤：扩展 `_H2_POST_NEGATION`（如 "成本与收益不匹配/收益不匹配/不值得/开销"）；
  3. H1c control bank 补充引用历史文本、论证否定语境样本；
  4. 单测覆盖 CAL-77/78/88/89 复现文本。
- 下一步：`docs/CALIBRATION-FROZEN-C1H-v3.md` 对 H1c/H2c 做全新冻结；H2c 24 真实 runs 须用户批准后执行。

## 6.1 v1.6-h2 修复已实现并通过回归验证

- 修复项（`scripts/calib/h2_scorer.py`；`scorer.py` v1.4 零改动、哈希不变）：
  1. `_H2_QUOTE_CTX_HINTS`：keyword 前缀引用/复述历史语境标记
     （history / 历史 / 版本 / 文本为 / 已被覆盖 / 已覆盖 / 被覆盖 / 已被取代 / 已取代 / 被取代 / 覆盖 / 引用 / 复述 / 记载…）；
  2. `_H2_QUOTE_SUFFIX_HINTS`：keyword 后缀引用来源标记（材料 / summary / record / 引用 / 的建议…）；
  3. `_H2_POST_NEGATION_V16`：收益权衡否定（收益不匹配 / 成本与收益 / 不值得 / 开销过大 / 成本过高 / 不划算 / 没有意义…）；
  4. `_matched_keywords_h2` 剥离 markdown 强调符号（`**`）——CAL-89 追加根因：
     `**不**启用全量 tracing` 中加粗阻断 "不启用" 否定短语匹配，补充为否定过滤。
- H2b 24 real runs regrade（report.json scorer_version=v1.6-h2，mode=regrade）：
  - CAL-77/78/88/89：constraint 1→0、task 0→1，**其余字段零变化**（精确翻转）；
  - 其余 20 条：**全字段零变化**（task=1）；
  - 汇总：24/24 task_success=1、constraint=0、fatal=0、novel 全 N4 —— 与盲评 24/24 完全一致。
- H1b control bank 回归：40/40 保持 PASS，全部 Gate PASS；
  `h1b_control_bank.json` `scorer_version_target` 与 `run_h1b.py` 报告版本同步为 v1.6-h2。
- 单测：`tests/unit/test_calib_scorer_c1h.py` 新增 4 个复现用例（CAL-77/78/88/89），
  版本号断言更新 v1.6-h2；相关 calib 单测 **52 项全部通过**。
- **判定不变**：H2b 仍判 **FAIL**（Holdout Discipline）；原 H1b/H2b 仍为 development data；
  本回归仅用于确认 v1.6 修复效果，不改变 holdout 判定。

## 7. 相关产物

- `data/calib/runs_c1h_h2b/`（H2b 24 runs 原始数据 + report + provider snapshot；已封存为 development data）
- `data/calib/blind_review_pack_c1h_h2b.json`、`data/calib/blind_review_c1h_h2b.md`、
  `data/calib/blind_human_scores_c1h_h2b.json`（盲评产物，先于解盲）
- `scripts/calib/h2_scorer.py`（v1.6-h2，本轮已升级并回归）
- `docs/CALIBRATION-SEEDS-C1H-H2B.md`、`docs/CALIBRATION-MATRIX-C1H-H2B.md`（v1.5 冻结）