# R2/L2-1 统一注入预算硬上限验收报告

> Goal: `9aa8f0a3-aca6-4765-ba5c-182578290bff`
> Base: `34b6706 feat(injection): enforce L1 semantic boundaries`
> Date: 2026-08-30
> Verdict: **PASS**

## 1. 范围

R2 只落地一个行为：**所有 prompt-visible program-origin 自动附录共享同一个硬字符预算**。

本阶段不做：

- R3 的 K 轮按需、指针化、session seen-set/去重；
- R4 的恢复次数/单恢复边界策略；
- R5 的身份问答剥离；
- R6 的 user truth 物理尾位重排；
- R7/L3 的模型行为 A/B 与最终参数校准。

因此 `8000` 只能称为 **R2 候选默认值**，不能称为最佳值或最终值。

## 2. 单一预算 SoT

新增 `src/llm_loop/core/injection_budget.py`，预算相关规则集中在该模块：

- `DEFAULT_INJECTION_BUDGET_CHARS = 8000`；
- `MIN_INJECTION_BUDGET_CHARS = 512`；
- `BudgetBlock`：不可分割预算单元；
- `BudgetPriority`：唯一优先级；
- `plan_prompt_injection_budget(...)`：统一收集 + plan；
- `enforce_injection_budget(...)`：唯一 keep/drop 裁决器。

`build.py` 不再定义来源级预算，只负责把中央 plan 应用到实际 prompt 结构。

配置接线：

- `Settings.injection_budget_chars`；
- env `INJECTION_BUDGET_CHARS`；
- `.env.example` 明示 `8000` 为候选值；
- 小于 512 的配置运行时钳制到 512，保证超限回执本身仍能计入同一硬预算。

## 3. 覆盖面

一次预算裁决覆盖三类真实 prompt material：

1. **persisted program-origin**：已经进入 history/build `built` 的 memory / experience / model-switch / status / recovery 等；
2. **current dynamic parts**：`_inject_parts` 的 memory fallback / interop / tip / hotcard / gate / frontier 等；
3. **Cognitive enforce projection**：`_packet_parts` 以及 semantic decision header；非 packet 路径则覆盖 task anchor。

特别锁定了一个绕过边界：`COG_RUNTIME_MODE=off` 且本轮没有新 `_inject_parts` 时，历史中只要存在 program-origin 块，仍必须进入 R2 budget gate。

R1 的显式 semantic label 是 persisted program-origin 的识别锚；普通用户正文没有显式 program label 时不会被预算器误分类。

## 4. 统一优先级与整块裁决

从高到低：

1. budget receipt；
2. `[任务·程序恢复]`；
3. critical status：decision header / task anchor / task frontier / interop / gate note；
4. 其他 `[通知·状态]`；
5. `[资料·记忆/经验]` reference。

同级内当前动态块优先于陈旧 persisted history；persisted history 内越新的越先。

R2 只允许两种结果：**完整保留一个 block** 或 **完整丢弃一个 block**。预算器不做字符串切半、不保留半个 reference frame。

## 5. 超限回执

当总候选成本超过预算：

`[注入预算] 本轮自动程序附录超过候选预算上限 N 字符；部分低优先级块未进入请求。该记录仅描述本轮组装结果。`

性质：

- 纯事实，不含“请/必须/继续/调用”等祈使动作；
- 自身是 `[通知·状态]`；
- receipt 自身的 slot/outer-wrapper 成本也计入同一个预算；
- `action.injection_budget/pruned` 记录 `used/budget` 与 dropped block 数量。

## 6. 与 Cognitive packet 预算的关系

现有 `COG_RUNTIME_PACKET_BUDGET=2000` 没有被冒充为总预算。它是 Cognitive Runtime 内部的 WARM 投影压缩约束，发生后只会进一步减少 packet。

R2 `INJECTION_BUDGET_CHARS` 才是跨 persisted/dynamic/packet 来源的最终总上限；预算 accounting 在 compiler 渲染前按原始/保守成本计费，所以 packet 后续压缩不会突破 R2，只会让实际 wire 更小。

## 7. 硬门证据

### 7.1 专项测试

`tests/unit/test_injection_budget.py`：**7 PASS**，覆盖：

- priority + whole-block keep/drop；
- `used_chars <= budget`；
- receipt 非祈使且在同预算计费；
- dynamic group overhead 只计一次；
- 普通 user text 不误判 program-origin；
- production-shape dynamic appendix 端到端；
- Cognitive=off persisted-only 绕过回归；
- env 1024 生效、1 钳制到 512（同测试文件配置断言）。

### 7.2 实际 wire 矩阵

使用 R1/1210 production-shape fixture，off/shadow/enforce 各跑 512/700/900/2000/8000：

| mode | budget | accounting used | actual program chars | dropped |
|---|---:|---:|---:|---:|
| off | 512 | 447 | 338 | 3 |
| off | 900 | 884 | 731 | 2 |
| off | 8000 | 2055 | 1832 | 0 |
| shadow | 512 | 447 | 338 | 3 |
| shadow | 900 | 884 | 731 | 2 |
| shadow | 8000 | 2055 | 1832 | 0 |
| enforce | 512 | 447 | 312 | 3 |
| enforce | 900 | 884 | 353 | 2 |
| enforce | 8000 | 2055 | 1408 | 0 |

完整矩阵还包含 700/2000 两档，全部满足：

`actual program chars <= accounting used <= INJECTION_BUDGET_CHARS`

### 7.3 R1 + R2 regression

R1 报告原覆盖面 + R2 + CR invariants/compiler/integration：**199 PASS**。

静态质量：

- touched production `py_compile`: PASS；
- touched production `pyright`: **0 errors / 0 warnings**；
- `git diff --check`: PASS；
- ruff 在当前 venv 未安装，因此未伪造 ruff 结果。

额外运行 broader config suite 时有 **1 个既有失败**：`tests/unit/test_config.py::test_load_settings_full` 仍断言默认 `data_dir == "./data"`，但当前 R1 base 的 `config.py` 已在更早的 split-brain 修复中改为仓库绝对 data 路径。R2 未修改该语义，也未借本阶段顺手修测试债务。

### 7.4 R0 frozen regression

- `analysis_injection_baseline.py`: `R0-1` ~ `R0-4` 全 PASS；
- `tests/unit/test_injection_baseline_analysis.py`: **4 PASS**；
- `git diff -- docs/injection-governance/r0`: **0 bytes**。

R0 历史数字保持冻结：post-user 41.76%、duplicate 51.05%、reference imperative 3.45%、wire tail violation 18.81%。R2 不用“预算减少”冒充这些后续结构指标已经归零。

## 8. 结论

R2/L2-1 验收通过：

- 总预算只有一个跨来源 SoT；
- persisted/history 不能绕过；
- current dynamic / packet/header 同门裁决；
- block 不被 R2 截半；
- accounting 不超过 100%；
- 超限有同预算内、非祈使、可审计回执；
- 8000 保持候选身份；
- R0/R1/CR provider 相关约束未回归。

下一阶段依赖链应另立 Goal 进入 **R3：资料按需化 + 指针化 + 会话级去重**，不能在本 R2 Goal 内提前实现。
