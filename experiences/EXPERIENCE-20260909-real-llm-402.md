---
title: real_llm 冒烟失败的基线对照分流法（402 余额型失败≠分支回归）
scenario: 带 key 跑 real_llm 冒烟时部分用例失败，需判断是分支回归还是环境问题（账户余额/provider 行为），决定是否阻塞 PR
root_cause: ""
solution: 三步分流：1) 若全 skip 先用 -rs 看门控（DEEPSEEK_API_KEY/LLM_API_KEY），仅导出需要的 key、unset 会错误路由的 LLM_MODEL/LLM_BASE_URL；2) 读失败详情定性：HTTP 402 Insufficient Balance=账户余额（确定性降级按设计生效），400/模型不调工具=provider 侧行为；3) 在基线 commit 的 worktree 用相同命令复跑同批用例，逐一相同=非分支回归，PR 照常开并在正文如实记录差异。
evidence: "job-7a87d51c341b4908b3b5（分支 3 FAILED）/job-83c28124a8784b41b66f（基线同 3 FAILED）；PR #4 正文记录"
tags: [real-llm-smoke, ci, triage, http-402, insufficient-balance, base-comparison, pr-gating]
source:
  job_branch: job-6318c18376874b8985f5
  job_detail: job-ee0b9937e87b472089d3
  job_base: job-83c28124a8784b41b66f
  pr: "https://github.com/deyi2026/llm-first-loop/pull/4"
status: active
created_at: "2026-09-09T22:17:49.017158+08:00"
updated_at: "2026-09-09T22:17:49.017158+08:00"
---

时间线：22:09 授权执行"real_llm 冒烟→PR"。首跑 16 全 skip（缺 DEEPSEEK_API_KEY/LLM_API_KEY）；从 .env 仅导出 DEEPSEEK_API_KEY 且 unset LLM_MODEL/LLM_BASE_URL/LLM_API_KEY（避免路由到 glm 端点+错配 key）后 13 过/3 失败；3 失败含 HTTP 402 Payment Required (Insufficient Balance)。分流法：同 3 用例在 lfl/main 基线 worktree 同参复跑→逐一相同失败=环境/账户问题，非分支回归，不阻塞 PR（在 PR 正文如实记录）。要点：①real_llm 冒烟首查 skip 原因（-rs）；②402/余额类失败先做基线对照再定性；③deepseek 账户 402 会出现为确定性降级 note 而非测试崩溃，读 SummaryResult.source/note 定位。