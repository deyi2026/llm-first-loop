# Calibration Measurement Freeze C1

> 状态：**C1 EXECUTED / REVIEWED — EXPLORATORY GO / CONFIRMATORY NO-GO / FORMAL SCREENING NO-GO**
> 说明：C1 首个 DeepSeek 请求前，fixture family / scorer / runner / 18-run 矩阵 / blind review 顺序全部冻结。
> 执行期修订（runner infra fix + scorer v1.3/v1.4）见 §8 修订记录。
> 正式审阅结论见 `CALIBRATION-C1-REVIEW-v1.md`：C1 为 scorer development set，**暂不进入 S**，下一阶段为 C1H。
> Provider：`deepseek/deepseek-v4-flash`（thinking，1M context）

## 1. Measurement Decisions

- 采用 C1 fixture family T01-T06（`CALIBRATION-SEEDS-C1.md`），覆盖 C0 空缺的 5 种样本形态。
- 18-run 冻结矩阵：6 paired seeds × 3 variants = CAL-31..CAL-48（`CALIBRATION-MATRIX-C1.md`，randomization seed `202608260000`）。
- **Scorer Reasoning-Field Policy：B (verbosity)**（三选一声明，见 MATRIX-C1 §4）。
- scorer 由 v1.1 升级为 **v1.2**（合规 version bump，见 §4）。

## 2. C1 Entry Condition 检查表

| Entry Condition（FROZEN-v3 §8 / SCORER-v1.1 §14） | 状态 |
|---|---|
| New fixture family（T01-T06，与 S01-S10 文本完全不同） | ✅ `CALIBRATION-SEEDS-C1.md` |
| DeepSeek resolved parameters | ✅ `deepseek/deepseek-v4-flash`，thinking=true，1M context |
| scorer 在首个请求前冻结（v1.1 → v1.2） | ✅ `CALIBRATION-SCORER-v1.2.md` |
| Natural hard-negative distribution | ✅ T01 / T03 / T06（dry fail → 0/18） |
| N3/N4 rubric 可产出 verified-but-not-integrated | ✅ T02 / T05（novel_success 仅整合语义判 N4） |
| Benign unknown / over-verification 观测 | ✅ T04（`unnecessary_verification_count`） |
| Human review protocol | ✅ blind review 顺序已冻结（MATRIX-C1 §3） |
| Run matrix | ✅ 18 runs，C1 专用 CLI `run_calib_c1.py` |

## 3. C1 Pre-Registration Scope

```text
冻结产物：
- SEEDS-C1（T01-T06 hidden oracle + predicates）
- MATRIX-C1（18-run 矩阵 + blind review 顺序 + Reasoning Policy B 声明）
- SCORER-v1.2（规则 + Policy B + 否定检测增强）
- fixtures.py（T01-T06 数据层；S01-S10 未动）
- scorer.py v1.2 / runner.py（provider 泛化）/ run_calib_c1.py（C1 CLI）
- test_calib_scorer_c1.py（14 单测）

明确不冻结（执行时生成）：
- data/calib/runs_c1/ 下的 run 结果（真实 DeepSeek 输出）
- provider_snapshot.json / report.json（执行后重新生成）
```

## 4. Scorer Version Bump 合规性（v1.1 → v1.2）

FROZEN-v3 §3 Governance 要求：C1 开始后修改 scorer 必须 version bump，禁止边看 DeepSeek 结果边调 scorer。

```text
- version bump 已执行：scorer_version = "v1.2"
- 变更发生在任何 DeepSeek 请求之前（Pre-Registration 阶段）
- v1.2 未用于任何真实模型结果
- v1.2 变更清单见 CALIBRATION-SCORER-v1.2.md §2
```

历史对照：FROZEN-v3 冻结的 `scripts/calib/scorer.py` 哈希 `5f832313...`（v1.1）不再匹配当前文件；C0 的 v1.1 判定语义被 v1.2 全部保留（C0 30 runs 重评分 0 mismatch）。

## 5. SHA-256（Pre-Registration 冻结快照，v1.2）

> 历史快照：C1 首个请求前的冻结哈希。执行期修订后终版见 §9（v1.4）。

### C1 冻结产物（冻结后不得修改）

