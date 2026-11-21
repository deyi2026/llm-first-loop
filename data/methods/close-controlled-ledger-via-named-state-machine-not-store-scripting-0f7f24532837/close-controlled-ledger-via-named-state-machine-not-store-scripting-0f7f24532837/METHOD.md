---
method_id: close-controlled-ledger-via-named-state-machine-not-store-scripting-0f7f24532837
name: close-controlled-ledger-via-named-state-machine-not-store-scripting
description: 任务文本点名受控状态机工具为唯一合法写路径并明令不绕过时，收口只剩接口调用序列：只读核验前提→查队列闸→带CAS迁移→终态close→登记checkpoint。判别器在动手前已齐备：CAS参数（id/version/head）任务已逐字给出，前提核验回执已确认包含关系；此时解释器管道直改存储、目录级定位账本文件，都是违反合同且会被安全守卫硬阻断的歧途。迁移被拒时，回执列出的合法迁移集就是路由表，经合法中间态到达终态，全程零override。
aliases: lane收口别用脚本改账本文件, 管道命令被安全守卫硬阻断后怎么正规收口, 状态迁移被拒绝后按允许列表路由, 点名了工具就别绕到存储层操作, 队列闸空闲后一步步状态机收口
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b81d97a3-af1f-463a-9f1f-ac9cf885c32b:176:c23f4af9f1092cc3d8da
evidence_refs: learning:learn:02a42ff9f602
created_at: 2026-11-17T01:44:46.947483+08:00
updated_at: 2026-11-17T01:44:46.947483+08:00
---
## Trigger
要求把受控账本/状态机记录（如 lane）收敛到终态（merged/closed），任务文本已点名合法写路径（受控CAS状态机工具）并写明"不绕过"，且只读前提核验（祖先包含关系等）已通过。

## Discriminator
两个动手前已知事实：①任务文本显式指定状态机工具为唯一合法写路径并禁止绕过；②收口所需CAS参数（lane_id、version、head）已由任务文本给出。二者齐备时，脚本级存储改写与存储文件定位grep均为不必要动作——后续接口调用全程只凭 lane_id 即成功，证明文件定位本不需要。

## Short path
- 只读核验收口前提：git fetch 后用 merge-base --is-ancestor 确认 lane head 已含于权威 main
- 查询受控队列/账本（如 lane_queue_status）确认闸空闲、无冲突条目
- 用任务文本已给出的参数调用状态机迁移工具并携带 CAS（version、head）；若指向终态的迁移被拒，读错误回执中的合法迁移集，先迁入合法中间态再继续
- 调用终态收口工具，reason 写全可核验事实锚（merge SHA、祖先核验方式、CI run 回执）
- 登记 Goal checkpoint 并保持 Goal 非完成态，停止；全程零代码修改/push/部署

## Stop conditions
- 前提核验失败（head 不在权威 main 中）→ 保持现状并报告，不收口
- 状态机或队列闸拒绝且回执中无合法迁移路由 → 按任务书保持现状并报告，不绕过、不提权脚本改写
- 终态回执与 checkpoint 回执均到手 → 停止，不追加确认性动作

## Verification
- 每步迁移回执显示 CAS 通过：version 递增、head 匹配
- 终态回执 reason 含可独立复核的事实锚（merge SHA、祖先核验方式、CI 证据）
- 全程无 override/force，也无安全硬阻断事件

## Counterexamples
- 状态机工具不可用/损坏，且用户经提权审批明确授权直接修复存储：此时走 escalation 拿一次性令牌后再动，仍非静默绕过
- 任务本身就是对账本文件的只读审计或考古：文件定位与内容读取是任务目标而非歧途
- 存储没有受控状态机接口（裸文件、任务明确授权编辑）："点名工具"这一判别器不存在，本方法不适用
- 解释器管道用于与受控存储无关的本地计算：那是通用姿势问题，不涉及本方法的存储写路径判别
