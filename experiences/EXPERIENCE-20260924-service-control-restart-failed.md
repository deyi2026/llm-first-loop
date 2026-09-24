---
title: service_control restart 受理≠终态：failed 只落私有台账、无主动反馈通道
scenario: service_control restart 为异步两阶段动作（受理回执即返回，执行发生在会话外）；终态 failed 只写私有台账 data/runtime/service-control-actions/<action_id>.json，不产生 event_stream 事件，pending_actions.failed_service_actions 被新动作接管自愈后即清空，无任何主动推送/唤醒通道。
root_cause: ""
solution: "发起 restart/publish 后不得以\"受理\"收尾：必须挂终态闭环（schedule 定时提醒查 status，或下次会话开场主动 status 核对 gen/PID/terminal 状态）；restart 前先 publish 使 desired 绑定当前树头，避免 git_head mismatch 硬门拒绝。已提 evolution 建议：程序侧终态 failed 写 event_stream 事件 + failed_service_actions 改为待确认语义（接管可自愈但痕迹保留、下次会话开场注入、verify_acknowledge 后清）。"
evidence: "1) 台账文件 data/runtime/service-control-actions/svc-6d0ecaa3d7914585ba4a270b29072dc1.json：action=restart target=web status=failed updated_at=2026-09-24T01:46:57Z（本轮 grep+json.load 回执）；2) event_stream(scope=workspace, query=svc-6d0ecaa3) 仅命中本会话 action_trace 自查痕迹、无 service 系统事件；3) architecture_status(pending_actions).failed_service_actions=[]；4) service_control(status, web) 现态 gen91/PID 85572/9cf20a53e succeeded_at 2026-09-24T02:02:12Z。"
tags: [service-control, restart, async-two-phase, silent-failure, feedback-loop, accepted-not-terminal]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-24T10:07:17.392687+08:00"
updated_at: "2026-09-24T10:07:17.392687+08:00"
supersedes: [EXPERIENCE-20260920-service-control-restart-deployment-binding-failed, EXPERIENCE-20260918-service-control-restart-fail-closed, EXPERIENCE-20260921-web-service-restart-run-lease]
---

2026-09-24 svc-6d0ecaa3（restart web）09:46:57 终态 failed（git_head mismatch: desired=1a146b17, actual=9cf20a53e，直接原因是 restart 前漏 publish）。失败仅落盘 data/runtime/service-control-actions/svc-6d0ecaa3*.json；event_stream 无 service 事件、pending_actions.failed_service_actions 被新动作接管后清空为 []、无会话开场注入/飞书/唤醒，静默 15 分钟至人工 grep 才发现。教训两层：(1) 模型层：service_control restart/publish 的受理回执≠终态，异步两阶段动作必须挂终态跟踪（稍后 status 核对或 schedule 提醒），restart 前确认 desired 已 publish 到当前树头；(2) 架构层：终态 failed 需主动反馈通道（event_stream 事件 + 下次会话开场注入 + 接管自愈但保留待确认痕迹），已另提 evolution 建议。