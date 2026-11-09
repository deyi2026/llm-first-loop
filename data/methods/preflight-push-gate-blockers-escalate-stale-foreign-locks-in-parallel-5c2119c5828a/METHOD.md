---
method_id: preflight-push-gate-blockers-escalate-stale-foreign-locks-in-parallel-5c2119c5828a
name: preflight-push-gate-blockers-escalate-stale-foreign-locks-in-parallel
description: 受并发写闸保护的共享 main 推送，其阻塞谓词（他人 verifying/merging 收口 lane）在开工前就能从共享账本+闸门源码廉价查出。当协调面已显示某外来会话停更、其 lane 处于收口态且未进合并队列（死会话残留锁）时，不要先投入 修lane→测试→独立审查→合入 的长管线、到 push 才撞闸：计划期就查 blocker 集，把『是否授权代收口 / 用户自处理 / 等 TTL 回收』这一所有权决定与修复工作并行抛给用户（help_request 留痕）；即便对方 lane 凭证看起来齐全也不代他人收口。撞闸后才发现同类死锁时同理：核实活性→留痕→带代价选项升级，不自行接管。
aliases: 推送被别的会话挡了先做什么, 卡住main推送的僵尸lane怎么处理, 别人的收口lane没合完我推不了, 开工前先摸一下推送会不会被拦, 帮他收口卡住的lane还是等回收
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:9fd8f866-77d0-4951-8e25-686ea3761026:83:4b20d0cc918e8fb6ed29
evidence_refs: learning:learn:ff6c06b96eeb
created_at: 2026-11-09T18:01:03.120862+08:00
updated_at: 2026-11-09T18:01:03.120862+08:00
---
## Trigger
共享多会话工作区里，计划执行一条以受保护写（如 push 共享 main）为终点的长管线（修复→测试→独立审查→合并），且该写闸的阻塞条件可由共享账本/协调面在动手前查询

## Discriminator
闸门源码/文档已明示 push 只被他人 verifying/merging live lane 阻塞、并有 TTL 自动回收；协调面一次查询即见某外来 owner 会话 last_activity 早已停更、不在运行、其 lane 未进合并队列——blocker 是死会话残留锁而非真实并发，而处置他人 lane（合并/关闭）属所有权决定，需用户授权

## Short path
- 恢复状态、取齐待办清单后，先确认写闸阻塞谓词：什么状态的外来 lane 会挡 push、有无 TTL 自动回收（未知量：闸会在什么条件下拦我）
- 一次共享账本/协调面查询列出当前外来收口态 lane 及其 owner 活性；发现死会话残留锁即触发升级，不等长管线跑完才暴露
- 投递 help_request（need=block）留协调痕迹，并向用户呈现代价分明的选项：授权代收口（对方验证凭证已核实）/ 用户自处理 / 等 TTL；该决定与修复工作并行推进，不因等待停摆
- 正常执行修复→测试→独立审查→合入本地 main，不对他人 lane 或账本做任何写操作
- 临 push 复核 blocker：已按用户决定解除则推送；仍在则汇报等待，并说明 main 一动本批审查即失效需重审的成本，以及 push 顺带携带的他人已合入提交

## Stop conditions
- 外来 owner 会话仍在运行或 last_activity 新鲜 → 属真实并发：等待或按协调协议请求让行，不进入代收口选项
- 账本协议明文授权验证凭证后可回收孤儿 lane → 直接按协议执行，无需升级用户
- 用户已给出处置决定 → 停止枚举选项，按决定执行并复核结果

## Verification
- blocker 事实链各有权威来源：lane 状态出自共享账本、owner 活性出自协调面运行态、合并态出自 git 对账，不以任何一方转述为准
- help_request 已入账且对方/用户可见；本会话未对他人 lane、账本产生任何写改动
- push 范围内顺带携带的他人提交已向用户如实披露

## Counterexamples
- blocker 是本会话自己的 lane：属自身所有权，直接走自收口方法，无需升级用户
- 阻塞只能发生在写时（远端非快进、他人此刻才并发推送）：预查无收益，改为临写前刷新远端拓扑
- 修复到推送之间几乎没有可摊销的长管线（一分钟小改）：提前查与撞闸再查等价，别加仪式
- 距 TTL 自动回收仅剩几分钟：等待大概率优于打扰用户