| Artifact | SHA-256 |
|---|---|
| `docs/CALIBRATION-SEEDS-C1.md` | `9726133a674b2f3767359193d6b93282c17154b097cb25241d3296b1221afe1b` |
| `docs/CALIBRATION-MATRIX-C1.md` | `6f5b31a4942de464e2399c83ad65ef9fc351b0453c52d3806485e1102afdfdd6` |
| `docs/CALIBRATION-SCORER-v1.2.md` | `80bcee1e1b6b556c01eecff0dd1b101f5f03dcb9ca0b576d41bcbd3d006cc12c` |
| `scripts/calib/fixtures.py` | `2e408e840b4b0300adba9fa05b76e99d2e2a4f21026b28df5616e17d741dcafd` |
| `scripts/calib/scorer.py` | `ee1c99f63a7551ea84f0c14f6fc41df4ccecc64a8dba35ff9340333618f1f563` |
| `scripts/calib/runner.py` | `a1bdacc7bc5404f027e06297106ea7fa4830bac73962ad4493317606b4b2c241` |
| `scripts/calib/run_calib_c1.py` | `e67a86d46663f0532c1136ab224d6b11dfb4ad5610ccfb712ea93e23658de3ec` |
| `tests/unit/test_calib_scorer_c1.py` | `a17095c965eb1f0ef8b1f11fc6eb7798fbd4c467e88251581341e5955bfae2f4` |

### C0 引用产物（未修改，哈希应与 FROZEN-v3 一致）

| Artifact | SHA-256 |
|---|---|
| `scripts/calib/run_calib.py` | `62e19e744b004106ab9d40aa8ca01f898f58f688d90b1d84806c5921a6f3dec1` |
| `scripts/calib/treatments.py` | `d7bfc219f7b9631501b4ddb3831aa1dd6a0fa1f9ead932c5b9e499eaf33be8e6` |
| `tests/unit/test_calib_scorer.py` | `6c0e0e14a1a103447f4b638f2f501256eb10740bf1efd272e1c5184fa5805f88` |
| `docs/CALIBRATION-SCORER-v1.1.md` | `ec8bdd09a23951fe922f601b10b39ffe9e54d75577a78f8e969e116c082513dd` |
| `docs/CALIBRATION-FROZEN-v3.md` | `4c00239bc26fbb1713a8242218fca3d5118f79bddc0541e9f7e5c25a141a1c89` |
| `data/providers.json` | `a5e6221a344d08d37c0135931762e95e9371c4073d9dd1cd33903e3599a4a874` |

## 6. Governance

- C1 真实执行开始后，任何对上述 C1 冻结产物的修改须重新 pre-register 并版本化；禁止边看 DeepSeek 结果边改 fixture / scorer / matrix。
- 执行严格按 MATRIX-C1 §2（Seq 顺序、INFRA retry、resolved model 校验、thinking_mode=true 协变量）。
- 本 freeze 不产生任何 Architecture effectiveness / global promotion claim。
- 真实执行前须删除 dry 验证产物（见 §7），避免污染。

## 7. Execution Log

```text
- 执行前检查：DEEPSEEK_API_KEY 就绪；runs_c1 空目录；冻结哈希一致 → PASS
- CAL-31 首次请求：INFRA_FAILURE（HTTP 400，DeepSeek thinking 需回传 reasoning_content）
  → runner.py infra 修复（M20 THK-04）→ INFRA retry → COMPLETED
- CAL-31..CAL-48 全部 18 runs：COMPLETED（0 INFRA_FAILURE / 0 ROUND_LIMIT）
- 自动评分：scorer-v1.4 → task_success 18/18、fatal 0/18、constraint 0/18、novel N4×18
- blind human review（独立 agent，脱敏）：task/fatal/constraint/novel/stale 全维度 18/18 一致
- 结果产物：data/calib/runs_c1/（18 run json + report.json）、
  data/calib/blind_review_c1.md / blind_review_pack_c1.json / blind_human_scores_c1.json
```

## 8. 执行期修订记录（version bump 合规）

| 修订 | 触发 | 类型 | 变更 |
|---|---|---|---|
| runner.py | CAL-31 首次 400 | infra 修复 | assistant 工具调用消息回传 `reasoning_content`（M20 THK-04） |
| scorer v1.3 | CAL-31 误判 fatal=1 | 测量缺陷修复 | `_NEG_PHRASES` 扩充 + `_EVALUATION_MARKERS` 新增 + T02 novel_success 补充 |
| scorer v1.4 | CAL-45 误判 fatal=1 | 测量缺陷修复 | `_NEG_PHRASES` 再扩充（不将/不视为/…）+ 目标语境标记 + T02 整合语义再补充 |

均属"C1 执行期发现的测量缺陷修复"，version bump 合规（v1.3/v1.4 未用于任何真实结果的既有判定后再静默改规则；每次修订均记录触发证据并全量重评分）。C0 seed/oracle/matrix/raw outputs 零改动。

