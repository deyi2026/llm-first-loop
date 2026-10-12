---
title: 真实 LLM 集成测试的三大环境坑：bash env 注入污染 / 注册表缺失 / engine API 漂移
scenario: 跑 run_real_smoke.sh --quick（真实 LLM 冒烟）失败链：①LLM 摘要降级 deterministic（API 400）；②模型未发起工具调用；③tool_call.arguments NoneType 断言失败。逐层排查根因。
root_cause: "1) .env 值 `KEY=value  # 注释` 经 restart_system.sh `_val=\"${_val%% #*}\"` 剥后仍留尾随空格 → bash 子进程/测试直读 os.environ 拿到带空格模型名 → DeepSeek API 400（'unknown variant `max   `'/模型名带前缀）。python load_settings 有 .strip() 兜底，但 bash 注入路径（run_real_smoke.sh load_env_val、测试内联 Settings）没有。2) 测试 fixture 用 tmp_path 作 data_dir → load_registry 读 {data_dir}/providers.json 不存在 → 回退 L0 合成（无模型映射）→ factory resolve 失败 → engine.llm 用带前缀模型名（deepseek/deepseek-v4-flash）直发 API 400（Summarizer/Extractor 直调 engine.llm）。3) 测试调 engine.run_turn（不存在，应为 run_single）。4) 断言会话加载后 assistant.tool_calls 只剩空占位（id/name 空、args None）——正确断言依据是 LoopResult.tool_calls 执行轨迹。"
solution: "1) 所有 bash env 注入路径统一剥行内注释 + rtrim 尾随空格（restart_system.sh `_val=\"${_val%\"${_val##*[![:space:]]}\"}\"`、run_real_smoke.sh load_env_val sed -E）；测试内联 Settings 对 llm_model/base_url/reasoning_effort 加 .strip() 防御。2) 测试 fixture 把项目 data/providers.json 拷贝进 tmp_path/data（保持隔离同时注册表真实可用）。3) engine API 用 run_single(user_text)→LoopResult。4) tool-call 参数断言用 resp.tool_calls（执行轨迹 dict 含 arguments），不依赖会话加载的 tool_calls。"
evidence: commit 1caa12f/4b5c27e（2026-08-17）；真实冒烟 quick 全绿（real_llm 2 用例 + tool-call 往返 1 用例）；错误链实测：400 unknown variant 'max   ' → resolve 失败带前缀 → run_turn AttributeError → arguments NoneType
tags: [集成测试, env注入, providers.json, 真实LLM, 冒烟, API漂移]
source: {}
status: active
created_at: "2026-08-17T14:26:32.172603+08:00"
updated_at: "2026-08-17T14:26:32.172603+08:00"
---