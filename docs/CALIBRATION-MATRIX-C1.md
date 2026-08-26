# Calibration 18-Run Matrix C1（DeepSeek Cross-Style）

> 状态：FROZEN CANDIDATE（最终哈希见 `CALIBRATION-FROZEN-C1.md`）
> Randomization seed：`202608260000`
> Design：6 paired seeds（T01–T06）× 3 variants = 18 runs
> Provider：`deepseek/deepseek-v4-flash`（thinking，1M context）

## 1. Run Matrix

| Seq | Run ID | Seed | Slot | Variant | Isolation Tag |
|---:|---|---|---:|---|---|
| 1 | CAL-31 | T01 | 3 | V2-Full | `iso-t01-3` |
| 2 | CAL-32 | T01 | 2 | V1-Contract | `iso-t01-2` |
| 3 | CAL-33 | T01 | 1 | V0-Baseline | `iso-t01-1` |
| 4 | CAL-34 | T02 | 2 | V1-Contract | `iso-t02-2` |
| 5 | CAL-35 | T02 | 1 | V0-Baseline | `iso-t02-1` |
| 6 | CAL-36 | T02 | 3 | V2-Full | `iso-t02-3` |
| 7 | CAL-37 | T03 | 1 | V0-Baseline | `iso-t03-1` |
| 8 | CAL-38 | T03 | 3 | V2-Full | `iso-t03-3` |
| 9 | CAL-39 | T03 | 2 | V1-Contract | `iso-t03-2` |
| 10 | CAL-40 | T04 | 2 | V1-Contract | `iso-t04-2` |
| 11 | CAL-41 | T04 | 3 | V2-Full | `iso-t04-3` |
| 12 | CAL-42 | T04 | 1 | V0-Baseline | `iso-t04-1` |
| 13 | CAL-43 | T05 | 2 | V1-Contract | `iso-t05-2` |
| 14 | CAL-44 | T05 | 3 | V2-Full | `iso-t05-3` |
| 15 | CAL-45 | T05 | 1 | V0-Baseline | `iso-t05-1` |
| 16 | CAL-46 | T06 | 1 | V0-Baseline | `iso-t06-1` |
| 17 | CAL-47 | T06 | 2 | V1-Contract | `iso-t06-2` |
| 18 | CAL-48 | T06 | 3 | V2-Full | `iso-t06-3` |

## 2. Execution Freeze

- 严格按 Seq 执行；INFRA retry 紧跟原 run。
- 每个 run 新 session；同 seed Agent-visible fixture 字节级相同，仅 treatment 不同。
- resolved model 必须为 `deepseek/deepseek-v4-flash`；fallback / 其它 model → INFRA_FAILURE。
- Calibration 不对 cache/latency 做 Architecture effectiveness 结论。
- Cache carry-over 策略：record-and-randomize；不人为加入 cache-busting nonce。
- thinking mode = true（provider profile），每个 run metadata 记录 `thinking_mode=true` 作为协变量（PROVIDER-MATRIX-v2 §15.2）。

## 3. Blind Human Review Order

1. `CAL-46`
2. `CAL-38`
3. `CAL-43`
4. `CAL-39`
5. `CAL-40`
6. `CAL-48`
7. `CAL-37`
8. `CAL-41`
9. `CAL-33`
10. `CAL-42`
11. `CAL-45`
12. `CAL-36`
13. `CAL-32`
14. `CAL-35`
15. `CAL-47`
16. `CAL-34`
17. `CAL-31`
18. `CAL-44`

## 4. Scorer Reasoning-Field Policy（PROVIDER-MATRIX-v2 §15.1，三选一声明）

C1 在首个 DeepSeek 请求前强制声明 reasoning 字段处理方式：

```text
Policy: B (verbosity)
```

含义：

- scorer v1.2 读取 `reasoning` 字段（DeepSeek thinking 输出）。
- `reasoning_chars` 与 `reasoning_reflection_count` 作为 Decision Latency / Unnecessary Verification 的 verbosity 维度计入观测。
- task_success / novel_stage / fatal / constraint 的判定仍以 `final_answer` 与 `requested_sources` 为准，不因 reasoning 内容直接改判（防止 reasoning 与 answer 语义漂移污染核心指标）。
- 新增输出字段：

```yaml
reasoning_chars: int                # 本轮 reasoning 文本总字符数
reasoning_reflection_count: int     # reasoning 中过度反思标记出现次数（re-verify / double-check / 再确认 等）
```

- 若某 run 缺失 reasoning 字段（应不会发生，thinking=true），记录 0 并标注 `reasoning_missing: 1`。

## 5. Sample Distribution（对应 C0 Gate 空缺）

| 样本形态 | Seeds | 目标 |
|---|---|---|
| decision-relevant novel signal | T01, T06 | 验证 novel 结果确实改变决策，而非仅记录 |
| natural hard negative | T01, T03, T06 | 提供真实 Task Success negative 的可能性，校准 specificity |
| verified-but-not-integrated → N3 | T02, T05 | 制造 N3 真实判分样本 |
| benign unknown / over-verification | T04 | 观测 unnecessary_verification_count |
| cross-style expression robustness | T05（全 seeds 通用） | scorer 同义覆盖中英文表达 |