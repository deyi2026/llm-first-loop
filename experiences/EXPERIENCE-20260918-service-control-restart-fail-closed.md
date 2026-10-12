---
title: 活跃会话内触发 service_control restart 会自锁于空闲门并 fail-closed
scenario: 镜像工作区 web 服务重启：在活跃 agent 会话内通过 service_control(restart) 触发
root_cause: ""
solution: 活跃 run 期间不要在会话内等待重启完成。方案A（首选）：回合结束、锁释放后，由用户在终端直接执行 RESTART_WAIT_IDLE=1 FORCE=1 bash scripts/restart_mirror.sh web（与 worker 调用同一预检链）。方案B：会话内 dispatch service_control restart 后立即结束回合（不轮询等待），下一 5s 轮询即见空闲并继续。禁止 RESTART_FORCE_ACTIVE_RUNS=1 硬切（仅紧急人工裁决）。注意 run 锁在 data/sessions/<workspace-dir>/<session>.run.lock，不在 sessions 根下。
evidence: "data/restart-receipt.json 2026-09-18T21:41:52+08:00 active_run_precheck_failed；service_control action svc-943630a32e8e459ab8b18a06ccb89a84 status=failed requester_session_id=8264c548-85f1-4132-ad60-06764dbeb232；active_run_locks 输出 data/sessions/--Users-yyj-Project-llm-first-loop-mirror--/8264c548-….run.lock；scripts/restart_mirror.sh _restart_precheck/_stop_web 源码"
tags: [restart, service_control, self-deadlock, run-lock, fail-closed, mirror]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T21:43:07.147027+08:00"
updated_at: "2026-09-18T21:43:07.147027+08:00"
---

2026-09-18 镜像 web 重启（gen 30 publish 后）从当前活跃会话触发 service_control restart：worker 起 restart_mirror.sh web，_restart_precheck 以 active_run_locks(data/sessions/<workspace>/<session>.run.lock) 为忙判定，唯一活跃 run 恰是发起重启的会话本身 → 5s 轮询死等 300s 超时 → _web_run_busy fail-closed（FORCE=1 也不硬切，需人工 RESTART_FORCE_ACTIVE_RUNS=1 且有 llm.partial_checkpoint）→ 回执 active_run_precheck_failed，动作 failed，服务原封未动。排查要点：(1) run 锁在 data/sessions/<workspace-dir>/ 下，不在 sessions 根目录，ls data/sessions/*.run.lock 会漏查；(2) restart_mirror.sh 卡 5s sleep 轮询即 _restart_precheck 等空闲；(3) _stop_web 有界（10s 优雅+SIGKILL 兜底 3s），不会卡分钟级。正确路径：回合结束后由终端直接跑 RESTART_WAIT_IDLE=1 FORCE=1 bash scripts/restart_mirror.sh web（同官方预检链），或 dispatch 后立即结束回合让锁释放。