## 9. SHA-256（v1.4 终版）

### C1 冻结产物（冻结后不得修改）

| Artifact | SHA-256 |
|---|---|
| `docs/CALIBRATION-SEEDS-C1.md` | `9726133a674b2f3767359193d6b93282c17154b097cb25241d3296b1221afe1b` |
| `docs/CALIBRATION-MATRIX-C1.md` | `6f5b31a4942de464e2399c83ad65ef9fc351b0453c52d3806485e1102afdfdd6` |
| `docs/CALIBRATION-SCORER-v1.2.md` | `80bcee1e1b6b556c01eecff0dd1b101f5f03dcb9ca0b576d41bcbd3d006cc12c` |
| `docs/CALIBRATION-SCORER-v1.4.md` | `e2acbccf6adc324b4d0e92d50af7d1eacabb18e8e34d6ff83a8f134f61639a06` |
| `scripts/calib/fixtures.py` | `2e408e840b4b0300adba9fa05b76e99d2e2a4f21026b28df5616e17d741dcafd` |
| `scripts/calib/scorer.py` | `66e76d305cfdf8c6b6656b3a290153c4a76ba57eedf5cb5e655802457da1c1be` |
| `scripts/calib/runner.py` | `31b46ece8cc9cfeb2036c5bf76e6c04fdcb6a10718fa2875c4dcae2d92e1bd65` |
| `scripts/calib/run_calib_c1.py` | `c474dcbde92f1169c3c71b3968d78b1bd2352cd917a584a794928a781e3336cd` |
| `tests/unit/test_calib_scorer_c1.py` | `7cb2d4ea58a469e0f39ba588d47e3a13f6e4e1a77c6378bd03eb51b3fe182076` |
| `data/calib/blind_review_c1.md` | `45539c23ce4ef3764d94747d142820faf789e6738967a35476c266f998448e82` |
| `data/calib/blind_review_pack_c1.json` | `01c54d51b6f9bc8a52d81165dea9756dc9ba2a02c2a9cfa68d1e26e4b07c74ea` |
| `data/calib/blind_human_scores_c1.json` | `35c768df40f57e7a53e110fc01c2a227cf6dcf0e0254458429d47665fb5f568d` |

### C0 引用产物（未修改，哈希应与 FROZEN-v3 一致）

| Artifact | SHA-256 |
|---|---|
| `scripts/calib/run_calib.py` | `62e19e744b004106ab9d40aa8ca01f898f58f688d90b1d84806c5921a6f3dec1` |
| `scripts/calib/treatments.py` | `d7bfc219f7b9631501b4ddb3831aa1dd6a0fa1f9ead932c5b9e499eaf33be8e6` |
| `tests/unit/test_calib_scorer.py` | `6c0e0e14a1a103447f4b638f2f501256eb10740bf1efd272e1c5184fa5805f88` |
| `docs/CALIBRATION-SCORER-v1.1.md` | `ec8bdd09a23951fe922f601b10b39ffe9e54d75577a78f8e969e116c082513dd` |
| `docs/CALIBRATION-FROZEN-v3.md` | `4c00239bc26fbb1713a8242218fca3d5118f79bddc0541e9f7e5c25a141a1c89` |
| `data/providers.json` | `a5e6221a344d08d37c0135931762e95e9371c4073d9dd1cd33903e3599a4a874` |

## 10. Next

```text
C0: COMPLETE / GO-WITH-REVISIONS
C1: EXECUTED / REVIEWED（Exploratory GO, Confirmatory NO-GO, Screening NO-GO）
审阅依据：docs/CALIBRATION-C1-REVIEW-v1.md

Next action（审阅决定，待用户确认后启动 C1H Pre-Registration）:
1. 暂不进入 S（Multi-Provider Screening）—— measurement system 尚无独立 holdout validation
2. 启动 C1H — Holdout Measurement Validation：
   ├─ H1: Frozen Scorer Control Bank（scorer-v1.4 冻结；8 classes × 5 = 40 labeled traces；
   │       阈值: fatal/constraint 100%、task >=95% balanced、novel >=90% exact、stale/scope/ambiguous >=95%）
   └─ H2: Unseen DeepSeek Real Holdout（8 new paired seeds × 3 variants = 24 runs；
          fixture 与 T01-T06 完全不同；scorer-v1.4 零 edits；blind review 先于解盲）
3. Holdout Discipline：若 scorer 在 H1/H2 暴露 bug → holdout FAIL → scorer v1.5 → 全新 H1b/H2b
4. 满足 Screening Readiness Gate（REVIEW §10）后再进入 S
```
