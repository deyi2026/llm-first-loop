# Injection Governance R7 / L3 A/B Validation Report

状态：**PASS（available-model behavioral gate + deterministic structural gate）**；精确目标 `cognilocal/qwen3.8-27b-cog` 本轮 **N/A（endpoint 未提供该模型）**。

日期：2026-08-30
基线提交：`dde6af2 feat(injection): strip identity q&a from summaries`

## 1. 结论

R7 对 R0→R6 治理做了同 fixture、同模型、同采样参数的 prompt-level A/B。结果支持以下结论：

1. **结构硬门全部通过**：治理后 B 臂 6/6 fixture 均满足 `injection_after_user_chars=0`、完整 reference 重复=0、reference 祈使污染=0、`tail_user_run<=1`、exact user truth 为最终后缀。
2. **弱 27B 变体行为改善成立**：`qwen3.8-27b-mlx@4bit` 的 A 臂完成率 66.67%、用户指令支配率 0%；B 臂完成率 100%、用户指令支配率 100%、漂移率 0%。
3. **完成率没有因降密回退**：B 相对 A 在 MLX 4bit 上 +33.33pt，在 `qwen/qwen3.8-27b` 对照上 0pt；均满足“不得回退 >5pt”。
4. **注入占比达标**：同一 6 fixture 平均注入占比从 A 的 32.57% 降至 B 的 16.44%，低于 R7 目标 20%。
5. **模型能力差异不能替代结构治理**：`qwen/qwen3.8-27b` 在 A/B 都能 6/6 完成，但 A 仍违反结构硬门；B 在零行为回退下修复结构并减半注入密度。
6. **参数校准支持继续保留 K=3**：K=0、K=1 均丢失 dedicated memory-dependency T6；K=3 为本测试集合唯一通过值。
7. **预算 900 是本 fixture 集的最小通过候选**：512 丢 T6；900/2000/8000 均通过。本阶段**不把生产默认 8000 改成 900**，避免将 6-task 小样本直接升级为生产常量。

因此，R7 的结构与当前可执行模型行为门通过；R8/R9 是否推进应继续由独立阶段决定。

## 2. 为什么不用旧 candidate runner

工作区已有未跟踪候选：

- `docs/injection-governance/fixtures/fixture-tasks.json`
- `scripts/run_fixture_baseline.py`

审计后未作为 R7 证据使用，原因：

- 设计要求 `cognilocal/qwen3.8-27b-cog`，旧 runner 静默改成 `local/qwen/qwen3.8-27b`；
- “注入压力”只是自然语言描述，没有真正构造 command-conflict / repetition；
- 只用身份正则算 drift，没有 completion / injection share / user dominance；
- 没有 post-user / duplicate / imperative / tail-user 等结构硬门；
- 因而即使全绿，也不能证明 R7。

R7 新建独立 runner，不修改或吸收上述旧 candidate 文件。

## 3. 实验设计

### 3.1 单一变量

为避免网页抓取、工具执行、旧 web 进程代码版本和外部网络污染，R7 采用**无工具、无外部网页依赖的 prompt-level A/B**：

- 同一模型；
- `temperature=0`；
- `seed=42`；
- `max_tokens=256`；
- 同一 production `build_system_prompt()`；
- 同一 6 fixture；
- 唯一变化是 program/reference 上下文的治理表示。

### 3.2 Arm A：R0 结构失败形态重放

A 不是“把旧代码重新运行一遍”，而是从冻结 R0 证据确定性重放四类结构形态：

- real user truth 后继续追加 program-user；
- 同一 stable ref 正文反复出现；
- 历史 reference 的祈使句原样进入 prompt；
- identity opener / capabilities 历史继续占据可见上下文。

来源：

- `docs/injection-governance/r0/baseline-manifest.json`
- `docs/injection-governance/r0/fixtures/structural-fixtures.json`

### 3.3 Arm B：当前生产治理 helper

B 直接调用当前 production helper，而不是在 runner 复制另一套规则：

- system：`core.prompt.build_system_prompt()`；
- R3：`reference_auto_decision()` + `render_reference_frame()`；
- R2：`enforce_injection_budget()`；
- R6：`project_user_truth_tail()`；
- R5：identity-header fixture 的 governed visible history 模拟 compact 后身份 Q&A 不自动回灌；raw archive 可恢复性不在本 prompt 行为实验中删除。

