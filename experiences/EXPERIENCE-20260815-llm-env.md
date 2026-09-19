---
title: "LLM 上下文压缩应\"摘要优先、截断兜底\"，且需检查 .env 实际覆盖值"
scenario: LLM-First Loop 的 history 分层降级（_layer_trim）把旧的长 tool 消息机械截断为首尾各 400 字，导致中间关键信息丢失，AI 推理时必须 search_archive 二次取回，token 翻倍且推理中断。排查时发现实际折叠阈值不是代码默认值，而是被 .env 里 TOOL_TRIM_THRESHOLD=800 覆盖（比默认 2000 更激进）。
root_cause: 1) 折叠机制（_layer_trim）与智能摘要机制（_archive_key_facts/extract_key_info）脱节：系统里已有规则提取关键事实/路径/URL 的能力，但折叠时没用，只做机械首尾截断。2) 实际生效配置被 .env 环境变量覆盖：load_settings 装配时 _env_int 优先读环境变量，代码默认值 2000/8000 不生效，.env 里 800 才是真实阈值，导致折叠过于激进。
solution: 1) _layer_trim 折叠时复用 extract_key_info 提取关键事实+关键路径/URL 注入（规则提取零 LLM），提取不到才回退首尾截断兜底；facts 需清洗原文行前缀避免 '- - xxx' 重复噪音。2) tool_trim_threshold 默认值 2000→8000（config.py dataclass + load_settings 装配 + history.py 签名 + engine.py getattr fallback 四处同步），.env 里 TOOL_TRIM_THRESHOLD=800→8000 并更新注释。3) 测试用 'D'*5000 依赖旧阈值，改为显式传 tool_trim_threshold=100 与默认值解耦（测 age/长度逻辑时用显式小阈值强制触发）。4) 改 .env 后需重新 source / 重启进程才生效（shell 环境变量优先）。
evidence: 实际运行阈值=800（.env 覆盖）导致 1500 字符被折叠；修复后 test_history_layering.py 14 个测试全过（含新增 test_trim_uses_key_facts_digest 验证摘要优先）；clean env 装配验证 tool_trim_threshold=8000
tags: [llm_loop, context-compression, layer_trim, config-env, token-saving]
source: {}
status: active
created_at: "2026-08-15T16:08:33.685794+08:00"
updated_at: "2026-08-15T16:08:33.685794+08:00"
---