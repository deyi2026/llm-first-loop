# Stage S1 — Multi-Provider Screening Freeze v1

> 状态：**PRE-REGISTRATION FROZEN — SCORED REAL RUNS BLOCKED**
> 日期：2026-08-26
> Architecture effectiveness claims：0
> 本 freeze 之后尚未发送任何 Stage S provider request。

## 1. Entry Evidence

H2c unseen holdout 已通过：task/fatal/constraint/stale 核心字段 blind vs auto 24/24 一致；novel 22/24=91.7%；首请求后 zero scorer edits。Stage S 因此允许进入 pre-registration，但 Calibration 结果本身不构成 Architecture effectiveness claim。

## 2. Full Panel

```text
MiniMax  / MiniMax-M3            anchor, thinking=false
DeepSeek / deepseek-v4-flash     anchor, thinking=true
Kimi Code / k3                   holdout, thinking=true
GLM      / glm-5.2               holdout, thinking=true
```

Provider resolution：`SCREENING-S0-PROVIDER-RESOLUTION-v1.md` + `s_provider_manifest.json`。

当前 credential snapshot（仅布尔，不保存 secret）：

```text
MINIMAX_API_KEY  present
DEEPSEEK_API_KEY present
KIMI_API_KEY     present
GLM_API_KEY      missing
```

因此当前 **不能启动 scored S runs**。

## 3. Fresh Effectiveness Fixture Family

使用 P01-P08；不得复用 H17-H24。原因：H2c 是 measurement holdout，DeepSeek 已见过；S 必须保持 calibration data 与 effectiveness data 分离。

关键难度：无 Candidate current truth；多数任务 3 sources / 最多 2 次 request；包含不可逆 action gate、latest directive、DRU waiver、benign distractor、closed-decision reopen、durable memory、provider-scoped capability。

## 4. Scorer Freeze

```text
core scorer    = v1.6-h2 (scripts/calib/h2_scorer.py, unchanged)
S seed adapter = v1.6-s1-adapter (scripts/calib/s_scorer.py)
```

Adapter 只加入 P01-P08 seed-specific entity/keyword/oracle mapping；N0-N4、waiver、引用/否定/论证过滤、stale assertion、over-verification 等 core 语义复用 holdout-validated v1.6-h2。

冻结前 offline controls 曾发现英文 `Do not <fatal-action>` 与既有中文否定 core 的覆盖边界。处理方式不是扩 core，而是把 S canonical decision/control 统一到任务主语言中文并收窄 seed keyword；该调整发生在任何 S provider output 之前。

## 5. Matrix Freeze

```text
4 providers × 8 paired seeds × 3 variants = 96 runs
randomization seed = 202608260714
provider blocks = 24 runs each
```

每 provider block 内按 `SCREENING-MATRIX-S1-v1.md` Block Seq 严格执行。分析单位：

```text
Delta_provider(seed) = Treatment(seed) - Baseline(seed)
```

8 seeds/provider 是 screening，不用于最终显著性 Promote。

## 6. Blind Review Freeze

已预选 24 条：每 provider × 每 variant 各 2 条。结果出来后不得换样。以下额外条件强制 review：task failure、fatal/constraint、N0-N3、waiver、needs_human、provider parser/protocol anomaly。

## 7. Pre-Freeze Validation

```text
S scorer unit tests: 20/20 PASS
S runner unit tests: 5/5 PASS
existing C0/C1/C1H scorer regression: PASS
combined selected test suite: 103/103 PASS
96-run dry pass: 96/96 task_success
dry novel: N4×84 / N2×12
N2×12 = P05 DRU waiver (4 providers × 3 variants)
```

Dry outputs 已删除；`data/calib/runs_s1/` 当前为空。Dry 数据不构成模型 evidence。

## 8. Smoke Gate — Must Complete Before ANY Scored S Request

四家 provider 必须全部先通过不使用 P01-P08 的独立 smoke：

```text
plain completion
one synthetic tool-call round trip
usage/reasoning telemetry
configured model identity/profile check
thinking-provider reasoning-content round trip
no fallback
```

命令（真实 provider request，**仍需用户明确批准后才能运行**）：

```text
.venv/bin/python scripts/calib/smoke_screening_provider.py minimax
.venv/bin/python scripts/calib/smoke_screening_provider.py deepseek
.venv/bin/python scripts/calib/smoke_screening_provider.py kimi
.venv/bin/python scripts/calib/smoke_screening_provider.py glm
```

`run_screening_s.py --execute-real` 会检查 `data/calib/smoke_s1/<provider>.json`。本项目进一步要求四家 smoke 全过后才授权第一个 scored S request；当前 GLM credential 缺失，所以 gate 未满足。

若 smoke 暴露纯 wire/protocol adapter 问题：允许修复，但**必须先 version bump S freeze 并重新四家 smoke**，然后才开始 scored runs。Smoke output 禁止用于调 scorer 语义。

