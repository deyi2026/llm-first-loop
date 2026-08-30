# 注入治理专项任务图（INJECTION-GOVERNANCE）

> 立项: GOAL-20260829-afd095ab | 2026-08-30 | 状态: **R0 PASS；R1/L1 PASS；R2/L2-1 PASS；R3+ 未开始**
> 依赖链: R0 → R1 → {R2, R3, R4, R5, R6 并行} → R7 → R8(shadow，可后置) → R9。R0 未过数据门不得进入行为实现。

## R0 基线取证与 fixture 建立（数据门）— ✅ PASS
- 内容: 用真实 `data/event_logs` 重建 human turn，区分 user truth / user-role program appendix / system notice；量化尾后注入、会话级重复、资料祈使污染、provider wire 连续 user；按 model/compact/recovery 分桶；冻结脱敏结构 fixture。
- 产物:
  - `scripts/analysis_injection_baseline.py`
  - `docs/injection-governance/r0/baseline.jsonl`
  - `docs/injection-governance/r0/baseline-manifest.json`
  - `docs/injection-governance/r0/report.md`
  - `docs/injection-governance/r0/fixtures/structural-fixtures.json`
  - `tests/unit/test_injection_baseline_analysis.py`
- 验收: R0-1~R0-4 全 PASS；origin coverage ≥95%；request attribution ≥95%；四类结构 fixture 可确定性复现；不调用 LLM。
- 说明: 既有 cognilocal 随机行为复测不属于 R0 硬门；用户此前已取消重复基线跑，行为 A/B 统一留到 R7/L3。
- evidence_required: true

## R1 L1 语义边界落地 — ✅ PASS
- 内容: `injection_labels.py` 单一真相源；四层标记；每个 program appendix 最多一条冲突仲裁声明；资料块去祈使句。
- 产物: `src/llm_loop/core/injection_labels.py`、`tests/unit/test_injection_labels.py`、`docs/injection-governance/r1/report.md`，并迁移 memory/experience/archive/hotcard/digest/model-switch/declaration/recovery/status/build 聚合链。
- 验收: 核心 program-user 全部带 canonical origin metadata；production enforce 夹具仲裁声明计数=1；REFERENCE command-shaped 历史改为中性占位+ref；focused 147 tests PASS；R0 frozen diff=0。
- 说明: R1 只完成来源/语义边界，不宣称消除 R0 的尾后注入、重复或 wire 违规；这些属于 R2-R7。
- evidence_required: true

## R2 注入预算硬上限（L2-1）— ✅ PASS
- 内容: `INJECTION_BUDGET_CHARS` 候选值 + 统一优先级丢弃 + 非祈使回执；在统一 assembler 门闸实现，不能各注入源各算一套。
- 产物: `src/llm_loop/core/injection_budget.py`、`tests/unit/test_injection_budget.py`、`docs/injection-governance/r2/report.md`；`config.py` / `.env.example` 接入候选参数，`build.py` 只消费中央 budget plan。
- 验收: persisted/dynamic/header 三类 program-origin 同一门闸；超限整块丢弃、不截断半块；accounting `used_chars <= budget`；off/shadow/enforce 多预算矩阵实际 wire 均低于 accounting；非祈使 receipt 同预算计费；8000 明示仅候选。
- 说明: `COG_RUNTIME_PACKET_BUDGET` 保留为 Cognitive packet 内部投影压缩预算，只能进一步减少 packet；跨来源最终硬上限的 SoT 是 R2 `INJECTION_BUDGET_CHARS`。R3+ 未启动。
- evidence_required: true

## R3 资料按需化 + 指针化 + 会话级去重（L2-2）
- 内容: 前 K 轮/任务切换才自动给目录；每帧 ≤2 行（事实 + ref）；session-scoped `seen_injection_set`，stable ID 优先、无 ID 用规范化内容 hash，跨 compact 保持。
- 验收: 同 session 同一完整事实帧重复率=0；K+1 后无自动正文；再次命中最多给 1 行 ref；主动检索能力不回归。
- evidence_required: true

## R4 程序恢复边界（L2-4）
- 内容: auto_continue 注入统一 `[任务·程序恢复]`；明示非用户发起；单恢复动作、完成即回到当前用户任务边界。
- 验收: 恢复块最多一个；不携带开放式“顺便继续下一阶段”；恢复后不跑飞。
- evidence_required: true

## R5 身份问答剥离（L2-3）
- 内容: 压缩/摘要链路过滤身份类问答对，仅保留单行计数占位。
- 验收: identity trap 不进入长期摘要细节；非身份内容零误伤。
- evidence_required: true

## R6 用户原话尾位 + wire invariant（L2 横切）
- 内容: 逻辑顺序固定 `stable system → history → program appendix → user truth`；provider 投影不能破坏 system/tool 协议；GLM 等使用单 user envelope，user truth 原文逐字位于末尾。
- 验收: `injection_after_user_chars=0`；GLM `tail_user_run<=1`；tool pairing 合法；用户原文不复制、不改写。
- evidence_required: true

## R7 L3 A/B 验证
- 内容: 治理前冻结 R0 + 治理后同 fixture、同模型、同采样参数；弱模型重点跑 identity/command-conflict/repetition trap。
- 验收: 原三指标（漂移≤10%、注入占比≤20%、完成率≥80%）+ 新硬门（尾后注入=0、完整重复=0、资料祈使=0、GLM wire 违规=0、完成率回退≤5pt）。
- evidence_required: true

## R8 按模型能力分档（L2-5，后置 shadow）
- 内容: 基于 model_catalog/provider capability 计算 `minimal/standard/full` 推荐 profile；第一阶段只 shadow，不改变 prompt。
- 验收: shadow attribution 完整；弱模型建议 minimal；所有 profile 仍受同一预算/去重/尾位/wire invariant 约束。
- evidence_required: true

## R9 主区应用与收口
- 内容: 镜像实现与 A/B 证据提交用户审批 → 主区应用 → 重启 → 运行观察。
- 验收: 用户批准记录；主区应用后无新增注入结构违规；目标收口。
- evidence_required: true

## 风险登记
- stable prompt/标签变更可能导致一次前缀缓存冷启动；集中一次变更，之后保持字节稳定。
- 资料按需化可能损失“无意识相关性”；以任务切换检测 + 主动检索补偿。
- user truth 尾位不得通过新增第二条 user 实现，必须服从 provider wire contract。
- REASONING_TAIL 思维链回传不并入本专项。
