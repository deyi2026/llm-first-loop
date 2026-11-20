---
method_id: stale-gate-reconcile-local-ref-forward-cas-conflict-as-done-retry-gate-be1494339389
name: stale-gate-reconcile-local-ref-forward-cas-conflict-as-done-retry-gate
description: 受管冻结审查/门禁（merge_review_start 类）首次调用被自描述 stale 错误码（如 lane_base_or_head_stale）拒绝时，不要扩大排查：错误码已点名 ref 维度，任务书又已给出权威 base/head 精确 SHA，未知量只剩『本地引用是否对齐』。用一次只读 rev-parse 比对本地 ref 与权威值，用祖先关系区分落后与分叉；落后则只做带旧值校验的前向快进。当写入失败且回执显示 ref 已在目标值时，说明并发协调者已完成同步——把它当『修复已完成』信号直接重试门禁，不再重写、不再补测。分叉或 head 归他人 lane 则停手上报。重试成功后核对终态 JSON 的 base/head 与任务书逐字一致再 checkpoint。
aliases: lane 校验说引用过期先对齐本地分支, 本地 main 落后远端导致审查拒绝启动, 引用更新撞车等于别人已同步, 先快进再重启独立评审, 启动评审被拒的最小排查路径
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b81d97a3-af1f-463a-9f1f-ac9cf885c32b:546:eacf0a967cef7d0b0d50
evidence_refs: learning:learn:36e9157ff75b
created_at: 2026-11-17T09:07:48.896237+08:00
updated_at: 2026-11-17T09:07:48.896237+08:00
---
## Trigger
受管冻结 diff 审查/门禁调用被命名 stale 错误码拒绝（lane_base_or_head_stale 类），且任务书已提供权威 base/head 精确 SHA。

## Discriminator
被拒后一次只读 rev-parse 显示本地 ref（如 main）不等于任务书权威值、且权威值是其祖先（落后而非分叉）——搜索空间即收缩为『单次前向引用同步』；若 CAS 写入回执显示 is at 目标值，则进一步证明修复已被并发写者完成。

## Short path
- 被拒后只做一次只读核对：rev-parse 本地 main/lane head，与任务书给定权威 SHA 逐字比对
- 一次祖先判定（merge-base --is-ancestor 或首个回执已有的标记）区分落后 vs 分叉；分叉立即停手上报，不改 ref
- 落后 → 前向快进本地 ref（引用更新带旧值校验），不引入管道直连解释器等会被安全硬阻断的组合命令
- 写入失败且回执显示 ref 已在目标值 → 并发协调者已完成同步，视为修复完成，直接重试门禁调用
- 门禁成功启动后等待终态结构化 JSON，核对 base_sha/head_sha 与任务书一致，记录 child_id 并 checkpoint

## Stop conditions
- 本地 ref 已等于任务书权威值（含 CAS 冲突回执证明已到位）→ 不再写，直接重试门禁
- 权威值不是本地 ref 的祖先（真分叉）→ 停止，报告协调者，不重写共享 ref
- 任务书给定值与远端实测不一致 → 先钉权威远端（fresh fetch/ls-remote），不按任务书盲写
- 过期维度指向他人 lane 拥有的 head 指针 → 不动他人指针，回报 owner
- 拒绝码为通用权限/合同错误、未点名 ref 维度 → 本方法不适用

## Verification
- 重试的门禁调用成功，终态 JSON 的 base_sha/head_sha 与任务书精确 SHA 逐字一致
- 前向性证明：写入前旧值是目标值的祖先（快进零丢失），且旧值校验在写入时生效
- 未触碰禁改面（未改码/未写 verify_ref/未 push/merge），checkpoint 记录 child_id 与证据

## Counterexamples
- 本地 main 与权威远端真分叉（权威值非其后代）：快进会错误对齐历史，必须上报而非改 ref
- 本地并非落后而是领先或含未推送提交：前向覆盖会丢弃本地提交，应走 inventory/salvage 流程而非引用重写
- stale 指向他人 lane 的 head 指针：改写他人指针违反 lane 归属边界，只能回报
- 拒绝原因是权限/配额类通用错误：不存在引用对齐未知量，套用只会白做 rev-parse
