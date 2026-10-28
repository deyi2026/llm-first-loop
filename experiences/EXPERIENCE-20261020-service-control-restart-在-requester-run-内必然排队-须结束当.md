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

> **当前工具对齐（2026-10-28 复核，代码核对）**：结论仍成立——restart 的 busy 与 requester 无关，是上一轮 run 仍持有 run.lock；拿不到 physical 阶段就不要在本 run 内轮询等待。
>
> 需要更正两处表述：① 900s 不是"建议等待时长"，而是代码预算常量 `_REQUESTER_EXIT_TIMEOUT_S = 900.0`（src/llm_loop/runtime/service_control.py:133，`_requester_run_active` 在 :2819，超时 detail 仍输出 "~900+idle s+ before physical restart"）；② 验证依据是动作终态（status 的 succeeded/failed + deployment_generation + 新 pid/started_at）加外部观察，而不是凑满某个时长——结束当前 run 后下一次 status 查询就足以判定，无需空转到 900s。
>
> 派发时用 service_control.restart 带 `expected_generation=最新 status 观察值`，并保存 action_id 供后续核对；generation 冲突回执即当前事实，按回执 current 重试即可。