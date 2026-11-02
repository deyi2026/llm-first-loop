---
method_id: value-source-swap-check-same-name-shadow-ec2222eac648
name: value-source-swap-check-same-name-shadow
description: 在已读代码块内替换某变量的生产来源（如由裸字符串派生改为 resolver/canonical 解析）时，同一读取回执里已可见的同名再赋值行会在块内静默覆盖新值。编辑前先盘点该块内全部同名赋值，把删除 shadow 行并入同一遍编辑（或紧邻的第二次编辑）；编辑后立即对整文件 grep 同名赋值模式，确认只剩唯一生产者，再去动其他文件。把『事后 grep 发现再补一刀』变成『同遍处理+相邻验证』，消除改动静默失效的窗口。
aliases: 改了变量来源却被旧赋值盖回去, 同名赋值覆盖检查, 替换取值来源先盘点同名再赋值, 规范化解析改造后旧的清洗残留, 编辑后立即 grep 同名赋值防 shadow
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:c70ac3c2-9b73-442c-9a37-94a9ff1bb6f7:449:f85c1ddfd8e528fbe803
evidence_refs: learning:learn:9ab475aebda4
created_at: 2026-10-31T21:13:38.379218+08:00
updated_at: 2026-10-31T21:13:38.379218+08:00
---
## Trigger
要在一个已读且读取回执仍代表当前状态的代码块内，替换某个局部变量的生产来源（引入新 resolver/新派生逻辑，而原有同名赋值行仍留在块内）时

## Discriminator
同一读取回执中，该变量在新来源位置之后已存在同名再赋值行（本集：resolve_id 返回的 stem 随后被 stem = exact 的旧裸派生行覆盖，两行同在编辑前已读的 40 行窗口内）——编辑前即可据已读事实预测 shadow，无需任何后续信息

## Short path
- 从既有读取回执盘点目标名在该块内的全部赋值行，识别位于新来源之后、会顺序覆盖新值的再赋值
- 把『换来源』与『删 shadow 行』并入同一遍编辑（单 hunk 工具则紧邻补第二刀），不把验证推迟到其他文件的编辑之后
- 编辑后立即整文件 grep 同名赋值模式（如 'stem ='），确认文件内只剩唯一 canonical 生产者，其余同名赋值属于不同作用域/分支
- 复读编辑块，确认下游消费（ref 构造、账本写入）用的是新来源产出的值，然后停止

## Stop conditions
- 文件内该名只剩一个生产者，且写后复读显示下游消费的是新来源（canonical）值
- grep 发现的其余同名赋值经作用域/分支判断不构成顺序覆盖，记录后停止

## Verification
- 对整个文件 grep 同名赋值模式，而不是只看编辑窗口内的行
- 利用写后复读回执核对 ref/标识构造使用的是 resolver 返回值而非旧的裸派生值

## Counterexamples
- 同名赋值位于另一分支或另一作用域（else 分支、别的函数），没有顺序覆盖关系，照删会破坏正常逻辑
- 连续赋值本身是分步规范化管线，中间赋值是数据流的一步而非 shadow，需按数据流方向判断而非见到同名就删
- 变量本来就只有单一赋值点、直接修改原来源而非并行引入新来源——不存在 shadow 风险，无需此流程
