---
title: 发布类硬闸前先探审查者额度：reviewer_rate_limited 可能是供应商配额而非稿件问题
scenario: "LFL 推广班要发一篇头条长文：调研、写稿、配图、R1/R2 两轮独立审稿、编辑器自检（GATE PASS）、发布前一致性预演（match_ratio 0.9324 PASS）全部做完，CDP 预览抽屉已开、「确认发布」按钮坐标实见，但 RULE-AI-28 宿主发表准入连续 9 次返回 qualification=UNAVAILABLE / reviewer_failed:reviewer_rate_limited。根因是宿主 reviewer 模型所在 GLM Coding Plan 套餐周/月上限耗尽（provider code 1310「限额将在 2026-11-16 23:21:13 重置」），备援 glm-5.3-flashx 本 key 无权限（code 1311）。这是供应商侧配额窗口，与稿件质量、登录态、平台校验都无关。"
root_cause: 宿主 reviewer 模型链单点依赖单一供应商且备援模型在本 key 上无权限；配额耗尽的错误语义与「审查未通过」混在同一回执字段里，导致上游无法区分「等」与「改」。
solution: |
  1) 区分失败类别：reviewer_rate_limited + provider 1310/1311 = 配额/权限窗口，不是稿件被否；此时正确处置是 fail-closed 不发布、如实记录、留好可重跑的产物，而不是降级放行或改稿件。2) 开工第一步跑「发布闸额度探针」：对 reviewer 首选模型做一次最小调用，只读 HTTP 状态与错误体（不回显 key），不通就只出稿不进发布，省掉后续全部机检时间。3) 重试只能靠等窗口：scope=patch 对 article_publish 不适用（paths_ignored=true），material 恒定，缩 scope 降载无效。4) 额度恢复后重跑发布链路即可，无需重做调研/写作/配图/审稿——把主稿、HTML、图片、脚本、回执全部落盘并把受阻状态写成 receipts/，是能把这一班变成「半成品可交接」的关键。5) 已就此提交演进建议 EVO-20261116-65f8e29d（reviewer 链跨供应商 + 回执新增 failure_class + 开工前额度探针），未自行改宿主配置。
  
  当前性验证：复现 = 对 GLM 端点发一次最小 chat 调用并只读 HTTP 状态与 provider 错误体，预期在额度窗口内回 429 `code 1310`（限额重置时间）或 `code 1311`（FlashX 无权限）；档位确认 = `grep -n '_REVIEWER_MODEL\|_REVIEWER_FALLBACK_MODELS' src/llm_loop/tools/review_host_admission.py` 应仍显示主模型 glm/glm-5.3 与唯一备援 glm/glm-5.3-flashx；受阻状态 = `cat docs/promotion/receipts/d91-publish-blocked.json` 应含 attempts_count=9 与 published=false。
evidence: "docs/promotion/receipts/d91-publish-blocked.json：attempts_count=9，全部 reviewer_failed:reviewer_rate_limited，candidate_sha256=09832d9d…，material_chars=41836；provider 探针 glm-5.3/glm-5.3-flash → HTTP 429 code 1310「限额将在 2026-11-16 23:21:13 重置」、glm-5.3-flashx → HTTP 429 code 1311「当前订阅套餐暂未开放GLM-5.3-FlashX权限」；runtime.toml 第 9–12 行既知登记该 key 无 FlashX 权限；src/llm_loop/tools/review_host_admission.py:2561/2568 单一备援链；review_admission 回执 scope.reason=not_applicable_for_article_publish。"
tags: [RULE-AI-28, RULE-AI-30, review_admission, promotion, provider-quota, fail-closed, handoff]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-16T14:20:22.462998+08:00"
updated_at: "2026-11-16T14:20:22.462998+08:00"
---