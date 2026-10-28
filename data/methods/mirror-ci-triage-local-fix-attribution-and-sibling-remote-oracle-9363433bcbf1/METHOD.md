---
method_id: mirror-ci-triage-local-fix-attribution-and-sibling-remote-oracle-9363433bcbf1
name: mirror-ci-triage-local-fix-attribution-and-sibling-remote-oracle
description: 多远端 mirror 仓收到 CI 失败报告且本地 main 领先失败远端时：先 git remote -v 定位失败 run 所属远端与共享历史、同 workflow 的兄弟远端；失败归因优先读本地历史中失败 commit 之后的 fix(ci) 提交信息（与上报 job 名称/时长逐条对齐），远端日志仅作后台确认，不在前台与超时网络缠斗；推送前必查兄弟远端对本地 HEAD 的 run list——『最后绿→首红』暴露『已被修复』是否被后续回归取代；再在 detached worktree 的精确 HEAD 上按 CI 同口径复跑各门禁枚举具体违规，全绿后才推送并以 run ID 回执确认。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8fe12f72-6aae-49af-8d1e-a8278b807b48:5:03e1ed0991ff436397d8
evidence_refs: learning:learn:1c8311e77697
created_at: 2026-10-14T21:47:56.620774+08:00
updated_at: 2026-10-14T21:47:56.620774+08:00
---
## Trigger
CI 失败报告指向某仓库，本地克隆是多远端 mirror（本地 main 领先失败远端的 main），且远端 CI 日志获取超时/不可靠，或需要先归因再决定是否推送修复时。

## Discriminator
git remote -v 已显示失败仓库映射到哪个远端，并存在共享提交历史且运行同一 workflow 的兄弟远端；失败 run 的 commit 已在本地历史中，其后跟随 fix(ci) 提交，其提交信息精确归因了与用户上报一致的失败 job（含时长/规则）。这两条当时可见的事实分别替代『远端日志』与『推送试探』两个宽搜索。

## Short path
- git remote -v + gh run list -R <失败仓库>：锁定失败 run 的 commit 与所属远端，同时记下共享历史、跑同一 workflow 的兄弟远端。
- git log <失败commit>..HEAD：查其后的 fix(ci)/fix 提交并读全文，若归因与上报失败 job 逐条吻合即视为一次归因；远端 --log-failed 只放后台重试作确认。
- 推送决策前查兄弟远端 run list 对本地 HEAD 及中间提交：最后绿→首红判定『已修复』是否被后续提交的新回归取代，避免『直接推上去就行』的假结论。
- 在 detached worktree 检出精确 HEAD，用仓库自身脚本/锁定环境按 CI 同口径复跑失败门禁（安全扫描/静态 ratchet/测试），枚举具体违规清单。
- 最小机械修复后本地全部门禁复验通过，推送受影响远端（兄弟远端同因红灯一并推），以 run ID 确认两地 success 回执。

## Stop conditions
- 所有受影响远端对已推送 HEAD 均存在 success run 回执（以 run ID 为证，而非无通知推断）。
- 失败归因已与 fix 提交信息/本地同口径复验双向印证，且兄弟远端显示当前 HEAD 为绿：无需再扩大排查。

## Verification
- 本地复验命令与 workflow YAML 步骤逐项对齐：同一脚本、同一 flags、同一锁文件环境。
- fix 提交信息中的失败清单与用户上报的失败 job（名称、时长、规则）逐条对上才算归因成立。
- 最终以各远端 run ID 复查状态为 success；本地假红的 race 敏感测试需孤立复跑区分 flaky 与真回归。

## Counterexamples
- 单远端克隆或失败 commit 不在本地历史（如 fork PR）：本地 fix 归因不可用，必须取远端日志，本方法退化。
- 兄弟远端 workflow 不同或不含本地 HEAD 提交：不能当 CI 预言机，只能依赖本地精确树复现。
- 失败仅存在于 runner 环境（secrets、网络、runner 镜像差异）：本地与兄弟远端均绿但推送仍红，需回头读远端 job 日志。
- 工作树带未跟踪运行时产物：安全扫描必须扫 detached worktree 的已提交树，否则误归因到未提交文件。
