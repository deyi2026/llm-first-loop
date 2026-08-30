# 注入治理专项任务图（INJECTION-GOVERNANCE）

> 立项: GOAL-20260829-afd095ab | 2026-08-30 | 状态: **R0-R8 PASS（R7 exact cognilocal coverage=N/A；R8 shadow PASS / canary NOT READY）；R9 未开始**
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
- 说明: `COG_RUNTIME_PACKET_BUDGET` 保留为 Cognitive packet 内部投影压缩预算，只能进一步减少 packet；跨来源最终硬上限的 SoT 是 R2 `INJECTION_BUDGET_CHARS`。R3 已在其外层约束下完成资料降密。
- evidence_required: true

## R3 资料按需化 + 指针化 + 会话级去重（L2-2）— ✅ PASS
- 内容: `REFERENCE_AUTO_TURNS` 候选 K + 显式任务切换门；每帧 ≤2 行（事实 + ref）；stable ref 优先/hash fallback；seen-set 从持久 message metadata 重建，跨 compact 保持。
- 产物: `src/llm_loop/core/reference_injection.py`、`tests/unit/test_reference_injection_{policy,integration}.py`、`docs/injection-governance/r3/report.md`；memory/experience/skill/digest/compact/hotcard 自动表示迁移到 pointer-era。
- 验收: K+1 后 memory 自动检索即停止；09c44093 x18 stable-ref trap 完整正文仅 1 次；显式 task switch 时 seen ref 最多 1 行、新 ref ≤2 行；compact 不再回灌 key facts/index/snippets；主动 `search_records/search_archive` 不回归；原 R3 237 focused tests PASS；post-R3 adversarial audit 进一步验证 human-ref poisoning=0、memory/experience/digest ref 可精确水合、session scope 与真实 restart，并以 281/281 扩展回归 PASS；R2 15 点预算矩阵 PASS；R0 frozen diff=0。
- 说明: K=3 仍为候选；seen-set 不新增 Session 顶层状态，而从 durable metadata 重建。hotcard 只改成两行 file pointer，消费/恢复语义留 R4。
- evidence_required: true

## R4 程序恢复边界（L2-4）— ✅ PASS
- 内容: auto_continue 收敛为 closed `ProgramRecoveryAction` + `[任务·程序恢复]` canonical template；可执行 recovery 不再持久化为 session Message，而是 per-session `_RunState` one-shot slot，next-build 消费后清空；旧 persisted recovery 仅从 provider view 退休，storage/event truth 不删。
- 审计: 新增 `program.recovery` session event，记录 action/trigger/turn_ref/scope；可审计事实与可执行 prompt 生命周期分离。
- 验收: 143/143 focused、458/458 expanded PASS；A/B session 并发隔离；真实 1210 E2E 第二 payload 恰好一个 recovery、后续用户轮为 0；R2×R4×R6 15 点全 PASS；R0 frozen 0-byte；pyright 0/0。
- 说明: R4 不实施 R5 identity stripping、R7 A/B、R8 model tiering。
- evidence: `docs/injection-governance/r4/report.md`
- evidence_required: true

## R5 身份问答剥离（L2-3）— ✅ PASS
- 内容: sequence-aware identity/self-description episode 只治理长期 summary/index projection；ArchiveStore raw content/reasoning 与 Session trim backup 原样保留。identity 起点用 `[身份问答 x N 轮，已略——本会话主体任务见下]`，episode 后续详情不进 summary。
- 实现: `core/identity_summary.py` 保守 classifier + genuine-human episode boundary；`_archive_sink` 对新 identity archive 写 `summary_source=identity_filtered` 并跳过 LLM backfill；`search_archive(with_summary=true)` 不得从 raw preview 二次摘要；legacy Session trim 多轮 identity 聚合成单行 xN。`fixed_summary/summary_chain` 保持 inert。
- 验收: 97/97 focused、542/542 expanded PASS；冻结三问题会话各命中 1 个纯 identity opener，clean-control 69715765 的 102 个 genuine-human turn identity hit=0；mixed `你现在是什么模型？上一轮我让你记了什么？` 保留；R2×R4×R5×R6 15/15；R0 frozen 0-byte；pyright 0/0。
- 说明: pre-R5 archive 不做破坏性迁移；R3 已阻止其自动 prompt 回灌。R5 不进入 R7/R8/R9。
- evidence: `docs/injection-governance/r5/report.md`
- evidence_required: true

