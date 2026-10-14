---
method_id: verify-deployment-state-via-runtime-receipt-not-unrelated-local-mirror-921affe7d537
name: verify-deployment-state-via-runtime-receipt-not-unrelated-local-mirror
description: 核验『已重启/已收口』这类部署态声明时，服务自身 status 回执通常已内嵌权威代码身份（版本串 g<hash>、git_dirty），它就是该声明的首要 provenance；本机 checkout 只是未验证候选副本。先由回执裁决声明；如需报告本地残留，在 cwd 直接 git status（不枚举 home、不沿用过期绝对路径）；把本地 status 解读为证据前，先确认与回执 commit 同源（remote URL / ancestry），否则未跟踪文件只是无关 lineage 的本地残留；fetch 不得丢弃 stderr，防止 remote 名猜错时静默拿到陈旧数据。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1e362f1c-6242-47df-8cfd-2b1de1b0b20e:18:c20454aa750a4e095891
evidence_refs: learning:learn:48d1e6dced4b
created_at: 2026-10-13T21:33:40.339963+08:00
updated_at: 2026-10-13T21:33:40.339963+08:00
---
## Trigger
需要核验关于已部署服务的状态声明（已重启/代码已收口干净），且工具回执报记忆中的 workdir 无效、或本机存在多个可能不同源的 checkout

## Discriminator
服务 status/版本回执是否已内嵌运行时代码身份（commit hash、git_dirty/version 串）——它在任何文件系统搜索之前就已可裁决声明；以及本地 checkout 的 remote 与 ancestry 是否与该 commit 同源

## Short path
- 读服务 status 回执，一次解析两个未知量：重启是否生效（当前代次 stable）、服务 repo 是否干净（HEAD + git_dirty）
- 声明若指向服务 repo：此处即已核验，不发起本地文件系统搜索；仅当还需报告本机残留时继续
- 在 cwd 直接 git status（pwd 已示 checkout 位置，不 ls 枚举全目录、不使用过期绝对路径）
- 把本地 status 解读为证据前：git remote -v + ancestry 对比回执 commit；不同源则标记为本地-only 残留、非权威、不阻塞
- fetch/pull 保留 stderr 或先确认 remote 名存在，防止静默 no-op 后把陈旧 log 当新数据
- 结论按对象拆分：服务侧由回执证实；本地尾巴如实单列交用户决定，然后停止

## Stop conditions
- 服务回执已同时证实重启生效与运行代码树干净（HEAD 与 dirty 明确）
- 本地 checkout 已被证实与回执 commit 不同源，其未跟踪文件已标注为本地残留
- 声明所指对象（服务 repo vs 本地工作区）已分别核验并区分表述

## Verification
- 最终报告引用的 HEAD 与回执中的 commit/版本字段一致
- 本地 checkout 的 remote URL 与服务 repo 对应，ancestry 检查给出同源/无关的明确判定
- 任何 fetch 的 stderr 无『remote 不存在』类错误，或已先经 git remote -v 确认 remote 名

## Counterexamples
- 声明本身针对本地工作区（如『把我本地两个文件提交』）——本地 git status 即权威目标，服务回执无关
- 回执不含 git 身份字段（无 commit/dirty）——必须定位服务真实 checkout，文件系统搜索成为必要路径而非绕路
- 唯一 checkout 且 remote 名确定——lineage 预检是纯开销，直接 fetch+比较即可
