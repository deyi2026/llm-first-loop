---
method_id: reconcile-final-report-claims-vs-worktree-escalate-unowned-residue-b5c171bc7eb0
name: reconcile-final-report-claims-vs-worktree-escalate-unowned-residue
description: 用户交付终局/交接报告时，不直接复述确认。先把报告中可机械验证的断言（分支/HEAD、门禁结果、红项归属、附带改动的形状如'纯搬移/只动同函数'、是否还有遗留）逐条与仓库真值对账：status、diff --cached --stat、log。最锋利的判别是类型不匹配：叙述称纯搬移，staged 却有新测试文件与跨模块净增——新文件与纯搬移在类型上互斥，不必读 diff 内容即可判定存在叙述外残留。匹配的断言照实确认；不匹配的残留定性为无人认领半成品，作为归属决策点交用户（接手收口/stash 保底/归还原会话），不擅自 stash、不代改、不静默吸收。
aliases: 终局报告先对账再确认, 纯搬移的说法对不上 diff 怎么办, 收尾时发现没人认领的 staged 改动, 交接报告核实工作树残留, staged 半成品是收口还是 stash
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ce8b88af-7349-4903-91ab-b37a329e0489:1111:9975ff92ed2f120fcc01
evidence_refs: learning:learn:e42e114fb9c1
created_at: 2026-10-29T06:53:19.595254+08:00
updated_at: 2026-10-29T06:53:19.595254+08:00
---
## Trigger
用户交付终局/收尾/交接报告，叙述中含有对已完成改动形状（纯重构/纯搬移/只动某函数）与完成度的断言，且本地仓的机械状态可直接核验

## Discriminator
首次 git status 已可见的形状类型不匹配：叙述称附带改动为'同函数纯搬移'且无其他待办，而 staged 区却出现新增测试文件（A tests/...）与跨模块净增——新增文件与纯搬移在类型上互斥，无需深入 diff 内容即可判定存在叙述未覆盖的残留

## Short path
- 从终局报告列出可机械验证断言清单：分支/HEAD 落点、门禁数字、红项归属、附带改动的形状、是否还有遗留
- 一次 status/branch 调用确认落点并盘点 staged/untracked；staged 清单中出现新文件即与'纯搬移'叙述类型冲突，这已足够中止对 worktree/日志的宽枚举
- git diff --cached --stat 逐文件核对形状类型；按时间窗/批次路径查 log 寻找该 staged 批次的收口提交
- log 无收口提交→定性为无人认领半成品；已验证断言照实确认（含用户自己完成的边界判断），残留作为归属决策点呈报：接手收口、stash 保底、还是归还原会话——不单方面处置

## Stop conditions
- 报告中每条可验证断言要么被机械真值确认、要么已作为决策点呈报用户
- staged 形状与叙述完全匹配且 log 存在对应收口提交→确认后即停，不再枚举 worktree/日志寻找更多差异
- 用户已显式声明工作树含其他在途工作、要求忽略→残留即有主，不再升级

## Verification
- staged diff --cached --stat 的文件清单与净增删形状，逐项对照叙述的改动类型
- git log（时间窗/批次涉及路径）为空，证实该批次无收口提交
- 当前分支/HEAD 与报告落点一致；用户已做的归属实证（如 stash 验红）按其机制引用而非重做

## Counterexamples
- 叙述本就描述功能性大批改动，且 staged 形状与之相符→确认即停，不制造升级
- 仅存在 untracked 临时脚本/receipts 等工作区碎屑，而无 staged 跟踪文件改动→正常残留，不当无人认领半成品
- 断言只涉及远端 CI 结果且本地仓与该树无共享会话→对账对象是门禁回执，而非本地工作树
- 用户已声明'工作树有别的在途任务，别动'→按声明归属，不再对账升级
