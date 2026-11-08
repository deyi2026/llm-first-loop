---
method_id: pristine-base-rerun-attribution-when-scoped-fix-fails-final-gate-dff6ad4d9084
name: pristine-base-rerun-attribution-when-scoped-fix-fails-final-gate
description: 限定文件清单的修复轮在最终全量门禁（CI/R9）exit≠0 时，第一未知量不是'怎么修这些失败'，而是'失败归因于本轮 diff 还是 base 自带'。判别：把失败检查点名的文件/函数与授权改动面求交集；再 stash 本轮改动（或在 base SHA 的隔离 worktree）于纯 base 树原样重跑同一门。base 同败⇒继承债：不越权修、不提交（守住'门未过不提交'红线），冻结候选指纹，上报归因证据（含 base commit 验证声明与实测矛盾的'验证漂移'线索）并给裁决选项；base 过而本轮败⇒回头修自己。
aliases: CI挂了先看是不是老代码的锅, 测试失败全不在我的改动文件里, stash掉改动在原HEAD重跑归因, 棘轮基线超标是不是历史遗留, commit说过了CI但复跑失败, 门禁没过能不能先提交
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:1292:37336cff30f20af625ce
evidence_refs: learning:learn:46dfa77926d5
created_at: 2026-11-07T23:17:08.961929+08:00
updated_at: 2026-11-07T23:17:08.961929+08:00
---
## Trigger
带明确改动文件清单与门禁红线的最小修复/补丁轮，已完成实现+定向测试+独立审查，收尾提交前跑全量 CI 门禁 exit≠0，且失败项看似与本轮改动无关（如落在其它模块的棘轮基线、lint、测试）

## Discriminator
失败报告点名的目标（文件/函数/规则）与授权 diff 面的交集是否为空，以及失败是否属'基线登记值 vs 实测值'类差分（此类差分天然指向历史增长而非本轮新增）。交集为空 + 基线差分 ⇒ 强烈指向 base 自带，用纯 base 树原样重跑一锤定音

## Short path
- 读门禁失败报告，把每个失败项映射到其点名的文件/函数，与授权改动文件清单求交集（未知量：失败是否可能由本轮引起）
- 交集为空的项：stash 本轮全部改动（或以 base SHA 建只读隔离 worktree），确认工作树==base 后原版重跑同一门禁（未知量：base 树是否同样失败）
- base 同败 ⇒ 归因=继承债：恢复本轮改动，逐项记录'base 树同败'证据；不修清单外文件、不本地提交（门禁红线）
- 顺带核对 base commit message/verify_ref 中的验证声明与 base 实测是否矛盾，如实标注'验证漂移'（既往验证可能跑在与最终提交不同的树态），不作超出证据的推断
- 冻结本轮候选逐文件 SHA，向授权人呈报归因矩阵+阻断点，并给受限选项（先清 base 债再重跑门 / 先追查既往验证声明），等待裁决后按原序列续跑

## Stop conditions
- 纯 base 树同败已复现并留档 ⇒ 归因完成，停止本地排查转上报，不得无授权改动清单外文件
- base 树通过而本轮树失败 ⇒ 立即放弃'赖 base'假设，回到自身 diff 修复
- 门禁结果不稳定（环境/flaky）⇒ 归因不可判定，按门禁自身故障上报，不下结论性归因

## Verification
- stash 后用 git status/rev-parse 确认工作树即 base 原样再跑门禁；跑完恢复改动并复核候选逐文件 SHA 与冻结指纹一致
- 失败项逐条比对 base 树与本轮树的失败集合是否逐项相同（同一测试、同一违规清单），而非仅测试名相同
- 对'base commit 声称门禁通过'的漂移，保留 base 树门禁输出原文为证，不以口头推断替代

## Counterexamples
- 失败检查目标落在授权改动面内（即使 base 也可能有份）：交集非空 ⇒ 先按本轮引入处理，直接修自己，不写阻断报告
- 门禁在纯 base 树无法原样运行（依赖本轮新增 fixture/文件）：动态重跑不可用，退化为 git show base:<file> 静态锚点比对，且结论降级为'疑似'
- 门禁本身 flaky（网络/缓存/顺序敏感）：单次 base 重跑不足为凭，须先判稳定性
- 授权本就是全仓收口、无文件清单约束：继承失败同样在职责内，直接修，无需归因上报
