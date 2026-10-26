---
title: 多代理编码-审查-准入-部署-push 流水线的跨 run 调度与五类机械故障处置
scenario: LFL 多代理流水线（编码子代理→独立审查闸→Rule28 Host 准入→全量门→部署→push）跨 run 调度，涉及子代理被 run 停止连累取消、审查回执被 git 安全扫描拦截、复合命令被准入绑定拒绝、准入审查 child 空响应等故障模式
root_cause: ""
solution: "五条已验证处置固化：(1) 委派任务书自包含可重放（含精确断言/教训/禁令），子代理被取消即原样重派——本会话两次 run 停止连累取消均以重派零损耗恢复；(2) 子代理禁 git 写与 uv run，父级收工统一 git add+守卫复跑+.venv/bin 直调，避免 uv.lock 漂移与守卫 staged 口径盲区；(3) 审查回执入库前机械相对化绝对路径（git_security_scan 拦 /Users/*），verdict/findings 零改动；(4) 保护动作（git push/ci_gate）必须单命令直发+workdir 参数，产物一变（含 1 个 docs 提交）即重走准入；(5) 准入 child 空响应（DENIED: review_has_no_live_host_attestation）为 provider 抖动，退避 2-4 分钟重启 admission 即 PASS。"
evidence: lfl/main=c24015a99（B1 提交 46a15a79e+报告 c24015a99，ls-remote 核对）；docs/governance/receipts/20261016-e4376979-b1-settlement-wiring-code-review.json（T2 PASS）；admission da3a6914(full_test)+07e318cc(git_push)+0e389791(git_push)；ci_gate exit=0；learning generation=268 进程 31043 核验；重派 T1/subagent_723ee9357d2a 成功 vs 取消的 subagent_c78648fa1de3（rounds=3 零编辑）
tags: [multi-agent-pipeline, rule28-gates, subagent-redispatch, git-security-scan, admission-retry]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-16T01:10:58.329078+08:00"
updated_at: "2026-10-16T01:10:58.329078+08:00"
---

1) 任务书自包含可重放：spawn 前把设计依据、精确断言、教训清单、禁令写进任务文本；子代理死掉/被取消即原样重派，不依赖其内存活状态。2) 父级只做机械核验+git 写操作：子代理禁 git 写（守卫按 staged 口径读源时，父级收工统一 git add + 复跑守卫）；子代理禁 uv run（防 uv.lock 改写），一律 .venv/bin/ 直调。3) 审查回执入库前查绝对路径：git_security_scan 拦截任何 /Users/ 形态，机械相对化（verdict/findings 零改动）即可过；全量门 pytest 会自生成 reports/phase* 副作用，收口统一 checkout 还原后再做 publish 的干净树绑定。4) 复合命令含保护动作（git push / ci_gate）会被 Host 拆分阻断：workdir 用参数传，不写 cd &&；产物一变（哪怕 1 个 docs 提交）就要重走对应 kind 的准入。5) 准入审查 child 死于 LLMEmptyResponseError 时 qualification=DENIED(review_has_no_live_host_attestation)，属 provider 抖动：退避 2-4 分钟重试 start 即恢复。