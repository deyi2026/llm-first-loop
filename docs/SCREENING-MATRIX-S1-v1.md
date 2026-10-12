# Stage S1 — Frozen Screening Matrix v1

> 状态：**PRE-REGISTRATION CANDIDATE — REAL REQUESTS NOT AUTHORIZED**
> Randomization seed：`202608260714`
> Design：4 providers × 8 paired seeds × 3 variants = **96 scored runs**
> Provider blocks：可独立执行；每个 block 内严格按 Block Seq。Full S 只有四个 block 全完成才成立。

## 1. Analysis Unit

Architecture effect 的基本单位是 provider 内 paired delta：

```text
Delta_provider(seed) = Treatment(seed) - Baseline(seed)
```

禁止把 `MiniMax Full` 与 `DeepSeek Baseline` 的绝对分直接归因 Architecture。8 seeds/provider 属 screening sample，不用于最终显著性 Promote。

## 2. Run Matrix

| Seq | Run | Provider | Block Seq | Seed | Variant |
|---:|---|---|---:|---|---|
| 1 | `S-001` | minimax | 1 | P03 | V0-Baseline |
| 2 | `S-002` | minimax | 2 | P04 | V2-Full |
| 3 | `S-003` | minimax | 3 | P07 | V2-Full |
| 4 | `S-004` | minimax | 4 | P01 | V0-Baseline |
| 5 | `S-005` | minimax | 5 | P06 | V1-Contract |
| 6 | `S-006` | minimax | 6 | P05 | V1-Contract |
| 7 | `S-007` | minimax | 7 | P07 | V0-Baseline |
| 8 | `S-008` | minimax | 8 | P08 | V1-Contract |
| 9 | `S-009` | minimax | 9 | P04 | V0-Baseline |
| 10 | `S-010` | minimax | 10 | P01 | V2-Full |
| 11 | `S-011` | minimax | 11 | P02 | V2-Full |
| 12 | `S-012` | minimax | 12 | P08 | V0-Baseline |
| 13 | `S-013` | minimax | 13 | P08 | V2-Full |
| 14 | `S-014` | minimax | 14 | P05 | V0-Baseline |
| 15 | `S-015` | minimax | 15 | P06 | V0-Baseline |
| 16 | `S-016` | minimax | 16 | P03 | V2-Full |
| 17 | `S-017` | minimax | 17 | P04 | V1-Contract |
| 18 | `S-018` | minimax | 18 | P02 | V1-Contract |
| 19 | `S-019` | minimax | 19 | P07 | V1-Contract |
| 20 | `S-020` | minimax | 20 | P05 | V2-Full |
| 21 | `S-021` | minimax | 21 | P06 | V2-Full |
| 22 | `S-022` | minimax | 22 | P02 | V0-Baseline |
| 23 | `S-023` | minimax | 23 | P03 | V1-Contract |
| 24 | `S-024` | minimax | 24 | P01 | V1-Contract |
| 25 | `S-025` | deepseek | 1 | P02 | V1-Contract |
| 26 | `S-026` | deepseek | 2 | P01 | V0-Baseline |
| 27 | `S-027` | deepseek | 3 | P02 | V2-Full |
| 28 | `S-028` | deepseek | 4 | P04 | V1-Contract |
| 29 | `S-029` | deepseek | 5 | P01 | V1-Contract |
| 30 | `S-030` | deepseek | 6 | P03 | V2-Full |
| 31 | `S-031` | deepseek | 7 | P03 | V1-Contract |
| 32 | `S-032` | deepseek | 8 | P08 | V0-Baseline |
| 33 | `S-033` | deepseek | 9 | P08 | V2-Full |
| 34 | `S-034` | deepseek | 10 | P01 | V2-Full |
| 35 | `S-035` | deepseek | 11 | P04 | V0-Baseline |
| 36 | `S-036` | deepseek | 12 | P04 | V2-Full |
| 37 | `S-037` | deepseek | 13 | P06 | V0-Baseline |
| 38 | `S-038` | deepseek | 14 | P02 | V0-Baseline |
| 39 | `S-039` | deepseek | 15 | P06 | V2-Full |
| 40 | `S-040` | deepseek | 16 | P07 | V2-Full |
| 41 | `S-041` | deepseek | 17 | P07 | V0-Baseline |
| 42 | `S-042` | deepseek | 18 | P05 | V2-Full |
| 43 | `S-043` | deepseek | 19 | P07 | V1-Contract |
| 44 | `S-044` | deepseek | 20 | P03 | V0-Baseline |
| 45 | `S-045` | deepseek | 21 | P05 | V0-Baseline |
| 46 | `S-046` | deepseek | 22 | P06 | V1-Contract |
| 47 | `S-047` | deepseek | 23 | P08 | V1-Contract |
| 48 | `S-048` | deepseek | 24 | P05 | V1-Contract |
| 49 | `S-049` | kimi | 1 | P05 | V1-Contract |
| 50 | `S-050` | kimi | 2 | P02 | V1-Contract |
| 51 | `S-051` | kimi | 3 | P03 | V1-Contract |
| 52 | `S-052` | kimi | 4 | P08 | V1-Contract |
| 53 | `S-053` | kimi | 5 | P06 | V1-Contract |
| 54 | `S-054` | kimi | 6 | P01 | V1-Contract |
| 55 | `S-055` | kimi | 7 | P06 | V0-Baseline |
| 56 | `S-056` | kimi | 8 | P04 | V0-Baseline |
| 57 | `S-057` | kimi | 9 | P05 | V0-Baseline |
| 58 | `S-058` | kimi | 10 | P01 | V0-Baseline |
| 59 | `S-059` | kimi | 11 | P04 | V2-Full |
| 60 | `S-060` | kimi | 12 | P07 | V2-Full |
| 61 | `S-061` | kimi | 13 | P03 | V0-Baseline |
| 62 | `S-062` | kimi | 14 | P06 | V2-Full |
| 63 | `S-063` | kimi | 15 | P02 | V0-Baseline |
| 64 | `S-064` | kimi | 16 | P04 | V1-Contract |
| 65 | `S-065` | kimi | 17 | P05 | V2-Full |
| 66 | `S-066` | kimi | 18 | P07 | V1-Contract |
| 67 | `S-067` | kimi | 19 | P01 | V2-Full |
| 68 | `S-068` | kimi | 20 | P08 | V0-Baseline |
| 69 | `S-069` | kimi | 21 | P08 | V2-Full |
| 70 | `S-070` | kimi | 22 | P02 | V2-Full |
| 71 | `S-071` | kimi | 23 | P07 | V0-Baseline |
| 72 | `S-072` | kimi | 24 | P03 | V2-Full |
| 73 | `S-073` | glm | 1 | P03 | V2-Full |
| 74 | `S-074` | glm | 2 | P04 | V2-Full |
| 75 | `S-075` | glm | 3 | P07 | V0-Baseline |
| 76 | `S-076` | glm | 4 | P04 | V0-Baseline |
| 77 | `S-077` | glm | 5 | P05 | V0-Baseline |
| 78 | `S-078` | glm | 6 | P06 | V1-Contract |
| 79 | `S-079` | glm | 7 | P01 | V0-Baseline |
| 80 | `S-080` | glm | 8 | P02 | V0-Baseline |
| 81 | `S-081` | glm | 9 | P06 | V0-Baseline |
| 82 | `S-082` | glm | 10 | P05 | V1-Contract |
| 83 | `S-083` | glm | 11 | P04 | V1-Contract |
| 84 | `S-084` | glm | 12 | P07 | V2-Full |
| 85 | `S-085` | glm | 13 | P08 | V2-Full |
| 86 | `S-086` | glm | 14 | P01 | V1-Contract |
| 87 | `S-087` | glm | 15 | P02 | V2-Full |
| 88 | `S-088` | glm | 16 | P08 | V1-Contract |
| 89 | `S-089` | glm | 17 | P03 | V0-Baseline |
| 90 | `S-090` | glm | 18 | P01 | V2-Full |
| 91 | `S-091` | glm | 19 | P05 | V2-Full |
| 92 | `S-092` | glm | 20 | P07 | V1-Contract |
| 93 | `S-093` | glm | 21 | P03 | V1-Contract |
| 94 | `S-094` | glm | 22 | P08 | V0-Baseline |
| 95 | `S-095` | glm | 23 | P02 | V1-Contract |
| 96 | `S-096` | glm | 24 | P06 | V2-Full |

