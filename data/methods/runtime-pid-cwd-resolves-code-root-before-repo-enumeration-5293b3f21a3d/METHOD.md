---
method_id: runtime-pid-cwd-resolves-code-root-before-repo-enumeration-5293b3f21a3d
name: runtime-pid-cwd-resolves-code-root-before-repo-enumeration
description: 给运行中的托管服务发布/重启新代码时，若本机有多个候选 git 仓/worktree 而不确定真代码源，不要先猜工作区目录再 find 枚举 .git：服务状态回执已显式给出运行进程身份，一次 OS 级反查（ps -p <pid> 取 cwd）即得权威 code_root，发布回执的 runtime_root 会与之互相印证。本集先猜 ~/lfl-workspace（实为文档仓）、再枚举子目录 .git、再核 rt-fix-full（无目标提交对象），三次扩散后才反查 pid 一次命中真仓；随后在仓内定位 main/worktree 干净停在目标提交，publish 并核回执 git_head。与 per-process 祖先测试法互补：那一张解决『已合并 vs 已生效』，本张解决其前置的『哪个仓才是服务真源』。
aliases: 服务代码在哪个仓怎么找, 用进程反查代码目录, 发布前定位真实代码仓, 多个worktree找发布源, 服务cwd就是代码根, 找运行服务用的仓库
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:1855:aaccbd291133720e5c5e
evidence_refs: learning:learn:75760076b09f
created_at: 2026-10-29T07:57:52.340270+08:00
updated_at: 2026-10-29T07:57:52.340270+08:00
---
## Trigger
需要为已在运行的托管服务发布/重启新代码（publish 契约显式要求 code_root），本机存在多个候选 git 仓/worktree 不确定真代码源，且服务状态回执已给出运行进程身份（pid/created_by）

## Discriminator
回执已点名承载服务的 pid——进程 cwd 就是服务实际加载代码的权威指针。这条 provenance 边已存在时，『猜目录→find 枚举 .git→逐仓核对提交』是在扩散搜索空间而不是缩小未知量

## Short path
- 读服务状态回执，记下当前 generation/git_head 与承载进程 pid——未知量：服务在跑什么代码、由谁承载
- ps -p <pid> -o command=（或 lsof 取 cwd）——未知量：权威 code_root；一条命令替代全部目录猜测与逐仓枚举
- 在该仓内 rev-parse main / git worktree list，定位目标提交所在分支或 worktree 并核干净度——未知量：合并是否在位、哪棵树可作发布源
- publish(code_root=该仓)，核回执 published.git_head 包含目标提交——『发布头包含目标提交』核验点
- restart 后按回执契约查终态；若回执写明需等 requester 会话退出才执行，登记续跑排程并退出会话，不在会话内空等生效回执

## Stop conditions
- code_root 已由进程 cwd 确证，且与 publish 回执 runtime_root 一致
- 目标提交在权威仓中的干净落点（分支/worktree）已核清

## Verification
- publish 回执的 code_root/runtime_root == 进程 cwd
- published.git_head == 目标提交（发布头包含目标提交）

## Counterexamples
- 服务未运行、无 pid 可查（纯 git 历史/远端状态任务）——进程锚不存在，应改用变更指纹枚举定位仓，本方法不适用
- 回执中的 pid 已过期（服务其间重启换 pid）——先 ps 验活再取 cwd，死 pid 反查无效
- 多个服务各自运行在不同仓/worktree——须逐服务 pid 反查，不能把一个 cwd 推广为全局 code_root
