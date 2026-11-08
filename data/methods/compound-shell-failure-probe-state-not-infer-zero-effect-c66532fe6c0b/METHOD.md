---
method_id: compound-shell-failure-probe-state-not-infer-zero-effect-c66532fe6c0b
name: compound-shell-failure-probe-state-not-infer-zero-effect
description: 多语句串联的 shell 命令（heredoc 落盘+回显/校验片段）以 syntax error 非零退出时，退出码不等于零副作用：/bin/sh 逐语句执行，出错行号之前的写操作可能已落盘。用回执自带的解释器身份与出错行号把命令分区为『可能已执行前缀/未执行后缀』，再直接探测副作用目标的实际状态决定补写还是跳过；/bin/sh 下不写进程替换等 bash 专有语法。
aliases: shell报错但文件其实写进去了, 语法错误前面的语句执行了吗, 命令失败了文件到底写没写, 重跑前先确认有没有已经执行, 写盘命令报错要不要再跑一次
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7007267a-8cde-4b7c-bcc4-b677b3653671:28:7f889d729a79b51f967e
evidence_refs: learning:learn:adb5cde4f219
created_at: 2026-11-07T00:55:37.593971+08:00
updated_at: 2026-11-07T00:55:37.593971+08:00
---
## Trigger
一次 exec 中串联多条语句（写文件+验证片段+计数）以非零退出码失败，尤其是解析期 syntax error；或执行回执显示解释器为 /bin/sh 而拟执行的命令含 bash 专有语法（进程替换、数组等）

## Discriminator
失败回执自带两个当时即可用的判别事实：stderr 前缀给出解释器身份（/bin/sh: -c:），出错行号给出失败位置（本例 line 148，位于 heredoc 之后）——逐语句执行的 shell 中，出错行之前的写副作用可能已生效，『exit≠0 ⇒ 零副作用』推断不成立；且 /bin/sh 下出错构造（bash -n <(sed ...)）本身是方言语法

## Short path
- 组包长命令前，从既有执行回执确认解释器（exec_mode=shell、stderr 前缀 /bin/sh）⇒ 只写 POSIX 语法，进程替换/数组改用临时文件或显式 bash -c 包裹
- 失败发生后，先读回执中的 shell 名与出错行号，把命令切成『可能已执行前缀』与『确定未执行后缀』两个区段，不急于归因或重跑
- 直接探测副作用目标状态（ls/stat/读回目标文件），把实际状态当待观测未知量，不从退出码推断『没写入』
- 目标已存在且内容与意图一致 ⇒ 跳过重写；缺失才补写，且重写保持幂等（同内容覆盖无害）
- 移除引发失败的方言语法后，仅重跑未完成的校验部分，以 wc/grep 抽查内容即停

## Stop conditions
- 副作用目标已确认处于预期状态（存在+内容一致），且方言语法已从重跑命令中移除
- 探测发现目标不存在 ⇒ 补写一次并读回验证后停止，不反复重跑

## Verification
- 重跑前后各一次直接读回目标产物（ls + wc/grep 抽查），确认状态判定与实际一致
- 确认最终交付物内容与首次写入意图一致，未因重跑产生分叉

## Counterexamples
- syntax error 落在首条语句或所有副作用语句之前 ⇒ 前缀未执行，可直接整条修正后重跑
- 执行器先整体编译再执行（部分沙箱 runner 或 SQL 类引擎）⇒ 解析失败即零副作用，行号分区逻辑不适用
- 回执解释器是 bash/zsh ⇒ 进程替换等语法合法，失败另有原因，不应归因于 shell 方言
- 副作用非幂等（mv 覆盖、rm、消费型操作）⇒ 不可直接重跑，状态探测从建议升级为重试前必须
- 单条原子命令失败（无前缀语句）⇒ 退出码即完整状态，无需分区
