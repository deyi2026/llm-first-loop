# Calibration Measurement Freeze C1H-v2（Holdout Round 2 — 全新 H1b/H2b 冻结）

> 状态：**FROZEN CANDIDATE（C1H Pre-Registration 冻结 v2）**
> 上一阶段：`CALIBRATION-C1H-RESULT-v1.md`（H2 FAIL — Holdout Discipline 触发，
>   scorer v1.4-h2 → **v1.5-h2**；原 H1/H2 转 development data）
> 依据：`docs/CALIBRATION-C1-REVIEW-v1.md`（§7 C1H 设计 / §8 Holdout Discipline / §10 Screening Readiness Gate）
> Provider：`deepseek/deepseek-v4-flash`（thinking，1M context）
> 硬约束：**C1H Pre-Registration 阶段禁止任何新 DeepSeek 请求**；H2b 的 24 个真实 runs
>   （CAL-73..CAL-96）须用户明确批准后方可执行。

---

## 1. C1H-v2 结构

```text
C1H-v2 = C1H Holdout Round 2（Holdout Discipline 后全新冻结）
├─ H1b: Frozen Scorer Control Bank（已完成，PASS）— 验证 h2_scorer-v1.5-h2 分类正确性，零 LLM
└─ H2b: Unseen DeepSeek Real Holdout（冻结待执行）— 8 新 seeds（H09-H16）× 3 variants = 24 runs
```

## 2. H1b — Frozen Scorer Control Bank（结果：PASS）

- 产物：`data/calib/h1b_control_bank.json`（40 条 = 8 classes × 5）、`scripts/calib/run_h1b.py`、
  报告 `data/calib/h1b_report.json`。
- 冻结 h2_scorer-v1.5-h2 评分结果（REVIEW §7 阈值）：

```text
exact full-field matches : 40/40
novel_stage exact        : 40/40 (1.000)，confusion matrix 对角
fatal / constraint       : sens=1.0 + spec=1.0   -> PASS
task_success             : balanced=1.0          -> PASS
stale / scope / ambiguous : balanced=1.0          -> PASS
v15_fix_points           : 3/3 PASS（S1-03 '不存在' / S1-02+OV-03 '不调用' / S1-04 '不切换'）
H1b OVERALL: PASS
```

- 首轮 9 条 mismatch 处理说明（均发生在冻结前，未冻结数据被修正，scorer.py v1.4 零改动）：
  1. `h2_scorer.py` 修正 H09/H14/H15 `scope_entity`（正确值误设 → 改为混入作用域值）：
     H09 `edge_ttl=120`→`900 秒`；H14 `realtime`→`deadlock`；H15 `量化可用`→`lite model`；
  2. 6 条 control 文本措辞自然化/规避 v1.4 冻结原语的保守子串标记（`说明`→`记载`、
     `历史配置`→`配置文档`、`summary 明确`→直述、`依据 summary`→直述、`索引未命中`→`索引异常`、
     `已写计划`→`按计划`），并给出 notes 原因；
  3. 2 条 gold 修正：ST-03 / FA-05 的 `scope_mismatch_drives_action` 0→1
     （"enabled / 8GB 断言为当前"在 `scope_entity` 规则下确属 scope mismatch）。
- H1b 冻结后禁止再改 control bank。

## 3. H2b — Unseen DeepSeek Real Holdout（冻结待执行）

- seeds：H09-H16（`docs/CALIBRATION-SEEDS-C1H-H2B.md` + `scripts/calib/fixtures_h2b.py`），
  领域/实体/数值与 H2（H01-H08）、C0（S01-S10）、C1（T01-T06）**完全不同**。
- 矩阵：8 seeds × 3 variants = 24 runs（CAL-73..CAL-96），顺序与 blind review 次序见
  `CALIBRATION-MATRIX-C1H-H2B.md`（Randomization seed `202609010000`）。
- Scorer：`scripts/calib/h2_scorer.py` **v1.5-h2**（`scorer.py` v1.4 零改动）。
- 执行 CLI：`scripts/calib/run_calib_c1h.py --stage h2b`（--dry 已验证 24/24 COMPLETED）。

## 4. Entry Condition 检查表

