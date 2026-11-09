---
method_id: owner-liveness-gate-before-relay-deliverable-rediscovery-de59bab84e90
name: owner-liveness-gate-before-relay-deliverable-rediscovery
description: 接手跨会话接力/交接快照后，在做任何交付物状态再发现（分支清点、设计文档通读、diffstat、目录枚举）之前，先闭合『属主会话是否仍存活且在途推进剩余任务』这个门控未知量：以协调回执里他人 running job 为线索，对快照点名的属主会话事件流做一次有界尾读，同时定存活与归属。写者在途→快照待办已被在途工作按构造取代，转只读姿态，仅一次核验外部副作用终态并报告快照-现在 delta；写者终态才展开交付物深挖。坑：协调视图 per-session last= 是 checkpoint 时间而非活跃时间，可落后数小时，不可当写者已停的判据。
aliases: 接力快照先判写者死活, 属主会话还活着就别接管, 协调last时间戳是checkpoint不是活跃, 事件流尾读判来源会话在途, 接手快照先查谁还在写, handoff先定属主存活性再清点交付物
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:b0f42188-bede-4dd0-a783-7cf26f7f556c:0:f806d1e3f35e90652547
evidence_refs: learning:learn:ca8413eef5a1
created_at: 2026-11-09T07:02:19.260186+08:00
updated_at: 2026-11-09T07:02:19.260186+08:00
---
## Trigger
接手跨会话接力/交接快照，快照含未结算待办并明确要求先核验来源会话执行状态与外部副作用终态；且下一步候选动作里包含对交付物/代码/文档的状态再发现（git 分支与日志枚举、设计文档通读、diffstat、目录清点）

## Discriminator
①协调回执的 jobs=N(others) 带 observed 时间戳，说明存在他人在跑的 job，但未指名属主；②各 session 的 last= 只是 checkpoint 时间，可落后实际活跃数小时（本集落后 5.5h），把它读成『写者已闲置』是误导；③goal 回执的 owner_session_id + 跨会话任务图写拒绝，已把可行动空间压为零或只读。真正的判据是属主会话自身事件流的尾读（最新分片 mtime / 末几条事件的时间戳与工具名），一条有界读即可同时闭合存活与归属。

## Short path
- 读 goal/task 回执：确认属主会话、剩余的 in_progress 任务、跨会话写边界——未知量：还剩什么、我能否合法推进任务图
- 读协调回执：他人 running job + observed 时间戳；把各 session 的 last= 仅当 checkpoint 下界，不当活跃判据——未知量：在跑的 job 是否就是属主
- 对属主会话事件流最新分片做一次有界尾读——未知量：属主是否存活且正在推进剩余任务（分钟级新鲜事件、最近工具名为执行/等待异步 child 即在途）
- 分流：属主在途→只读姿态，一条命令核验外部副作用终态（git status/log + 回执台账最新记录），报告快照→现在的 delta，明确拒绝重放/接管；属主终态→才进入交付物深挖与接管闸门管线

## Stop conditions
- 属主在途已被事件流证实、且外部副作用终态经一次真值读数核验完毕→停止发现，输出只读报告与两条路径建议（默认等属主收敛 / 用户明示接管后再动）
- 用户已明确指令『接管』或『只读审查』→按该指令的任务面展开，闸门只决定核验顺序，不用于拒绝执行

## Verification
- 报告中每条『属主在跑/已停』断言都锚定事件流的事件时间戳与事件名，而非协调视图的 last= 字段
- 全程零写侧动作（无 checkout/stash/push/任务图写入），且每个『不动手』的理由都有回执级证据（owner 写拒绝、写者在途、脏工作树归属他人）

## Counterexamples
- 快照明示来源会话已终结，或用户明说『接管某任务』：闸门平凡通过，交付物清点本身就是主任务
- 任务就是只读审查属主产物：深读设计文档与 diffstat 是任务本体，不构成搜索扩散
- 环境没有协调/事件流基础设施（单会话工作区）：退回仓侧新鲜度信号（晚于快照落盘的提交/mtime）判写者活跃
- 他人 running job 经事件流归属到无关会话：属主存活性仍是开放未知量，须单独闭合，不能由『有人在跑』推出『属主在跑』
