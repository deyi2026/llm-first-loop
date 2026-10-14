---
title: web 服务重启的 busy 级联与 requester 自锁死结：override 到脚本预检层即失效
scenario: 定时续跑会话（requester 即重启发起方）尝试把 web 服务重启到新 desired deployment；会话自身与另一活跃会话各持 run.lock，服务重启的 busy 门禁层层放行后仍在脚本预检层 fail-closed
root_cause: ""
solution: "不要用 override 强推 busy 门链：即使放行 worker 两层等待门，restart_mirror.sh 的 precheck:active_run 仍会 fail-closed（env 快照无法事后注入）。正确路径：发起 restart 后立即结束本 run（不 override、不再轮询），让 worker Phase1（requester exit）在本 run 结束后自然通过、Phase2/脚本预检在外部会话锁空隙自然通过；验证留给下一次有真实 ingress 的 run（schedule 的 wake 不可递归）。precheck 级失败是良性零副作用（receipt stage_fact=not_started），不会触发 known-good 自动回滚；desired deployment 不变，可直接重试。RESTART_FORCE_ACTIVE_RUNS=1 仅限紧急人工裁决，模型不得自行设置。"
evidence: "src/llm_loop/runtime/service_control.py 行2946-3014（_wait_for 动态消费 override）、1938-1957（pending_gates_for_action）、2120+（record_model_override 校验）、3349-3362（running 转换时 env 快照）；scripts/restart_mirror.sh 行91-92（_override_enabled 仅读 env）、450-508（_restart_precheck 超时回退确认流程）；运行回执：svc-c1ee39ea failed detail=\"restart_mirror rc=1; receipt=stage_fact=not_started\"、desired 保持 deploy-57d0fae6 gen 248；schedule 拒绝回执\"ingress 不可委派：必须是未委派的真实 human ingress\"（2026-10-13）"
tags: [service_control, web-restart, run-lock, busy-gate, override, scheduled-wake]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-13T07:35:02.076331+08:00"
updated_at: "2026-10-13T07:35:02.076331+08:00"
---

web 重启的 busy 有 4 层：worker Phase1 waiting_for_requester_exit（requester 自身 run.lock）→ worker Phase2 waiting_for_idle（全部 run.lock）→ 脚本 RESTART_WAIT_IDLE 300s 轮询 → 脚本 precheck:active_run fail-closed（rc=1 + 回执 active_run_precheck_failed）。前两层可 service_control(action=override) 附证据推进（等待循环每次轮询重读 model_override，消费同名门）；但第 4 层的 LFL_RESTART_OVERRIDE_GATES env 在 worker 转 running/spawn 脚本时一次性快照（_override_gates_for_action(latest)，latest 在 lifecycle lease 内重读），而 record_model_override 严格校验 gate ∈ pending_gates_for_action：waiting 态只开放同名等待门，precheck 门仅 accepted/running 态可记录——accepted 窗口实测仅 ~73ms（receipt→waiting 标记），模型回合不可达。结论：脚本 precheck 的 override 通道对"requester 会话自己发起并守着验证"的场景实际不可用。另外：precheck 级失败（stage_fact=not_started）不触发 known-good 自动回滚——G2 回滚仅在 failure_released is False（停机级 mid-run 失败）时触发；屏障按回执释放，desired 不变。递归唤醒被拒（wake 不可递归），所以"结束 run 释放锁→定时唤醒验证"只能用一层：若本 run 已是 wake 产物，则重启收敛后的终态核验只能留给下一个人类/主链 run（动作终态 + event_stream(query=service_action_terminal) 持久可查）。