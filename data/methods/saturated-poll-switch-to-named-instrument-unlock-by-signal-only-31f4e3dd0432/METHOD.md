---
method_id: saturated-poll-switch-to-named-instrument-unlock-by-signal-only-31f4e3dd0432
name: saturated-poll-switch-to-named-instrument-unlock-by-signal-only
description: 异步审查/门禁/外部修复等待回合中，把每次轮询对准唯一能改变当前未决量的权威面：status取审查终态、job_output取后台job真实exit与统计、命名修复确认文件的revision递增是唯一解锁信号。连续回执字段零新增＝该面已饱和，不再原样重发；git树变更/稳定等旁路观察不构成行动条件，至多快照一次入报告；窗口耗尽信号未现就如实报未完成，不延窗、不代行修复。
aliases: 轮询没新信息还要原样重查吗, 修复已stage但fix-ready不出现, 等外部修复窗口超时怎么收尾, 查job进度用wait还是job_output, staged_tree稳定不等于解锁, 解锁只认信号文件revision
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:edd6c807-a70f-408b-860e-fdaf9558ac3c:90:9a703ef40181f6e9f2aa
evidence_refs: learning:learn:7b7555f342ee
created_at: 2026-11-09T14:26:05.898762+08:00
updated_at: 2026-11-09T14:26:05.898762+08:00
---
## Trigger
异步协议回合中需要等待三类事实——审查child的terminal/verdict、后台job的真实exit与统计、外部修复者的完成确认——且任务书或回执已点名各未决量的权威面（status为唯一完成信号、job_output查退出码与输出、命名修复确认文件revision递增为唯一解锁）。

## Discriminator
①连续两次轮询回执字段完全相同＝该面对当前未决量已饱和，原样重发不再产生新信息；②任务书原文把下一步动作唯一绑定在命名信号上（revision递增→复核冻结指纹→新child窄复审），因此旁路面状态（staged_tree已变更/已稳定、working干净）不构成行动条件，只可各快照一次作报告证据。

## Short path
- 写下当前未决量（terminal/exit/unlock）与其权威面（任务书或回执点名的那一个）
- 按协议节奏轮询权威面；回执零新增即停止原样重发，改用child终态/subagent_result面一次取齐verdict细节
- 后台job以job_output核对真实exit与统计；计时器到期只是配速信号不是完成信号
- 解锁等待期只轮询命名信号文件；git树等旁路面至多快照一次供failure报告引用
- 窗口耗尽信号未现：写failure/evidence如实报告未完成，不延窗、不代行修复、不伪造成功

## Stop conditions
- 权威面给出terminal completed＋verdict（P0/P1）＋qualification PASS且指纹一致→停止轮询进入下一步
- job真实exit与统计到手（以job_output为准，CLI退出码≠门禁退出码）
- 命名信号revision递增→才解锁冻结指纹复核与新child窄复审
- 等待窗口耗尽且信号未现→按未完成如实报告

## Verification
- verdict/exit/revision均取自对应权威面回执原文，而非计时器到期或旁路面推断
- 解锁后先复核冻结指纹与facts新revision一致，才开新child

## Counterexamples
- 协议以『等待参数＋次数上限』定义阻塞等待且原样重发即语义时：重发同一等待是正确行为，勿因零新信息而切换工具或提前放弃
- 无更细粒度替代面（没有job_output类工具）时只能继续按节奏等待
- 旁路面本身就是协议规定的解锁条件（如『等staged_tree稳定』）时，树观察即权威面
- 闸门合同规定仅status为完成信号且禁止窥探中间态时，不得用其他面替代完成判定
