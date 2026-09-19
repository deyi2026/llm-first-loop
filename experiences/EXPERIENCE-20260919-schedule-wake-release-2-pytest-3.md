---
title: schedule wake 在手动完成后触发 + 压缩折叠回执 → 已完成动作重放（release 发布 ×2、pytest ×3）
scenario: "用 schedule(wake=true) 做长任务等待/续跑提醒，同时又在当前 run 手动推进同样步骤的多步任务；或任何\"提醒式续跑\"与\"手动完成\"可能竞态的场景。"
root_cause: "一次性 schedule wake 触发点（06:44:09）落在手动完成（06:44:03 汇报）之后 + run.compact 把已执行回执折叠出工作视图；wake message 是\"任务清单\"语义而非\"哨兵+核验\"语义，续跑侧无从判断步骤已完成。"
solution: 手动完成即 schedule_cancel(sid)；wake message 必须含已完成判据与幂等护栏（先核验终态、禁止重放动作）；重复若已发生，按幂等性分级处置（幂等跳过、孤儿进程 kill、job 句柄丢失则 ps 直接核对）。
evidence: "event_stream(current_session since 06:35)：06:43:45 首次 release edit → 06:44:03 汇报完成 → 06:44:09 schedule.wake delegated_ingress → 06:44:18 第二次 release edit；architecture_status.tool_history 显示 release edit ×2、pytest 后台 job ×2（job-190361c100ab4cb8b0b6 done/exit0、job-94dd24a5e9c54286b558 running 后查无此任务）+ nohup pytest ×1、job_output 任务不存在 ×3；ps 确认残留 pytest PID 57137 已 kill；release 终态 draft=false published=06:44:32Z。"
tags: [schedule-wake, compaction, duplicate-execution, idempotency, session-continuity]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T14:47:12.707005+08:00"
updated_at: "2026-09-19T14:47:12.707005+08:00"
---

机制：schedule wake 是"到点自动续跑当前会话"的一次性入口，但它不感知续跑前会话里已手动完成的步骤；且续跑发生在 run.compact 折叠之后（本例 folded_results=32），"已执行成功"的回执不在工作视图里，续跑模型按清单语义重新推导并重放已完成动作。2026-09-19 实例（session 863879fe）：06:19 注册 +480s wake（sched-133d7aee，内容是"合并→重打tag→发布→汇报"清单）；实际工作在 06:27-06:43 手动完成，06:44:03 已汇报；wake 06:44:09 才触发，导致 gh release edit --draft=false --latest 重放 ×2（幂等无害）、本地全量 pytest ×3（2 个后台 job + 1 个 nohup；1 个 exit 0、1 个孤儿被 kill、job 注册表丢失其中 1 个句柄）、job_output 用错 id ×3。无数据损坏、无重复投影（trace_removed=0）。防再发：(a) 手动完成清单项后立即 schedule_cancel 对应 sid；(b) wake message 里写明幂等哨兵（如"若 release v0.6.14 已 published 则直接核验终态并简报，禁止重放发布/测试动作"）；(c) 长等待优先用"状态查询型"短轮询而非"任务清单型" wake。