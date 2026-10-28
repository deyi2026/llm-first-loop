---
method_id: verify-committed-trace-via-git-object-at-known-ref-5cc15057a418
name: verify-committed-trace-via-git-object-at-known-ref
description: 核实「已留痕」类声明（回执/登记随某次提交落库）时，若会话已持有该工件的 provenance（提交号或 分支+路径），直接用 git 对象库定址读取（git show <commit>:<path>、merge-base --is-ancestor）验证，不要跨根目录/文件系统搜索：工作树只反映当前检出分支，多会话并行下 main 可能已前进，工作区 ls 不到 ≠ 未提交；存在性核验用最简子串 grep，定长上下文正则会因 BSD grep 255 重复上限产生假阴性。
aliases: 核实回执已提交, git show 读提交里的回执, 工作区没有但 main 有, 多 worktree 找回执, grep 没命中先怀疑模式, 确认留痕落在 main
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:62423b4e-2e2c-44f3-82e5-45126a6bce95:229:3a169d3c2aca891e6f0e
evidence_refs: learning:learn:a5763351eb3c
created_at: 2026-10-26T16:32:41.053791+08:00
updated_at: 2026-10-26T16:32:41.053791+08:00
---
## Trigger
用户要求确认先前动作（合并/审批/修复）已留下记录（回执、登记、备注），且会话内已持有该记录的提交号或「分支+路径」provenance；环境存在多根（工作区+镜像仓）或多 worktree、或文件系统搜索被沙箱守卫拦截。

## Discriminator
是否已持有该工件的确切 git 地址（commit id 或 branch+path）。持有即把「在哪个根、哪个目录、哪个检出找」缩成单一对象库地址；且「目录不存在 / 越权拒绝 / ls 失败」只证明文件系统通道不对，不构成「未留痕」的证据——工作树内容锚定在当前检出分支，不锚定在工件落库的分支。

## Short path
- 用已持有 provenance 直接问对象库：git show --stat <commit> 确认提交存在并列出回执路径（未知量：提交是否携带该工件）
- git show <commit>:<path> 取工件内容到 /tmp 或临时区（未知量：内容是否含用户声明的字段/延期条款），无需解释器管道
- grep -n '<关键词>' 做存在性核验（未知量：棘轮延期、P2 计数等具体声明是否在文中，带行号取证）
- git merge-base --is-ancestor <commit> <目标分支> 验证 ancestry（未知量：并行会话推进分支后，工件是否仍在目标分支历史内）
- 把 ancestry 检查顺带暴露的分叉事实（main 前进、分支领先/落后）作为新状态上报，不再扩大 worktree/目录枚举

## Stop conditions
- 工件已从提交对象读出，关键声明行（带行号）已用最简模式 grep 命中
- ancestry 检查退出码 0，确认提交在目标分支历史内
- 对象库中确无该提交/路径时，才把「留痕缺失」作为独立结论上报并回到发现通道

## Verification
- git show <commit>:<path> 的字节数与 grep -n 命中行号相互印证
- 「在 main 上」只由 merge-base --is-ancestor 退出码判定，不用工作树状态或分支 tip 字面 hash 相等判断
- 负结论前用最简子串模式重跑一次 grep：定长上下文前缀不满足或 {N} 超过 BSD grep 255 上限时是工具假阴性，不是内容缺失

## Counterexamples
- 手头没有 provenance（用户只说「上次留了记录」，无提交号）→ 对象库无从定址，应走 store 检索/处理函数定位（见 locate-authoritative-record-via-handler-store-code）
- 工件是未提交 WIP 或不在 git 内（workspace 文件、外部台账）→ 只能文件系统/检索定位
- 问题本身是「磁盘上现在有没有该文件」（运行时依赖）→ 工作树才是权威，git show 回答的是提交内容而非磁盘状态
- 单仓单检出且当前就在目标分支 → 直接读文件即可，无需绕对象库
