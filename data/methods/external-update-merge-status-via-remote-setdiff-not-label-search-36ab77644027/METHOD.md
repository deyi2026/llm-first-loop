---
method_id: external-update-merge-status-via-remote-setdiff-not-label-search-36ab77644027
name: external-update-merge-status-via-remote-setdiff-not-label-search
description: 用户问"某外部来源的更新(常为俗称,如开发平台名)是否已并入并生效"时,不要在分支名/提交信息/记录/文档里做标签文本搜索——俗称常与仓库对象名不匹配,全部 miss 也推不出任何结论。应把问题重述为拓扑问题:"运行时 HEAD 是否包含各远端/分支的提交"。枚举 remotes,对每个 remote 计算 main..remote/main 集合差,用 patch-id/cherry 排除"换形态已并入",结合进程 HEAD 与 FETCH_HEAD 新鲜度给出生效结论;仅当多个未并入批次造成歧义时才回问用户要 PR/分支号。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:1136:492927b88335df40001b
evidence_refs: learning:learn:d68e8c54d5d5
created_at: 2026-09-23T15:44:06.116339+00:00
updated_at: 2026-09-23T15:44:06.116339+00:00
---
## Trigger
用户用非仓库对象名的俗称询问"某来源的更新有没有并进来/生效",且运行环境是 git 管理的部署(仓库路径或语境表明是 mirror,存在多个 remote)

## Discriminator
进入宽搜索前已知三条事实:pwd 显示仓库路径含 '-mirror'(外部更新经 remote refs 到达);用户问句用"并进来"这一 merge 语汇;进程状态工具按 git HEAD 报告运行版本——合并状态是可达性/集合差问题,与标签能否文本匹配无关。标签在分支/记录/文档里搜不到 ≠ 答案不可知,只说明该名称是俗称

## Short path
- 1. 用部署/进程状态核"重启生效":各服务 pid、started_at、git_head、generation 匹配、无 admission barrier
- 2. git status --porcelain 把 dirty 告警分类为 tracked 修改 vs 纯 untracked,确认"进程代码=HEAD"是否成立
- 3. 由 mirror 事实导出下一跳:git remote -v 枚举外部来源;对每个 remote 执行 git log --oneline main..<remote>/main;查 FETCH_HEAD 时间评估 refs 新鲜度
- 4. 对差集里每个提交做 git cherry / patch-id 等价性检查,排除"以别的形态已并入本地"
- 5. 恰好一个未并入批次 → 报告其内容摘要与"未并入未生效"结论并回问用户确认俗称所指;差集为空且 refs 新鲜 → 报告外部更新均已并入
- 6. 可选:对新 HEAD 引入的特性跑聚焦测试回答"有没有问题",然后停止

## Stop conditions
- 所有 remote 差集为空且 FETCH_HEAD 新鲜 → 断言外部更新均已并入并停止
- 唯一未并入批次经 patch-id 证实本地无等价形态 → 给出"未并入未生效"结论并停止,等用户确认后再执行合并
- refs 陈旧且网络 fetch 失败 → 结论必须附新鲜度 caveat,不得把"本地看不到"当作"上游没有"
- 多个未并入批次无法唯一归因于俗称 → 停止枚举,回问用户要 PR 号/分支名

## Verification
- 确认运行中各服务的 git_head 等于本地 main tip(部署与源码一致)
- 确认未并入提交在本地 main 无 patch-id 等价物(git cherry 双向核)
- 确认 dirty 告警已分类:tracked 零修改才可声明"代码=HEAD"
- 确认新特性聚焦测试全绿作为功能级生效证据

## Counterexamples
- 更新不经 git 交付(热改文件/镜像 tag/制品投递)——拓扑差集看不见,应改对比部署清单或制品哈希
- 仓库无 remote 或单仓单源——问题退化为 log 检查,remote 枚举步骤多余
- 用户俗称恰好就是真实分支/remote 名——直接单条 diff 即可,无需歧义分支处理
- remote refs 严重陈旧且网络不可用——差集为空也可能是假阴性,必须先修复新鲜度再下"无未并入"结论
- 运行环境非 git 管理(工作区含 tracked 未提交热改)——HEAD 可达性不代表运行代码,须先核 working tree