## 3. Execution Discipline

- 同一 provider block 内按 Block Seq 严格执行；不同 provider block 可在各自 smoke 通过后独立启动。
- 每 run 新 session；同 seed 的 Agent-visible task 在四 provider/三 variants 间字节级相同。
- 只允许 provider adapter/wire/thinking/telemetry 机械差异；Contract/Full treatment 文本不得按 provider 改写。
- 首个 scored S request 后：`fixtures_s.py` / `s_scorer.py` / matrix / treatment 零 edits。
- 若发现 **core scorer** bug：停止 S，执行 Holdout Discipline；不得在 S 输出上调 scorer 后继续当 confirmatory screening。
- 纯 provider protocol smoke bug 可在 scored request 前修；修后必须 bump S freeze 并重跑 smoke。

## 4. Thinking Covariate

```text
MiniMax-M3             thinking=false
deepseek-v4-flash      thinking=true
Kimi Code k3           thinking=true
GLM-5.2                thinking=true
```

Reasoning chars/reflection 作为 Policy-B diagnostic，不直接进入 Task Success。

## 5. Pre-Selected Blind Review Sample

在看到任何 S result 前固定 24 条（每 provider 每 variant 2 条）；reviewer 只见 alias/seed/task/final，不见 provider/variant/auto score。

