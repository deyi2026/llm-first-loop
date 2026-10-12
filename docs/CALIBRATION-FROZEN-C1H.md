# Calibration Measurement Freeze C1H（Holdout Measurement Validation）

> 状态：**FROZEN CANDIDATE（C1H Pre-Registration 冻结）**
> 上一阶段：`CALIBRATION-FROZEN-C1.md`（C1 EXECUTED / REVIEWED — Exploratory GO / Confirmatory NO-GO / Screening NO-GO）
> 依据：`docs/CALIBRATION-C1-REVIEW-v1.md`（§7 C1H 设计 / §8 Holdout Discipline / §10 Screening Readiness Gate）
> Provider：`deepseek/deepseek-v4-flash`（thinking，1M context）
> 硬约束：**C1H Pre-Registration 阶段禁止任何新 DeepSeek 请求**；H2 的 24 个真实 runs 须用户明确批准后方可执行。

---

## 1. C1H 结构

```text
C1H = C1 Holdout Measurement Validation
├─ H1: Frozen Scorer Control Bank（已完成，PASS）— 验证 scorer-v1.4 分类正确性，零 LLM
└─ H2: Unseen DeepSeek Real Holdout（冻结待执行）— 8 新 seeds × 3 variants = 24 runs
```

## 2. H1 — Frozen Scorer Control Bank（结果：PASS）

- 产物：`data/calib/h1_control_bank.json`（40 条 = 8 classes × 5）、`scripts/calib/run_h1.py`、
  设计文档 `docs/CALIBRATION-H1.md`、报告 `data/calib/h1_report.json`。
- 冻结 scorer-v1.4 评分结果（REVIEW §7 阈值）：

```text
exact full-field matches : 40/40
novel_stage exact        : 40/40 (1.000)，confusion matrix 对角
fatal / constraint       : sens=1.0 + spec=1.0   -> PASS
task_success             : balanced=1.0          -> PASS
stale / scope / ambiguous : balanced=1.0          -> PASS
H1 OVERALL: PASS
```

- 首轮 6 条 mismatch 均为 control 文本措辞自然化修正（scorer.py 零改动），详见 `CALIBRATION-H1.md` §5.1。
- H1 冻结后禁止再改 control bank。

## 3. H2 — Unseen DeepSeek Real Holdout（冻结待执行）

- seeds：H01-H08（`docs/CALIBRATION-SEEDS-C1H.md` + `scripts/calib/fixtures_h2.py`），
  领域/实体/数值与 C0（S01-S10）、C1（T01-T06）**完全不同**。
- 矩阵：8 seeds × 3 variants = 24 runs（CAL-49..CAL-72），顺序见 `CALIBRATION-MATRIX-C1H.md`。
- Scorer：`scripts/calib/h2_scorer.py`（H 层规则，复用 scorer-v1.4 判定原语；`scorer.py` 零改动）。
- 执行 CLI：`scripts/calib/run_calib_c1h.py`（--dry 已验证 24/24 COMPLETED）。

## 4. Entry Condition 检查表

| Entry Condition | 状态 |
|---|---|
| H1 control bank 8 classes × 5，冻结后生成 | ✅ `h1_control_bank.json` |
| H1 达预注册 Gate（fatal/constraint 100%、task ≥95%、novel ≥90%、stale/scope/ambiguous ≥95%） | ✅ H1 OVERALL PASS |
| H2 fixture 与 T01-T06 文本完全不同 | ✅ H01-H08 |
| H2 覆盖 REVIEW §6.2 全部 7 种场景结构 | ✅ H01-H08（见 SEEDS-C1H 末表） |
| N2/N3/waiver/over-verification 真实覆盖机会 | ✅ H01-H08 设计 |
| scorer-v1.4 完全冻结，H2 首个请求后 zero scorer edits | ✅ `scorer.py` 哈希未变（§7） |
| blind human review 先于 auto score 解盲 | ✅ MATRIX-C1H §3 |
| run matrix 24 runs + 专用 CLI | ✅ `run_calib_c1h.py` |

## 5. Holdout Discipline（REVIEW §8 — C1 最重要的经验）

```text
如果 scorer 在 H1/H2 上发现 bug：
  1. 当前 holdout 判 FAIL；
  2. 允许修 scorer 并 version bump；
  3. 原 H1/H2 变成 development data；
  4. 必须生成全新的 H1b/H2b 才能重新验证。

禁止：
  看 holdout
  -> 修 scorer
  -> 在同一 holdout 上 regrade
  -> 宣称 holdout PASS
```

C1H 的 H2 判定逻辑已全部预注册在 `h2_scorer.py`；H2 首个请求后
**zero edits**（包括 `h2_scorer.py` 与 `fixtures_h2.py`）。

## 6. 执行前要求（H2 真实 runs）

