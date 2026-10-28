---
method_id: pin-host-remote-then-predicate-classify-branch-cleanup-a9a97c29a9bf
name: pin-host-remote-then-predicate-classify-branch-cleanup
description: 用户点名某托管站点（如 GitHub）要求分支卫生清理（没问题的并入 main、已合并的删除）时，第一个未知量是『哪个 remote 是该站点的权威仓库』，而不是本地分支长什么样：一条 git remote -v 钉住范围后，直接对权威 remote 的 refs 查处置谓词（--merged、ahead/behind、cherry），两个桶即得『删除/核验』清单，跳过会截断、诱发分页重读的本地全量注解清单。未合并桶逐支验证 main 仍缺该改动后按治理闸合并与 push，删远程 ref 及本地镜像与空 worktree；legacy remote 与本地开发 worktree 属相邻越界集合，列为待用户裁决项而非静默扩大。本集先读 74 行本地注解清单并分页重读原文，才收窄到权威远端。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8672274c-c75a-4ab5-b849-aca58f25110f:10:a3f1571bdb4b0cde5360
evidence_refs: learning:learn:50c5da575876
created_at: 2026-10-22T23:41:57.344696+08:00
updated_at: 2026-10-22T23:41:57.344696+08:00
---
## Trigger
用户要求清理某代码托管站点上积累的分支（没问题的及时并入 main、已合并的删除），而仓库配置多个 remote 或存在大量本地分支/worktree，首次枚举面临『枚举什么、枚举哪个命名空间』的范围选择时

## Discriminator
用户语句本身已同时给出目标 host 与处置谓词（已合并→删；未合并且有效→合）；git 对该谓词有直接查询（--merged / ahead-behind / cherry）。而本地带 worktree 注解的全量清单既不回答范围问题，还会因超长截断触发对同一原文的分页重读——范围未知量应先用一条 remote -v 解决，枚举对象应是权威 remote 的 refs 而非本地全量注解。

## Short path
- 解析 live 仓库根（pwd/ls；不用记忆中的跨环境路径当 workdir），钉住操作环境
- git remote -v：把用户点名的 host 映射到权威 remote（默认名 origin 不是权威信号，legacy remote 单独隔离），解决『清理范围是哪个命名空间』
- 只对权威 remote 的 refs 查处置谓词：--merged 其 main 得『可删桶』，其余算 ahead/behind 与 cherry/tree-diff 得『待核验桶』，不解析本地 74 行注解原文
- 待核验桶逐支验证 main 是否仍缺该改动（定点 grep/diff + merge-tree 冲突检查），按仓库自身治理闸（合并闸/push 闸）执行合并与 push，删除已合并远程 ref 及其本地镜像与空 worktree
- 相邻但越界的集合（legacy remote 分支、本地开发 worktree 分支）不静默扩大范围，整理成带选项的待裁决清单呈现给用户后停止

## Stop conditions
- 权威 remote 分支列表只剩 main（加显式保留项），且每条被删 ref 的内容已确认可从 main 到达
- 所有剩余分支都有明确处置：已合入 / 记录理由保留 / 列为待用户裁决
- 合并与 push 均按仓库治理闸取得有效 PASS 回执，本地同名分支与空 worktree 已同步清理

## Verification
- 删除后 git branch -r 过滤权威 remote，确认只剩预期 ref 集合
- 删除前对每条 ref 跑 --merged 或树级/patch-id 等价核验，零内容丢失
- 合并与 push 按治理闸执行并落盘回执（不拿口头声明或旧回执充数）
- legacy remote 与本地开发 worktree 以待裁决清单出现在最终答复中，未被静默处置

## Counterexamples
- 单 remote 仓库且用户明确指本地 hygiene：host 钉定退化为一次确认，直接对本地 refs 查谓词即可，先枚举远程反而绕远
- 任务目标是产出逐分支审计报告（需要每条 subject/注解）：分页读全量清单是任务本身，不是浪费
- 仓库策略要求已合并的 release 分支保留若干版本：--merged 谓词必须先与保护/保留清单求交，否则误删受保护 ref
- 用户语句未点名 host 且『分支』语义含糊：应先澄清范围，不默认 remote-only 路径
