---
method_id: verify-matching-commit-receipt-before-reexecution-f2aaa0d6097e
name: verify-matching-commit-receipt-before-reexecution
description: 当指令要求执行一个具体、机械、自包含的处置（修复+验证+commit+过门），且该处置可能已被先前会话完成时，先把仓库账本（git log）当执行真值：提交信息与处置签名（目标 artifact+动作+门标签）匹配即视为执行回执，切换为 verify 模式——在当前 HEAD 活测该处置仍生效、git show 逐行比对 diff 与指令一致，只为缺回执的步骤（如测试复跑，须用项目自身环境）补新证据。不冗余重执行，也不扩大到门范围外的存量问题。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ba2daf39-ade3-4308-855e-bf3018c00381:238:4b07bf03b4afed413b08
evidence_refs: learning:learn:a98cbd6ac226
created_at: 2026-10-06T21:30:42.673961+08:00
updated_at: 2026-10-06T21:30:42.673961+08:00
---
## Trigger
用户/上级指令下达明确的机械处置（fix+测试复跑+单独 commit+gate 判定），事前无回执确认是否已执行；git log 中出现与处置签名逐项匹配的提交（本例：337e2855f 的 message 含 factory.py+mechanical ruff I001 fix+FR-1 G3 gate，其后仅 docs/eval 提交）。

## Discriminator
在任何修复/发现动作之前，git log 已显示该签名匹配提交，且其后无触碰目标文件的代码提交——这条当时可见的事实把候选行动从『执行四步处置』缩成『验证已执行+补缺口』；本例中该回执在最早两次调用内已出现，而后续两个发现类调用（search_files、search_docs miss）仍在服务已过期的执行计划。

## Short path
- git status+log 作前提核对；发现 message 与处置签名匹配的提交 ⇒ 冻结『重新执行』计划
- 未知量：修复在当前 HEAD 是否仍生效 ⇒ 对目标文件跑 ruff --select I001（回执 All checks passed）
- 未知量：已记录动作与指令是否逐项一致 ⇒ git show 该提交，逐行核对 diff（纯 import 重排、行为零变化）
- 未知量：门字面口径与既有判定 ⇒ grep 目标 PLAN 文档的 gate 行（六路径范围+既往 G3 PASS 记录）
- 未知量：哪些步骤缺本会话回执 ⇒ 仅补缺失项：compileall+import smoke、项目 .venv 下聚焦测试（666 passed）、六路径 ruff 全绿
- checkpoint 留痕，按 步骤→证据 逐项报告：零代码改动

## Stop conditions
- 指令的每一步都已有『已验证的既往回执』或『本会话新回执』，可给出步骤→证据映射时停止
- 活测显示既往修复在 HEAD 已失效，或 diff 与指令的范围/行为不符 ⇒ 退出 verify 模式，按原指令重新执行
- 门/任务范围外的问题（如全仓 26 处其他 ruff 报错）只记录不处置，不扩大范围

## Verification
- 在当前 HEAD（而非仅旧提交）对目标 artifact 重跑机械检查器，证明修复现在仍生效
- git show 逐行审读回执提交 diff，确认与指令同文件、同机械范围、行为中性
- 缺回执的验证步骤（测试复跑）必须在正确环境取得新鲜通过回执——本例系统 python 因缺 pypdf 收集失败，项目 .venv 才是有效环境

## Counterexamples
- log 中只有风格相似但签名不匹配的提交（不同文件/动作，或修复在其他分支/worktree）⇒ 不得当作已执行，直接查工作树并活测
- 回执提交存在，但其后有提交改动了同一文件/路径 ⇒ 以 HEAD 活测为准；失效则重新执行
- 用户明确要求本次强制重做，或协议要求动作必须发生在本会话/特定时点之后（如 gate 时序约束）⇒ 执行而非仅验证
- 处置状态不落在 git 账本里（外部系统、缓存、部署面）⇒ 本方法不适用
