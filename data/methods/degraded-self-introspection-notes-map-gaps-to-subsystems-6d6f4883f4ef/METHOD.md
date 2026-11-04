---
method_id: degraded-self-introspection-notes-map-gaps-to-subsystems-6d6f4883f4ef
name: degraded-self-introspection-notes-map-gaps-to-subsystems
description: 用户要求评估/改进本系统某能力域（如多任务并发协调）时，运行态自省回执（协调/调度/目标状态）是第一发现面：每条 degraded/未接线注记同时给出缺口名称与负责子系统，把宽泛架构讨论直接缩成定点模块审计清单。docs 在『自家当前能力』问题上 miss 是常态信号，应转读被点名子系统的源码真值，而非换措辞重查 docs 或全库文件名枚举。与 memory→schema 卡的区别：判别面是回执内嵌的缺口+归属指针，权威落点是子系统源码而非工具注册表。
aliases: 谈架构建议前先盘自家真实能力面, 降级注记就是现成的缺口地图, docs 搜不到自家机制就直接读代码, 系统自评从状态回执入手, 未接线提示直接指到该读的模块, 给改进意见先做能力审计再谈方案
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:73172f2a-c1f6-4868-9611-d4af1d463c48:0:042b6aa9632c4aa29475
evidence_refs: learning:learn:cf610d8a91fe
created_at: 2026-11-03T17:00:00.136688+08:00
updated_at: 2026-11-03T17:00:00.136688+08:00
---
## Trigger
用户请求对本系统某能力域给评估或架构改进建议（非设计史问题），且系统提供运行态自省/状态类工具可先行查询

## Discriminator
自省回执中降级/未接线行是否带注记点名负责子系统（缺口与归属同时出现，如『running.children: 未采集子代理租约』）；同时 docs miss 回执列出的近期文档若全属他域，即证明 docs 层无本域覆盖，换措辞重查无益

## Short path
- 先调运行态自省面（协调/调度/goal 状态）——未知量：本域当前真实能力与已知缺口
- 把每条降级行机械转成『缺口→负责子系统』对，得到定点审计清单
- 至多一次 docs 检索验证设计文档是否覆盖本域（miss 回执的文档清单本身即证据），不再重试
- 按清单做定点源码定位与代码结构阅读——未知量：各子系统机制成熟度与真实缺口（假并行、缺 CAS、缺派发器等）
- 输出已核实能力底座表+逐条有代码证据的缺口+按杠杆排序建议，停止

## Stop conditions
- 每个降级缺口都已在对应子系统源码/定义面找到证据，能力底座表可逐行标注来源
- docs 与 records 均确认无本域覆盖且点名子系统源码已读，即不再扩大枚举

## Verification
- 最终建议中每个『缺口』能指回具体模块/行级证据，每个『已有能力』能指回已读源码结构
- 确认没有把 docs miss 当作『换个措辞再查』的信号，也没有在已有子系统清单后做宽文件名枚举

## Counterexamples
- 问的是设计意图/历史演变/路线图（为何这样设计）——docs/设计文档才是权威，代码读不出动机
- 自省回执全绿、无任何降级行——回执不提供缺口指针，适度宽枚举是合法首步
- 闭盒平台无源码可读——应转 schema/工具注册表等机器权威面（彼处适用 memory-as-hypothesis 卡）
