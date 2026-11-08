---
method_id: shared-lane-ledger-occupancy-gate-before-goal-lane-registration-58335a756f2c
name: shared-lane-ledger-occupancy-gate-before-goal-lane-registration
description: 多会话共享仓库中，任务要求本会话 create_goal+lane_open（或登记任何跨会话全局唯一资源），且任务文本已给出确切 branch/worktree/goal 标识并带并发停止条件（如'不允许第二条 lane'）时，任何登记写之前必须先用一条只读探针查共享 lane 账本中这些确切标识的占用：命中 status=active 且 owner_session_id≠本会话（以 last_activity 新近/对方 worktree 脏改动佐证仍在写）即占用成立，此时零写入停止，向用户呈报占用事实并给出让位/授权移交/另开隔离面三选项。关键反直觉点：本会话 get_goal 为空、合并队列 0 项槽空闲都不是可登记证据——lane 占用只活在共享账本里。
aliases: 开 lane 前先查账本有没有人占着, 别的会话在同一个 worktree 干活, 队列空闲不代表能开 lane, 登记 goal 前查分支占用冲突, 多会话抢同一个分支怎么办, 续跑发现重复开工要不要让位
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7c754418-3018-4bd2-a122-d3af509b0bd7:10:398f1f009c7de74a297e
evidence_refs: learning:learn:664d0acaff91
created_at: 2026-11-07T16:24:40.468245+08:00
updated_at: 2026-11-07T16:24:40.468245+08:00
---
## Trigger
多会话/多代理共享仓库中，任务要求本会话 create_goal + lane_open（或登记任何跨会话全局唯一资源），任务文本已给出确切 branch/worktree/goal 标识，并带有并发类停止条件（如'并发规则不允许第二条 lane'）

## Discriminator
占用判定的唯一权威是共享 lane 账本（如 data/audit/lanes.jsonl）中按任务文本里逐字的 branch/worktree 串命中的记录：status=active 且 owner_session_id≠本会话，last_activity 新近或其 worktree 有与声明 paths 一致的未提交改动。反证清单：本会话 get_goal='无活动目标'、lane_queue_status 队列 0 项/槽空闲——两者只反映本会话与合并队列，不反映 lane 占用，不能作为放行证据。

## Short path
- 恢复上下文时先分类未知量：get_goal/list_evidence 只回答'本会话有没有目标'，不回答'要登记的标识是否被其他会话占用'——后者才是登记前的门禁未知量
- 从任务文本提取要登记的确切 branch/worktree/goal 标识；必要时读 lane_open schema 确认'在途唯一'硬约束，确立账本为权威源
- 一条只读 grep/tail 共享 lane 账本按确切串命中，读 status/owner_session_id/last_activity；需要时用 coordination_status 或对方 worktree 脏改动二次确认仍在写
- 占用成立且任务带并发停止条件 → 零写入停止（不 create_goal、不 lane_open、不改任何共享文件），回报占用事实并列出让位/授权移交/另开隔离面三选项等用户裁决
- 账本无命中或命中已终态（closed/merged）→ 占用不成立，正常登记继续
- 解析账本 JSON 用普通文本工具或'先落盘再执行'姿势，不做管道直连解释器

## Stop conditions
- 账本中同 branch/worktree 存在其他会话在途 lane 且任务给定并发停止条件 → 立即停止一切登记写动作
- 已向用户呈现占用证据与处置选项；裁决前保持只读
- 无占用命中且账本为最新读取（非缓存/过时快照）→ 占用检查结束，进入正常登记流程

## Verification
- 命中记录 owner_session_id 与 coordination_status 的 self 字段比对确为异会话
- 活跃性有二重证据：last_activity 时间戳新近 + 对方 worktree 存在其 paths 声明范围内的未提交改动
- 门禁类回执若来自自动探测工具，用显式 repo_root/main_head 参数复核一次（自动探测曾返回空 main）
- 停止后自查零写：本会话无 create_goal、无 lane_open、无共享文件写入

## Counterexamples
- 命中记录 status=closed/merged/aborted → 占用不成立，直接登记，不必停下询问
- 任务指定全新 branch/worktree 且账本无命中 → 一次 grep 成本即放行，不套用'停下上报'
- 用户已预授权免问自行裁定 → 不停下询问，按授权自行让位或独占推进并写入回报
- lane 账本无文档化读取路径/属私有实现 → 不逆向猜文件，改让 lane_open 的占用冲突失败回执充当权威信号（其承诺如实返回已占用 lane_id）
- 单会话独占仓库、资源无跨会话唯一性约束 → 无需此占用门禁
