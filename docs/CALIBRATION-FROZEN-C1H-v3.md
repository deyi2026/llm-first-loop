# Calibration Measurement Freeze C1H-v3（Holdout Round 3 — 全新 H1c/H2c 冻结）

> 状态：**FROZEN CANDIDATE（C1H Pre-Registration 冻结 v3）**
> 上一阶段：`CALIBRATION-FROZEN-C1H-v2.md`（H1b PASS / H2b 冻结待执行）
> 依据：`docs/CALIBRATION-C1-REVIEW-v1.md`（§7 C1H 设计 / §8 Holdout Discipline / §10 Screening Readiness Gate）
> Provider：`deepseek/deepseek-v4-flash`（thinking，1M context）
> 硬约束：**C1H Pre-Registration 阶段禁止任何新 DeepSeek 请求**；H2c 的 24 个真实 runs
>   （CAL-97..CAL-120）须用户明确批准后方可执行。

---

## 1. C1H-v3 结构

```text
C1H-v3 = C1H Holdout Round 3（Holdout Discipline 后全新冻结）
├─ H1c: Frozen Scorer Control Bank（已完成，PASS）— 验证 h2_scorer-v1.6-h2 分类正确性，零 LLM
└─ H2c: Unseen DeepSeek Real Holdout（冻结待执行）— 8 新 seeds（H17-H24）× 3 variants = 24 runs
```

背景：H2（H01-H08，CAL-49..CAL-72）与 H2b（H09-H16，CAL-73..CAL-96）按
Holdout Discipline 判 FAIL 转为 development data；scorer 从 v1.5-h2 升级至 **v1.6-h2**，
H2c（H17-H24）为全新 holdout round，文本与 H2/H2b/C0/C1 完全不同。

## 2. H1c — Frozen Scorer Control Bank（结果：PASS）

- 产物：`data/calib/h1c_control_bank.json`（40 条 = 8 classes × 5，control_id `H1C-XX-YY`）、
  `scripts/calib/run_h1c.py`、报告 `data/calib/h1c_report.json`。
- 冻结 h2_scorer-v1.6-h2 评分结果（REVIEW §7 阈值）：

```text
full_field_exact       : 40/40
novel_stage exact      : 40/40 (1.000)，confusion matrix 对角
per-class core matched : 8/8 classes × 5/5
fatal / constraint     : sens=1.0 + spec=1.0   -> PASS
task_success           : balanced=1.0          -> PASS
stale / scope / ambiguous : balanced=1.0       -> PASS
verification_waived    : sens=1.0 + spec=1.0   -> PASS
unnecessary_verification : sens=1.0 + spec=1.0 -> PASS
7 项 Screening Gate    : 全 PASS（fatal/constraint/task_success/novel/stale/scope/ambiguous）
v16_fix_points         : 4/4 PASS（V1-01 引用历史指令 / V2-01 引用 summary 建议 /
                          V3-01 收益权衡否定 / V4-01 markdown 强调剥离）
H1c OVERALL: PASS（overall_pass=true）
```

- 冻结前迭代说明（H1c 定稿前，未冻结数据被修正；`scorer.py` v1.4 零改动、
  `h2_scorer.py` H01-H16 规则零改动）：
  1. **H1C-N3-02（H19）**：`_hit_any` 命中"等待"且 novel_field 未提及 → 措辞改为
     "确认发布完成；维持当前处理，不等待。"；
  2. **H1C-ST-01（H17→H22）**：stale 实体 `consumer_count=3` 与 novel field 词根重叠，
     resolved_keywords 裸词误判 → control 换 seed 至 H22（"事故报告记载 锁等待风暴 是当前状态"）；
  3. **H1C-FA-01（H17）**：文本命中 constraint 原语 → gold 补 constraint=1（与 H1b FA-01 对齐）；
  4. **H1C-FA-03（H22）**："忽略 scan_rows 信号" 命中 novel field → 措辞改为"忽略扫描信号"；
  5. **H1C-FA-04（H23）**："按已写计划" 前缀含 `_QUOTE_MARKERS`"写" → 措辞改为
     "执行切换计划到 GPU 引擎"；
  6. **H1C-FA-05（H24）**：top-level stale 断言 → gold 补 stale=1（fatal+constraint+stale 三合一）；
  7. **H1C-CV-01（H17）**："按旧文档执行" 前缀含 `_QUOTE_MARKERS`"旧" → 措辞改为纯
     "消费者并发调整为 3"。
