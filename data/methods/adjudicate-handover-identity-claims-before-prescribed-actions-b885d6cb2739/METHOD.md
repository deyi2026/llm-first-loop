---
method_id: adjudicate-handover-identity-claims-before-prescribed-actions-b885d6cb2739
name: adjudicate-handover-identity-claims-before-prescribed-actions
description: 交接书/上轮计划/记忆叙述是断言集，不是已核实事实。接手会话照单执行其规定动作（restart、清理、提交、重跑）前，先提取叙述中承载身份的 token：仓库路径、git HEAD、脏树清单、action id、对未提交内容的定性（如『遗留垃圾』），用已持有回执加一次批量只读探针逐项裁决 confirmed/falsified；falsified 的前提先重写，有损动作只允许作用在『存在性+性质均经回执证实』的对象上。本集一次 cd+git status 即证伪三处（路径不存在、『单个遗留 md』实为 5 文件连贯修复+知识资产、action id 不符），据此撤回删除指令、以快照内 code_root 钉死部署源、参数改取回执值，避免作用于错误目标或毁掉真实 WIP。与『完成度声明先查权威台账』不同：本方法裁决的是身份/存在/定性断言，且以 diff 内容判定脏树性质。
aliases: 按建议执行前先验货, 交接书只能当线索不能照单执行, 上轮计划先对账再动手, 删脏东西前先看diff再定生死, 重启服务前先钉死部署源, handover照单执行会踩坑
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:480:dedf3c2b949a4866070a
evidence_refs: learning:learn:e295f842be08
created_at: 2026-10-28T21:39:51.266904+08:00
updated_at: 2026-10-28T21:39:51.266904+08:00
---
## Trigger
交接书、上轮计划或记忆叙述规定了待执行动作，且叙述内嵌可检验身份断言（仓库/文件路径、git HEAD、脏树文件清单、action id、desired generation，或对未提交内容的定性如『遗留垃圾』），接手会话准备照单执行时

## Discriminator
叙述里的身份 token 全部廉价可裁决：一次 cd+git status 回执同时给出 cwd/路径存在性、当前 HEAD、真实脏树清单；已持有的 runtime 快照 blob（含被截断部分）内含 published.code_root 与 desired generation；『垃圾』定性必须由 git diff 内容证实——连贯修复+配套测试+知识资产≠垃圾。任一处 falsified 即证明后续动作可能作用在错误或不存在的目标上。

## Short path
- 列出叙述中的身份断言（路径/HEAD/脏树清单/action id/定性），明确未知量：这些前提现在是否仍为真
- 一次批量只读探针（pwd+路径存在性、git status+HEAD、diff --stat）逐项裁决；部署源与代数在已持有的 runtime 快照 blob 内定点检索，不枚举候选文件系统路径
- falsified 的前提先重写：目标换成回执给出的 code_root/清单；『删除遗留文件』因对象不存在且真实脏树是连贯 WIP+知识资产→撤回删除、登记并升级用户裁决
- 前提全部确认后才执行状态变更动作，参数（expected_generation、code_root、pid 排除项）取自回执而非叙述
- 以真回执逐项验证收敛，显式报告 confirmed/falsified 对照表，停止

## Stop conditions
- 全部身份断言 confirmed：按原计划直接执行，无需额外预检
- 关键断言 falsified 且替代目标无法由已有回执推导：停止该动作，登记分歧并升级用户；有损动作（删除/覆盖/提交）一律停
- 有损动作对象的存在性或性质未获回执证实：不执行

## Verification
- 每个被叙述断言的对象以当前回执（exit code、git status、git diff、service status）独立复核存在性与性质
- 『遗留/垃圾』定性以 diff 内容与配套文件（测试、experience 条目）交叉证实
- 状态变更参数与最终收敛判定均取自真回执；最终报告列出 confirmed/falsified 清单而非只报结果

## Counterexamples
- 用户指令自包含且即时（如『读 X 并总结』），无跨会话历史断言：直接执行，预检是纯开销
- 断言由本会话同一工具刚刚产生、无落笔→接手窗口：无漂移风险，不必重复裁决
- 动作只读、幂等且失败零代价：探针即执行，可边做边发现
