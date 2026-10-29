---
method_id: locate-batch-repo-by-change-fingerprint-not-filename-search-9829cbed8a0e
name: locate-batch-repo-by-change-fingerprint-not-filename-search
description: 用户问『那批改动提交了吗/并 main 了吗』而指称对象是早前会话留下的变更批次时，第一个未知量不是当前目录仓的状态，而是『这批变更在哪个仓』。cwd 仓一次 status 证明暂存区为空即排除；随后一条命令枚举本机 git 仓并按批次指纹（非空暂存区/分支名/文件集）过滤定位。不要按文件名全局搜索，在含快照/发布镜像的树里只会命中只读副本，区分不了活工作树。与『钉权威远端』同理，但作用于本机多仓归属。
aliases: 那批改动到底在哪个仓库, 上次会话改的代码落在哪个仓, 多仓库定位未提交的变更批次, 提交了吗并main了吗去哪个仓查, 从一堆快照副本里找活的工作树
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:1695:1457bc9c0fe6c6f08ec0
evidence_refs: learning:learn:b3bd79071212
created_at: 2026-10-29T07:53:29.537021+08:00
updated_at: 2026-10-29T07:53:29.537021+08:00
---
## Trigger
用户询问某批早前（含其他会话）产出的变更是否已提交/合入/推送；该批次的来源 provenance（产生会话或登记记录）在上下文中已知或可回忆；当前 cwd 仓与该批次的关系未确证

## Discriminator
cwd 仓 status 输出本身——暂存区为空、仅无关修改与 untracked，立即证伪『批次在此』；且『批次处于暂存态』当时已知，非空暂存区在多仓环境里近乎唯一，可用逐仓 staged 计数一条命令判别；而文件名搜索命中 .releases/<sha>/ 类路径前缀时，该前缀本身即标记为快照镜像而非活工作树

## Short path
- 未知量1：批次是否在 cwd 仓？一次 status/porcelain 判定；暂存区为空即排除，不再对该仓换参数重查
- 未知量2：哪个仓持有该批？find -name .git -type d 枚举仓库根，逐仓取 staged 计数与当前分支，按指纹（staged>0、fix 分支名、文件集）过滤
- 未知量3：是否就是那批？diff --cached --stat 与记忆/登记中的文件集、规模、演进标识核对
- 在该仓内回答提交/合入/push 三问并开展后续工作；一切 ahead/behind、分支、remote 结论取自该仓真值

## Stop conditions
- 目标仓已定位且 diff --cached --stat 与批次指纹吻合
- 对用户三问（提交/合入/推送）的结论均已从目标仓的 git 真值得出

## Verification
- 暂存 stat 的文件集与此前会话登记/记忆的批次一致
- 未再从 cwd 仓或快照副本得出任何状态结论

## Counterexamples
- 问题指向本会话或当前仓的改动：cwd 仓即指称对象，直接查，不枚举
- provenance 已给出确切仓库路径：跳过枚举直接进入该仓
- 批次已 commit 而非 staged：staged 计数过滤会漏，改按分支新鲜度或 log -S 指纹过滤
- 目标仓不在默认扫描深度/卷内：扩大扫描范围或改用登记记录里的路径，而非断定不存在