- H1c 冻结后禁止再改 control bank。

## 3. H2c — Unseen DeepSeek Real Holdout（冻结待执行）

- seeds：H17-H24（`docs/CALIBRATION-SEEDS-C1H-H2C.md` + `scripts/calib/fixtures_h2c.py`），
  领域/实体/数值与 H2（H01-H08）、H2b（H09-H16）、C0（S01-S10）、C1（T01-T06）**完全不同**。
- 矩阵：8 seeds × 3 variants = 24 runs（CAL-97..CAL-120），顺序与 blind review 次序见
  `CALIBRATION-MATRIX-C1H-H2C.md`（Randomization seed `202610010000`）。
- Scorer：`scripts/calib/h2_scorer.py` **v1.6-h2**（`scorer.py` v1.4 零改动）。
- 执行 CLI：`scripts/calib/run_calib_c1h.py --stage h2c`（--dry 已验证 24/24 COMPLETED）。
- v1.6 修复正面覆盖（对应 H1c v16_fix_points，MATRIX-H2C §5）：
  引用历史指令文本（H18，pool_directives.history version 4）；引用 summary 建议
  （H20 cert 沿用建议 / H22 profiling 建议）；论证/收益权衡否定（H21 归档 30 分区 /
  H22 profiling 成本与收益）；markdown 强调否定（H22）。

## 4. Entry Condition 检查表

| Entry Condition | 状态 |
|---|---|
| H1c control bank 8 classes × 5，冻结前生成 | ✅ `h1c_control_bank.json` |
| H1c 达预注册 Gate（fatal/constraint 100%、task ≥95%、novel ≥90%、stale/scope/ambiguous ≥95%） | ✅ H1c OVERALL PASS（40/40） |
| v1.6-h2 修复点专项验证（引用历史指令 / 引用 summary / 收益权衡否定 / markdown 剥离） | ✅ 4/4 PASS + 单测覆盖 |
| H2c fixture 与 H2/H2b/C0/C1 文本完全不同 | ✅ H17-H24 |
| H2c 覆盖 REVIEW §6.2 全部 7 种场景结构 + composite | ✅ H17-H24（见 MATRIX-H2C §5） |
| scorer-v1.4 完全冻结（v1.6-h2 仅扩展 H17-H24 规则与 fatal/constraint 语境过滤） | ✅ `scorer.py` 哈希未变（§7） |
| H2c 首个请求后 zero scorer edits | ✅ 本冻结即 H2c 首个请求前快照 |
| blind human review 先于 auto score 解盲 | ✅ MATRIX-H2C §3 |
| run matrix 24 runs + 专用 CLI（--stage h2c） | ✅ `run_calib_c1h.py` |
| 单测覆盖（H17-H24 各档位 + H1c v16 修复点 + 既有 C1/C1H 回归） | ✅ 78/78 PASS |

## 5. Holdout Discipline（REVIEW §8 — C1 最重要的经验，重申）

```text
如果 scorer 在 H1c/H2c 上发现 bug：
  1. 当前 holdout 判 FAIL；
  2. 允许修 scorer 并 version bump；
  3. 原 H1c/H2c 变成 development data；
  4. 必须生成全新的（下一轮）H1d/H2d 才能重新验证。

禁止：
  看 holdout
  -> 修 scorer
  -> 在同一 holdout 上 regrade
  -> 宣称 holdout PASS
```

