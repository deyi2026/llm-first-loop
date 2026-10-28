---
method_id: locate-authority-repo-by-live-hash-membership-not-fs-enumeration-455cf755a248
name: locate-authority-repo-by-live-hash-membership-not-fs-enumeration
description: 当运行时/部署回执已给出 live 代码身份哈希（git HEAD）但不含仓库路径、而本地散布多个日期不一的同项目副本/缓存/工作树时，定位权威真源不要 ls 家目录、不要逐一对比全部副本 HEAD、也不要 ps 反查进程：把身份哈希当作 git 对象库的查询键，锚定日期戳最新的 deploy 命名 checkout，单仓一次批量执行 cat-file -e / branch --contains / remote -v——对象库是否包含 live commit、remote 指向哪个上游主仓立即揭晓；全 miss 才扩大到部署 manifest 的 generation→git_head 映射。本集家目录枚举+8 副本 HEAD 对比+ps 失败约 6 条冗余命令，最终答案其实是一组 git 元数据查询，且修复最终就落在最初锚点 deploy 目录。
aliases: 多个仓库副本找真源, 运行时HEAD反查主仓库, 一堆checkout哪个是权威, 别ls家目录找主仓, git哈希成员探测定位仓库
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ad759489-d317-4570-bcdd-114f028420aa:0:0f837a19709dd1c0d767
evidence_refs: learning:learn:7ac22f27e566
created_at: 2026-10-26T07:53:49.698178+08:00
updated_at: 2026-10-26T07:53:49.698178+08:00
---
## Trigger
运行时/部署回执给出 live 代码身份（commit 哈希或版本 token）但不含源码路径；本地存在多个同名项目的副本/缓存/工作树；任务需要确定权威仓库以实施修改或对齐真源

## Discriminator
身份哈希本身在枚举发生前就已是 git 元数据查询键：任一候选仓库用 git cat-file -e <hash> / branch --contains 即判定其对象库是否包含 live commit，git remote -v 直接命名上游主仓；deploy/<今日日期> 命名的 checkout 是最优先探测锚点（日期戳即新鲜度证据，已在手的目录清单可见）

## Short path
- 按记录自带 provenance（file:lines + baseline commit）在已命中副本一次读取确认缺陷存在
- 取一次运行时身份回执，锚定 live 身份哈希（未知量：live 代码的身份→位置）
- 在日期戳最新的 deploy checkout 单仓批量执行 git cat-file -e <hash> + branch --contains + remote -v（未知量：哪个对象库含 live commit、主仓在哪）
- 命中即权威闭合：在 live commit 上复核目标代码（git show <hash>:<path>），进入修改与部署
- 对象查询全 miss 才扩大：改查部署 manifest / release 目录的身份映射，而非家目录或全副本枚举

## Stop conditions
- 已确定包含 live 身份的 checkout 及其上游主仓，并在 live commit 上复核目标代码状态，即停止定位进入修改
- 任务只需按记录给出的 baseline commit 阅读/比对代码：git show <baseline>:<path> 即止，无需权威定位

## Verification
- 权威仓库 git log --all / branch --contains 能看到 live 身份哈希（祖先或可达）
- 修改落地后部署回执的 git_head/generation 与新 commit 一致

## Counterexamples
- 唯一真源仓库已知 → 直接修改，不做成员探测
- live 版本来自外部 CI 构建产物，本地任何对象库都不含该哈希 → cat-file 全 miss，应查部署 manifest 而非继续换目录探测
- live 哈希位于 fork/实验分支，remote 指向的主仓并非任务归属仓库 → 修改处须按任务归属裁决，不能机械跟 remote
- 纯读分析且记录已给 baseline commit → 任一含该 commit 的仓库 git show 即可，不必找主仓
