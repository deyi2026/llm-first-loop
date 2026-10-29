---
title: 承载当前会话的 web 重启会等待 requester 退出：重启后的部署核验必须留给下一会话
scenario: 在承载当前会话的 web 服务上执行 service_control restart（部署新代），并期望在同一会话内核验 git_head/matches_desired_generation/pid_alive
root_cause: ""
solution: "restart 受理后动作状态是 waiting_for_requester_exit（两阶段等待：先等发起会话退出，再等目标空闲），因此「重启后」的三条部署核验在本会话内物理上无法完成。正确做法：publish 后立刻记录 desired generation + deployment_id + git_head + webui_artifact_sha256 作为「已发布」证据；restart 只声明「已受理、待会话退出执行」；把 git_head/matches_desired_generation/pid_alive 三条核验与活体验收明确标为下一会话待办，并给出 action_id 供下轮直接查终态。不要因为 publish 成功就把部署写成已完成。当前性验证：任一会话内执行 service_control(action=status, action_id=<重启 action_id>)，若 requester_session_id 等于当前会话则 status 应为 waiting_for_requester_exit；会话退出后再查应变为 succeeded/failed。"
evidence: "service_control(action=restart,target=web,expected_generation=333) 受理回执 + status(action_id=svc-971a603cbc5f4e6dbe5e45d7e7acedc1) 返回 status=waiting_for_requester_exit、requester_session_id=c7e4e166-3401-45cd-9402-77e522055d10、worker_pid=86717；同轮 status 显示 live git_head=dfb627bee generation=332（evidence://v1/d988bc273fe82e3d00b47fde2e40e8cf3481e2532cfc6bcd476fe149d453b349）"
tags: [service_control, deploy, restart, verification, honesty]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T16:33:42.946972+08:00"
updated_at: "2026-10-28T16:33:42.946972+08:00"
---