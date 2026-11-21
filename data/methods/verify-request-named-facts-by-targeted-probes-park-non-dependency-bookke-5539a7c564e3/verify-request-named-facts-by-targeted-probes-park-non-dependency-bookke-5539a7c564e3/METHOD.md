---
method_id: verify-request-named-facts-by-targeted-probes-park-non-dependency-bookke-5539a7c564e3
name: verify-request-named-facts-by-targeted-probes-park-non-dependency-bookkeeping
description: 当本会话以路径租约 owner 身份收到点名式协调/裁决请求（文本已逐字给出外来 SHA、租约文件、分支名、远端 tip）且限定只读一轮收口时，把请求当作现成核验计划：每条断言映射为一条定点 git 探针在点名位置执行，不做全库 search/grep/ls 扫描；定点探针证伪点名断言时如实记录而非自行扩大排查。回执许可 issuer revert 的依据是字节级不相交证明：外来 hunk 只含违规行、本 lane 改动在无交集血缘的提交上、违规前后基线逐字节一致。决策不依赖的簿记（如账本字段修正）在收尾报告显式停泊为遗留项，不在任务中途追猎其存储位置。
aliases: 跨lane裁决请求先核点名SHA, revert外来提交前证明我的行不重叠, owner许可revert的硬条件, 一轮收口别追猎账本位置, 请求点名的事实直接git show定点核验
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:4ea6a78e-8253-4002-b27b-26c495af4605:1802:e72786ac14af024536f4
evidence_refs: learning:learn:b460a4d93617
created_at: 2026-11-17T09:46:03.021938+08:00
updated_at: 2026-11-17T09:46:03.021938+08:00
---
## Trigger
以租约 owner 身份收到阻断级跨 Lane 协调请求，请求文本已逐字点名待核事实（精确 SHA、文件路径、分支、远端 tip）并限定只读、一轮收口、禁写共享 ref

## Discriminator
决策依赖的未知量已全部被请求文本点名，且首次 git worktree list 已显示点名 worktree 的真实路径——每个未知量对应一条定点只读探针，不存在需要宽搜索才能缩小的开放未知量；此时全库扫描与账本位置追猎都是决策依赖集之外的动作

## Short path
- 把点名词表映射为探针清单：git show <SHA> --stat+hunk 验外来提交内容；远端 ref 对比验未 push；点名 worktree 内该文件的 log/diff 验本 lane 改动所在提交与血缘；违规链两端点名 SHA 互 diff 验基线逐字节一致
- 逐条判定点名断言真/伪；证伪如实记录（如分支名与请求不符），只有证伪阻断决策时才回询请求方，不自行扩大搜索
- 决策事实齐备即经官方通道回执裁决：允许 revert 附硬条件（结果与基线逐字节一致、不触本 lane 分支/worktree、禁 force push、要求回执结果 SHA+路径表+空 diff）
- 决策不依赖的簿记在收尾报告中显式停泊：列出遗留项、归属与不阻塞理由，不在任务中途 ls/ls-files 追猎其存储位置

## Stop conditions
- 点名断言全部核验完成且官方回执已发出（state 变更已确认）
- 某点名断言被证伪且阻断裁决：停止自排查，向请求方升级要求澄清/补证
- 收尾报告已列出全部遗留簿记及其归属，无未决探针

## Verification
- 最终报告用「断言 vs 实测」表逐条对照点名事实与探针结果
- revert 许可附字节级不相交证明：外来 hunk 只含违规行、本 lane 行在无交集血缘提交、违规前后基线 diff 为空
- 确认 help_resolve 回执 state 已变更，且本会话对共享 ref 零写入

## Counterexamples
- 请求文本无精确 SHA/路径、只有模糊时间窗（'某时刻后有人改了该文件'）：第一步就该对租约文件做 git log 清扫，宽发现是合法起点
- 定点探针证伪了决策必需断言（SHA 不存在、租约归属存疑、远端 tip 与点名不符）：扩大发现或升级，不能据此放行
- 被想停泊的簿记本身在依赖集内（账本就是裁决面，或该字段正卡其他 lane 的闸）：它是核心未知量，必须定位处理或限期升级，不能静默停泊
- 本会话是违规的发现方而非租约 owner：不发许可，走 freeze-and-route 把处置权投递给 owner
