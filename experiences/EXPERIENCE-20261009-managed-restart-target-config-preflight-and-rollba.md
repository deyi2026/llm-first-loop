---
title: 常用约定：受管发布/重启前必读方法卡 managed-restart-target-config-preflight-and-rollback-binding（目标版本启动配置预检+回滚绑定）
scenario: 用户授权的受管服务发布/重启/回滚或 Canary 启用场景；2026-10-09 gen213/gen214 因相对配置路径连续启动失败，由 ChatGPT 与用户完成恢复并沉淀方法候选，本会话按交接接收为常用工作约定。
root_cause: gen213 与 gen214 均在 _read_operator_config 的绝对路径检查退出（Canary 配置相对路径）；provider_proxy 字段对旧回滚版本不兼容为次生风险；发布前只做了 TOML schema 校验，未用目标版本真实加载器做完整启动配置预检。
solution: 受管发布/重启前固定前置：检索并完整重读方法卡 managed-restart-target-config-preflight-and-rollback-binding-356473240ac6（status=candidate，unbaselined），按当时目标版本契约核验后执行；两阶段启用（先 Canary OFF 成 known-good）、回滚组合须代码+配置同时兼容、同 Web run 重启后自己收尾并交外部接力。
evidence: "method:managed-restart-target-config-preflight-and-rollback-binding-356473240ac6（本会话 search_records 完整读取回执，2026-10-09T19:42+08:00）；用户交接消息 2026-10-09T19:42:30+08:00；service_control status：gen215@4b9ff14e0/PID94963/svc-29a449bfebcd49bc97007cb2300cedb4 succeeded/19:41:43"
tags: [managed-restart, preflight, rollback-binding, canary, convention, service-control, gen213-gen214-incident]
source: {}
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-10-09T19:44:11.163953+08:00"
updated_at: "2026-10-09T19:44:11.163953+08:00"
---

触发条件（常用约定）：用户对受管 Web/Feishu/Learning 授权发布、重启、恢复、回滚，或 Canary 接线启用（service_control publish/update/restart 或运行时配置接线）时，动手前第一步固定为：search_records(kind="method", query="受管重启 启动配置预检 Canary 绝对路径 回滚", limit<=5) → exact hydrate method:managed-restart-target-config-preflight-and-rollback-binding-356473240ac6 → 按卡内 Short path 执行并按当时目标版本契约重读卡内 freshness 引用的四个文件（runtime/resolver.py、web/task_budget_canary.py、runtime/service_control.py、scripts/restart_mirror.sh）。核心顺序：现状/权限/目标身份 → 目标版本完整启动配置预检（TOML schema 不足够；Canary 绝对路径/权限/字段/会话绑定用目标版本真实加载器核验）→ 代码+配置兼容的回滚组合 → 新版本先 Canary OFF 生效成 known-good → 必要时单独启用已授权 Canary → 受管 action_id 终态+live 身份+健康核验。附加规则：同一 Web 自身 run 请求重启后要结束自己，接力观察交外部 controller/持久回执，不靠旧进程挂 wake 承诺续跑；仅阅读/接收不算 applied，真实复用后才 method_manage(record_use)，任务收益独立评价；方法不新增逐条审批，已有授权按其范围继续。当前性验证：grep -n "LFL_TASK_BUDGET_WEB_CANARY_CONFIG" src/llm_loop/web/task_budget_canary.py 应仍在且仍为唯一启动开关；search_records(kind="method", query="受管重启", limit<=5) 应命中该卡 exact ref。来源事故：gen213/gen214 相对配置路径启动失败，关闭过期 Canary 后 svc-4b0595ab7a0a4ebf9979588a1688cb7e succeeded（gen214@14352cc6f/PID85960），随后 gen215@4b9ff14e0 于 19:41:24 生效（svc-29a449bfebcd49bc97007cb2300cedb4 succeeded）。