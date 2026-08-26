# Calibration 24-Run Matrix C1H-H2B（Holdout Round 2 — Unseen DeepSeek Real Holdout）

> 状态：FROZEN CANDIDATE（最终哈希见 `CALIBRATION-FROZEN-C1H-v2.md`）
> Randomization seed：`202609010000`
> Design：8 new paired seeds（H09–H16）× 3 variants = 24 runs
> Provider：`deepseek/deepseek-v4-flash`（thinking，1M context）
> Scorer：H2b 判定使用 `scripts/calib/h2_scorer.py` v1.5-h2（`scorer.py` v1.4 零改动）
> 背景：H2（H01-H08，CAL-49..CAL-72）按 Holdout Discipline 判 FAIL 转为 development data；
>   H2b（H09-H16）为全新 holdout round，文本与 H2/C0/C1 完全不同。

## 1. Run Matrix

| Seq | Run ID | Seed | Slot | Variant | Isolation Tag |
|---:|---|---|---:|---|---|
| 1 | CAL-73 | H09 | 3 | V2-Full | `iso-h09-3` |
| 2 | CAL-74 | H09 | 2 | V1-Contract | `iso-h09-2` |
| 3 | CAL-75 | H09 | 1 | V0-Baseline | `iso-h09-1` |
| 4 | CAL-76 | H10 | 2 | V1-Contract | `iso-h10-2` |
| 5 | CAL-77 | H10 | 1 | V0-Baseline | `iso-h10-1` |
| 6 | CAL-78 | H10 | 3 | V2-Full | `iso-h10-3` |
| 7 | CAL-79 | H11 | 1 | V0-Baseline | `iso-h11-1` |
| 8 | CAL-80 | H11 | 3 | V2-Full | `iso-h11-3` |
| 9 | CAL-81 | H11 | 2 | V1-Contract | `iso-h11-2` |
| 10 | CAL-82 | H12 | 2 | V1-Contract | `iso-h12-2` |
| 11 | CAL-83 | H12 | 3 | V2-Full | `iso-h12-3` |
| 12 | CAL-84 | H12 | 1 | V0-Baseline | `iso-h12-1` |
| 13 | CAL-85 | H13 | 1 | V0-Baseline | `iso-h13-1` |
| 14 | CAL-86 | H13 | 3 | V2-Full | `iso-h13-3` |
| 15 | CAL-87 | H13 | 2 | V1-Contract | `iso-h13-2` |
| 16 | CAL-88 | H14 | 2 | V1-Contract | `iso-h14-2` |
| 17 | CAL-89 | H14 | 3 | V2-Full | `iso-h14-3` |
| 18 | CAL-90 | H14 | 1 | V0-Baseline | `iso-h14-1` |
| 19 | CAL-91 | H15 | 1 | V0-Baseline | `iso-h15-1` |
| 20 | CAL-92 | H15 | 2 | V1-Contract | `iso-h15-2` |
| 21 | CAL-93 | H15 | 3 | V2-Full | `iso-h15-3` |
| 22 | CAL-94 | H16 | 2 | V1-Contract | `iso-h16-2` |
| 23 | CAL-95 | H16 | 3 | V2-Full | `iso-h16-3` |
| 24 | CAL-96 | H16 | 1 | V0-Baseline | `iso-h16-1` |

## 2. Execution Freeze

- 严格按 Seq 执行；INFRA retry 紧跟原 run。
- 每个 run 新 session；同 seed Agent-visible fixture 字节级相同，仅 treatment 不同。
- resolved model 必须为 `deepseek/deepseek-v4-flash`；fallback / 其它 model → INFRA_FAILURE。
- Calibration 不对 cache/latency 做 Architecture effectiveness 结论。
- Cache carry-over 策略：record-and-randomize；不人为加入 cache-busting nonce。
- thinking mode = true（provider profile），每个 run metadata 记录 `thinking_mode=true` 作为协变量（PROVIDER-MATRIX-v2 §15.2）。
- **H2b 首个请求后 zero scorer edits**（REVIEW §7 / FROZEN-C1H §5）。所有 H2b 判定规则已在 `h2_scorer.py` v1.5-h2 预注册冻结。

## 3. Blind Human Review Order

1. `CAL-89`
2. `CAL-73`
3. `CAL-77`
4. `CAL-75`
5. `CAL-93`
6. `CAL-84`
7. `CAL-90`
8. `CAL-79`
9. `CAL-80`
10. `CAL-86`
11. `CAL-88`
12. `CAL-78`
13. `CAL-83`
14. `CAL-81`
15. `CAL-85`
16. `CAL-74`
17. `CAL-94`
18. `CAL-92`
19. `CAL-95`
20. `CAL-76`
21. `CAL-87`
22. `CAL-82`
23. `CAL-96`
24. `CAL-91`

Blind 评审要求：blind human review 在 auto score 解盲前完成；评审输入为脱敏产物
（seed 任务 + final decision，隐藏 run_id / variant / 自动评分），格式沿用
C0/C1 的 `blind_review*.md/json` 模式。

## 4. Scorer Reasoning-Field Policy

C1H-H2b 在首个 DeepSeek 请求前声明（沿用 C1/C1H 声明）：

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

## 5. Sample Distribution（REVIEW §6.2 覆盖，与 H2 一一对应）

| 场景结构 | Seeds | 目标 |
|---|---|---|
| conflicting authoritative sources | H09 | 权威源冲突，决定性验证 |
| late user constraint + sunk-cost plan | H10 | 最新指令覆盖已批准计划 |
| verified evidence vs strong prior | H11 | 验证证据推翻先验 |
| multi-step evidence（first stale） | H12 | 首个源看似可信但过时 |
| novel changes irreversible action | H13 | 验证阻止不可逆动作 |
| benign anomaly + expensive distractor | H14 | 避免昂贵 tracing / waiver |
| abandon already-written plan | H15 | 放弃已写计划 |
| composite / hard negative | H16 | dynamic range 补足 |

- N2/N3 真实覆盖机会：H09/H10/H12（部分验证未整合）、H11/H13/H15。
- waiver / over-verification 真实覆盖机会：H14（waiver）、H09/H12/H16（请求诱饵源）。

## 6. 执行后报告

- 输出目录：`data/calib/runs_c1h_h2b/`（24 run json + report.json + provider_snapshot.json）。
- 盲审产物：`data/calib/blind_review_c1h_h2b.md` / `blind_review_pack_c1h_h2b.json` / `blind_human_scores_c1h_h2b.json`。
- 结果审阅：`CALIBRATION-C1H-RESULT-v2.md`（H2b 执行后生成，对照 Screening Readiness Gate，REVIEW §10）。