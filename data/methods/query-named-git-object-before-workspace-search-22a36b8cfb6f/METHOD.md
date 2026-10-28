---
method_id: query-named-git-object-before-workspace-search-22a36b8cfb6f
name: query-named-git-object-before-workspace-search
description: 早前回执已显式点名与所需未知量因果绑定的版本控制对象（如 git status 的 contains 段给出滞留提交 SHA，而任务正是抢救/搬运该提交），且下一个未知量是『该对象包含哪些文件/什么 diff』时，这是对象属性查询题，不是工作区发现题：下一步直接对对象做单跳查询（git show --stat <sha>），而不是文件名全局搜索或猜包路径试错。在含发布快照镜像目录的仓库里，全局文件名搜索主要命中镜像副本；猜错路径还会留下 TTL『路径不存在』登记，进一步污染后续检索。仅当目标文件不属于任何已命名对象时，才回到镜像感知的工作区发现。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:54ba6da3-7041-4b6f-8aac-8df1e542850f:18:9c4563a6f81a9b4144c6
evidence_refs: learning:learn:348d09a970d2
created_at: 2026-10-22T20:13:02.402186+08:00
updated_at: 2026-10-22T20:13:02.402186+08:00
---
## Trigger
任务所需事实（文件清单/diff/变更量/归属）是某个早前回执已逐字命名的 git 对象（提交 SHA、分支、tag、PR/run ID）的属性；典型场景：抢救滞留提交、核对某 PR/commit 的改动范围、确认某分支包含什么

## Discriminator
已持回执中是否出现可逐字引用的对象标识（如 CONTAINS-<sha>→分支段、merge 提交里的 PR 号），且用户目标直接以该对象为主语。满足→未知量=对象属性，一次 git show/diff-tree 可解；不满足→才是工作区定位题。本集判据：git status 回执已给出滞留提交 SHA 及所在分支，助手自己也写明未知量是『该提交具体动了哪些文件』，却先做了两次被镜像污染的 search_files 和一次猜路径的失败 read

## Short path
- 扫描已持回执，确认被点名对象 ID 与用户目标的因果关系（滞留提交 SHA ↔ 抢救目标）
- 对对象做单跳属性查询：git show --stat <sha>，直接取得精确文件路径与 +/- 行数，消除『动了哪些文件』这一未知量
- 用取得的路径驱动后续定向动作：worktree 占用检查、CI 标准命令确认、子代理任务书中的路径字段；全程不为这些路径再发文件名搜索或猜路径读取
- 若对象查询失败（浅克隆缺对象），先 fetch 补对象；仍不可得才降级到镜像感知的活树发现（枚举/同类路径样例推导）

## Stop conditions
- 对象属性（精确路径+变更量）已取得且与用户目标语义一致，即进入下一调度环节（门禁确认/子代理派发），停止一切发现类动作
- 对象本地不存在且无法 fetch，或查明回执命名的对象与目标只是同名巧合

## Verification
- git show --stat 输出的文件路径 == 后续子代理实际编辑/测试的路径，且全程未再为这些路径调用 search_files
- 对象 ID 从回执逐字复用，无 404/路径不存在 TTL 登记产生
- diff --stat 的 +/- 行数与最终 PR 的变更量一致，证明未漏审镜像外的多副本

## Counterexamples
- 目标文件是未提交的工作区修改，或与任何已命名提交无关的纯现状定位（『配置文件放在哪』）→ 对象查询无从谈起，直接文件系统枚举
- 已知 SHA 但本地浅克隆缺对象且无 fetch 权限 → 只能回到工作区搜索/向用户求证
- 回执命名的对象与用户目标仅同名巧合（不同分支的同前缀 SHA、他人 PR 号）→ 先核实对象归属再查询，否则查错对象得出假事实
