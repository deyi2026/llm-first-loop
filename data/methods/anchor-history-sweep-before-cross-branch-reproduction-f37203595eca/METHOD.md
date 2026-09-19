---
method_id: anchor-history-sweep-before-cross-branch-reproduction-f37203595eca
name: anchor-history-sweep-before-cross-branch-reproduction
description: 当一致性 checker 报『文件F缺锚点』且F对该锚点家族零命中时，用一次跨已知 commit refs 的 git 历史横扫完成归因（预存失效 vs 本次回归），而不是到其他 worktree/分支复跑 checker 或起全量测试套件：历史 0 命中⇒锚点从未存在于F⇒stale-contract 假红；再看锚点现居模块与契约跟踪单测即可定向修复（对齐契约或委托测试）。一条命令同时回答『分支特异性』与『是否回归』，删除冗余复现运行。附带纪律：门禁退出码不经管道中间环节读取，❌输出与 exit=0 并存的矛盾须当场解决，不得先报后改。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:010fcc8e-3ba8-4948-9ae5-66a30cc8ea6e:704:cadc9017cc896bd687e0
evidence_refs: learning:learn:8e0eac9d3da8
created_at: 2026-09-17T15:14:11.985701+00:00
updated_at: 2026-09-17T15:14:11.985701+00:00
---
## Trigger
同步/一致性 checker 失败，报错形如『文件 F 缺少预期锚点』；且此前对 F 的直接搜索已显示锚点家族在 F 中零命中（整体缺失而非部分缺失）；需要归因：预存失效 vs 本次变更引入的回归

## Discriminator
两个当时已知事实的组合：(1) 对 F 的 grep 显示锚点家族零命中（类别性缺失）；(2) checker 断言逻辑要求这些字面量出现在同一路径。二者把候选原因{回归、分支特有、环境}收窄为一个可单步判定的问题——『锚点是否在 F 的 git 历史任何时点存在过』；且全部待采样 commit refs（各线/worktree HEAD）在早期 status/log 输出中已经暴露，无需先做任何运行即可横扫

## Short path
- 当前树跑一次 checker 并读其断言逻辑：确认它要求哪个文件包含哪些字面锚点（复现+契约读取合并为一步）
- 用已知的全部相关 commit refs 做一次 git grep -c <锚点> <refs> -- F 的历史横扫：同时回答『是否曾存在』与『是否分支特有』
- 全仓 grep 锚点家族现居何处（当前模块/契约跟踪单测），只跑该单测文件确认现行契约状态，不起全量套件
- 历史 0 命中 + 锚点现居他处 + 跟踪测试绿 ⇒ 判定 stale-contract 假红、预存成立；停止一切复现性运行
- 检查 checker 是否接入 CI/Makefile 等门禁以定影响面；量化陈旧副本差异并执行带备份的低风险修复；checker 修复定向为对齐现行契约或直接委托跟踪测试

## Stop conditions
- 历史横扫覆盖两条线/全部 worktree 的采样 refs 均为 0 ⇒ 归因完成（预存 stale contract），停止复现，转入修复决策
- 任一 commit 上锚点计数 >0 ⇒ 放弃 stale-contract 假设，转入回归定位/bisect 分支
- 契约跟踪单测绿而 checker 红 ⇒ 双契约漂移确认，修复收敛为对齐或委托，不再扩大调查

## Verification
- 门禁脚本退出码直接读取（不经 tail 管道）；❌ 输出与 exit=0 并存属矛盾信号，当场排查，不得留到终稿更正
- 根因结论须三证齐备：锚点在 F 全历史 0 命中、锚点现居位置、契约跟踪测试结果
- 宣布影响面之前先 grep checker 的门禁接线（Makefile/.github/CI 配置）

## Counterexamples
- F 仍含家族部分成员（如缺 02..05 但有 01）或锚点在近期 commit 存在过 ⇒ 是真回归，跨分支/worktree 复跑与 bisect 才是正确工具
- 失败形态是崩溃/超时/环境依赖而非锚点字面缺失 ⇒ 必须复现以隔离环境，历史横扫无信息量
- F 未跟踪或不在版本控制内 ⇒ 无历史可扫，退回单次新鲜运行+读 checker 源码
- 该 checker 本身就是唯一契约载体（无独立跟踪测试）⇒ 它红即内容真漂移，应修内容而非修 checker
