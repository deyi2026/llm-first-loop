---
title: publish 永不派发 restart action：收敛靠调用方自觉，单服务 publish 后忘重启其余服务必复发
scenario: managed services（web/feishu/learning）共享同一 desired deployment；publish 只推进代数，restart 按服务单独发起；2026-09-24 feishu 告警（head mismatch + stable 停 gen98）复盘
root_cause: ""
solution: "处置时不要问\"publish 为什么漏了 X\"——publish 按设计零派发。排查顺序：1) ls data/runtime/service-control-actions/ 按 updated_at 还原 gen 窗口内 target 分布（本例 web×10/learning×1/feishu×0 即定论）；2) 防复发靠收敛可见性：publish/update 成功回执里加只读 convergence 块（per-service matches_desired_generation / lag_generations / lagging 列表），已提交 submit_evolution；短期纪律：任何 publish 后必跑 status 核对三服务 stable.generation，落后者当场 restart。"
evidence: "src/llm_loop/runtime/service_control.py L3383-3465（CLI publish 仅 CAS 零 action）；src/llm_loop/tools/builtin/service_control.py L231-258（模型 publish 零 action 仅文本 next）；data/runtime/service-control-actions/ 台账 dump（gen99-103 窗口 11 action=web×10+learning×1，feishu×0），evidence://v1/19da7ccb63212128e2ade93bc1d1af5fdb9588e756b4248c71a225e8d44bb86f"
tags: [service_control, publish, desired-generation, convergence, feishu, postmortem]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-24T14:45:14.536250+08:00"
updated_at: "2026-09-24T14:45:14.536250+08:00"
supersedes: [EXPERIENCE-20260920-service-control-restart-deployment-binding-failed]
---

2026-09-24 feishu 告警真正的上游根因（补齐 EXPERIENCE-20260924-stage-facts 之外的完整链条）：

【设计事实】publish（CLI src/llm_loop/runtime/service_control.py L3383-3465 与模型侧 src/llm_loop/tools/builtin/service_control.py L231-258）只做 build_deployment+generation CAS 写 desired，零 restart action 派发；模型侧回执仅文本提示"接着 restart target=..."。update 才是 publish+accept_restart 单语义（restart_target 缺省按 code_root 路径名推导，推导不出则 all）。

【台账事实】data/runtime/service-control-actions/ 全量还原 gen98→103：04:35-04:36Z 三服务全量 succeeded@gen98；随后 gen99-103 窗口共 11 个 restart action，全部 origin=restart（无 origin=update），target=web×10 + learning×1(gen103 06:20Z)，feishu×0——直到本会话 06:38Z svc-4df27c34 才补上 feishu@gen103。

【为何无门禁拦截】各服务落后 desired 代在 identity 视图有 stable.stale/lag_generations 与 audit_signals，但 AC-19/L24 明确审计信号只读、永不进入 restart_required；收敛完全靠调用方自觉。窗口内每个调用方只重启自己在改的服务（web），没人对 feishu 发 action。

【判读结论】"publish 漏 feishu"不是 publish 的目标选择 bug——publish 根本没有目标选择；是"desired 推进后各服务收敛无任何强制/提示"的设计缺口。只要下次 publish 后调用方又只 restart 单服务，同样的告警会原样复发。