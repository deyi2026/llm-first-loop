---
title: 审稿子代理连环投影熔断时：停止换模型重试，发表闸门改走 review_admission Host reviewer 并如实记录降级
scenario: 文稿发表前需要独立审查子代理（RULE-AI-28 / 任务硬门），当日多个 provider 的子代理在答复投影阶段连环熔断 LLMProjectionError（active_run_ingress_unexpected_marker）：核验工具调用均成功、最终答复与报告落盘均无法产出。历史上 2026-10-18 也发生过 4 模型连环熔断仅 1 通道幸存。
root_cause: ""
solution: 熔断 ≥2 次即不再换模型盲试；发表类审查改走 review_admission（Host 独立 reviewer 通道，冻结产物 SHA 签发一次性资格）承担 RULE-AI-28 闸门；事实核对由父会话伴生 ledger 全量对照替代；STATUS/回执如实记录「未获独立子代理事实审稿 PASS」，不冒充。若 review_admission 也失败则停下上报，不降级发布。当前性验证：重遇连环熔断时先跑一次 review_admission action=status 确认 Host reviewer 通道当日可用，再决定是否走降级路径。
evidence: docs/promotion/receipts/20261019-daily21-zhihu.json（process_defects_and_fixes.D21-D、host_admission）；4 个熔断子代理 child_id：c65336994a25 / 734f28226c4b / 332306577752 / d28422597bf4
tags: [子代理, LLMProjectionError, 审稿熔断, review_admission, RULE-AI-28, 发表闸门, 降级路径]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-19T20:57:50.293516+08:00"
updated_at: "2026-10-19T20:57:50.293516+08:00"
supersedes: [EXPERIENCE-20261014-47773fff5-独立补审-pass-generation-隔离修复经独立子代理三维核验-347]
---

2026-10-19 晚班知乎发布前独立审稿：spawn_subagent 四连熔断——deepseek/deepseek-v4-pro（21 工具）、再派同模型（14 工具）、workbuddy/deepseek-v4-pro（14 工具，已按「每完成一项立即追加落盘」策略仍只写出报告首行）、glm/glm-5.3（22 工具），全部在答复投影阶段 LLMProjectionError: active_run_ingress_unexpected_marker，核验工具调用都成功、最终输出通道失效。与 2026-10-18 daily18 记录的同类故障（当日 4 模型熔断、仅 1 个通道幸存）叠加，判定为当日环境级系统性故障。处置：停止第 5 次重试；发表闸门改走 review_admission（action=start kind=article_publish，Host 独立只读 reviewer，冻结 manuscript+artifacts SHA，签发一次性资格——本次 PASS candidate_sha256=966080d0…）；事实核对由父会话 R5 伴生 ledger 全量对照+放大点复核替代；STATUS 与回执如实记录「未获独立子代理事实审稿 PASS」。结果：发布成功且公网验收全过，无因审稿降级造成的内容事故（事后 Host reviewer PASS 佐证）。

当前性验证：grep -n 'subagent_67ba67665262\|qualification' docs/promotion/receipts/20261019-daily21-zhihu.json 应命中 host_admission.PASS 记录；grep -rn 'LLMProjectionError' 本卡 scenario 所指 4 个子代理运行记录（若归档）可复核熔断事实。