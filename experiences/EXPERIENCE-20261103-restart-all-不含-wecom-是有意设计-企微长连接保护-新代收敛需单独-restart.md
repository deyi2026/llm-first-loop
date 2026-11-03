---
title: restart all 不含 wecom 是有意设计：企微长连接保护，新代收敛需单独 restart wecom
scenario: mirror 工作区 publish 新代后的服务收敛：restart all 的物理执行面只含 web/feishu/learning，wecom 需每代单独补重启
root_cause: ""
solution: "1) status 核对：restart all succeeded 后查 service_control(action=status)，看 wecom 的 matches_desired_generation/restart_required 与 audit_signals.generation_lag（无 verified_generation 抵扣=未收敛）。2) 补重启：service_control(action=restart, target=wecom, restart_target=wecom, expected_generation=<desired>, reason=...)，核对受理回执 generation。3) 终态：等发起会话结束后 worker 自动执行，下轮 status 复核 wecom git_head==desired.git_head 且 lagging 不含 wecom。"
evidence: "1) service_control status @2026-11-03T08:01:47 (evidence://v1/1d18f641cd0075aa55897e99afe70c76c044bc6c1bcbd6504a76fc5e03909fbb)：gen376 restart all (svc-e19cc11e70c54a5d929f9cc696f4a4d8) succeeded，verify_evidence 仅 web/feishu/learning；wecom live head=30e9d2b6c（gen375），restart_required=true。2) 源码：scripts/restart_mirror.sh:1331-1332 注释（本轮 read_file 核实）。3) 本轮补重启受理回执：action_id=svc-0538dfbf716f4080ad5684fe985b18c6, generation=376。"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-03T08:06:35.687626+08:00"
updated_at: "2026-11-03T08:06:35.687626+08:00"
---

现象：publish 新代后 service_control(action=restart, target=all) 终态 succeeded，但 status 中 wecom matches_desired_generation=false、restart_required=true，wecom 静默停在旧代。gen375（svc-f006abc886134265a0a5df4fce12d94f）与 gen376（svc-e19cc11e70c54a5d929f9cc696f4a4d8）连续两代发生。

根因（有意设计，非 bug）：scripts/restart_mirror.sh:1331-1332 注释：all 分支不含 wecom——企微单机器人同一时刻只允许一个长连接，批量重启 web/feishu 不应连带踢掉在服企微长连接。stage_facts.wecom.status=succeeded 只是记账面（barrier 释放），不是物理重启成功。

正确姿势：每次 restart all 完成后，用 status 核对四服务 matches_desired_generation；若 wecom 落后，单独执行 service_control(action=restart, target=wecom, restart_target=wecom, expected_generation=<desired 代次>, reason=...)。两阶段等待下 restart 会等发起会话结束才物理执行（waiting_for_requester_exit），受理回执核对 generation 后收尾，下轮 status 复核终态（判据：wecom git_head==desired 且 convergence.lagging 不含 wecom）。

已提交演进建议：EVO-20261103-4fbe523a（all succeeded 回执增加 uncovered_services 显式标注 + stage_facts 区分 skipped_by_design）。