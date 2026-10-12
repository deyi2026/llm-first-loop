---
method_id: read-resolution-receipts-before-config-source-search-ca36593b1d8b
name: read-resolution-receipts-before-config-source-search
description: 核实『重启后的进程是否真的装载了某配置/特性』时，先读该次启动自身的解析回执（restart log、restart-receipt、runtime manifest、resolved-binding 输出）——它们已枚举该 pid/generation 实际生效的配置源路径，把问题缩成几次定点读取。不要先探测一个猜测通道（如某 env 文件），更不要在探空后断言『未装载』并随即发起无具名目标、无深度上界的文件系统搜索找『配置本体』；多源解析链下单一通道阴性探测不构成裁决。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fd840981-a906-404c-8c80-1c3452e1c66a:562:44bd645a7b6a62f0f6e6
evidence_refs: learning:learn:842edba9c5de
created_at: 2026-10-09T21:43:47.834809+08:00
updated_at: 2026-10-09T21:43:47.834809+08:00
---
## Trigger
需要判断某配置/开关是否已在重启或运行中的进程里生效，且此前工具输出中已出现该次启动的具名回执面（启动/重启日志、restart-receipt、runtime manifest、resolved-binding 映射）。

## Discriminator
重启日志已打印该次启动实际解析出的配置映射（code_root、data_dir、各配置源路径与脚本路径）——这是配置真值的权威枚举；同时更早的探测输出已列出具体 receipt/log 文件名。二者把『配置从哪来』缩成几个定点读取目标；而对单一猜测通道的一次阴性探测，在存在文档化多源解析链时不足以推出『未装载』。

## Short path
- 先分层收窄未知量：进程存活→HTTP 健康→配置装载→下游消息/流量进入；用进程列表+健康探测先锁定活层
- 读已点名的 restart log/receipt：取退出码、generation 与 resolved binding 映射（它枚举实际生效的配置源）
- 对映射中具名的路径逐个定点 cat/grep 验证目标配置项；禁止无具名目标、无深度上界的 find
- 用 runtime manifest/事件流验证配置的下游效果（如目标会话是否收到流量）
- 汇出分层裁决（哪层成功、真正缺口在哪一层）后停止，不再重复确认已定层

## Stop conditions
- 回执/manifest 与活进程实测（env、事件流、健康探测）一致地回答了『是否装载』和『真正缺口』，即停止发现
- 单一猜测通道的阴性探测只产生假设，不得据此直接写『未装载』结论

## Verification
- 每条装载结论都能指认到回执/manifest 中具名路径的定点读取，或对活进程的直接实测，而非通道猜测
- 全程零次无界搜索与超时重试；每个发现类命令都有具名目标和深度上界

## Counterexamples
- 进程无任何启动日志/receipt 且配置通道无文档：此时才允许有界定向搜索（必须带深度上界/目录白名单）
- 存在并发写者或多次重启竞争、receipt 可能滞后于活 pid：不能只信回执，须按『成稿前重读权威记录』方式对活进程直接探测
- 部署文档明确单一配置通道：阴性探测即可裁决 OFF，立即停止，无需任何搜索
- 用户报告的缺口是『某操作/消息未发生』而非配置装载：直接查事件流/操作记录，配置装载只是中间证据而非终点
