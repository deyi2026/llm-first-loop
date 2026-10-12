---
method_id: reconcile-secondhand-state-report-via-authoritative-record-48bf01698e45
name: reconcile-secondhand-state-report-via-authoritative-record
description: 当任务以'另一位 agent 的进展报告 + 基于该状态的后续操作'形式到达时，先不按报告框定的下一步执行：用权威状态源（部署/desired-state 记录、进程表、git refs、action 日志）逐条核对报告中的 generation/SHA/PID/ref/'已完成'结论，分类为已确认/过期/为假；核对时只检查记录中显式给出的对象（code_root、工件哈希、PID），不做全盘枚举；对每个服务通道补一次跟随重定向的直连探测以识别 desired≠live 混合态；遇到 operator-only 操作或缺凭据时停止枚举，返回明确卡点与中转请求。用记录字段把待核对对象从'所有可能'缩为少数确定路径，并避免按过期前提执行带来的返工。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:1027:2f37cb46ef202e6fde64
evidence_refs: learning:learn:6054606ba02c
created_at: 2026-09-18T19:15:52.713854+00:00
updated_at: 2026-09-18T19:15:52.713854+00:00
---
## Trigger
用户提供另一 agent 的状态/进展文本（含 generation、commit SHA、PID、ref、'已完成 X' 类结论）并要求据此执行验收或后续操作；且本地存在可 O(1) 查询的权威状态记录（部署记录、服务 action 日志、进程表、git refs）。

## Discriminator
报告中的关键标识符都能与权威记录字段直接比对；任一带时间戳字段不一致（如 desired generation、ref 值、action 状态）即判定报告为过期快照，把任务从'执行报告的下一步'改为'先收敛真值再决策'；且记录已显式给出 code_root 与工件哈希，把待核对对象缩为两三个确定路径，无需扫描全部构建产物目录。

## Short path
- 查权威部署/状态记录：确定 desired generation、code_root、runtime_root、工件哈希，建立报告声明与记录字段的逐条映射（未知量：现状真值是什么）
- 用进程表/端口、action 日志、git rev-parse 逐条核对报告声明，分类为已确认/过期/为假（未知量：哪些声明可信、报告的下一步还成立吗）
- 只对记录显式给出的对象做一致性核对：比对两个已知 dist 根的树哈希与记录的 artifact sha，不枚举其它 dist 目录（未知量：磁盘工件是否等于 desired 工件）
- 对每个服务通道做一次直连探测：跟随重定向取真实 UI/JS，确认实际服务的构建内容（未知量：live 是否等于 desired，是否存在混合态）
- 对账后处理被报告掩盖或失实的收尾（如被 worktree 占用挡住的 ref 快进，在占用位 ff-only 完成）；遇 operator-only hook 或凭据缺失即停止，输出卡点与中转请求（未知量：哪些事我做不了、该由谁做）

## Stop conditions
- 报告的每条关键声明都已被直接证据分类（已确认/过期/为假），不一致处已显式列出
- 请求的操作要么完成、要么被判定为 blocked 并指明责任方（operator-only / 需用户提供凭据）
- 文档化认证途径（env 配置、Bearer key）查证为不存在后停止凭据枚举：不逆向哈希、不翻历史/源码续猜、不绕过 hook
- 权威记录不存在或所需字段缺失时，停止本方法，转入必要的 broad discovery

## Verification
- 每条最终结论都能指名证据来源：记录字段、PID/端口表、ref 实际值、action 日志行或直连响应
- live 探测结果与记录比对；desired≠live 的差异被显式报告为混合态，而非默认一致
- 对'已完成'类声明核对其实际副作用（ref 真值、文件树哈希、进程身份），而非仅核对话术
- 跟随重定向后再判断端点内容，避免把 303 当作内容缺失

## Counterexamples
- 没有权威状态记录的临时服务/脚本：无法逐字段对账，目录与端点的宽枚举才是正确起步
- 用户只想总结或评价报告本身、不触发任何状态操作：无需完整对账流程
- 记录只表达 desired 而问题恰是 live 真值：记录字段仍可缩小对象集，但结论必须来自 live 探测，不能把记录当 live 事实
- 文档化的 Bearer/会话途径实际存在且可用：不要停在'向用户要密码'，直接走可用途径完成验收