## R6 用户原话尾位 + wire invariant（L2 横切）— ✅ PASS
- 内容: provider-view 出口统一 `program appendix → fixed separator → exact user truth` 单 user envelope；Session/event history 不改序；仅 initial human-ingress 投影，tool-followup 不重放 truth。
- 产物: `src/llm_loop/core/user_truth_wire.py`、`tests/unit/test_user_truth_wire.py`、`docs/injection-governance/r6/report.md`；`history.py` 只在 initial ingress 保护 current human exact；`err1210.py` 新增 USER_ENVELOPE 安全 strip/defer。
- 验收: 413/413 扩展回归 PASS；off/shadow/enforce×5 budget 共15点均 `generated<=used<=budget` 且 `tail_user_run=1`；compact 后 exact truth 仍尾位；oversized current user 不再被 surrogate 替换；1210 retry 保留 exact user；R0 frozen 0-byte diff；pyright 0/0。
- 说明: R6 不改变 R4 recovery 动作策略、R5 identity stripping、R7 A/B 或 R8 model tiering。
- evidence_required: true
- evidence_required: true

## R7 L3 A/B 验证 — ✅ PASS（exact cognilocal 覆盖 N/A）
- 内容: 冻结 R0 结构失败形态 A 臂 vs 当前 R2/R3/R5/R6 production helper B 臂；6 个无工具 synthetic fixture 覆盖 identity-header、command-conflict、repetition、injection-pressure 与 critical memory-dependency；同模型/temperature=0/seed=42/max_tokens=256。
- 模型: `qwen3.8-27b-mlx@4bit` 弱变体 + `qwen/qwen3.8-27b` 同系列对照；原指定 `cognilocal/qwen3.8-27b-cog` 在 8901 本轮未提供，明确记 N/A，不做别名替代。
- 验收: MLX B 完成率 100%、漂移 0%、用户支配率 100%、平均注入占比 16.44%、结构硬门全 PASS；A 完成 66.67%、支配率 0%、注入 32.57%、结构 FAIL。GGUF control A/B 均 100% 完成，但仅 B 结构 PASS，且注入降至 16.44%。
- 校准: K=0/1 均丢 critical T6，K=3 PASS → 保留 K=3；budget 512 丢 T6，900/2000/8000 PASS → 900 仅为本 fixture 最小通过候选，R7 不修改生产默认 8000。
- evidence: `docs/injection-governance/r7/report.md`、`r7/results-mlx4bit.json`、`r7/results-qwen27b.json`。
- evidence_required: true

## R8 按模型能力分档（L2-5，后置 shadow）— ✅ PASS（metadata READY；behavior canary NOT STARTED）
- 内容: 只读取当前路由绑定的 ProviderRegistry/ModelSpec；`weak/unknown -> minimal`，`strong+reasoning=false -> standard`，`strong+reasoning=true -> full`。第一阶段固定 `mode=shadow, applied=false`，不改变 prompt。
- 归因: 新增独立 `injection.profile.shadow` event；primary / fallback / err1210 retry 逐真实 provider attempt 记录，避免 request.meta 的 round 级模型快照误归因 fallback。
- 零行为证据: capability-only minimal↔full 对照的实际 `messages+tools` byte-identical；R2×R4×R5×R6 15/15；R0 frozen 0-byte；focused 268/268；pyright 0/0。
- runtime inventory: R8 初验为 11/11 unknown、覆盖 0%；Post-R8 R8.1 只对有受控证据的模型补 metadata；owner 随后退役不用的 Qwen3.6，R8.2 远端受控 A/B 后，mxnook 持续 HTTP 502，且 owner 明确表示可忽略，现已从 active inventory 退役；当前 active inventory 为 9/9 已分类（strong=1、weak=8、unknown=0，覆盖 100.0%，full=1/minimal=8），`canary_ready=true`。这只表示 metadata gate READY，behavior canary 尚未启动。Git-ignored providers.json 已做 metadata-only 更新，但未调用 refresh_config；不把剩余缺元数据伪装成弱/强。
- evidence: `docs/injection-governance/r8/report.md`、`docs/injection-governance/r8/shadow-inventory.json`、`docs/injection-governance/r8/capability-audit.md`。
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
