---
method_id: restart-verify-truncated-receipt-continue-before-disk-echoes-43f632cf9358
name: restart-verify-truncated-receipt-continue-before-disk-echoes
description: 核验受管服务重启/发布是否生效时，若权威 status 回执已成功返回但可见首段被历史噪声（旧代次 audit/lag 长列表）占满且 range 标 complete:false，判定所需的 per-target live/desired/stable 字段其实在未读段：按 next_start 续读或按 target 定点重查同一回执即可裁决，不要因此切换到文件系统枚举同名 runtime manifest——旧实例目录里的陈旧快照会给出误导性“未生效”反证；磁盘证据仅在回执真正读尽仍缺字段、或任务本就是审计落盘一致性时使用，且必须先对表 pid/started_at 与回执 live 段一致。
aliases: 被 lag 列表刷屏的回执先续读, 核验重启生效别翻旧 manifest, 同名 manifest 哪份是当前状态, 先续读回执再考虑磁盘旁证, 过期实例快照不是未生效证据
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:1896:518507e6f2580db6402c
evidence_refs: learning:learn:2208a3825557
created_at: 2026-10-28T09:15:58.793880+08:00
updated_at: 2026-10-28T09:15:58.793880+08:00
---
## Trigger
用户或调度回报受管服务“已重启/已发布”，需要核验生效；第一跳权威控制面回执返回 success，但可见段被与本次判定无关的历史信号列表占满并被 range 截断（complete:false 且给出 next_start），判定字段尚未出现

## Discriminator
已读段内容全是与判定无关的历史信号（如几十条旧代次 lag、空的 admission_barriers），且 range 元数据明示未读尽——缺的是同一回执的下一段，不是新证据类；若转磁盘，工作区常存多套同名 manifest，pid/started_at 早于被验重启时间的那份是陈旧回声，其落后 git_head 不构成“未生效”证据

## Short path
- 把唯一未知量定为：live.git_head/generation 与 restart action 终态是否等于 desired
- 对同一回执按 next_start 续读，或按 target 定点重查 status，直到 live/desired/stable 段出现
- 以 live.pid 存活 + live.git_head==desired.git_head + action succeeded + lag 归零完成裁决
- 服务健康用真实入口探针（页面路由 GET → 200）一次确认
- 磁盘证据仅用于回执确无的独立待核项（如 release 物化），先核对 pid/started_at 与回执一致；未重启的 target 显式声明不枚举

## Stop conditions
- 回执 live 段与 desired 一致且入口探针 200 → 停止一切发现性枚举，进入汇报
- 回执 complete:true 且首段已含全部判定字段 → 直接裁决，零续读零磁盘
- 续读到真 EOF 仍无判定字段 → 才允许切换证据类

## Verification
- 最终答案中每个判定字段可追溯到同一控制面回执的具体续读段或定点查询
- 任何磁盘补充证据的 pid 与 started_at 必须和回执 live 段一致，否则标记为陈旧快照不采信
- 未重启 target 的状态以回执为准显式声明，不用旁证推断

## Counterexamples
- 回执一次返回即 complete 且已含 live/desired/stable → 直接裁决，不续读不查磁盘
- 回执不提供分段续读机制且确实缺失判定字段 → 文件系统/进程旁证是正当下一跳
- 任务目标本身就是磁盘与回执一致性审计（如前端产物 sha 逐字节比对、release 目录物化检查）→ 目录枚举是任务本体而非绕路
- 沙箱禁止进程命令时，pid 存活性由回执与入口探针承担，不应反复尝试 ps 类命令