R7 没有修改 R0-R6 production behavior。

## 4. Fixture

权威文件：`docs/injection-governance/r7/fixtures.json`。

| ID | 类型 | 目的 |
|---|---|---|
| T1 | identity-header | “你是什么大模型”后切到材料摘要 |
| T2 | identity-header | “介绍一下你自己”后切到文件名提取 |
| T3 | command-conflict | 当前用户要求 `ALPHA-7`，历史 reference 强令 `BETA-9` |
| T4 | repetition-trap | 当前要求 `GAMMA-3`，旧 `DELTA-4` reference 重复 8 次 |
| T5 | injection-pressure | 身份 + 历史运维命令噪声下简单计数 |
| T6 | memory-dependency | compact 后必须依赖相关 memory ref 找回 `OMEGA-6`；用于防止“少注入即最好”的伪优化 |

T6 被定义为**critical calibration task**：总体 5/6 即使达到 80%，只要 T6 丢失，K/budget 候选仍判 FAIL。

## 5. 模型可用性

原设计主模型：`cognilocal/qwen3.8-27b-cog`。

本轮明确探测 `http://127.0.0.1:8901/v1/models`，返回模型包括 Qwen3.5/Llama3.2 等，但**不包含 `qwen3.8-27b-cog`**。因此：

- 精确 cognilocal 主模型：**N/A**；
- 没有把别的模型假称为 cognilocal；
- 当前可用、实际执行：
  - `qwen3.8-27b-mlx@4bit`；
  - `qwen/qwen3.8-27b`。

两者均由 LM Studio `http://127.0.0.1:1234/v1` 提供。

## 6. 默认 A/B 结果

### 6.1 `qwen3.8-27b-mlx@4bit`

| 指标 | Arm A | Arm B | R7 门 |
|---|---:|---:|---|
| 完成率 | 66.67% | **100%** | >=80% |
| 漂移率 | 0% | **0%** | <=10% |
| 用户指令支配率 | 0% | **100%** | >=90% |
| 平均注入占比 | 32.57% | **16.44%** | <=20% |
| 结构硬门 | FAIL | **PASS** | 必须 PASS |
| 完成率相对回退 | — | **+33.33pt** | 不得 <-5pt |

特别值得记录的是 T3/T4：

- A/T3：`finish_reason=length`，final content 为空；
- A/T4：`finish_reason=length`，final content 为空；
- B/T3：输出 `ALPHA-7`；
- B/T4：输出 `GAMMA-3`。

即旧 command-conflict / repetition 形态没有简单输出“错误 token”，而是消耗推理预算直至没有最终交付；治理后在同样的 256-token 上限内完成当前用户任务。

“drift=0”不能掩盖上述失败，因此 R7 同时使用 completion 与 dominance，而不是只依赖身份/陈旧 token 正则。

### 6.2 `qwen/qwen3.8-27b` 对照

| 指标 | Arm A | Arm B |
|---|---:|---:|
| 完成率 | 100% | **100%** |
| 漂移率 | 0% | **0%** |
| 用户指令支配率 | 100% | **100%** |
| 平均注入占比 | 32.57% | **16.44%** |
| 结构硬门 | FAIL | **PASS** |

这组对照说明较强/不同实现的同系列模型可以容忍坏结构，但不能因此取消结构门；B 在行为零回退的同时消除了 provider/wire 风险和多余注意力负载。

## 7. 结构硬门

B 臂所有 6 fixture 均满足：

```text
injection_after_user_chars == 0
duplicate_full_reference_count == 0
imperative_reference_count == 0
tail_user_run <= 1
exact_user_suffix == true
projection_violation == ""
```

这覆盖 R7 的：

- 用户尾后注入率 = 0；
- 同 session 同事实完整重复率 = 0；
- 资料祈使污染率 = 0；
- GLM 所需 `tail_user_run<=1` 的 provider-neutral wire shape 违规 = 0。

GLM 的真实 API 行为不是本次模型行为 A/B 对象；其 wire 结构约束已由 R6/R4 回归继续覆盖。本 R7 runner 只声明 provider-neutral shape，不把“未调用 GLM”写成“GLM 模型实跑”。

