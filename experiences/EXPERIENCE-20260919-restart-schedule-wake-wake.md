---
title: restart 后 schedule wake 一次性续跑失效：跨重启终态验证不可托付 wake
scenario: restart all 前登记了 4 分钟一次性 wake 用于查终态；服务重启完成后唤醒未触发
root_cause: wake 为同会话一次性机制，服务重启更换宿主状态后唤醒丢失（根因未直证，现象由时间线与用户报告确证）
solution: 跨重启的验证不依赖 wake：重启前把验收清单写入可恢复位置（goal checkpoint/handoff），并在下一轮交互立即补验收；唤醒只用于服务不重启期间的推进
evidence: ""
tags: [schedule, wake, restart, service-control, post-restart-verification]
source: {}
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-09-19T13:46:37.832326+08:00"
updated_at: "2026-09-19T13:46:37.832326+08:00"
---

2026-09-19 restart all@gen48 时登记 4 分钟 wake（查三进程 PID/version/stable receipt），13:39–13:40 服务重启完成后唤醒未触发，验证空档由用户手动恢复会话补上。wake 语义是"当前真人 run 签发的一次性同会话续跑"，宿主/服务重启会使其丢失。涉重启的任务：唤醒只用于"服务不重启期间"的推进；重启后的终态验证要改为（a）重启前告知用户手动回来核对，或（b）重启完成后由下一次交互立即补验收，并提前把验收清单（PID、版本标识、receipt action_id、canary 端口与预期码）写进可恢复位置。注意 canary 端口要按当前部署取（本轮 web 实际监听 127.0.0.1:8903，8787 已过时）。