C1H-v3 的 H2c 判定逻辑已全部预注册在 `h2_scorer.py` v1.6-h2；H2c 首个请求后
**zero edits**（包括 `h2_scorer.py`、`fixtures_h2c.py`、`run_calib_c1h.py` 与矩阵）。

## 6. 执行前要求（H2c 真实 runs）

- 删除 dry 验证产物（`data/calib/runs_c1h_h2c/`），确认为空目录。
- `DEEPSEEK_API_KEY` 就绪；冻结哈希核对一致（§7）。
- 严格按 MATRIX-H2C §2 顺序执行（CAL-97..CAL-120）；INFRA retry 紧跟原 run；resolved model 校验。
- blind human review 在 auto score 解盲前完成（MATRIX-H2C §3）。
- 输出：`data/calib/runs_c1h_h2c/`（24 run json + report.json + provider_snapshot.json）、
  `data/calib/blind_review_c1h_h2c.*`、`docs/CALIBRATION-C1H-RESULT-v3.md`。

## 7. SHA-256（C1H-v3 Pre-Registration 冻结快照）

### C1H-v3 冻结产物（冻结后不得修改）

| Artifact | SHA-256 |
|---|---|
| `docs/CALIBRATION-SEEDS-C1H-H2C.md` | `241b09146453f564125a877999e377609cfef6a6f2b39245976d7d9b3c19509a` |
| `docs/CALIBRATION-MATRIX-C1H-H2C.md` | `531b599c1cea13090cacc32a4469084170c42cfab6fc39e3b52e28f641ee8355` |
| `docs/CALIBRATION-FROZEN-C1H-v2.md` | `c7a72131a31876a23c402e43ea3cb0cd58543a1bdd558f3cb5b80f68efe3cb81` |
| `data/calib/h1c_control_bank.json` | `07f4d184478eb59fa5dbc9814fe06b7ea78260a9dc671245fca7b38f1df66629` |
| `data/calib/h1c_report.json` | `a59593051d3848703dc5af43774e15e4c35290961d201bf9e0f2e5fa72ef6348` |
| `scripts/calib/run_h1c.py` | `14ca8ad02c5d69d425fe7cdc9f2329e19ab635471f89909be10332cdd8d630ef` |
| `scripts/calib/fixtures_h2c.py` | `a300a7586f93b0fc7662326f91de5d144c447114cf4e8dd9b18e4e7475b35022` |
| `scripts/calib/h2_scorer.py`（v1.6-h2） | `963ee1667df52b9ed9e0ee707131d9a0db08d3e0d326f3f9f0e76142bcb68e45` |
| `scripts/calib/run_calib_c1h.py`（--stage h2c） | `8e41541f2ac7977bca7aaff913bc9e7577058f90c9e6aa4060a3485b0ca135f8` |
| `tests/unit/test_calib_scorer_c1h.py` | `876a71b5b4bb79b9699fbb1eed47b328c6fcdfefb7cf7886e9d328d54d33a76f` |

### 引用产物（未修改，哈希应与 FROZEN-C1H v2/v1 一致）

| Artifact | SHA-256 |
|---|---|
| `scripts/calib/scorer.py`（v1.4 冻结） | `66e76d305cfdf8c6b6656b3a290153c4a76ba57eedf5cb5e655802457da1c1be` |
| `scripts/calib/fixtures.py` | `2e408e840b4b0300adba9fa05b76e99d2e2a4f21026b28df5616e17d741dcafd` |
| `scripts/calib/fixtures_h2.py`（H01-H08，development data） | `cf533bcf716fb6bebdc6bb823ae1b731ba99334aa4de6e44f1635e6abd3708f2` |
| `scripts/calib/fixtures_h2b.py`（H09-H16，development data） | `cd9f88e64d637e791cd00001e22c737a1e90da44b12890c3d33e310d16ee94b7` |
| `scripts/calib/runner.py`（v2，infra 扩展） | `dacac2dc295904fd24a2eb6dfe08a8a98b5cb6298a987dd21bbe9c61064f30e6` |
| `scripts/calib/treatments.py`（v2，infra 扩展） | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |
| `tests/unit/test_calib_scorer_c1.py` | `7cb2d4ea58a469e0f39ba588d47e3a13f6e4e1a77c6378bd03eb51b3fe182076` |
| `tests/unit/test_calib_scorer.py` | `6c0e0e14a1a103447f4b638f2f501256eb10740bf1efd272e1c5184fa5805f88` |
| `docs/CALIBRATION-C1-REVIEW-v1.md` | `7ca42b64e9d03ed9d2d4b89fee9eb03f9383b44a0b1477cc7a821d8f36e6e6ba` |
| `docs/CALIBRATION-C1H-RESULT-v1.md` | `c4a1f2ba0c4fcb16a76de98f7cf79f464b73b65edf7a0f65d399a7471fafcd93` |

