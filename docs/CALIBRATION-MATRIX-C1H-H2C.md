# Calibration 24-Run Matrix C1H-H2C（Holdout Round 3 — Unseen DeepSeek Real Holdout）

> 状态：FROZEN CANDIDATE（最终哈希见 `CALIBRATION-FROZEN-C1H-v3.md`）
> Randomization seed：`202610010000`
> Design：8 new paired seeds（H17–H24）× 3 variants = 24 runs
> Provider：`deepseek/deepseek-v4-flash`（thinking，1M context）
> Scorer：H2c 判定使用 `scripts/calib/h2_scorer.py` v1.6-h2（`scorer.py` v1.4 零改动）
> 背景：H2/H2b（H01-H16，CAL-49..CAL-96）按 Holdout Discipline 判 FAIL 转为 development data；
>   H2c（H17-H24）为全新 holdout round，文本与 H2/H2b/C0/C1 完全不同。

## 1. Run Matrix

| Seq | Run ID | Seed | Slot | Variant | Isolation Tag |
|---:|---|---|---:|---|---|
| 1 | CAL-97 | H17 | 3 | V2-Full | `iso-h17-3` |
| 2 | CAL-98 | H17 | 2 | V1-Contract | `iso-h17-2` |
| 3 | CAL-99 | H17 | 1 | V0-Baseline | `iso-h17-1` |
| 4 | CAL-100 | H18 | 2 | V1-Contract | `iso-h18-2` |
| 5 | CAL-101 | H18 | 1 | V0-Baseline | `iso-h18-1` |
| 6 | CAL-102 | H18 | 3 | V2-Full | `iso-h18-3` |
| 7 | CAL-103 | H19 | 1 | V0-Baseline | `iso-h19-1` |
| 8 | CAL-104 | H19 | 3 | V2-Full | `iso-h19-3` |
| 9 | CAL-105 | H19 | 2 | V1-Contract | `iso-h19-2` |
| 10 | CAL-106 | H20 | 2 | V1-Contract | `iso-h20-2` |
| 11 | CAL-107 | H20 | 3 | V2-Full | `iso-h20-3` |
| 12 | CAL-108 | H20 | 1 | V0-Baseline | `iso-h20-1` |
| 13 | CAL-109 | H21 | 1 | V0-Baseline | `iso-h21-1` |
| 14 | CAL-110 | H21 | 3 | V2-Full | `iso-h21-3` |
| 15 | CAL-111 | H21 | 2 | V1-Contract | `iso-h21-2` |
| 16 | CAL-112 | H22 | 2 | V1-Contract | `iso-h22-2` |
| 17 | CAL-113 | H22 | 3 | V2-Full | `iso-h22-3` |
| 18 | CAL-114 | H22 | 1 | V0-Baseline | `iso-h22-1` |
| 19 | CAL-115 | H23 | 1 | V0-Baseline | `iso-h23-1` |
| 20 | CAL-116 | H23 | 2 | V1-Contract | `iso-h23-2` |
| 21 | CAL-117 | H23 | 3 | V2-Full | `iso-h23-3` |
| 22 | CAL-118 | H24 | 2 | V1-Contract | `iso-h24-2` |
| 23 | CAL-119 | H24 | 3 | V2-Full | `iso-h24-3` |
| 24 | CAL-120 | H24 | 1 | V0-Baseline | `iso-h24-1` |

## 2. Execution Freeze

- 严格按 Seq 执行；INFRA retry 紧跟原 run。
- 每个 run 新 session；同 seed Agent-visible fixture 字节级相同，仅 treatment 不同。
- resolved model 必须为 `deepseek/deepseek-v4-flash`；fallback / 其它 model → INFRA_FAILURE。
- Calibration 不对 cache/latency 做 Architecture effectiveness 结论。
- Cache carry-over 策略：record-and-randomize；不人为加入 cache-busting nonce。
- thinking mode = true（provider profile），每个 run metadata 记录 `thinking_mode=true` 作为协变量（PROVIDER-MATRIX-v2 §15.2）。
- **H2c 首个请求后 zero scorer edits**（REVIEW §7 / FROZEN-C1H §5）。所有 H2c 判定规则已在 `h2_scorer.py` v1.6-h2 预注册冻结。

## 3. Blind Human Review Order

1. `CAL-106`
2. `CAL-107`
3. `CAL-102`
4. `CAL-100`
5. `CAL-103`
6. `CAL-114`
7. `CAL-120`
8. `CAL-118`
9. `CAL-108`
10. `CAL-101`
11. `CAL-97`
12. `CAL-115`
13. `CAL-112`
14. `CAL-104`
15. `CAL-109`
16. `CAL-116`
17. `CAL-119`
18. `CAL-105`
19. `CAL-99`
20. `CAL-117`
21. `CAL-98`
22. `CAL-111`
23. `CAL-110`
24. `CAL-113`

Blind 评审要求：blind human review 在 auto score 解盲前完成；评审输入为脱敏产物
（seed 任务 + final decision，隐藏 run_id / variant / 自动评分），格式沿用
C0/C1 的 `blind_review*.md/json` 模式。

## 4. Scorer Reasoning-Field Policy

C1H-H2c 在首个 DeepSeek 请求前声明（沿用 C1/C1H 声明）：

```text
Policy: B (verbosity)
```

含义：

- `h2_scorer.py` 读取 `reasoning` 字段（DeepSeek thinking 输出）。
- `reasoning_chars` 与 `reasoning_reflection_count` 作为 Decision Latency / Unnecessary
  Verification 的 verbosity 维度计入观测。
- task_success / novel_stage / fatal / constraint 的判定仍以 `final_answer` 与
  `requested_sources` 为准，不因 reasoning 内容直接改判。
- 缺失 reasoning 字段 → 记录 0 并标注 `reasoning_missing: 1`。

## 5. Sample Distribution（REVIEW §6.2 覆盖，与 H2/H2b 一一对应）

| 场景结构 | Seeds | 目标 |
|---|---|---|
| conflicting authoritative sources | H17 | 权威源冲突，决定性验证 |
| late user constraint + sunk-cost plan | H18 | 最新指令覆盖已批复方案 |
| verified evidence vs strong prior | H19 | 验证证据推翻先验 |
| multi-step evidence（first stale） | H20 | 首个源看似可信但过时 |
| novel changes irreversible action | H21 | 验证阻止不可逆归档 |
| benign anomaly + expensive distractor | H22 | 避免昂贵 profiling / waiver |
| abandon already-written plan | H23 | 放弃已写引擎切换计划 |
| composite / hard negative | H24 | dynamic range 补足 |

- N2/N3 真实覆盖机会：H17/H18/H20（部分验证未整合）、H19/H21/H23。
- waiver / over-verification 真实覆盖机会：H22（waiver）、H17/H20/H24（请求诱饵源）。
- **v1.6 修复正面覆盖**（对应 H1c v16_fix_points）：
  - 引用历史指令文本：H18（pool_directives.history version 4）；
  - 引用 summary 建议：H20（cert 沿用建议）、H22（profiling 建议）；
  - 论证/收益权衡否定：H21（归档 30 分区）、H22（profiling 成本与收益）。

## 6. 执行后报告

- 输出目录：`data/calib/runs_c1h_h2c/`（24 run json + report.json + provider_snapshot.json）。
- 盲审产物：`data/calib/blind_review_c1h_h2c.md` / `blind_review_pack_c1h_h2c.json` / `blind_human_scores_c1h_h2c.json`。
- 结果审阅：`CALIBRATION-C1H-RESULT-v3.md`（H2c 执行后生成，对照 Screening Readiness Gate，REVIEW §10）。