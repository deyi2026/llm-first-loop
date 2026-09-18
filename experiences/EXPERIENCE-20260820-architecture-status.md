---
title: architecture_status 维度名白名单与镜像自测基线
scenario: "镜像环境（llm-first-loop-mirror）自测：调用 architecture_status 时传 rules/cache/models/evolution/exceptions 等维度名会返回\"维度 X 暂不可用\"；传 available_dimensions 列出的真实名（rules_version/current_phase/context_usage 等）则正常返回。"
root_cause: "architecture_status 维度白名单固定（action_trace/architecture_config/context_usage/current_phase/exception_log/memory_state/message_flow/model_fallback/pending_actions/process_versions/program_faults/recovery/rules_version/tool_history/workspace_changed），无 rules/cache/models/evolution/exceptions 维度；返回\"暂不可用\"是真实参数校验结果而非假错误。"
solution: "调用 architecture_status 前先读回执中的 available_dimensions，只用真实存在的维度名；\"维度 X 暂不可用\"= 维度名不在白名单（非工具故障），用正确名重调即可。镜像侧基线：rules_version=3（docs/ai_rules.lite.md 头部 version=3）、当前模型 deepseek-v4-flash（默认装配）、recovery pending_count=0。"
evidence: "镜像自测轮 1：architecture_status(dimensions=[\"rules\",\"cache\",\"models\",\"recovery\",\"evolution\",\"exceptions\"]) 中 5/6 维度返回\"暂不可用\"，recovery 正常；轮 2 用真实名 rules_version/current_phase/context_usage/tool_history/workspace_changed 验证。"
tags: [architecture_status, dimensions, 镜像, 自测, 工具验证]
source:
  channel: mirror_self_test
  session: llm-first-loop-mirror
  date: 2026-02-08
status: active
created_at: "2026-08-20T16:27:35.853702+08:00"
updated_at: "2026-08-20T16:27:35.853702+08:00"
---