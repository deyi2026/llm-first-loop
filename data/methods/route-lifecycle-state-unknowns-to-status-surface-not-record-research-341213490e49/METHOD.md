---
method_id: route-lifecycle-state-unknowns-to-status-surface-not-record-research-341213490e49
name: route-lifecycle-state-unknowns-to-status-surface-not-record-research
description: 当用户问题取决于某个被系统跟踪对象（演进提案、工单、部署、任务）的当前生命周期状态，且首次检索已拿到对象身份与内容时，剩余未知量只有一个：状态。状态由状态机维护，应直接查询权威状态面（pending_actions/状态存储/architecture_status），而不是对同一记录库换关键词重搜，也不是扩大成全目录文件枚举或事件流内省。记录全文检索对状态类关键词的确定性 miss（回执明确『未找到匹配』而非超时）是换源信号，不是换词信号。拿到『内容』+『状态』两个各自权威的事实即停止，不重复确认已持有的内容。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a997d0bf-003d-4335-ade1-4f3981aa79e1:281:4307b1be7fe235fe9cba
evidence_refs: learning:learn:cd6adb6d9ad7
created_at: 2026-10-17T09:20:20.272566+08:00
updated_at: 2026-10-17T09:20:20.272566+08:00
---
## Trigger
用户问题可分解为『对象主张什么』+『对象现在处于什么状态』两半，且第一跳检索已成功返回对象内容/身份，但生命周期状态（accepted/executing/pending/executed 等）仍是未知量

## Discriminator
对象内容检索已命中（说明记录库管内容），而对状态类关键词的检索返回确定性 miss（回执明确『未找到匹配』）——这表明状态不存在于全文记录中，只能来自专用状态面；此时继续换词搜记录或枚举文件都是在错误的源类里找状态

## Short path
- 检索对象内容/身份（记录或文档），回答问题中『是什么/主张什么』的一半
- 显式命名剩余未知量为『当前生命周期状态』，直接查询该对象的权威状态面（pending_actions / 状态存储 / 架构状态维度），一步取得状态
- 仅当计划对该对象采取动作时，再查该动作的状态前置经验（如仅 executing 可登记完成）；纯问答则跳过
- 把状态映射为对用户问题的解释（如 accepted 且 executing=0 = 已批准无人实施，而非无需完善），两半各有权威来源即停止，不再重复检索已命中的内容

## Stop conditions
- 对象内容与权威当前状态均已从各自对应的来源取得，足以回答用户问题
- 已持有的事实不再重复确认：同一查询二次命中不产生新信息，属于 post-sufficiency 动作应跳过

## Verification
- 状态断言必须引用状态面的原始回执（含 scope/会话标识），不能用『记录里搜不到』反向推断状态
- 最终回答中『对象主张什么』与『对象什么状态』两半各有独立证据来源，且未出现同源重复调用

## Counterexamples
- 问题只涉及对象的内容/证据，无状态成分——内容检索命中后直接作答，无需状态查询
- 对象没有专用状态面，只存在于文件/记录中——此时记录与文件检索就是正路，换源判断不成立
- 状态面已知过时，或对象走人工路径绕过登记（如 CLI 人工标记）——需直读真实存储/账本，而非信任聚合状态面
