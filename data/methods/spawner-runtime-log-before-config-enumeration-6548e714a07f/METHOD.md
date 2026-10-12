---
method_id: spawner-runtime-log-before-config-enumeration-6548e714a07f
name: spawner-runtime-log-before-config-enumeration
description: 诊断'哪一层给派生进程施加了运行时约束(spawn 时继承的沙箱/EPERM/环境注入)'时，先沿进程树 provenance 取权威证据：初始进程列表通常已暴露嫌疑宿主的二进制绝对路径和它正在写的实时日志路径(如某个 tail -f 的目标)。约束在派生时刻生效→其机制与参数只会记录在 spawn 方的运行时日志里；枚举静态配置/数据库应作为该边断裂后的后备或最终旋钮确认。配套教训：grep 外部系统日志要用该系统自身词汇(模块名/表名)，命中集先计数再截断，避免 tail 掩盖早期关键命中。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:1449:5b33159324f86bb1d74c
evidence_refs: learning:learn:f4c05730894c
created_at: 2026-09-23T18:02:06.444506+00:00
updated_at: 2026-09-23T18:02:06.444506+00:00
---
## Trigger
多进程链路上出现只在运行时生效的约束(派生进程继承的 seatbelt/写权限拒绝/环境注入)，需要定位施加者、机制和可改的开关；且初始证据(进程列表/报错注释)中已可见嫌疑宿主的二进制路径或其实时日志路径

## Discriminator
初始 ps 输出在第一跳之前就已给出两条窄线索：(1) 嫌疑宿主可执行文件的绝对路径(可直接做 entitlements/元数据检查，区分系统 App Sandbox 与应用自施 sandbox-exec)；(2) 有进程正 tail 该宿主的实时日志文件——若约束在派生时刻生效，其参数(channel/workspace/mode 等)只会出现在这份运行时日志，而不在任何静态配置中

## Short path
- 从未知量'谁派生我的 exec 通道、带什么参数'出发：在嫌疑宿主的实时日志(路径已从 ps 可见)中 grep 派生行为关键词(spawn/channel/actor/workspace/coding 等该系统自身词汇)，先统计命中总数再查看，避免 tail 截断丢掉早期命中
- 命中行通常直接给出机制与参数(哪条通道、可写域、模式)→ 施加者与机制一次定位
- 用日志行中的标识(channel id/workspace)定点查询该系统的注册存储(如 DB 中该 channel 的 settings 字段)→ 找到可改的权限旋钮，而不是盲扫所有表
- 用宿主二进制路径做 entitlements 检查，区分系统级沙箱与应用自施沙箱→ 决定修复动作归属(UI 设置 vs 系统配置)
- 机制+参数+旋钮+修复归属齐备即停；不再展开无关存储(kv 表、历史调用表、备份 diff、bootstrap 日志)

## Stop conditions
- 已从运行时日志取得'施加者+机制+参数'，且旋钮位置被注册存储中对应条目证实
- 日志证实该宿主不产生派生记录(边断裂)→ 才转为静态配置枚举或活体复现

## Verification
- 日志行中的 channel/workspace 标识与注册存储里实际条目一致
- 日志推出的可写域假设与已有写探针结果(工作区内 OK/区外 EPERM)一致
- entitlements 检查结论与旁证(无系统容器目录等)一致
- 静态配置中确实 grep 不到该约束，佐证其为运行时行为

## Counterexamples
- 约束是静态声明的(配置文件 allowlist、manifest)，宿主几乎不打日志→静态配置枚举才是首选，本方法不适用
- 运行时日志已轮转或不含派生时刻记录→应活体复现(触发一次派生并 tail 日志)而非历史 grep
- 进程列表里既看不到宿主二进制也看不到日志路径→没有可用的 provenance 边，需要先做目录级 broad discovery
- 用户要的本来就是'配置里写了什么'的静态真值→直接读配置文件，不要绕道运行时日志
