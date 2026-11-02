---
title: service_control 重启动作因 desired generation 漂移被 supersede 后，目标服务可能一直不收敛（需显式绑定当前 generation 的重启）
scenario: "svc-61ca147212ab4f0eae834d437e819b25（action=restart, target=all, deployment_generation=351, requester_session=本会话）在等待期间 desired deployment 前进到 generation 352，于 21:31:58 以 failed 终态收口，detail='superseded while waiting: desired deployment advanced while waiting: bound_generation=351 current_generation=352'。此后 stage_facts/evidence_refs 对 feishu/learning/wecom 仍指向该 failed 动作，21:47→22:04 五次轮询三者 live git_head 恒为 b008c9fae、restart_required=true、terminal_action_barrier=null，无新动作在飞；同批 web 由另一个动作 svc-01242a79b77943f78e0eeda8b3be73b0 已成功收敛到 62939c22a。"
root_cause: 部署面在等待期发生 generation 漂移，旧绑定动作被作废且未为未收敛服务自动补发新绑定；仅 web 由另一动作补齐。
solution: 读到 restart 动作终态 failed 时，先读 detail 区分『物理失败』与『generation 漂移 superseded』：后者表示该动作的绑定代已过期，需要显式绑定当前 generation 的新重启动作（须真人授权），不宜重复 publish 造成发布风暴。收敛判定统一用 process_versions 与 services.live.git_head 轮询，不用仓库 HEAD 推断。
evidence: "service_control(status, action_id=svc-61ca147212ab4f0eae834d437e819b25)：status=failed、detail='superseded while waiting: desired deployment advanced while waiting: bound_generation=351 current_generation=352'、deployment_generation=351；status(target=all).deployment：generation=352、git_head=62939c22a…、code_root=.releases/62939c22a…；stage_facts：web=succeeded(svc-01242a79…)，feishu/learning/wecom=failed(svc-61ca…)；22:04:08 快照 services.feishu：git_head=b008c9fae…、matches_desired_generation=false、reasons=['live_git_head_mismatch …']、restart_required=true；idle_state：feishu/learning/wecom=confirmed_idle、web/all=confirmed_busy(2 locks)。"
tags: [service_control, superseded, generation漂移, 重启, 收敛]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T22:05:01.321674+08:00"
updated_at: "2026-10-31T22:05:01.321674+08:00"
supersedes: [EXPERIENCE-20261028-承载当前会话的-web-重启会等待-requester-退出-重启后的部署核验必须留给下一会话, EXPERIENCE-20260924-service-control-stage-facts-per-service-succeeded, EXPERIENCE-20261025-受管重启认证写回与代次判读]
---

当前性验证：复现命令 service_control(action='status', target='feishu') —— 收敛前 services.feishu.live.git_head=b008c9fae…且 matches_desired_generation=false、reasons 含 live_git_head_mismatch；收敛后应为 62939c22a46498d4c3ebe09b424150800c33ecdf 且 restart_required=false。随后 review_admission(action='start', kind='full_test', workdir='/tmp/lfl-integrate', command='python3 -m pytest -q') 应返回 child_id 而非 git_state_too_large。若再次出现 superseded，先读该新动作 detail 确认其 bound_generation 是否等于当前 desired generation。