---
method_id: worktree-enoent-pivot-to-main-repo-absolute-for-shared-host-ledgers-3d35fae22b99
name: worktree-enoent-pivot-to-main-repo-absolute-for-shared-host-ledgers
description: 受管多worktree会话中，宿主级共享产物（权威lanes账本、协调注册表等跨会话状态）在主仓根目录，不在当前分支worktree的内容树里。当这类以仓库相对路径指称的文件探针返回显式『路径不存在/No such file』回执时，不对同一相对路径换工具重试（回执已登记不存在，是停止信号），也不把search_files无匹配当作不存在的证据（审计/协调目录常在搜索范围外）：跑一次pwd，若含<主仓>/.worktrees/<branch>段，机械截去该后缀得主仓根，拼绝对路径做一次定点grep/读取；与任务报备值逐项比对一致后，才发唯一一次带expected_version的CAS更新。
aliases: worktree里找不到账本文件怎么办, 相对路径不存在改绝对路径, 从pwd反推主仓根目录, 隔离worktree下读共享审计文件, 账本不在当前分支里
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:37596905-cd68-421a-ad2d-d6dcf2ffd14f:50:d67c2ba03b840a47275d
evidence_refs: learning:learn:c5f4a17b9269
created_at: 2026-11-19T17:15:29.483470+08:00
updated_at: 2026-11-19T17:15:29.483470+08:00
---
## Trigger
受管会话中需只读核验一个跨会话共享/宿主级产物（如权威lane账本、注册表），任务以仓库相对路径指称它，而相对路径探针（stat/read/grep）返回显式『路径不存在』回执，且会话运行在隔离worktree中。

## Discriminator
两个当时可见事实：①ENOENT回执明确说该相对路径不存在且已登记（不是空内容或权限错误）；②pwd输出（或任务上下文的branch/隔离worktree表述）表明cwd形如<主仓>/.worktrees/<branch>——共享协调状态归主仓根所有，不可能出现在分支worktree树内，主仓根可由pwd机械推导。

## Short path
- 未知量=账本中目标lane的version/head_sha/paths当前值；先做一条相对路径定点探针（不并行重复同一未知量）
- 收到『路径不存在』回执即停手：不对同一相对路径换工具重试，登记TTL回执是停止信号
- 跑一次pwd；若含/.worktrees/<branch>段，机械截去该段得主仓根，拼出绝对路径
- 用绝对路径做一次定点grep/读取，提取目标lane最新记录
- 与任务报备值逐项比对；一致才发带expected_version的一次CAS更新，读回执即停

## Stop conditions
- 绝对路径读取成功且version/head_sha/paths与报备一致→直接进入唯一一次CAS写
- CAS回执返回新version→只报告真实回执与新version，停止
- 版本与报备不一致→停止并报冲突，不做任何写
- pwd无.worktrees段（cwd已在主仓根）或回执提示文件可能刚被创建→本方法不适用：改走store寻址方案确认或重新read确认

## Verification
- 绝对路径来自pwd机械推导（取/.worktrees/之前的前缀），不是猜测
- grep命中记录的lane_id/branch/owner_session与任务一致，version/head_sha/paths与报备逐项相同
- 最终报告只引用真实工具回执，不把任务报备值当作已核验结果转述

## Counterexamples
- 目标是分支内容（src/docs等本lane租约内文件）：worktree相对路径本来就对，ENOENT=该分支确实无此文件，不应去主仓找
- pwd已是主仓根（无.worktrees段）：相对ENOENT属路径错误或store命名方案不明，应解析寻址方案（如读设计文档/源码），不从pwd推根
- 回执提示『文件刚被创建请重新read确认』：先重新read确认新鲜度，而不是跳去主仓
- search_files对该文件名无匹配：审计/协调目录常在搜索范围外，单独的search miss不构成本方法的触发条件，也不可作为文件不存在的证据
