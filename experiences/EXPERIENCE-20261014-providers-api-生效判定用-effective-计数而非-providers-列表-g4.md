---
title: providers API 生效判定用 effective_* 计数而非 providers 列表（G4 验收字段口径）
scenario: web 通道剥离 G4 验收：外部注册模块（deepseek-web）是否在生产进程生效。重启后 GET /api/v1/providers 返回 5 个 provider 且无 deepseek-web 条目、启动日志无外部模块痕迹、warning 亦无——三个阴性信号叠加，极易得出「注册失败」结论。实际 registry 生效计数为 6/29，注册早已成功。
root_cause: ""
solution: 计数核验读 effective_provider_count/effective_model_count（registry 真值），不以 providers 列表长度为准；列表缺失时先找快照函数里的独立生效计数字段再下结论。本次凭 effective_* 字段反转，避免了错误排查方向。
evidence: "providers API 实测输出：len(providers)=5 且无 deepseek-web 条目，同响应 effective_provider_count=6 / effective_model_count=29；web.log 09:57:48 provider=deepseek-web；源码 provider_admin.py snapshot()：providers 列表迭代 raw（_effective_config），effective_* 迭代 registry.providers（含 finalize 叠加）。"
tags: [web, providers, registry, 验收, 字段口径]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T09:59:08.940068+08:00"
updated_at: "2026-10-14T09:59:08.940068+08:00"
---

GET /api/v1/providers 的 providers 列表来自配置管理源（providers.local.json 的 raw 视图，source=local/mutable），不含外部 web provider 模块经 load_registry finalize 叠加进 registry 的条目；运行时真实注册数在 effective_provider_count / effective_model_count 字段。判注册是否生效必须以 effective_* 为准。外部模块加载失败仅 warning 降级、未配置则静默空——「无日志+列表无条目」≠未生效。诊断时优先用 runtime.launch --dry-run 的 effective 环境快照 + 生产同款解释器复现（注意 load_env_file 无参时基于模块位置解析，release 布局下需显式传项目根 .env 路径）。