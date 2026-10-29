---
method_id: same-topic-divergence-extract-missing-increment-not-branch-merge-ef21b94abd84
name: same-topic-divergence-extract-missing-increment-not-branch-merge
description: 用户要求把当前修复分支及时并入 main 时，交付策略不能默认整支 merge 可行：先 fetch 并用只读 range diff 回答『main 现在到底缺什么』。分叉后 main 上若已有同主题更新版本（新 env 基线计数、重写的守卫实现），整支合并会把分支上的旧版状态盖回 main，使基线门禁失效。正确交付物是逐文件树级 diff 提取的真增量：在与 main 同源的集成分支先审查再跑全量门禁，然后 cherry-pick 落 main，验证逐字节一致+针对性测试。main 被另一会话并发写入时：ff-only 失败即改 cherry-pick；在他人持续写入的工作树上取得的全量绿不可归因于自己的提交；推送 main（其领先部分含他人在飞提交）需用户明确授权，不代发他人工作。
aliases: main 分叉了还能直接 merge 我的分支吗, ff-only 推不动该怎么把修复送上 main, 只送 main 还没有的那部分改动, 有人同时在写 main 怎么落修复, 别把 main 上的新版盖回旧版, 先对比 main 再决定 merge 还是摘提交
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:947:7e8eb40f5f95f3180d35
evidence_refs: learning:learn:3a2eae507cbf
created_at: 2026-10-28T23:29:00.153593+08:00
updated_at: 2026-10-28T23:29:00.153593+08:00
---
## Trigger
用户指示把当前修复分支及时并入 main（『避免成为遗忘分支』类指令），且分支与 main 可能已分叉——带日期的旧分支名、共享检出、或多会话并行写同一 main 的仓库。

## Discriminator
动手合并前一次只读对比即可定论：`git log HEAD..main` 非空说明 main 已前进（ff-only 必失败，分支已不是 main 后裔）；逐文件 `git diff main -- <file>` 若显示 main 上同文件已是更新版本（更新的基线计数/重写实现），则『整支合并=覆盖 main 新工作』成立，唯一安全交付物是 main 缺失的真增量。最早预信号在首个 git status 里就有：带日期的分支名本身提示分支创建后时间已过。

## Short path
- 落分支提交后，先 fetch 并做只读对比：`git log --oneline HEAD..main` + `git diff main...HEAD --stat`（未知量：main 前进了多少、触及哪些同主题文件）
- 逐文件 `git diff main -- <file>` 把分支改动二分：main 缺失的真增量 vs main 已有更新版本（未知量：增量集合）
- 把真增量放到与 main 同源的集成分支，先取独立审查 PASS 再跑全量门禁（未知量：增量本身是否绿且归因清晰）
- cherry-pick 增量到 main，用 `git diff` 输出为空 + main 树内针对性测试验证一致
- 推送单独决策：main 领先部分含其他会话在飞提交时，报告用户并等明确授权；在他人工作树上只跑针对性用例，不据全量结果背书

## Stop conditions
- 增量文件与 main 逐字节一致（diff 为空）且 main 树内针对性测试通过，即停
- 若 HEAD..main 为空（分支仍是 main 后裔）：直接 fast-forward/常规 merge，本方法不适用

## Verification
- `git diff main -- <增量文件>` 输出为空
- main 树内跑该增量对应的针对性测试（不能只在集成分支上绿）
- 推送前重新 fetch 权威远端，确认 SHA 未再移动

## Counterexamples
- 分支独有改动与 main 零主题重叠（纯新增文件/独立功能）：整支合并不会覆盖 main 任何内容，按仓库常规 merge gate 走整支流程即可，逐文件抽取是多余开销
- main 上的『新版本』本身是待修复的坏改动、分支版本才是目标：不能机械『main 新即对』，冲突须语义与测试裁决
- 单人仓库、main 静止且分支是其直接后裔：ff 即可，无需集成分支与增量抽取
