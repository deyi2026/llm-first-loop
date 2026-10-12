---
title: Subject-binding v1 cue 退役下架：runtime.toml canary 遗留标志清除与 gen180 收敛
scenario: v3 subject-binding 确证实验判定 EFFICACY_NOT_QUALIFIED 且线已 retired 后，发现失败实验的 canary 开关仍留在活动运行时配置中持续生效（本会话 save_experience 工具描述实际携带实验提示即为证据）。
root_cause: ""
solution: "线退役时机械清除运行时配置开关并推进 desired deployment：runtime.toml method_subject_binding_experimental=true→false；发现 desired gen179 未随 main HEAD（a519f41b9）推进导致 restart 拒绝（git_head mismatch），用 service_control update（publish gen180 + restart all，action svc-ee19ab612973458791b17c9cadc47ee8）单语义收敛；重启经两阶段等待 requester 会话退出后自动执行。后续验证点：三服务 stable_generation=180 且新会话 save_experience 描述不含 lfl-method-applicability-subject-binding/v1 标记。当前性验证：grep -n \"method_subject_binding_experimental\" runtime.toml 应得 \"= false\"；service_control(action=status, action_id=svc-ee19ab612973458791b17c9cadc47ee8) 应得 succeeded 且 stable_generation=180。"
evidence: "① RESULT.json: /Users/yyj/Project/llm-first-loop-mirror/evals/method_binding_efficacy_v3/confirmatory_provider_v1/RESULT.json（disposition=EFFICACY_NOT_QUALIFIED, authorized=false, 92/92 healthy）；② 本会话宿主进程子环境实测 env LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL=1 且 .env/shell/LaunchAgents 均无该键，唯一定位为 runtime.toml:22 method_subject_binding_experimental=true；③ edit_file 回执 artifact://v1/bb8d30b48e4e460eaed25487b4efb118（写后复读一致 sha256=b2eb550e…）；④ service_control update 回执：desired generation=180, git_head=a519f41b9, action_id=svc-ee19ab612973458791b17c9cadc47ee8, status=waiting_for_requester_exit；⑤ 首次 restart 失败回执 detail=\"deployment binding failed: git_head mismatch desired=7a44a009f actual=a519f41b9\"。"
tags: [subject-binding, v3-confirmatory, line-retirement, runtime-canary, service-control, desired-generation-drift]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-06T16:37:16.525370+08:00"
updated_at: "2026-10-06T16:37:16.525370+08:00"
---

v3 确证终局：92/92 机械健康，双模型 challenge net_flip=2（门槛≥3）且 strong negative_flip=2（门槛≤1），EFFICACY_NOT_QUALIFIED，production_promotion_authorized=false；reverse-risk 保护成立（strong 4/6→6/6、weak 6/6、新伤害 0），guardrails/cost 全过——结论是"无效但无害"，不构成生产资格。但 runtime.toml（gitignored staged canary）仍保留 method_subject_binding_experimental=true，经 resolver 注入 env 后使全部活动运行时（web/feishu/learning，均由 mirror 根启动）的 save_experience 工具描述携带该实验提示——研究期遗留未随线退役清除。处置（user 指令"避免/下架/等优化再上"）：① runtime.toml 标志显式置 false 并注明退役与 reopen 条件；② 走 service_control update 以当前 HEAD a519f41b9 发布 desired gen180（旧 desired gen179 绑定 7a44a009f 造成 restart git_head mismatch——desired 未随 main 推进是另一个流程缺口）+ restart all；action_id=svc-ee19ab612973458791b17c9cadc47ee8（两阶段等待 requester 会话结束后执行）。reopen 仅按 docs/RESULT-20261006-method-binding-v3.md 三前置：遥测修复（已 commit a519f41b9）、全新 holdout+预冻结 SPEC、operator 显式授权。教训：研究线退役时必须同步清除 runtime 配置中的 canary 标志并推进 desired deployment generation，否则失败实验会继续注入生产工具面。当前性验证：grep -n "method_subject_binding_experimental" /Users/yyj/Project/llm-first-loop-mirror/runtime.toml 应得 "= false"行（true 即回潮，需重下架）。