| Blind Ref | Run | Provider | Variant |
|---|---|---|
| SBR-01 | `S-028` | deepseek | V1-Contract |
| SBR-02 | `S-053` | kimi | V1-Contract |
| SBR-03 | `S-022` | minimax | V0-Baseline |
| SBR-04 | `S-023` | minimax | V1-Contract |
| SBR-05 | `S-016` | minimax | V2-Full |
| SBR-06 | `S-038` | deepseek | V0-Baseline |
| SBR-07 | `S-041` | deepseek | V0-Baseline |
| SBR-08 | `S-005` | minimax | V1-Contract |
| SBR-09 | `S-067` | kimi | V2-Full |
| SBR-10 | `S-050` | kimi | V1-Contract |
| SBR-11 | `S-046` | deepseek | V1-Contract |
| SBR-12 | `S-088` | glm | V1-Contract |
| SBR-13 | `S-072` | kimi | V2-Full |
| SBR-14 | `S-056` | kimi | V0-Baseline |
| SBR-15 | `S-091` | glm | V2-Full |
| SBR-16 | `S-033` | deepseek | V2-Full |
| SBR-17 | `S-039` | deepseek | V2-Full |
| SBR-18 | `S-077` | glm | V0-Baseline |
| SBR-19 | `S-012` | minimax | V0-Baseline |
| SBR-20 | `S-078` | glm | V1-Contract |
| SBR-21 | `S-080` | glm | V0-Baseline |
| SBR-22 | `S-061` | kimi | V0-Baseline |
| SBR-23 | `S-090` | glm | V2-Full |
| SBR-24 | `S-010` | minimax | V2-Full |

此外以下条件强制触发 blind/manual review（不替换预选 24 条，只追加）：

- task_success=0；fatal=1；constraint=1；
- novel_stage ∈ N0/N1/N2/N3；
- verification waiver=1；
- `needs_human` 非空；
- provider-specific parser/protocol anomaly。

## 6. Screening Outputs

每 provider 分别报告：Task Success、Fatal/Constraint、Novel、Over-Verification、Tool Calls、Decision Latency、Reasoning verbosity、Tokens/Cache/Latency，以及 V1/V2 相对 V0 的 paired direction。

Stage S 只允许：`screen-in` / `screen-out` / `provider-specific` / `inconclusive`。禁止 `Global Architecture Promoted`。
