---
title: service_control restart 在 requester run 内必然排队：须结束当前 run 才会执行（900s 窗口）
scenario: 在 Web 会话内派生 service_control(action=restart) 后，在同一会话里轮询 status 等待重启结果。
root_cause: ""
solution: |
  restart 受理（status=waiting_for_requester_exit，worker pid 存活）后不要在同一 run 内等结果：立即结束当前 run 释放 run.lock，worker 会自动转入 Phase 2 并执行重启。结果核验放到下一次会话（generation/started_at/日志 elapsed）。历史失败样本：svc-7b4f0f09 detail "target still busy after 900s" 即同模式。
  当前性验证：grep -n "_requester_run_active\|_REQUESTER_EXIT_TIMEOUT_S =" src/llm_loop/runtime/service_control.py 应仍命中 2815 行附近与 900；再 service_control(action=status) 见 waiting_for_requester_exit 且 ps -p <worker_pid> 存活。
evidence: "代码 src/llm_loop/runtime/service_control.py:2815-2820 (_requester_run_active 检查 run.lock)、:3360-3450 (Phase1/Phase2 与 900s 超时)；实证 status 回执 waiting_for_requester_exit + worker pid 76437 存活；历史 action svc-7b4f0f09 failed \"target still busy after 900s: active run locks: 1\"。"
tags: [service_control, restart, requester_exit, deployment]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-20T11:21:26.849859+08:00"
updated_at: "2026-10-20T11:21:26.849859+08:00"
supersedes: [EXPERIENCE-20261013-web-服务重启的-busy-级联与-requester-自锁死结-override-到脚本预检层即, EXPERIENCE-20261014-并行-run-持有-restart-准入屏障且绑定-stale-desired-时的接管姿势, EXPERIENCE-20261006-subject-binding-v1-cue-runtime-toml-canary-gen180]
---