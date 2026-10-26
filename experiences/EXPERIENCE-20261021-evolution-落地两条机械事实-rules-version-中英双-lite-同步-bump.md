---
title: evolution 落地两条机械事实：rules_version 中英双 lite 同步 bump；弱模型档 A/B 须脚本内联描述直连 provider
scenario: 执行已批准的 evolution 建议，涉及 ai_rules 规则文本/rules_version bump，或 Provider Prompt 影响检查（弱模型档行为对照）
root_cause: ""
solution: rules_version bump：中英双 lite 文件同步改头部 version=N+日期，test_model_contract_slimming.py 的 vN 硬断言测试同步更新；跑 test_ai_rules_sync.py 验证。弱模型 A/B：不依赖 spawn_subagent（主进程缓存 registry），脚本内联改前/改后 description 直连 cognilocal API，身份轮+任务轮各两次，任务轮精确调用一致性为主要判定面。
evidence: "reports/evolution/20261021-evo-3d63d7c1-weakmodel-ab.json（身份轮+任务轮 A/B 原始输出）；reports/evolution/20261021-evo-3d63d7c1-weakmodel-task-repeat.json（任务轮复测 4/4 exact_cmd）；pytest 198 passed（test_ai_rules_sync 首轮失败于中英版本漂移 {'19','20'}，补 ai_rules.lite.en.md 后全绿，evidence://v1/ 对应 execute_command 回执）；evolution_exec_log 两条 executed 登记"
tags: [evolution-execution, rules-version, provider-prompt-check, weak-model-ab]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-21T19:05:14.047067+08:00"
updated_at: "2026-10-21T19:05:14.047067+08:00"
---

EVO-20261021-31e08d8d / EVO-20261021-3d63d7c1 执行实录（2026-10-21）：1) rules_version 真值源是 docs/ai_rules.lite.md 头部（src/llm_loop/introspection/status.py:_rules_version 解析），非 ai_rules.md；bump 时中英双 lite（ai_rules.lite.md + ai_rules.lite.en.md）必须同步，test_lite_files_are_versioned_and_small_maintenance_artifacts 强制断言 versions 集合大小为 1，且 test_model_contract_slimming.py 有硬编码 vN 断言测试需同步改名/改值（本次 v19→v20）。2) spawn_subagent 子代理工具 schema 来自主进程已加载 registry（src/llm_loop/tools/registry.py 内实现），主进程不重启则测不到改后 schema；故 Provider Prompt 影响检查的弱模型档 A/B 用脚本内联改前/改后描述文本，经 openai 格式 chat/completions 直连 cognilocal（localhost:8901，model=qwen3.8-flash-next），与主进程解耦且真正命中"发给 provider 的 tools[].description"这一影响面。身份轮单次采样组间差异（自称 Claude vs Qwen）属弱模型固有不稳，新句无身份线索时不可归因，判定以任务轮行为一致+无拒绝/无义务渗出为准（复测 4/4 精确一致加固）。