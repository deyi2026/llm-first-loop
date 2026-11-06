---
title: service_control restart target=all 物理面不含 wecom——全量重启后必须单核 wecom 再收尾
scenario: 用 service_control action=restart、restart_target=all 做全量服务重启收敛（四服务 desired generation 更新后），期望所有服务统一到新代。
root_cause: ""
solution: restart-all 的物理重启只覆盖 web/feishu/learning 三件套，wecom 仅记 skipped_by_design 记账行、不随批次重启，会以 1 代差静默滞后。收尾核对必须显式单核 wecom 的 matches_desired；滞后则单独 service_control action=restart restart_target=wecom 补启并等 verify ok 到新代。
evidence: "2026-11-06 gen 395 部署收口实测：restart-all 后 status 显示 web/feishu/learning 三件 verify ok@395 而 wecom 停留 gen 394（matches_desired=false）；执行单独 restart target=wecom（动作 svc-cebca9ea…）回执 succeeded，09:41:44 起新 pid 13127 head=7ae768519b45 matches_desired=true、verify ok@395；随后四服务 generation_lag=[] 全清。"
tags: [service_control, restart-all, wecom, deployment-checklist, generation-lag]
source:
  session: a6989bff-e814-43eb-9f8a-a24f42790dd9
  date: 2026-11-06
  deployment: gen 395 / 7ae768519b45
  remediation_action: svc-cebca9ea
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T10:00:09.530810+08:00"
updated_at: "2026-11-06T10:00:09.530810+08:00"
---

现象：service_control action=restart + restart_target=all 的期望是四服务（web/feishu/learning/wecom）全部收敛到新 desired generation，但物理重启面只覆盖 web/feishu/learning 三件套；wecom 在批次中仅产生一条 skipped_by_design 记账行，不实际重启，导致它以 1 代差静默滞后（2026-11-06 gen 395 部署实测滞后约 20 分钟，pid 不换、matches_desired=false）。

正确姿势（部署收尾清单化）：
1. restart-all 后，收尾核对显式包含 wecom，不能只看三件套——逐服务确认 matches_desired=True 与 verify ok 到目标代；
2. 发现滞后即单独补启：service_control action=restart restart_target=wecom（可带 expected_generation 防并发漂移）；
3. 补启后复查 status，确认 matches_desired + verify ok + generation_lag 清空；
4. 若复用批量脚本，把"restart-all → 单核 wecom"固化为标准步骤，避免依赖人工记忆。

边界：本条只针对 restart 的物理面；publish/update 等动作对 wecom 的行为需另行核验，不套用本结论。