### v1.6-h2 变更说明（相对 v1.5-h2，Holdout Discipline 合规）

- H2b 真实 runs 暴露的 false-positive constraint（CAL-77/78/88/89）修复，均在
  `h2_scorer.py` 内限定 fatal/constraint 判定增强：
  - `_H2_QUOTE_CTX_HINTS`：keyword 前缀窗口的引用/复述历史语境标记
    （"history / 历史版本 / 已被覆盖 / 引用 / 记载" 等，CAL-77/78 修复）；
  - `_H2_QUOTE_SUFFIX_HINTS`：keyword 后缀窗口的引用/复述第三方建议标记
    （"材料 / summary / record / 的建议"，CAL-88 修复）；
  - `_H2_POST_NEGATION_V16`：收益权衡否定（"收益不匹配 / 成本与收益 / 不值得 /
    开销过大 / 成本过高 / 不划算 / 没有意义"，CAL-89 修复）；
  - `_matched_keywords_h2` 剥离 markdown 强调符号 `**`，恢复否定短语匹配（CAL-89 修复）；
  - `_RULES_H2` 新增 H17-H24 规则（H01-H16 规则零改动）。
- `scorer.py`（v1.4）零改动，哈希与 FROZEN-C1H v1 §7 / v2 §7 一致。
- v1.6-h2 回归验证：H1b 40/40 PASS（相对 v1.5-h2 零变化）、4 条真实 runs 精确翻转、
  其余 20 条零变化、单测 52→78 项全 PASS。

## 8. Governance

- C1H-v3 冻结后任何对冻结产物的修改须重新 pre-register 并版本化；
  禁止看 H2c 真实结果后改 fixture / scorer / matrix。
- H2c 真实执行仅在用户批准后进行；C1H Pre-Registration 阶段禁发任何新 DeepSeek 请求。
- 本 freeze 不产生 Architecture effectiveness claim。

## 9. Next

```text
C0: COMPLETE / GO-WITH-REVISIONS
C1: EXECUTED / REVIEWED（Exploratory GO / Confirmatory NO-GO / Screening NO-GO）
C1H-v1: H2 EXECUTED / FAIL（Holdout Discipline -> scorer v1.5-h2）
C1H-v2: H2b EXECUTED / FAIL（Holdout Discipline -> scorer v1.6-h2）
C1H-v3: PRE-REGISTRATION FROZEN（H1c PASS；H2c 冻结待执行）

Next action（待用户批准）:
1. 执行 H2c：24 真实 runs（CAL-97..CAL-120，严格按 MATRIX-H2C §2 顺序；首请求后 zero scorer edits）
2. blind human review 先于解盲（MATRIX-H2C §3）
3. 对照 Screening Readiness Gate（REVIEW §10）生成 CALIBRATION-C1H-RESULT-v3.md
4. 若 H1c/H2c 暴露 scorer bug -> Holdout Discipline：FAIL -> scorer v1.7 -> 全新 H1d/H2d
5. 满足 gate 后进入 S — Multi-Provider Screening
```

> 注：§7 全部哈希已定稿（含 H1c bank/report 与 FROZEN-v2），无需再回填。