---
method_id: reflog-fourth-location-before-declaring-loss-in-shared-worktree-1c5b1e3fe44e
name: reflog-fourth-location-before-declaring-loss-in-shared-worktree
description: 多会话共用同一 git worktree 时，一份曾被明确观察到的未提交脏修改事后在 status/HEAD/stash 三处皆空，不得据此判『丢失/被收走』：已提交对象不随 checkout 消失，reflog 是该 worktree 的追加式变更台账，按定义记录任何人（含并发 session）的 commit。用该修改的唯一标识 token（任务 ID/文件名）+时间窗直接 grep HEAD/分支 reflog 定位提交；其落点=提交时刻的 HEAD（可能正被另一会话 checkout 到别的分支），再用 branch -a --contains 验证可达性与推送状态，滞留在未推送本地分支时以 cherry-pick 救回而非删分支。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:54ba6da3-7041-4b6f-8aac-8df1e542850f:7:5a0cdaf210d2436fedb0
evidence_refs: learning:learn:0add9a314509
created_at: 2026-10-22T19:07:25.164866+08:00
updated_at: 2026-10-22T19:07:25.164866+08:00
---
## Trigger
多个并发会话共用同一 git worktree（事件流可见不同 session_id 在同一路径操作）；一份带唯一标识 token 与出现时间戳的未提交脏修改，事后在 git status/HEAD/stash 三处均查无，期间发生过分支 checkout/pull，被怀疑『凭空消失或被人收走』

## Discriminator
进入排查时已持有的判别事实：(1) 报告本身给出唯一 token+出现时刻，且该修改在报告会话运行中途出现、非其所写→并发行为者几乎必然；(2) 三处检查（worktree/HEAD/stash）只覆盖未提交视角，而 git 中已提交对象即使切分支也不消失，reflog 必然留痕；(3) 共享 worktree 中 commit 的落点由当时 HEAD 决定，可能属于另一会话 checkout 的分支。三点合起来即可把『谁收走了/是否丢』缩为『reflog 时间窗内有无含该 token 的 commit』这一条可验证查询。

## Short path
- 一次廉价命令复核三处基线（status+stash list）确认未提交视角为真，但停在这里不下『丢失』结论
- 用唯一 token+时间窗对本 worktree 全部 reflog 做一次 grep（git reflog --date=iso 各 ref），未知量：窗内是否存在含该 token 的 commit
- 命中则 git show <sha> 核对文件与 diff 规模是否即那份消失的修改；未知量：是否同一笔内容
- git branch -a --contains <sha>（含远端）确定唯一可达 ref 与推送状态，并与主线合并时间线交叉（提交晚于 PR 推送则不在 main）；未知量：它现在挂哪、是否已进主线/远端
- 用事件流 session_id 归因提交者（并发会话 vs 自己遗忘），给出风险与救援动作：cherry-pick 到基于主线的新分支，且在确认无唯一提交前禁止 -D/清理该本地分支

## Stop conditions
- 已在 reflog 定位到内容匹配的 commit，且 branch -a --contains 明确其唯一可达 ref 与是否推送/进主线
- reflog 时间窗内确无该 token 的 commit 且事件流无并发会话写操作，才转入 git fsck --lost-found 搜 dangling blob（第四位置穷尽后才谈不可恢复）

## Verification
- 定位 commit 的改动文件与增删行规模与消失前观察到的 diff 一致（同一 token/任务 ID 出现在提交信息中）
- branch -a --contains 显示仅本地分支包含、无任何远端 ref → 判定未推送；与 PR 合并时间线交叉验证其不在 main
- 事件流时间戳：commit 时刻落在脏文件被观察到的存在窗口内，且提交者 session_id ≠ 报告会话，完成因果闭环

## Counterexamples
- 单会话独占 worktree 且 reflog 无该 token：修改可能从未被提交，reflog 无能为力，应转 fsck --lost-found 找 dangling blob 或承认不可恢复
- reflog 已过期（gc/prune）或所在分支被删且 reflog 清空：第四位置同样失效，只剩对象库搜救
- 非 git 工作区（普通目录/外部 store）没有 reflog 台账：须换用该存储自身的 append-only 变更日志或审计流
- 脏修改其实从未落盘（仅是计划/报告）：先核对事件流写入事件与 mtime 再谈去向，避免追一笔不存在的提交
