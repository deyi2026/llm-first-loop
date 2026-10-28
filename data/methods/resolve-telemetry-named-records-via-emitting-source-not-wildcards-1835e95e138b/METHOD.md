---
method_id: resolve-telemetry-named-records-via-emitting-source-not-wildcards-1835e95e138b
name: resolve-telemetry-named-records-via-emitting-source-not-wildcards
description: 用户要求查看某子系统的消息/协调/通知/待办记录时，若事件流或状态工具的 telemetry 行已命名具体记录（id=/ref=/files=/from= 字段），把这些字段当 provenance 指针：用 telemetry 中的字面串（如状态枚举值）做 content-grep 定位发出该行的服务源码，从源码常量读出存储根/收件箱路径，直接列目录并只读最新文件，再用 telemetry 行解释其处置状态。不要回退到全仓文件名通配枚举；若对确认存在的标识做文件名搜索仍 no-match，说明存储在文件名索引之外（运行时数据目录），应切换到『源码推路径或直接 ls 数据目录』，而非继续换通配模式。与『经 handler 定位权威存储』方法互补：本方法入口是 telemetry 已给出记录标识，且额外利用 no-match 作为索引外信号。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:31e64fa8-0da2-4a1c-afd1-a74ed4fcd805:74:87cd09e8c13d855cea12
evidence_refs: learning:learn:9cb31de2ca0f
created_at: 2026-10-19T08:23:41.854234+08:00
updated_at: 2026-10-19T08:23:41.854234+08:00
---
## Trigger
用户要求查看/核对某子系统（消息、协调、通知、待办）的记录，且事件流或状态工具输出中已出现结构化 telemetry 行，行内带具体记录标识（id=/ref=/files=/from= 等字段）

## Discriminator
telemetry 行是否直接命名了目标记录的标识/文件名；同时若按该标识做文件名通配搜索返回 no-match（而系统确实产出过该记录），这两个事实共同表明存储位置在文件名索引之外（运行时数据目录），唯一可信定位途径是发出该 telemetry 的服务源码——grep telemetry 中的字面枚举串即可定位该源文件，其内部定义了 data_dir/收件箱相对路径

## Short path
- 用一次 scoped 事件流查询（按子系统关键字过滤）确认目标子系统及记录标识：未知量=这些消息由谁产生、叫什么；产出=带 id/ref/files/from 的 telemetry 行
- 用 telemetry 中的字面状态串（枚举值/事件名）做受控 content-grep 定位发出该行的服务源码：未知量=这些记录物理存放在哪；产出=源文件路径
- 读服务源码中的存储根/收件箱常量，然后直接 ls 该数据目录（注意 pending/done 等分层）：未知量=当前有哪些真实消息文件；产出=待处理计数与最新归档文件
- 只读最新相关文件内容，并用 telemetry 行+源码注释解释其处置（为何生效/未生效）：未知量=用户要的消息内容与状态
- 标识、时间戳、路径三者在 telemetry、源码、磁盘间一致后停止并汇报

## Stop conditions
- 已从物理存储读到最新消息内容，且其处置状态可由 telemetry 与源码规则互相印证
- 专用查询工具（message_flow/状态类）已返回完整消息内容与待办计数，无需再定位物理存储
- 用户只问『有没有待处理』且状态计数已给出权威答案

## Verification
- 磁盘文件名/时间戳与 telemetry 的 id/ref/files 字段一致
- 实际存储路径与源码中定义的存储常量一致
- 解释处置状态的规则确实写在发出 telemetry 的源码中，而非推测

## Counterexamples
- 专用消息流/状态工具已返回完整消息正文与 pending 计数 -> 直接使用并停止，不必找物理存储
- 文件名搜索直接命中目标消息文件 -> 直接读文件，无需读服务源码推路径
- telemetry 发出方是远端/第三方服务，源码不在本地 -> 无法由源码推路径，改用该系统自身 API 查询
- 用户只关心 pending 有无 -> 状态计数即最终答案，不应深入 done/ 归档做历史分析
