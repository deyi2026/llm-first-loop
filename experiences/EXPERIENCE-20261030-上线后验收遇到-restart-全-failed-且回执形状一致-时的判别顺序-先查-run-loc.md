---
title: 上线后验收遇到「restart 全 failed 且回执形状一致」时的判别顺序：先查 run-lock 竞态，再谈闸与产物
scenario: "write_scope P1-a 命令族闸上线后验收：feishu/learning 的 restart 动作 succeeded+confirmed_ok，但 web 连续三次 restart 全部 failed，回执形状一致（target still busy after 900s: confirmed_busy: active run locks: 1 / requester run still active after 900s / active run locks: 3），web live git_head 仍是旧代。容易误判为「闸没生效/产物缺失/publish 没成功」，实际三者都对，真实阻塞是 run lock。"
root_cause: "service_control 的 restart 两段等待均 fail-closed：Phase1 waiting_for_requester_exit 只等请求方自己的 run 退出，Phase2 waiting_for_idle 要求 web 侧无任何前台 run lock（_target_idle_state → confirmed_busy: active run locks: N）；源码明写无模型侧强推路径（no model-side force-through path）。run.lock 是按 run 的排他 flock、由 web 进程自身持有、run 结束即释放；因此并发活跃会话数直接决定重启能否推进。"
solution: 判别顺序（先机械、后叙事）：1) 读 service_control(action=status) 与 data/runtime/service-control-actions/*.json，确认每条动作终态与 detail 原文形状——回执里出现 active run locks / requester run still active 即锁竞态，与闸无关；2) 用 llm_loop.resources.foreground.active_run_locks(data/sessions) 实测当前持锁会话（run.lock 是墓碑文件，existence≠activity，必须实测）；3) 对比 live git_head 与 desired 代，并在 .releases/<live>/src/llm_loop/core/ 内清点闸文件数量（0 ⇒ 该服务侧闸零生效），另在 .releases/<desired>/ 内确认闸文件齐全；4) 闸本身的正确性另证：在已发布代快照上用 PYTHONPATH=.releases/<desired>/src 直调判定层（越界写 allowed=False / scope 内 allowed=True / 读侧越界放行但记 unverified / shell 构造拒），并跑该快照自带 tests/（注意 tests 在快照根目录，不在 src/tests 子路径）。产物齐 ≠ live 生效；live 生效 ≠ 闸有效（另看该代是否被独立审查判 REVISE）。
evidence: "本轮实测：service_control(status)×4 + data/runtime/service-control-actions/{svc-49974f93,svc-ccda2ee7,svc-3fbc3891}.json detail 原文；active_run_locks 实测 3 锁（cab051cc 并发 writer / cbda67c5 本会话 / 31f2f5ae）；.releases/8c114428f.../src/llm_loop/core/ 闸文件计数 0 vs .releases/4ae2d8f7d.../ 同名文件齐全；PROD 快照自带 tests 121 passed；PYTHONPATH=PROD 直调越界 rm/echo> 判拒、scope 内判放行；src/llm_loop/runtime/service_control.py:2760 _target_idle_state 与 2844 _requester_run_active 源码"
tags: [write_scope, 上线验收, run_lock, service_control, restart, fail_closed, 产物级验证]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T19:56:03.362092+08:00"
updated_at: "2026-10-30T19:56:03.362092+08:00"
supersedes: [EXPERIENCE-20261021-排队重启与定时验证互相饿死-web-waiting-for-idle-的-run-lock-撞车与安, EXPERIENCE-20260921-wire-raw-registry-schema-provider-tools-g1]
---