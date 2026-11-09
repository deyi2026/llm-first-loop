---
method_id: repro-passes-but-live-rejected-check-actual-inputs-not-code-3e0c7a58d632
name: repro-passes-but-live-rejected-check-actual-inputs-not-code
description: 确定性守卫/校验器拒绝了真实调用，而按自拟参数复现却放行时，分歧几乎总在被拒调用的输入向量而非代码。先把「被拒调用实际收到的 command/workdir/cwd」定为唯一未知量，用会话可见的调用形态（cd 前缀、workdir 是否缺省）核对，再考虑源码或版本偏差排查。本集：lane worktree 提交被「目标 main」写闸拒绝，worktree 参数复现放行、.releases 运行版本一致，实因调用运行在主仓上下文（HEAD=main），守卫语义正确；先核对调用上下文本可省去读守卫源码、调用链、两轮复现与版本排查。
aliases: 守卫拦了但复现放行先查真实参数, 复现通过线上被拒差在哪, git守卫误判main先查cwd, 被拒调用实际workdir, 复现要用被拒调用的原样参数
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:2bd9d262-b7d9-4759-8ce0-0d7b40b2da12:212:093b008c47399118e4f5
evidence_refs: learning:learn:28ed7d11abcd
created_at: 2026-11-09T12:59:04.239167+08:00
updated_at: 2026-11-09T12:59:04.239167+08:00
---
## Trigger
确定性守卫/门（如 git main 写闸、参数校验器）拒绝了你的真实调用，而你按自认为相同的方式复现该判定却得到放行/通过

## Discriminator
拒绝回执本身写明了有限输入的判定谓词（本例：commit 的 main_target=branch(workdir)）。复现放行+运行版本核对一致，逻辑上只剩一个分歧来源：被拒调用的真实输入。当时已可见的输入证据：本会话此前所有命令的 cd 前缀都指向主仓根、主仓 HEAD 就在 main 且带着 staged 改动——被拒提交大概率在主仓上下文执行，守卫拦得对，是调用错误而非守卫 bug

## Short path
- 从拒绝回执提取谓词与输入集，把未知量定为「被拒调用实际收到的 command/workdir/cwd 是什么」，而不是「守卫代码哪里错」
- 用会话内可见事实核对被拒调用的真实上下文：命令串的 cd 前缀指向哪个仓库根、workdir 参数是否缺省、进程 cwd 落在哪个 worktree
- 若实际上下文是主仓（HEAD=main）→ 判定守卫正确拦下了「会在主仓执行的提交」，属调用错误，不必排查守卫实现
- 以显式 workdir（或先 cd 进目标 worktree）重发同一命令，守卫应放行且提交落在 lane 分支
- 在目标 worktree 内 git log 确认新提交位于 lane 分支后停止

## Stop conditions
- 以显式正确 workdir 重发的同一命令被守卫放行，且产物落在预期分支
- 已证明被拒调用与复现的 command 串、workdir 实参逐字一致且运行版本无偏差——此时才升级为守卫真 bug 并走修复流程

## Verification
- 在目标 worktree 内 git log/status 确认新提交在 lane 分支而非 main
- 复现脚本必须使用与真实调用逐字相同的 command 串与 workdir 实参，否则复现结论无效

## Counterexamples
- 守卫是概率性或远端服务（LLM 裁决、网络依赖）：同输入可合法产生不同结果，输入一致性框架不适用
- 回执已直接点名可核查的前置失败（workdir 无效、404、timeout）：直接修该事实，无需复现
- 真实输入确实不可恢复（日志仅存参数哈希且一次恢复尝试失败）：此后转向版本偏差/运行时快照排查（本集 .releases 检查）才是正当顺序
