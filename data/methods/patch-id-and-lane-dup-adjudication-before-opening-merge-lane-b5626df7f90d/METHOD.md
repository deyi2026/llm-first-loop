---
method_id: patch-id-and-lane-dup-adjudication-before-opening-merge-lane-b5626df7f90d
name: patch-id-and-lane-dup-adjudication-before-opening-merge-lane
description: 多会话共享 main 的仓库里，用户丢来一个具体（常悬空、出自其他会话）的 commit 要『并 main』时，第一个未知量不是『怎么整合』而是『是否已有等价在途/已完成工作』。先建分支钉住防 gc，再用 patch-id（--stable 口径或 git cherry）在全部 refs 与 topic 匹配的 worktree 头里找等价 commit，并查 lane 账本占用；找到 base=当前 main 的等价且门禁/审查回执齐备时，跳过自己的 lane/worktree/merge/门禁整链，剩余工作坍缩为凭据与协调升级（如 diff 触及 .github/workflows 需 workflow scope，push 被点名拒绝即停、向用户呈选项）。
aliases: 并main前先查是不是有人已经做完, 悬空提交先查重再开工, 别的会话已经rebase过怎么确认, 怎么找等价提交避免重复整合, 推送被拒缺workflow权限
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:2792:024a9cc8e53f1ba80dc1
evidence_refs: learning:learn:aeb4c9d6122f
created_at: 2026-11-11T00:54:06.558702+08:00
updated_at: 2026-11-11T00:54:06.558702+08:00
---
## Trigger
多会话共享 main 的仓库里，用户给出一个具体（常悬空、作者为其他自动化会话的）commit 要求『查一下/并进 main』，本 run 尚未登记 lane 或建 worktree 时

## Discriminator
开工前已可机械取得的事实组合：该 commit 小时级新鲜、dangling（for-each-ref --contains 为空）、仓库存在 lane 账本与多个兄弟 worktree——用 patch-id --stable 对该 commit 与全部 ref/topic 匹配 worktree 头做等价比对，加上 lane 账本占用查询，一次把『是否已有等价在途/已完成』缩成 yes/no

## Short path
- 识别与保护：git show --stat + for-each-ref --contains 判可达性；dangling 立即建分支钉住（防 gc，也让后续 cherry/patch-id 可用）
- 查重：git diff-tree -p <commit> | git patch-id --stable 取指纹，对 topic 匹配的分支/worktree 头及 origin/main 之后的全部 ref commit 比对（git cherry 可代劳）；同时查 lane 账本同分支/topic 占用
- 找到等价且 base=当前 main（可 fast-forward）→ 不登记 lane、不建 worktree、不重跑整合，沿既有门禁/审查回执
- 验证可平移性：等价头 parent 对 origin/main 可 ff + ls-remote 确认远端 main 未动；若 main 已前移则 merge-tree 复演或重跑门禁
- 剩余未知量只剩凭据/协调：diff 触及 .github/workflows/* 时先 gh auth status 查 scope；push 被点名缺 workflow scope 即停止重试，向用户呈凭据选项

## Stop conditions
- 等价 commit 已确认（patch-id 同口径双向一致）且 base=当前 main、既有门禁/审查回执齐备 → 停止自行整合，只做凭据/协调升级
- lane 账本已有活跃占用 → 撤销自己的重复登记，让位/声明冲突，不并行重做
- 无等价、无占用 → 才进入自己的整合流程（worktree 沙箱写权限预检走既有卡）
- push 被命名 scope 拒绝 → 不再重试，等用户选择凭据路径

## Verification
- patch-id 用同一 --stable 口径双向一致
- rev-list/merge-tree 确认等价头对 origin/main 可 fast-forward，且 ls-remote 确认远端 main 未动
- 既有 PASS 回执绑定的正是该等价头（审查/push_src 的 SHA 一致）而非旧 base 上的版本

## Counterexamples
- 单会话/无协调账本的仓库、commit 是自己未推的工作：无可等价对象，patch-id 查重无收益，直接整合
- patch-id 等价但 base 落后当前 main（非 ff）：等价不可平移，仍需自己 rebase 并重跑门禁
- 锁文件（如 uv.lock）重生成顺序漂移会让 patch-id 不等价但语义相同：查重 miss 不等于『无等价』，需回退用 lane 账本/审查回执佐证
- 用户明确要求独立复做以供审计：重复裁决不是目标，应直接开工
