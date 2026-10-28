---
method_id: sweep-artifact-consumers-before-reordering-verification-chain-d27df9ea3a0a
name: sweep-artifact-consumers-before-reordering-verification-chain
description: 当任务书/修复要求隐含改变既有构建-校验链的步骤顺序或产物覆盖范围（如让 manifest 进入 checksum 校验、把生成步骤前移）时，不要直接按字面实现：先 grep 受影响产物名在全仓 scripts/CI 的消费方，确认下游机械门禁（如 finalize 的资产集比对）在新顺序下仍成立。当前顺序常是负载契约——为避免哈希循环依赖而刻意设计，字面满足新要求可能让转正门以『多余资产』拒绝，最终被迫整体回退。实现前发现冲突应上报任务书来源对齐取舍，而不是先改再撞。
aliases: 改发布流程步骤顺序前先查谁在读这些产物, checksum 覆盖范围调整会不会破坏机械转正, 让 manifest 进校验和前先核 finalize 比对, 调换生成步骤顺序先扫下游脚本, 顺序调整被多余资产卡住怎么排查
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:20761eb6-10e4-4e71-ae2b-0465510a97d8:606:933fe7e199b0acc289c7
evidence_refs: learning:learn:0daf011dd1ce
created_at: 2026-10-27T21:18:22.301456+08:00
updated_at: 2026-10-27T21:18:22.301456+08:00
---
## Trigger
任务书/用户要求隐含把既有 release/构建/校验流水线中两个生成步骤调换顺序，或改变某产物（manifest/checksum/白名单）的覆盖范围，而该链已存在且可能另有下游消费者

## Discriminator
改动前即可观察：对受影响产物名做一次全仓 grep，若命中本文件之外的消费方（finalize/gate 脚本的 collect/比对函数、注释中写明的资产集规则），或 git log 中该产物与机械门禁同批出现——说明当前顺序是被消费的契约而非偶然排列

## Short path
- 从任务书抽出结构性含义：是否需要调换步骤顺序或改产物覆盖，标记为契约级改动
- 对受影响产物名做一次全仓 grep（scripts/、CI workflow），列出消费该产物或依赖其顺序的代码
- 逐个核对消费者在新顺序下的假设是否仍成立（如 manifest 生成时刻的目录内容 vs 上传资产集比对）
- 发现会破坏的消费者 → 先与任务书来源/用户对齐取舍（保留原顺序或同步改消费者），再动代码
- 实现后除跑任务书点名的测试外，再跑消费者自身门禁/单测，验证两侧契约均成立

## Stop conditions
- grep 未发现改动文件之外的任何消费者，或所有消费者已核对为顺序不敏感
- 冲突已上报并得到裁决（保留原顺序/同步修改消费者）
- 新断言与下游门禁两侧验证均通过

## Verification
- 改动后本地执行下游 gate 的判定逻辑或其单测，而非只跑任务书要求的测试
- diff 检查被调换步骤的命令字节是否原样、仅顺序变化
- 逐项比对上传资产集与 manifest/checksum 申报集在新顺序下的一致性

## Counterexamples
- 流水线是新建的或单消费者（无其他脚本读取这些产物），无需消费者扫描，可直接实现
- 两步骤间无数据依赖且无任何外部方消费其产物内容，纯局部重排
- 任务书本身已列出需同步修改的全部消费者清单并要求一并更新——按清单执行即可
