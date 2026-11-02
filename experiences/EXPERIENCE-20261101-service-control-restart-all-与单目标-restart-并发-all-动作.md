---
title: service_control restart all 与单目标 restart 并发：all 动作报 started_before_restart 假失败，需按证据裁决而非重跑
scenario: "同一目标代次落地时，先发起 target=wecom 的 restart（svc-5964，14:32:42→14:32:47 succeeded），随后 target=all 的 restart（svc-798d，14:32:13 创建）在物理重启阶段对 wecom 复核，因 wecom 进程 started_at=14:32:44 早于 all 动作的重启尝试，判 started_before_restart → 整个 all 动作 status=failed，detail 写 web/feishu/learning ok、wecom[started_before_restart]。"
root_cause: "all 动作的每个目标阶段独立复核\"进程是否由本次动作重启\"，并发单目标重启先赢时，all 的 wecom 阶段只能观测到\"进程不是自己拉起的\"，于是把可接受的物理结果判成失败；stage_fact 为空、finished_at 为空、无屏障残留。"
solution: "1) 不要因为 status=failed 就重跑 restart（会再触发四服务各一轮重启）。2) 用机械事实核验四目标是否已在目标代：alive(pid) + runtime_manifest.<svc>.json 的 git_head + guard_code 逐模块与当前 src 指纹相等 + 各服务自身活性信号（web /health 回 git_head、wecom_bridge 认证行、learning_admission.json 心跳）。3) 核验通过后调 service_control(action=verify_acknowledge, verdict=accept, evidence=…)：记录会保留 status=failed 并写 verify_verdict=accept + acknowledged_at + detail=\"failed acknowledged by model: …\"，不伪造成功。4) 预防：同一代次只发一个目标集合动作，不要在 all 飞行中再发单目标 restart。"
evidence: "2026-11-01 实测：svc-798d10eb08c6 status=failed detail 原样含 \"wecom[started_before_restart]\"；四 manifest git_head=f47b923d 且 guard_code 五模块与 src 指纹逐一相等；verify_acknowledge 回执 accepted=true，动作文件 status=failed + verify_verdict=accept + acknowledged_at=14:58:07。"
tags: [service_control, restart, race, verify_acknowledge, 部署核验]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-01T14:58:34.790859+08:00"
updated_at: "2026-11-01T14:58:34.790859+08:00"
supersedes: [EXPERIENCE-20261031-service-control-重启动作因-desired-generation-漂移被-super, EXPERIENCE-20261030-上线后验收遇到-restart-全-failed-且回执形状一致-时的判别顺序-先查-run-loc]
---