## 9. Zero-Edit / Holdout Discipline After First Scored Request

第一个 scored S request 之后以下全部 zero edits：

```text
fixtures_s.py
s_scorer.py
h2_scorer.py
scorer.py
s_matrix_v1.json
SCREENING-SEEDS-S1-v1.md
SCREENING-MATRIX-S1-v1.md
treatments.py
```

若 S output 暴露 core scorer bug：**STOP S** → 当前 S 数据降级为 development evidence → scorer bump → 全新 balanced controls + unseen H1d/H2d → 全新 S fixture family。禁止在同一 S 输出上调 scorer 后 regrade 并声称 confirmatory PASS。

## 10. Screening Decision Vocabulary

S 只允许：

```text
screen-in
screen-out
provider-specific
inconclusive
```

禁止：`Global Architecture Promoted` / `Architecture Proven`。正式 Promote 仍需 Stage A/G/B 的样本量与独立验证。

## 11. SHA-256 Freeze

| Artifact | SHA-256 |
|---|---|
| `docs/SCREENING-S0-PROVIDER-RESOLUTION-v1.md` | `423636e82fbd1272656aa2a91948f8b6520e9b064d40fcff4bd03df1adf50b6c` |
| `data/calib/s_provider_manifest.json` | `f7362bdb49d3a659d7c2b4784b630fc676aea4ca3926eb5ad2ce6480469207b8` |
| `docs/SCREENING-SEEDS-S1-v1.md` | `3350cc5ddb2b5f64dbafdf36f381cccbd61887797e64feeb862c075f4f1e7a0e` |
| `scripts/calib/fixtures_s.py` | `025e0551fa5a66527cef38446a7e9ec8ed715a884d01e734c0edfe381944b37d` |
| `docs/SCREENING-SCORER-S1-v1.md` | `a9a2ab014b0a70a84c9c352f81cbd7892eea4238edf25ac565684abf5101ab87` |
| `scripts/calib/s_scorer.py` | `bb3aa848baa25231fa632f23e8c69275e194e49cdbce15a39f7c05b3e7d15c55` |
| `data/calib/s_matrix_v1.json` | `8ae9302beeed0759dd63c823651310fcd660465abaa69238fd8d5bdb60b5682a` |
| `docs/SCREENING-MATRIX-S1-v1.md` | `d829c0284b8272781ac79c59e0f42fb5cfe745bc601d786f4c000f6c904ec9b8` |
| `scripts/calib/screening_runner.py` | `fac9d493f637b4879c88f925cc8e08354249f402211921d9931dee53254e5efa` |
| `scripts/calib/run_screening_s.py` | `5e37e12c98f911976e7dda856776a1c61d2e8e1e1a2ac55ff1bfa9961e03c38a` |
| `scripts/calib/smoke_screening_provider.py` | `1bf0b47b9fd13ed76348bab24add45caff041baacbfb26a0ad2e705dd77fce27` |
| `tests/unit/test_screening_s_scorer.py` | `4bb9962c492431a66664b7261f9f2e7511d95957befbdbf24dcddafb7b51b3f8` |
| `tests/unit/test_screening_s_runner.py` | `5081a1727790e8989aac8573fa0f7dc4e2219e6e0a7150ceffd5f1c5d0b0c5ac` |
| `scripts/calib/h2_scorer.py` | `963ee1667df52b9ed9e0ee707131d9a0db08d3e0d326f3f9f0e76142bcb68e45` |
| `scripts/calib/scorer.py` | `66e76d305cfdf8c6b6656b3a290153c4a76ba57eedf5cb5e655802457da1c1be` |
| `scripts/calib/treatments.py` | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |
| `docs/OPERATING-CONTRACT-LITE.md` | `47fdf25839b6d5da84e5505ab3f00992017e507a869877774b84ce34058b7de3` |
| `docs/ARCHITECTURE-ai-operating-v1.md` | `ea367a8fcd38065fec9423cb3b726bf1c2dc65ce84c70a732e1e82691d01f756` |
| `docs/CALIBRATION-C1H-RESULT-v3.md` | `7ebffacb25126efb10eb2fba4c18f8fefaa85a96c29d3b13c0e3ebcd2f094b27` |
| `docs/CALIBRATION-FROZEN-C1H-v3.md` | `8e10ffc97f83b12096e4486fd3a2aac0b0a33ec7aa41e2fad819995f60acb2d2` |

## 12. Current Readiness

```text
C1H-v3: PASS
S0 provider resolution: complete
S1 fixture/scorer/matrix: FROZEN
Stage S provider requests this freeze: 0
Smoke: NOT RUN
GLM_API_KEY: MISSING
Scored S execution: BLOCKED
```

下一状态转换必须是：**用户批准 provider smoke → 四家 smoke PASS →（如无 adapter change）申请 scored S execution 批准**。
