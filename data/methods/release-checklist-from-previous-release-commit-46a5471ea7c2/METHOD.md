---
method_id: release-checklist-from-previous-release-commit-46a5471ea7c2
name: release-checklist-from-previous-release-commit
description: 版本推进类任务（bump 版本号+同步文档+push/tag）在 git 历史里已有上一次 release 的完整可执行定义。用 `git log --grep=<当前版本>`（或 `git show <上一tag> --stat`）定位上次 release 提交，其 message 与 diff-stat 就是权威发布面清单（本集直接给出版本面四文件 pyproject/web SERVICE_VERSION/README 中英 + CHANGELOG/.env.example）。先以它为基线，再对当前树做差异核对，取代文件名搜索、全目录列举与多轮关键词 grep。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6480dae1-5c2d-4ebd-a622-83d1133fecd9:1:0c159d0604e596f1a8f3
evidence_refs: learning:learn:8b20777677bf
created_at: 2026-10-10T21:00:27.169218+08:00
updated_at: 2026-10-10T21:00:27.169218+08:00
---
## Trigger
任务是仓库例行发布仪式（更新版本号、同步文档、push/tag/Release），且当前树中『哪些文件构成发布面』尚未确定。

## Discriminator
git 历史中已存在上一次 release 提交，且当时即可直达：CHANGELOG 早期读取已显示当前已发布版本（v0.6.27）与例行发布节奏；`git log --grep='0.6.27'` + `git show --stat` 立即得到 message 明写『版本面(四文件)+README/CHANGELOG/.env.example 文档同步』的提交，其 stat 逐文件枚举发布面。该事实在进入宽搜索前已可获得，不依赖任何后见信息。

## Short path
- git status/log 掌握工作区与近期脉络（本已执行）；未知量：发布面清单
- head CHANGELOG.md 确认当前已发布版本与 Unreleased 段，拿到历史 grep 关键词
- git log --grep=<当前版本> 定位上次 release 提交 → git show <sha> --stat 得到权威发布面文件集；未知量解决
- 按清单差异执行：逐文件 grep 确认仍承载版本号并检出新增载体，bump 版本 + CHANGELOG 定版
- git remote -v 确认 push 目标；push 被拒（分支保护/非快进）时改走 PR 门禁并逐提交审计分叉，净内容核验后 merge 收敛
- tag+Release，取得远端回执即停止

## Stop conditions
- 发布面文件集已从上次 release 提交获得并与当前树核对一致 → 直接进入编辑，不再全仓枚举
- 版本面、CHANGELOG、tag/Release、远端同步回执齐备 → 任务结束

## Verification
- bump 后全仓 grep 旧版本号：除 CHANGELOG 历史行外零命中（或每处命中均被解释）
- 新 release 提交的文件集覆盖上次发布面，增删项均有说明
- 远端 tag/Release 回执与本地 ref 一致，分支 ahead/behind 归零

## Counterexamples
- 首次发布、历史中无上次 release 提交或 tag：无清单基线，回退到 pyproject+README 等常规搜索
- 上次发布后版本载体已知发生结构性变化（如新增承载版本号的文件）：上次提交只是基线，必须以当前树 grep 为准补齐，照抄会漏文件
- tag 列表按字典序输出、`git tag | tail` 不指向最新版本（本集 tail 给出 v0.6.5-0.6.9）：以 git log --grep 或 git describe 定位上一版，勿把 tail 当真值
- 普通功能提交/非发布类 push：不存在发布面清单，不适用本方法
