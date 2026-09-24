---
method_id: record-says-executed-code-absent-locate-commit-across-refs-03696a1a6f50
name: record-says-executed-code-absent-locate-commit-across-refs
description: 当记录（演进/工单/设计文档）声称某修复『已执行』或要求采纳，而当前主分支 grep 不到该变更的签名 token 时，先假设修复已存在于未合入 ref：用记录中的唯一工单 ID 做 git log --all --grep 定位既有 commit，确认未合入后 cherry-pick 并跑其自带回归，而不是通读现状源码从零重写。一次跨 ref 历史查询把『修复该长什么样』缩为『既有已测修复在哪个 ref』；全 refs 无命中则假设证伪，回落按规格实现。反模式：仅凭单一文档状态断言主分支现状而不做 token 交叉验证。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:527:1f44e4fac5a9fef14688
evidence_refs: learning:learn:a8cc458e5d8c
created_at: 2026-09-24T10:18:27.478064+00:00
updated_at: 2026-09-24T10:18:27.478064+00:00
---
## Trigger
任务要求把一条已登记的修复建议落地到当前主分支（如『按建议执行』），或观察到记录状态与代码现状矛盾：文档/记录称变更已执行，当前分支却无该变更痕迹

## Discriminator
知识时点事实：当前分支对变更签名 token（provider 错误码、函数新分支、测试断言）grep 为空，同时存在声称『已执行』的文档；且仓库 commit message 惯例内嵌唯一工单 ID。二者并存时『修复在未合入 ref』升为主导假设，一次带唯一 ID 的跨 ref 历史查询即可证实或证伪

## Short path
- 从权威记录水合建议全文：确切变更点、验收口径、状态字段（未知量：要采纳什么）
- 用签名 token 在当前分支 src/tests 做一次 grep，判定已落地/未落地（未知量：主分支现状）
- 若未落地而任何文档称已执行：git log --all --grep=<工单ID> 定位既有 commit，git branch -a --contains 确认所在 ref 未合入主分支（未知量：修复在哪）
- cherry-pick 到目标分支（或按语义重放），只跑该修复自带的定向回归测试（未知量：采纳后是否绿）
- 核对记录状态与主分支新现状一致即停，不重复登记、不扩大搜索

## Stop conditions
- 签名 token 已出现在目标分支且自带回归测试全绿——采纳完成，停止发现
- 全 refs grep 无该 commit——『存在于他处』假设证伪，转按记录规格从零实现
- commit 存在但与主分支后续重构冲突或语义分叉——放弃机械 cherry-pick，按规格与原测试意图重放

## Verification
- cherry-pick 前 git merge-base --is-ancestor <commit> <目标分支> 显式确认 not-in-main，避免对已合入提交重复操作
- 采纳后对签名 token 重跑 grep + 定向回归测试，把『已执行』断言锚定在当前分支可观察证据而非文档声明
- 最终汇报中说明矛盾来源（如：实测分支 vs 主分支），使状态归因可审计

## Counterexamples
- 记录的『已执行』指向另一仓库或部署环境（热修落在生产仓库）——本仓库历史搜索必然落空，先确认记录的作用域再查历史
- 变更只存在于未提交的 working tree 或 stash——无 commit 可 grep，应先查 git status/stash
- 仓库 commit 惯例不含工单 ID——需改用代码 token/函数名做历史搜索，或直接按规格实现
- 历史命中≠当前应采纳：fix 可能已被 revert 或被后续演进取代——须核对 revert 与后续记录再决定