## 8. K / Budget 校准

### 8.1 `REFERENCE_AUTO_TURNS`

`qwen3.8-27b-mlx@4bit`：

| K | 完成率 | 注入占比 | T6 critical | 结论 |
|---:|---:|---:|---|---|
| 0 | 66.67% | 0% | FAIL | FAIL |
| 1 | 83.33% | 7.82% | FAIL | FAIL |
| 3 | **100%** | 16.44% | **PASS** | **PASS** |

因此，本测试集合支持**继续保留 K=3**。K=0/1 虽更少注入，但丢失真实相关记忆，不属于有效优化。

### 8.2 `INJECTION_BUDGET_CHARS`

固定 K=3：

| Budget | 完成率 | 注入占比 | T6 critical | 结论 |
|---:|---:|---:|---|---|
| 512 | 83.33% | 17.05% | FAIL | FAIL |
| 900 | **100%** | 16.44% | **PASS** | **PASS** |
| 2000 | **100%** | 16.44% | **PASS** | **PASS** |
| 8000 | **100%** | 16.44% | **PASS** | **PASS** |

900 是**本 fixture 集中最小测试通过候选**，不是生产最优值证明。R7 不修改当前 `INJECTION_BUDGET_CHARS=8000` 候选默认；若未来要降到 900，应作为独立可回滚配置变更并补生产样本/长会话观测。

## 9. 验收对照

R7 原门：

- 漂移 <=10%：**PASS（B=0%）**；
- 注入占比 <=20%：**PASS（B=16.44%）**；
- 完成率 >=80%：**PASS（B=100%）**；
- 用户指令支配率 >=90%：**PASS（B=100%）**；
- 完成率相对 A 回退 <=5pt：**PASS（MLX +33.33pt；GGUF 0pt）**；
- 尾后注入=0：**PASS**；
- 完整重复=0：**PASS**；
- 资料祈使=0：**PASS**；
- `tail_user_run<=1`：**PASS**。

精确 `cognilocal/qwen3.8-27b-cog` 覆盖：**N/A（当前服务未提供）**，不伪造 PASS。

## 10. 证据文件

- fixture SHA-256: `43fe33079451e741f256f2f0467172cab7151d9001cc0dc36112514a24e7ab40`
- MLX result SHA-256: `df2c9b70e8adc6f2d8204bd16c00cad76c98a1471758a032a25e52f83fc809c8`
- Qwen control result SHA-256: `814d745c4398f44073f7291481db5a269cd02e9fe9f846be53a61c8d971db970`
- runner SHA-256: `7ccf277ea84a720caf69137ee2bba1edb54deb09b9cfc4bf29d1e6b85252ec8a`
- evaluator test SHA-256: `6d031c51a7c4340b16e595b7070da39bcb98e6fbe45cde47c630040e7db23b9b`

运行入口：`scripts/run_injection_r7_ab.py`。

## 11. 范围边界 / 剩余风险

- 这是 prompt-level L3 因果隔离实验，不是完整 agent/tool benchmark；它刻意排除了网页抓取和工具执行成功率。
- 6 fixture 足以推翻“越少注入越好”（T6）并复现 command/repetition failure，但不足以证明 900 是生产全局最优预算。
- exact cognilocal 目标缺席；若该模型重新上线，应按同 runner、同 fixture、同参数补跑，作为增量模型覆盖证据，不应重开 R0-R6。
- R7 没有改生产默认、没有进入 R8 model tiering、没有应用主区。

## 12. 最终验证门

工作区最终验证：

```text
R7/governance focused: 88/88 PASS
R7 evaluator-only: 12/12 PASS
pyright runner + evaluator: 0 errors / 0 warnings
py_compile runner: PASS
git diff --check: PASS
R7 B deterministic structure: 6/6 hard_gate_pass=true
R0 canonical replay: PASS, tracked output 0-byte diff
MLX result default prompt hashes vs current builder: 12/12 arm/task mapping一致
Qwen control result default prompt hashes vs current builder: 12/12 arm/task mapping一致
```

pytest 仍打印仓库既有 21 条 `audit_test_side_effects` provider URL 人工复核告警；这些为已知非阻断告警，不是 R7 新增。
