---
method_id: interrupt-reconcile-from-receipts-yield-to-active-owner-df8e729aafcf
name: interrupt-reconcile-from-receipts-yield-to-active-owner
description: 会话在系统重启/中断后恢复时，先用追加型回执（重启回执、journal、audit/演进记录）一次性回答三个未知量：上次动作终态、被批准事项是哪条、有无自己留下的半成品；再从 journal/会话证据判断在途工作是否已有活跃所有者。若有，选择零冲突只读角色（核验已落声明的真伪、备好回滚），把部署/写动作留给所有者。核验沿'演进记录→commit→自带锁定测试→运行时工件'证据链，不靠记忆断言状态。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:433:754a8dfd1c2423ea17ea
evidence_refs: learning:learn:04aa141c5b71
created_at: 2026-09-17T15:15:20.778493+00:00
updated_at: 2026-09-17T15:15:20.778493+00:00
---
## Trigger
任务始于中断/重启后的状态询问（如'刚中断了？'），环境是多会话共享的编排系统，存在追加型回执（restart receipt、journal、audit/EVO 记录）且可能有并行会话正在推进同一工作

## Discriminator
第一步合并回执即同时暴露四项事实：restart rc=0+运行 pid 在线；中断时刻之后 drafts/submissions 为空；journal 尾部是另一 session 的排队/运行事件；演进记录时间戳落在中断窗口内。这四项在第一时间就把行动空间从'我来续做实现'缩为'核实+零冲突支持'，且全部满足 knowledge-at-time。

## Short path
- 单命令合并读：重启回执+运行 pid+中断时刻后的 drafts/submissions+journal 尾，一次解三个未知量：重启成败、我有无半成品、谁在活跃
- 按中断时间窗过滤 records/演进状态，唯一定位被批准事项；同时确认提交者 session 非本会话
- 沿该演进的 commit 落点列分支新提交，读实现 diff+其引用的设计文档，得到'已落地内容与声明'
- 跑实现自带的锁定测试，并交叉核对部署代次记录与运行时工件（如 ledger 内容来源），验证声明在真实系统是否成立、有无测试残留污染
- 输出报告+分层回滚预案即停；不执行任何部署/写操作，留给活跃所有者，避免双写者冲突

## Stop conditions
- 三个初始未知量（重启终态、被批准事项、半成品）均由权威回执而非记忆回答
- 在途声明的关键安全断言已用其自身证据链（锁定测试+运行时工件）验证
- 回滚点已指认；且检测到活跃所有者时不再发起任何部署或写动作

## Verification
- 回执 rc/pid/git head 与运行态一致；演进记录↔commit↔设计文档↔测试文件相互引用一致
- 运行时工件（部署记录仍是旧代次、工件内容来源）与'未部署/残留'判断吻合
- 最终报告中的每条状态断言都能指向一条已读回执，无凭记忆补全的部分

## Counterexamples
- journal/回执显示中断后无其他会话活跃 → 不能只做审查，应升级为续做/完成在途工作
- 回执 rc≠0 或核心 pid 已死 → 优先恢复与诊断系统，而非演进审查
- 用户只问窄问题（纯是否中断）且无敏感部署在途 → 回答即停，全量审计+回滚预案属过度延伸
- 单会话环境无并发 → 所有权检测无意义，直接沿证据链续做即可
