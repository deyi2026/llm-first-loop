---
title: 异步审查终态：wait 只做配速，status 才是完成信号；每次 wait 到期必须跟一次 status
scenario: 用 review_admission(kind=full_test) 启动 GLM 独立审查后，在父会话里等待审查终态（审查是 Host 签发的异步 child，没有 execute_command job_id）
root_cause: ""
solution: "等待非 job 的异步终态时，把 wait 当\"配速器\"而不是\"完成信号\"：① 只用 wait(seconds≤120) 拉开节奏，绝不指望它返回完成；② 每一次 wait 到期后立刻调 review_admission(action=status, child_id=...)，status 才是唯一终态真相源（回执带 qualification=PASS/REVISE 与 candidate_sha256）；③ 仍有预算就在两轮之间做父侧既定工作（读文档、准备下一步），不要连续多次 wait 而中间不查；④ 若等待对象其实是 execute_command 后台任务，则相反——必须把 job_id 传给 wait，它在进程终态时真正唤醒（wake_reason=job_terminal）。判据：wait 回执 wake_reason=elapsed 表示\"时间到了\"，不等于\"任务没完成\"。反面证据：本轮对 child=subagent_fa0b528c1807/89ac6264d170/3425c7c852ea 连续 wait 120s 而不 status，分别白等约 10/20/50 分钟；其中 35e46b241ca6 的 PASS 在我查之前早已签发。"
evidence: "本轮实测：review_admission status 在 23:07 返回 qualification=PASS（candidate e7b14e46…），而上一次 status 查询在 21:2x，期间只做了 6 次 wait(seconds=120) 且回执均 wake_reason=elapsed（不携带任务状态）。对照：ci_gate 后台任务用 wait(job_id=job-e1e216f13e7a4fd197b5) 时回执带 state=running/exit，终态时 wake_reason=job_terminal。"
tags: [review_admission, wait, 轮询, 白等, 子代理终态, 参数语义]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-03T23:11:52.435331+08:00"
updated_at: "2026-11-03T23:11:52.435331+08:00"
---