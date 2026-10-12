---
title: LFL 改默认模型/降级链的正确姿势：.env 持久化 + 重启生效，refresh_config 仅目录热重载
scenario: 用户要求改 LFL 默认模型（LLM_MODEL）或调整降级链（MODEL_FALLBACKS）时，需预判改动何时真正生效
root_cause: ""
solution: "路径：改 .env → refresh_config → 回执会如实说明。实测（2026-08-30）：refresh_config 能检测到 LLM_MODEL 变更（回执\"字段: model\"），但默认 client 不原地热改（防半新半旧），需重启进程生效；MODEL_FALLBACKS 属启动装配字段（config.py:763 → factory.py:205 注入 pool.model_fallbacks_raw，replace_registry 不更新它），同样重启生效。会话级模型用 switch_model 即时切换。"
evidence: "evidence://v1/7859f0ac34d9c8fbd80b020fd7b4935fc2125be064b921c957d0103c6915b674；evidence://v1/4a34e316d067e6650fadd77614d486c2845d8f524448fd7418673c175878cacb"
tags: [llm-first-loop, model-config, refresh-config, hot-reload, model-fallbacks]
source: {}
status: active
created_at: "2026-08-31T00:18:51.094556+08:00"
updated_at: "2026-08-31T00:18:51.094556+08:00"
---

2026-08-30 飞书指令落地：LLM_MODEL=glm/glm-5.3；MODEL_FALLBACKS 移除 local/qwythos-*，新链 glm/glm-5.3-flash → deepseek/deepseek-v4-flash → minimax/MiniMax-M3。refresh_config 回执确认 model 字段变更被检测但未热改（设计如此），重启后全量生效。