- 删除 dry 验证产物（`data/calib/runs_c1h/`），确认为空目录。
- `DEEPSEEK_API_KEY` 就绪；冻结哈希核对一致（§7）。
- 严格按 MATRIX-C1H §2 顺序执行；INFRA retry 紧跟原 run；resolved model 校验。
- blind human review 在 auto score 解盲前完成（MATRIX-C1H §3）。
- 输出：`data/calib/runs_c1h/`（24 run json + report.json + provider_snapshot.json）、
  `data/calib/blind_review_c1h.*`、`docs/CALIBRATION-C1H-RESULT-v1.md`。

## 7. SHA-256（C1H Pre-Registration 冻结快照）

### C1H 冻结产物（冻结后不得修改）

| Artifact | SHA-256 |
|---|---|
| `docs/CALIBRATION-SEEDS-C1H.md` | `82c83a456b2915b57798a36150c015e9b5d9f29e8a11c53f0f25ffc54ce36e29` |
| `docs/CALIBRATION-MATRIX-C1H.md` | `98f44488655bc4a4b15df2962051ee750b58c0d8b85d794e6f52b1d48153b54a` |
| `docs/CALIBRATION-H1.md` | `2a43274920a947bd1905fa21dc154eecbc01d5e55c16cfb22a774e31e1c57c7b` |
| `data/calib/h1_control_bank.json` | `37392fab2c411b5d565e09669cb41d71b94ab5b0219d8f3a784178d5d094b524` |
| `scripts/calib/run_h1.py` | `34304b173f723b7c58cf44e3a1a859348db48aa653a3c304f2efdfeb9be57665` |
| `scripts/calib/fixtures_h2.py` | `cf533bcf716fb6bebdc6bb823ae1b731ba99334aa4de6e44f1635e6abd3708f2` |
| `scripts/calib/h2_scorer.py` | `9504f4a6c8666eb89d1a98013aee24b35261da3df60c83d29eb4329abdf7977c` |
| `scripts/calib/run_calib_c1h.py` | `b0a75deaacfab3032c93252ef7f7ce77e4d99d85716eff2f7a03c7c8925dea1e` |
| `scripts/calib/runner.py`（v2，infra 扩展） | `dacac2dc295904fd24a2eb6dfe08a8a98b5cb6298a987dd21bbe9c61064f30e6` |
| `scripts/calib/treatments.py`（v2，infra 扩展） | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |

### 引用产物（未修改，哈希应与 FROZEN-C1 §9 一致）

| Artifact | SHA-256 |
|---|---|
| `scripts/calib/scorer.py`（v1.4 冻结） | `66e76d305cfdf8c6b6656b3a290153c4a76ba57eedf5cb5e655802457da1c1be` |
| `scripts/calib/fixtures.py` | `2e408e840b4b0300adba9fa05b76e99d2e2a4f21026b28df5616e17d741dcafd` |
| `tests/unit/test_calib_scorer_c1.py` | `7cb2d4ea58a469e0f39ba588d47e3a13f6e4e1a77c6378bd03eb51b3fe182076` |
| `docs/CALIBRATION-SCORER-v1.4.md` | `e2acbccf6adc324b4d0e92d50af7d1eacabb18e8e34d6ff83a8f134f61639a06` |

### Infra 扩展合规说明（runner.py / treatments.py v2）

C1H 阶段对 `runner.py` / `treatments.py` 做 **infra 数据层注入扩展**
（`execute_run(data=...)`、`build_task_prompt(packets=...)`），
以支持 H2 独立数据层 `fixtures_h2.py`。C0/C1 默认行为不变（单测 24 个全通过）；
不涉及任何 scorer 判定语义，与 C1 执行期 runner 400 修复同属 infra 变更。

## 8. Governance

- C1H 冻结后任何对冻结产物的修改须重新 pre-register 并版本化；禁止看 H2 真实结果后改 fixture / scorer / matrix。
- H2 真实执行仅在用户批准后进行；C1H 阶段禁发任何新 DeepSeek 请求。
- 本 freeze 不产生 Architecture effectiveness claim。

## 9. Next

```text
C0: COMPLETE / GO-WITH-REVISIONS
C1: EXECUTED / REVIEWED（Exploratory GO / Confirmatory NO-GO / Screening NO-GO）
C1H: PRE-REGISTRATION FROZEN（H1 PASS；H2 冻结待执行）

Next action（待用户批准）:
1. 执行 H2：24 真实 runs（CAL-49..CAL-72，严格按 MATRIX-C1H 顺序；首请求后 zero scorer edits）
2. blind human review 先于解盲（MATRIX-C1H §3）
3. 对照 Screening Readiness Gate（REVIEW §10）生成 CALIBRATION-C1H-RESULT-v1.md
4. 若 H1/H2 暴露 scorer bug -> Holdout Discipline：H1/H2 FAIL -> scorer v1.5 -> 全新 H1b/H2b
5. 满足 gate 后进入 S — Multi-Provider Screening
```