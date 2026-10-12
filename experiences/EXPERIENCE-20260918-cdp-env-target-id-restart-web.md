---
title: 大页 CDP 死锁后的重绑恢复路径端到端验证：.env TARGET_ID 显式重绑 + restart web → 感知/谓词全恢复
scenario: Browser SMC Phase 1 大页死锁后的模型侧恢复路径闭环验证：capture 死锁导致 perceive/execute/wait 全瘫后，靠 shell CDP HTTP + .env TARGET_ID 显式重绑 + restart web 恢复，但当时 restart 被门禁拦截（另一工作线未发布），重绑后的感知恢复验证挂起。本会话 web 已重启到 gen29，执行该收尾验证。
root_cause: ""
solution: 恢复程序五步（可直接复用）：(1) curl <CDP_URL>/json/list 确认目标存活；(2) 必要时 /json/new 开新 tab、/json/close 关死页；(3) 更新 .env LFL_BROWSER_PERCEPTION_TARGET_ID；(4) service_control restart（注意 restart 门禁要求工作区干净且与发布一致）；(5) browser_perceive snapshot 验证 complete + 一个 typed wait 验证谓词路径。两者均 satisfied 即恢复成立。
evidence: "service_control status: gen29 deploy-4529cb50d02a4b4abc0a531e1cb7aecb / git_head 696f97268 与主仓 HEAD 一致；shell: curl 45918/json/version (Chrome 153.0.8010.48) + /json/list 显示 TARGET_ID 70B5E37978B948059E0399936388162C 存活为 page target (http://127.0.0.1:8811/form.html)；browser_perceive snapshot 回执 bsnap-30-e58ac48264c50ac1 (completeness complete=true, token_estimate 3949, 证据 evidence://v1/629864448678c4f320e22d47d9c84959d0231e966eb0b38dba88c669c5385f7c)；browser_wait_scope_ready 回执 bsnap-30-0048693f9b51ef2f (result=satisfied, sample_count=1, observer_error_count=0)"
tags: [browser-smc, cdp, recovery, phase-1, loopback]
source:
  deployment_generation: 29
  cdp_url: "http://127.0.0.1:45918"
  parent_experience: "experience:EXPERIENCE-20260918-smc-browser-phase-1-cdp"
  related_evolution: EVO-20260918-c63f0c21
  target_id: 70B5E37978B948059E0399936388162C
  verified_at: "2026-09-18T21:03:00+08:00"
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T21:04:11.939849+08:00"
updated_at: "2026-09-18T21:04:11.939849+08:00"
supersedes: [EXPERIENCE-20260918-smc-browser-phase-1-cdp]
---

死锁链（大页 47MB 单帧撕断 CDP → capture 死 → semantic_execute 无活 snapshot ref 拒绝 → wait 谓词因依赖 capture bundle 全瘫 → 模型侧无导航逃离路径）的模型侧恢复出口（已端到端验证，2026-09-18 gen29）：(1) shell 走 CDP HTTP：POST /json/new 换新 tab、GET /json/list 找可用 page target、/json/close 关旧死页；(2) 把新 target id 写入 .env 的 LFL_BROWSER_PERCEPTION_TARGET_ID（端口对应 LFL_BROWSER_PERCEPTION_CDP_URL，本例 http://127.0.0.1:45918，非默认 9222——curl 9222 空响应别误判 CDP 死）；(3) service_control restart web（restart 门禁会拦 tracked 未提交修改，属正确行为，等主工作线发布后再重启）；(4) 验证感知恢复：browser_perceive snapshot 得 complete WorldSnapshot（completeness.complete=true、dom+ax 双源、grounding_ref 有效）+ browser_wait_scope_ready 一次采样 satisfied（observer_error_count=0，证明谓词路径同时恢复）。边界：这只验证「恢复到可感知可等待」，大页 capture 帧超限本身是能力边界，修复归 EVO-20260918-c63f0c21（pending_review），不在本恢复路径范围内。