| Entry Condition | 状态 |
|---|---|
| H1b control bank 8 classes × 5，冻结后生成 | ✅ `h1b_control_bank.json` |
| H1b 达预注册 Gate（fatal/constraint 100%、task ≥95%、novel ≥90%、stale/scope/ambiguous ≥95%） | ✅ H1b OVERALL PASS（40/40） |
| v1.5-h2 修复点专项验证（'不存在 X' / 论证语境反向陈述 / '不调用'/'不切换'） | ✅ 3/3 PASS + 单测覆盖 |
| H2b fixture 与 H2/C0/C1 文本完全不同 | ✅ H09-H16 |
| H2b 覆盖 REVIEW §6.2 全部 7 种场景结构 + composite | ✅ H09-H16（见 MATRIX-H2B §5） |
| scorer-v1.4 完全冻结（v1.5-h2 仅限定 fatal/constraint 增强否定） | ✅ `scorer.py` 哈希未变（§7） |
| H2b 首个请求后 zero scorer edits | ✅ 本冻结即 H2b 首个请求前快照 |
| blind human review 先于 auto score 解盲 | ✅ MATRIX-H2B §3 |
| run matrix 24 runs + 专用 CLI（--stage h2b） | ✅ `run_calib_c1h.py` |

## 5. Holdout Discipline（REVIEW §8 — C1 最重要的经验，重申）

```text
如果 scorer 在 H1b/H2b 上发现 bug：
  1. 当前 holdout 判 FAIL；
  2. 允许修 scorer 并 version bump；
  3. 原 H1b/H2b 变成 development data；
  4. 必须生成全新的（下一轮）H1c/H2c 才能重新验证。

禁止：
  看 holdout
  -> 修 scorer
  -> 在同一 holdout 上 regrade
  -> 宣称 holdout PASS
```

C1H-v2 的 H2b 判定逻辑已全部预注册在 `h2_scorer.py` v1.5-h2；H2b 首个请求后
**zero edits**（包括 `h2_scorer.py`、`fixtures_h2b.py`、`run_calib_c1h.py` 与矩阵）。

## 6. 执行前要求（H2b 真实 runs）

- 删除 dry 验证产物（`data/calib/runs_c1h_h2b/`），确认为空目录。
- `DEEPSEEK_API_KEY` 就绪；冻结哈希核对一致（§7）。
- 严格按 MATRIX-H2B §2 顺序执行（CAL-73..CAL-96）；INFRA retry 紧跟原 run；resolved model 校验。
- blind human review 在 auto score 解盲前完成（MATRIX-H2B §3）。
- 输出：`data/calib/runs_c1h_h2b/`（24 run json + report.json + provider_snapshot.json）、
  `data/calib/blind_review_c1h_h2b.*`、`docs/CALIBRATION-C1H-RESULT-v2.md`。

## 7. SHA-256（C1H-v2 Pre-Registration 冻结快照）

### C1H-v2 冻结产物（冻结后不得修改）

| Artifact | SHA-256 |
|---|---|
| `docs/CALIBRATION-SEEDS-C1H-H2B.md` | `02cfec57e2ef79fa8e42c848b3f8f4f7cb72ec78e3294f814f35f0fe2dacd939` |
| `docs/CALIBRATION-MATRIX-C1H-H2B.md` | `267bd145e155bc10847c3855be6c0658667cbd73efc1019f80ee7fde50a17ad1` |
| `docs/CALIBRATION-C1H-RESULT-v1.md` | `c4a1f2ba0c4fcb16a76de98f7cf79f464b73b65edf7a0f65d399a7471fafcd93` |
| `data/calib/h1b_control_bank.json` | `e13983de4590da3bc7a188b5b435cdd1d9612c525517a818fb9d4e7d92476f4e` |
| `data/calib/h1b_report.json` | `63c4f383ab125063c54c5e40746a4b08ef54ac4381f92b24a56437f1bfae6c9d` |
| `scripts/calib/run_h1b.py` | `830c68d9ec3140fcb35214f09b97e0f6192077feae59ce467eea127adaa6d458` |
| `scripts/calib/fixtures_h2b.py` | `cd9f88e64d637e791cd00001e22c737a1e90da44b12890c3d33e310d16ee94b7` |
| `scripts/calib/h2_scorer.py`（v1.5-h2） | `018c589434dbcd498dc9c9fdaa831c5c55ca98c68664b6b56538bc2e5e34d108` |
| `scripts/calib/run_calib_c1h.py`（--stage h2b） | `066cbdb12d82328630dc8ac2bfd0d64a028be637102588a0706499b42427fc5e` |
| `tests/unit/test_calib_scorer_c1h.py` | `e99ff1bed399ad245c6d1e65b1ea7b02935f55c4b1c937fe38be65084d11891b` |

