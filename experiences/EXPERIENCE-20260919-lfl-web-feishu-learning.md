---
title: LFL 共享服务（web/feishu/learning）重启到新版本的标准流程
scenario: LFL 需要把 web/feishu/learning 三个受管服务从旧版本重启到新发布的代码版本（本次：→ c9f33b4c，generation 51）。
root_cause: ""
solution: "1) 先 service_control status 读当前 generation 与 git_head；2) 发布：python3 -m llm_loop.runtime.service_control publish --expected-generation <当前N> --code-root ... --runtime-root ... --data-dir data（要求 worktree clean，成功后 generation=N+1）；3) 重启：调用工具层 service_control restart(target=all, expected_generation=N+1, action_id=新uuid) 登记并拉起 detached worker（CLI 无 restart 子命令）；4) 本轮不轮询——worker 会等当前 run 结束和服务空闲后在 lifecycle lease 下物理重启；5) 数分钟后用 status 验证：三服务 pid_alive、git_head=新值、restart_required=false、stable.action_id 匹配且 matches_desired_generation=true。"
evidence: "service_control status 回执：deployment.generation=51, git_head=c9f33b4c3d2cbe92c7865d1aba1a6b9c8b165ed7；web(pid 70681, started 19:28:09)/feishu(pid 70841, 19:28:19)/learning(pid 71065, 19:29:01) 全部 pid_alive=true、restart_required=false、stable.action_id=svc-d1be262039cc4111bcd0105fe94725eb、matches_desired_generation=true、succeeded_at=2026-09-19T11:29:02.492608+00:00。"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-19T19:30:29.604759+08:00"
updated_at: "2026-09-19T19:30:29.604759+08:00"
---

设计要点：desired deployment（CAS，防并发覆盖）→ action 登记与物理执行解耦（detached worker，等发起轮结束再动）→ lifecycle lease 串行化物理重启 → 稳定回执（succeeded_at/matches_desired_generation）供事后验证。