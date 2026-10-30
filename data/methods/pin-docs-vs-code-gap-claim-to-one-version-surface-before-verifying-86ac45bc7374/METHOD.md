---
method_id: pin-docs-vs-code-gap-claim-to-one-version-surface-before-verifying-86ac45bc7374
name: pin-docs-vs-code-gap-claim-to-one-version-surface-before-verifying
description: 核实『文档说支持X、代码只接一半/绕过X』式缺口报告时，若仓库正被并发会话改（目标文件M态、未跟踪新特性文件、mtime新鲜），先怀疑报告的两个半边落在不同版本面：文档读自未提交WIP，代码却 judged 在已提交HEAD。一次定向 git diff 看 WIP 是否已含被指缺失的接线，再用 git show HEAD:path | grep 同符号验证 HEAD 是否全无。若 worktree 已有而 HEAD 为空，真实缺口是『特性未提交』而非『闸被绕过』：不改并发会话的WIP，出核实记录+独立对抗探针后收口。
aliases: WIP文档比HEAD代码的假缺口, 核实文档说支持但代码没接的报告, 并发改动仓库里bug报告前提错配, 特性没提交被当成闸被绕过, 文档代码版本面不一致怎么核
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:cab051cc-c0ca-4a09-b848-6d4a00ec0ffe:2227:8b734445af6965c75536
evidence_refs: learning:learn:acb330094c60
created_at: 2026-10-30T13:27:40.769916+08:00
updated_at: 2026-10-30T13:27:40.769916+08:00
---
## Trigger
用户或上轮给出『文档说支持 X 但代码只接一半/绕过』的缺口报告并要求核实（且修）；仓库为多会话共享，被点名文件处于未提交修改(M)状态或存在未跟踪新特性文件，特性可能正在落地中

## Discriminator
git status 显示被点名文件为 M 态，且其 WIP diff 本身已包含报告所称缺失的接线（就在报告点名的那个函数里）；配合 HEAD 副本对同符号 grep 为空（命令退出码1）。这一对当时即可见的事实，把『多种可能的代码状态』缩成『报告拿未提交WIP文档比了已提交HEAD代码』的前提错配

## Short path
- 定位被点名文件的 live 权威路径（跳过 .releases/ 等冻结副本）；未知量：现状代码在哪个版本面
- git status + 定向 git diff：该文件是否正被并发会话改、WIP 是否就是该特性的落地中
- 直读 worktree 中报告点名函数的函数体，核实所称『缺失的接线』是否实际存在
- 若 worktree 已有而报告称无：git show HEAD:path | grep 同符号，空命中即证明整个特性未提交
- 裁决并回报前提错配：真实缺口=特性未提交（回滚即复现），worktree 无活 bug；不改并发会话的 WIP，落核实记录并跑独立对抗探针（应拦输入+旧行为不变+拒绝无半成品）后收口

## Stop conditions
- 报告两侧已钉到同一版本面并经权威读取裁决（worktree 函数体 + HEAD 同符号检查）
- 独立行为探针对 worktree 中该闸门给出通过或证伪结论
- 目标文件由并发会话活跃持有（mtime 持续推进）→ 停在核实+交接，不编辑运行时代码

## Verification
- 同一符号在两个面各查一次：worktree 副本命中调用点；git show HEAD:file | grep 为空
- 对抗探针覆盖正控制、应拦输入、未传 scope 时旧行为逐字节不变、拒绝后无半产物

## Counterexamples
- 目标文件干净（worktree==HEAD）：单面断言，直接读 live 函数裁决即可，无需版本面配对
- 报告已显式钉住 commit/分支/tag：两侧都对该 pin 比较，而非默认 HEAD
- worktree 与 HEAD 都确实缺失该接线：bug 为真，不得用本方法把真缺口解释成前提错配
- 所引文档是外部发布版本而非仓库内受版本控制文件：无从做面配对，按发布文档版本核实