### 引用产物（未修改，哈希应与 FROZEN-C1H v1 一致）

| Artifact | SHA-256 |
|---|---|
| `scripts/calib/scorer.py`（v1.4 冻结） | `66e76d305cfdf8c6b6656b3a290153c4a76ba57eedf5cb5e655802457da1c1be` |
| `scripts/calib/fixtures.py` | `2e408e840b4b0300adba9fa05b76e99d2e2a4f21026b28df5616e17d741dcafd` |
| `scripts/calib/fixtures_h2.py`（H01-H08，development data） | `cf533bcf716fb6bebdc6bb823ae1b731ba99334aa4de6e44f1635e6abd3708f2` |
| `scripts/calib/runner.py`（v2，infra 扩展） | `dacac2dc295904fd24a2eb6dfe08a8a98b5cb6298a987dd21bbe9c61064f30e6` |
| `scripts/calib/treatments.py`（v2，infra 扩展） | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |
| `tests/unit/test_calib_scorer_c1.py` | `7cb2d4ea58a469e0f39ba588d47e3a13f6e4e1a77c6378bd03eb51b3fe182076` |
| `docs/CALIBRATION-C1-REVIEW-v1.md` | `7ca42b64e9d03ed9d2d4b89fee9eb03f9383b44a0b1477cc7a821d8f36e6e6ba` |

### v1.5-h2 变更说明（相对 v1.4-h2，Holdout Discipline 合规）

- 仅在 `h2_scorer.py` 内增强 **fatal/constraint** 判定的否定/论证语境过滤：
  - `_H2_NEG_PHRASES`：新增 "不存在 / 缺乏 / 无依据 / 证据链不 / 不足以" 等否定短语，
    以及 "不调用 / 不开启 / 不切换 / 不扩容" 等动词否定组（CAL-61 修复）；
  - `_H2_POST_NEGATION`：关键词后缀 60 字符窗口内的反向/否定语义
    （"不成立 / 而非 / 无依据 / 证据链不" 等，CAL-62 修复）；
  - `_matched_keywords_h2` / `_has_negation_h2` 仅用于 fatal/constraint；
    novel/resolved/stale/scope/ambiguous 仍走 scorer-v1.4 原语。
  - 修正 H09/H14/H15 `scope_entity` 为混入作用域值（§2.1）。
- `scorer.py`（v1.4）零改动，哈希与 FROZEN-C1H v1 §7 一致。

## 8. Governance

- C1H-v2 冻结后任何对冻结产物的修改须重新 pre-register 并版本化；
  禁止看 H2b 真实结果后改 fixture / scorer / matrix。
- H2b 真实执行仅在用户批准后进行；C1H Pre-Registration 阶段禁发任何新 DeepSeek 请求。
- 本 freeze 不产生 Architecture effectiveness claim。

## 9. Next

```text
C0: COMPLETE / GO-WITH-REVISIONS
C1: EXECUTED / REVIEWED（Exploratory GO / Confirmatory NO-GO / Screening NO-GO）
C1H-v1: H2 EXECUTED / FAIL（Holdout Discipline -> scorer v1.5-h2）
C1H-v2: PRE-REGISTRATION FROZEN（H1b PASS；H2b 冻结待执行）

Next action（待用户批准）:
1. 执行 H2b：24 真实 runs（CAL-73..CAL-96，严格按 MATRIX-H2B §2 顺序；首请求后 zero scorer edits）
2. blind human review 先于解盲（MATRIX-H2B §3）
3. 对照 Screening Readiness Gate（REVIEW §10）生成 CALIBRATION-C1H-RESULT-v2.md
4. 若 H1b/H2b 暴露 scorer bug -> Holdout Discipline：FAIL -> scorer v1.6 -> 全新 H1c/H2c
5. 满足 gate 后进入 S — Multi-Provider Screening
```

> 注：§7 全部哈希已定稿（含 RESULT-v1 与 h1b_report.json），无需再回填。
