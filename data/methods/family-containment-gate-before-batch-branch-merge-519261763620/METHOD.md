---
method_id: family-containment-gate-before-batch-branch-merge-519261763620
name: family-containment-gate-before-batch-branch-merge
description: 面对十余条未合并分支的批量并入/处置时，不要机械逐条 merge。先用分支名前缀+日期把清单聚类成族，再逐族做包含性/等价性验证（merge-base --is-ancestor 判 tip 包含、git cherry 输出为空判内容已 squash 入 main、树级 diff 判演进或等价残留），族内只合并最新完整版本；验证为旧快照/纯收据的整族跳过并留档证据。巨型混合分支（大量证据文件+少量代码）先拆分裁定再处置。执行中一旦发现目标 worktree 被并发写者占用或出现同主题新分支，立即冻结一切破坏性操作（不打 tag、不删分支、不 fast-forward），集成分支保持待命等收口裁定。本集 27 条中 14 条被证实为 main 已有更新形态，机械合并会把 main 往回拖。
aliases: 一堆没合的分支怎么处置, 先按前缀把分支分组, git cherry 空就是早合过了, 别把主干往回拖
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6c50a13c-1fe0-4283-ac06-c9bca4e9d637:138:df95d1d7811456a520b3
evidence_refs: learning:learn:8be828865462
created_at: 2026-10-17T00:57:53.153139+08:00
updated_at: 2026-10-23T05:53:11.935442+08:00
---
## Trigger
需要对一批（约≥10条）未合并分支做并入/归档/清理处置，且初始 unmerged 清单已呈现同前缀、相近日期的族结构（如 rule28×5、learning×6、web-v2×3）

## Discriminator
初始 unmerged+ahead 清单即暴露族结构：同前缀分支的 diff 面在同族内递增（2187→2288→2443）或完全相同（三条同为 19 文件/1118+/77-），commit 日期密集聚集——这表明族内是演进快照或 squash 等价残留而非独立工作，『每条都该合』的默认假设不成立；同时 worktree 被占用/同主题新分支出现是并发写者在场的直接信号

## Short path
- 列 unmerged+ahead 清单，按前缀+日期聚类识别族，先不下任何合并决定
- 逐族做包含性验证：merge-base --is-ancestor 判 tip 包含关系；git cherry 输出为空判内容已以 squash 进 main；树级 diff 判内容等价/演进/独立新增
- 族内选最新最完整版本进集成分支并跑测试；验证为旧快照或纯收据（零代码仅 docs 收据）的整族不合，逐条留档证据
- 巨型混合分支先做内容性质拆分：仅精确提取代码部分或整支归证据线，不整体盲合
- 执行中一旦发现 worktree 被并发代理占用或新开同主题分支，立即停手冻结破坏性操作，集成分支待命等统一裁定

## Stop conditions
- 每族已确定唯一合并代表，且所有『不合』分支均有 git cherry/树级 diff/字节级相同证据留档
- 发现并发写者占用目标对象（worktree 被占、同主题新分支出现）→ 停止 tag/删除/fast-forward，交用户裁定吸收路径
- 合并提交测试全绿（本集 82+29+29 passed）即停止，不再追加无信息枚举

## Verification
- 合并后运行完整测试套件确认无回归
- 『不合』决定逐条附机械证据（cherry 空/diff 面/逐字节相同）写入处置文档可复查
- 收口前以权威 git 状态（branch/tag/log/工作区）重读确认，结论表述为带时间戳快照而非终局

## Counterexamples
- 分支各自独立、无同前缀族结构（各 1-2 commit 不同主题）→ 族分析是纯开销，直接逐条评估合并
- 族内 tip 互不包含但内容均为独立新增（非演进覆盖，如 rule31×4 需语义并集）→ 不能只取一条，需全族合并解决冲突
- 单人静态仓库、无并发写者 → 无需 worktree 占用检查与冻结逻辑
- 单条长命功能分支 → 无族可比，直接走常规合并门即可
