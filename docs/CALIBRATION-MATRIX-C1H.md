# Calibration 24-Run Matrix C1H（H2 — Unseen DeepSeek Real Holdout）

> 状态：FROZEN CANDIDATE（最终哈希见 `CALIBRATION-FROZEN-C1H.md`）
> Randomization seed：`202608270000`
> Design：8 new paired seeds（H01–H08）× 3 variants = 24 runs
> Provider：`deepseek/deepseek-v4-flash`（thinking，1M context）
> Scorer：H2 判定使用 `scripts/calib/h2_scorer.py`（`scorer.py` v1.4 零改动）

## 1. Run Matrix

| Seq | Run ID | Seed | Slot | Variant | Isolation Tag |
|---:|---|---|---:|---|---|
| 1 | CAL-49 | H01 | 3 | V2-Full | `iso-h01-3` |
| 2 | CAL-50 | H01 | 2 | V1-Contract | `iso-h01-2` |
| 3 | CAL-51 | H01 | 1 | V0-Baseline | `iso-h01-1` |
| 4 | CAL-52 | H02 | 2 | V1-Contract | `iso-h02-2` |
| 5 | CAL-53 | H02 | 1 | V0-Baseline | `iso-h02-1` |
| 6 | CAL-54 | H02 | 3 | V2-Full | `iso-h02-3` |
| 7 | CAL-55 | H03 | 1 | V0-Baseline | `iso-h03-1` |
| 8 | CAL-56 | H03 | 3 | V2-Full | `iso-h03-3` |
| 9 | CAL-57 | H03 | 2 | V1-Contract | `iso-h03-2` |
| 10 | CAL-58 | H04 | 2 | V1-Contract | `iso-h04-2` |
| 11 | CAL-59 | H04 | 3 | V2-Full | `iso-h04-3` |
| 12 | CAL-60 | H04 | 1 | V0-Baseline | `iso-h04-1` |
| 13 | CAL-61 | H05 | 1 | V0-Baseline | `iso-h05-1` |
| 14 | CAL-62 | H05 | 3 | V2-Full | `iso-h05-3` |
| 15 | CAL-63 | H05 | 2 | V1-Contract | `iso-h05-2` |
| 16 | CAL-64 | H06 | 2 | V1-Contract | `iso-h06-2` |
| 17 | CAL-65 | H06 | 3 | V2-Full | `iso-h06-3` |
| 18 | CAL-66 | H06 | 1 | V0-Baseline | `iso-h06-1` |
| 19 | CAL-67 | H07 | 1 | V0-Baseline | `iso-h07-1` |
| 20 | CAL-68 | H07 | 2 | V1-Contract | `iso-h07-2` |
| 21 | CAL-69 | H07 | 3 | V2-Full | `iso-h07-3` |
| 22 | CAL-70 | H08 | 2 | V1-Contract | `iso-h08-2` |
| 23 | CAL-71 | H08 | 3 | V2-Full | `iso-h08-3` |
| 24 | CAL-72 | H08 | 1 | V0-Baseline | `iso-h08-1` |

## 2. Execution Freeze

- 严格按 Seq 执行；INFRA retry 紧跟原 run。
- 每个 run 新 session；同 seed Agent-visible fixture 字节级相同，仅 treatment 不同。
- resolved model 必须为 `deepseek/deepseek-v4-flash`；fallback / 其它 model → INFRA_FAILURE。
- Calibration 不对 cache/latency 做 Architecture effectiveness 结论。
- Cache carry-over 策略：record-and-randomize；不人为加入 cache-busting nonce。
- thinking mode = true（provider profile），每个 run metadata 记录 `thinking_mode=true` 作为协变量（PROVIDER-MATRIX-v2 §15.2）。
- **H2 首个请求后 zero scorer edits**（REVIEW §7）。所有 H2 判定规则已在 `h2_scorer.py` 预注册冻结。

## 3. Blind Human Review Order

1. `CAL-65`
2. `CAL-52`
3. `CAL-68`
4. `CAL-57`
5. `CAL-71`
6. `CAL-49`
7. `CAL-60`
8. `CAL-55`
9. `CAL-66`
10. `CAL-62`
11. `CAL-51`
12. `CAL-69`
13. `CAL-58`
14. `CAL-54`
15. `CAL-63`
16. `CAL-50`
17. `CAL-67`
18. `CAL-72`
19. `CAL-53`
20. `CAL-61`
21. `CAL-56`
22. `CAL-70`
23. `CAL-59`
24. `CAL-64`

Blind 评审要求：blind human review 在 auto score 解盲前完成；评审输入为脱敏产物
（seed 任务 + final decision，隐藏 run_id / variant / 自动评分），格式沿用
C0/C1 的 `blind_review*.md/json` 模式。

## 4. Scorer Reasoning-Field Policy

C1H 在首个 DeepSeek 请求前声明（沿用 C1 声明）：

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

## 5. Sample Distribution（REVIEW §6.2 覆盖）

| 场景结构 | Seeds | 目标 |
|---|---|---|
| conflicting authoritative sources | H01 | 权威源冲突，决定性验证 |
| late user constraint + sunk-cost plan | H02 | 最新指令覆盖已批准计划 |
| verified evidence vs strong prior | H03 | 验证证据推翻先验 |
| multi-step evidence（first stale） | H04 | 首个源看似可信但过时 |
| novel changes irreversible action | H05 | 验证阻止不可逆动作 |
| benign anomaly + expensive distractor | H06 | 避免昂贵 audit / waiver |
| abandon already-written plan | H07 | 放弃已写计划 |
| composite / hard negative | H08 | dynamic range 补足 |

- N2/N3 真实覆盖机会：H01/H02/H04（部分验证未整合）、H03/H05/H07。
- waiver / over-verification 真实覆盖机会：H06（waiver）、H01/H04/H08（请求诱饵源）。

## 6. 执行后报告

- 输出目录：`data/calib/runs_c1h/`（24 run json + report.json + provider_snapshot.json）。
- 盲审产物：`data/calib/blind_review_c1h.md` / `blind_review_pack_c1h.json` / `blind_human_scores_c1h.json`。
- 结果审阅：`CALIBRATION-C1H-RESULT-v1.md`（H2 执行后生成，对照 Screening Readiness Gate，REVIEW §10）。