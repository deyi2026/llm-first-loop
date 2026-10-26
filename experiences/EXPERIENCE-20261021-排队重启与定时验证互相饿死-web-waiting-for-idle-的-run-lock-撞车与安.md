---
title: 排队重启与定时验证互相饿死：web waiting_for_idle 的 run lock 撞车与安全恢复
scenario: mirror 部署：service_control 排队重启 web（waiting_for_requester_exit→waiting_for_idle 900s 预算）期间，任何定时唤醒会话/周期任务/并行用户对话持有 run lock 都会让 idle 永不满足；而为验证重启而注册的定时任务本身就会持锁，形成自我饿死。run.lock 为按 run 的排他 flock，由 web 进程自身持有，run 结束即释放；文件永久存在（墓碑），existence≠activity。
root_cause: ""
solution: "1) 排队式 web 重启的 idle 验证唤醒必须排在其 900s 窗口闭合之后（requester 会话退出时刻+900s+缓冲），不要排在窗口内；2) 诊断 waiting_for_idle 失败：读 data/runtime/service-control-actions/<action_id>* 的 detail，用 active_run_locks(data/sessions) + lsof（-- 开头路径要加 ./ 前缀）+ ps lstart 核对每个排他锁的持有进程与会话身份（session json 的 title/status/updated_at 判断是否用户真实对话在飞）；3) 只有确认排他锁全部来自定时任务/陈旧 run、无用户对话会被中断时，才用 service_control(action=override, action_id, gate=waiting_for_idle, evidence_level, evidence) 附证据推进；4) 重启 web 会杀死进程内全部在飞 run（锁都由 web 进程持有），活跃用户对话期间禁止 override。"
evidence: "data/runtime/service-control-actions/svc-d5e8956c38334f34bdd82ec77cb6a303*（detail=\"target still busy after 900s: active run locks: 1\", failed 08:16:53）；evidence://v1/33e0cb7b989dab58d9138bd3c33450fc8c0ec3ca96b873d200a2c471c103af11（status：desired gen298 git e0ecf4a82，web live pid594 旧码 5aff03c15 restart_required）；execute_command 回执：active_run_locks 4 个排他锁 lsof 全部指向 pid 594（evidence://v1/543b38e0afff7db60a88bea57c37b14fac8876b31a49850e881169dcd265a30c）；会话元数据：e47f7009 toutiao 用户对话 updated_at 08:27:58 仍在飞、6451fa3d 周期任务第2/90次、0f1ec2ed 本会话。"
tags: [service_control, restart, run-lock, schedule-wake, waiting_for_idle, deployment]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-21T08:30:29.478170+08:00"
updated_at: "2026-10-21T08:30:29.478170+08:00"
supersedes: [EXPERIENCE-20261020-service-control-restart-在-requester-run-内必然排队-须结束当]
---

2026-10-21 gen298 部署：web 排队重启动作 svc-d5e8956c 在 waiting_for_idle 阶段 900s 超时 failed。直接原因：08:12 定时验证唤醒会话（前次部署为验证而注册的 task_once）在 08:12–08:16:53 持有唯一 run lock，把 idle 窗口饿死。证据：data/runtime/service-control-actions/svc-d5e8956c* 的 detail="target still busy after 900s: confirmed_busy: active run locks: 1"；失败时刻 08:16:53 = 前会话退出 08:01:53 + 900s，说明预算从 requester 退出后起算。修复模式：① 重发 restart(target=web, expected_generation=<desired>)；② 验证唤醒排程必须定在 idle 窗口闭合之后（requester 退出+900s），本例定 09:05；③ override 仅在 lsof+active_run_locks 确认无用户真实对话在飞时使用（排他锁全部由旧 web 进程持有，重启会连带杀掉进程内所有在飞 run）。诊断要点：web 的 busy 判定=零个排他 run.lock flock（src/llm_loop/resources/foreground.py::active_run_locks），锁文件存在≠活跃（墓碑设计）；macOS 下以 -- 开头的路径会让 lsof 当作选项，需用 ./ 前缀相对路径。