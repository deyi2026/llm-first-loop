---
method_id: object-scoped-remediation-before-shared-worktree-mutation-b735540602a6
name: object-scoped-remediation-before-shared-worktree-mutation
description: 校验/机检 FAIL 时，先从失败输出与操作语义确认最小修复面：若失败指向提交元数据（如 subject 前缀不合规），直接用只动提交对象的操作（git commit --amend -m）修复；不要为满足未经核实的『干净工作区』前置条件先跑 git stash -u 之类的全工作区状态变更——amend 与提交对象级机检都不受未跟踪文件影响，而共享长生命周期工作区的 stash -u 会吞掉活动未跟踪文档，迫使额外核对与恢复。任何 stash -u/clean/reset 前，必须先用操作语义和 git status 证实前置条件真实存在；确需动工作区时用路径限定操作。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fd840981-a906-404c-8c80-1c3452e1c66a:344:e72cd2d12679550c2c52
evidence_refs: learning:learn:5f21b016a0a4
created_at: 2026-10-09T18:55:03.705444+08:00
updated_at: 2026-10-09T18:55:03.705444+08:00
---
## Trigger
在共享、长生命周期工作区内，机检对某次提交 FAIL 且失败信息点名提交元数据问题（如 subject 前缀不在白名单）；或准备执行 stash -u / clean / reset 等全工作区状态变更以满足一个未核实的前置条件。

## Discriminator
当时已可见的判别事实：(1) 机检 FAIL 输出自带修复规格——点名规则①前缀白名单，即改 subject 即可；(2) 机检脚本头部与实现（git log/diff-tree）表明它读提交对象、不读工作区，未跟踪文件不影响结果；(3) git commit --amend -m 只改 HEAD 消息，本就不要求 clean tree；(4) stash list 显示工作区累积着历史会话的活动 stash、session 中持续产生未跟踪文档——stash -u 必然吞掉活动内容。前置条件（需要清理）不存在，而变更代价真实存在。

## Short path
- 读机检 FAIL 输出，确认失败面是提交元数据而非工作区内容——修复即改 subject
- 执行对象级最小修复：git commit --amend -m 'fix(r9): ...'，跳过任何 stash/clean 前置动作
- 复跑同一机检确认 PASS，并核对 diff-tree 文件集与 amend 前一致（改消息不改内容）
- 若确需动工作区：先 git status --short 列出受影响面，再用路径限定的 stash push -u -- <paths>，不用无界 stash -u

## Stop conditions
- 机检 PASS、提交文件集与修复前一致、且 git stash list 与 git status 和操作前完全一致（零新增 stash、未跟踪文件零丢失）

## Verification
- amend 后复跑机检 PASS，且 git diff-tree 文件清单与修复前逐项一致
- 对比操作前后 git stash list 条目数与 git status --short 输出：未跟踪文件原样、无遗留 stash

## Counterexamples
- 切换分支时未跟踪文件与目标分支同名跟踪文件真实冲突——此时路径限定 stash 是正当前置，应使用
- 机检失败源于提交内容缺失（漏 add 文件）而非元数据——需动 index/worktree，但先 status 圈定影响面再操作，而非全量 stash
- 私有一次性 worktree、无共享状态且无活动未跟踪文件——stash -u 代价可接受，不必过度仪式化
