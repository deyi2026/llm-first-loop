---
method_id: reason-first-eventlog-triage-4a9aecab510c
name: reason-first-eventlog-triage
description: 排查『N 次重复失败/重排/重试』类症状时，症状计数本身证明存在带 reason 字段的结构化事件日志。先对日志做一次聚合（reason 分布、每对象循环次数、时间节奏），用主导 reason 字面量直接反查源码唯一 raise 点，再从该点向后读机制；不要先对 reason 已可排除的分支（前台锁、进程占用、worktree 状态）做环境态全量枚举。读条件块时须同时读其副作用（如失败即 invalidate 下一轮比较基线），这类副作用常解释『永远失败』的确定性循环。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:455:67dcbdba59a239daea71
evidence_refs: learning:learn:2258b6519a77
created_at: 2026-09-17T15:20:27.918926+00:00
updated_at: 2026-09-17T15:20:27.918926+00:00
---
## Trigger
系统以结构化 journal/审计流记录失败事件且每条带 reason 字段；症状以计数形式已知（如 592 次 requeue），排查目标是从『现象』定位到『raise 点与根因』

## Discriminator
计数化症状必然来自已被读过的事件日志，其 reason 字段是当时可得信息量最大的单一事实：主导 reason 字符串直接命名失败子系统（resource_authority_changed vs foreground_arrived 互斥），一次聚合即可同时排除前台锁假设并锁定资源授权链路

## Short path
- 定位并一次聚合失败事件日志：reason 分布、每 job 循环次数、首末时间与节奏（未知量：哪类失败主导、瞬态还是确定性、哪些对象被饿死）
- 用主导 reason 字面量 grep 源码，直接跳到唯一 raise 点（未知量：哪段检查在抛）
- 只读该函数的条件块：枚举全部析取触发条件，与部署事实（配置/装配）对表，并记录失败路径上的副作用如 invalidate/清空比较基线（未知量：哪个析取项恒真、为何恒真）
- 沿恒真项中的变量反向追安装/装配路径（未知量：哪一层写入了缺失或错误的状态，如 generation 未装）
- 回看日志的调度层效应补齐影响面（新对象是否被 FIFO 槽位饿死），并用跨重启/换代号对比确认确定性，三方一致即停止

## Stop conditions
- raise 点的触发条件已被代码+配置+日志三方证实恒真，且根因与下游影响（如队列饿死）均已定位，不再对已排除分支做环境枚举
- 聚合显示 reason 多样或无单一主导项 → 放弃单点反查，回到假设驱动的广度排查

## Verification
- 主导 reason 与源码 raise 点字面量严格一一对应（唯一命中）
- 根因能同时解释计数、循环节奏、跨重启/换代号不变性、以及新对象停滞这四类观测
- 被排除分支留有显式反证（reason 非 foreground 类、门控参数已在代码中确认实现）

## Counterexamples
- 失败只记录裸计数或泛化错误码（如 'error'/'timeout'），reason 字面量命中多处或不命中 → 反查不可行，需环境枚举或复现
- 单次新发失败、日志无积累 → 无分布可聚合，应先复现再定位
- 任务目标本身就是审计环境态（清理僵尸锁/陈旧 worktree）→ 全量枚举即目标，不是绕路
- 日志与实际运行代码版本不一致（漂移部署）→ 须先确认 code_root/manifest 对应的真源码再反查
