---
method_id: resumed-closeout-rescope-via-concurrent-authority-artifacts-0490548a1bc3
name: resumed-closeout-rescope-via-concurrent-authority-artifacts
description: 多会话共享工作区里续跑上轮遗留待办时，上轮结论只是过期采样：先用身份探针（暂存状态/文档 size+mtime/领先计数）diff 出漂移前提，再用并发会话留下的权威制品重定待办范围，消失的暂存按提交指纹对账、被更新的设计文档按其新写明的处方实施、HANDOFF/接管文档划定的 push 与 main 归属必须遵守（落分支不合不推），写权限外的纠偏以文本+锚点移交。核心：他方权威制品可能已把你待办清单里的项直接关闭或改写，先读它们再动手。
aliases: 续跑时上轮暂存不见了先查提交, 别的会话接管了git还能不能push, 设计文档mtime变了要先重读锚点, 上轮待办被并发会话做完了怎么办, 多会话共享仓库续跑先对账
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6e7b4358-a1b8-4e23-a99c-931d6e86bee2:643:5c56a776ffe6ef80f09f
evidence_refs: learning:learn:a32e7ec2188a
created_at: 2026-10-30T19:36:19.331485+08:00
updated_at: 2026-10-30T19:36:19.331485+08:00
---
## Trigger
『继续』类续跑指令带着上轮待办清单（修复、文档纠偏、暂存/提交归属等），待办前提是上轮观察快照（当时看到的暂存内容、文档正文、缺口是否还开着），且工作区为多会话共享（存在非本会话的提交链、他人 stash/tmp 文件，或文档 mtime 晚于上轮观测）。

## Discriminator
廉价的当前事实探针与上轮记录出现差值：暂存区为空但上轮记录有暂存、文档 size/mtime 变化、main 领先 origin 且领先提交非本会话所写、仓内存在他方 HANDOFF/接管文档。任一命中即证明待办清单已过期，第一未知量是『哪些前提被并发会话改写了』而非『如何执行原待办』。

## Short path
- 对每条待办前提做一次身份探针（status、文档 size/mtime、ahead 计数），与上轮记录逐条 diff，列出漂移项
- 漂移项用权威制品对账：暂存消失→全窗口 git log --numstat 按文件集+行数指纹比对是否已被提交；文档漂移→只重读待办相关锚点小节
- 按对账结果收缩清单：已被他方完成/升级的项以可复核证据关闭；文档已写明修法的项按文档处方逐字实施，不沿用上轮自拟方案
- 读他方 HANDOFF/接管文档划定写权：main 合并与 push 归属他方审查流程时，剩余工作落 side branch/worktree，不推不合
- 自己写权限之外的项（工作区锚外文件）输出逐字更正文本+精确锚点交属主应用，不强写

## Stop conditions
- 每条待办进入三态之一：证据关闭 / 权限边界内落地且测试通过 / 显式移交文本已交付
- 权威制品内容与当前 refs 核对一致，且无新的漂移信号出现

## Verification
- 分支基线等于读取接管文档时的 main HEAD，全部改动只在该分支，未触碰 origin
- 每项以『已关闭』处理的待办都留有可复核证据（提交指纹、文档行号或实测回执）
- 移交文本引用的锚点与当前文档行号一致（写入前用锚点预检命中数核对，防凭记忆复述错行号）

## Counterexamples
- 单会话独占仓库、探针与上轮记录无差值：直接执行原待办，不做对账流程
- 接管文档早于当前提交链、已被后续文档取代：以当前 refs 与最新文档为准再决定是否遵从其约束
- 文档漂移但改动段落与待办锚点无关：只重读自己的锚点，不全量重读，也不因此改修法
