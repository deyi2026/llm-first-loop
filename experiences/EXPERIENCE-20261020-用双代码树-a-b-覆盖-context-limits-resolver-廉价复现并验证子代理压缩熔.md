---
title: 用双代码树 A/B + 覆盖 context_limits_resolver 廉价复现并验证子代理压缩熔断
scenario: 子代理压缩后 provider 报 active_run_ingress_unexpected_marker，连续 3 次同错触发熔断；需要真实压缩场景验证修复，但生产模型窗口 1M，正常填充代价极高，且 live 服务可能仍跑旧代码。
root_cause: venv 的 llm_loop 实际指向 .releases/<commit>/src（生产代码快照），所以“默认导入”天然就是生产版本，PYTHONPATH=src 可切到工作区代码；压缩触发条件只取决于 resolver 返回的窗口，覆盖它即可用真实 provider 廉价触发。
solution: "写独立探针脚本：load_env_file+Settings(data_dir=临时目录并复制 data/providers.json) → build_engine → 取 subagent_runner；把 _context_limits_resolver 覆盖为 (40000, 24000, 1.0) 使压缩在 3~4 轮真实发生；用包装 client.chat 记录每次 wire 并检测 _active_run_ingress_ref；current_tool_discovery_scope 限定为 execute_command/search_archive/read_file 控制工具 schema 占用；任务要求 6 次 execute_command 各打印 4500 字符。A 组 PYTHONPATH=src 跑修复后代码；B 组不设 PYTHONPATH，venv 默认导入 .releases/<旧commit>/src 即生产同版本代码。判据：B 组 wire 出现 marker 且 3 次同错熔断，A 组压缩发生（child context projected）但 marker 为空且 outcome=completed。"
evidence: "2026-10-20 实测：B 组（.releases/32606b145，生产同版本）wires 7-9 含 _active_run_ingress_ref，报 LLMProjectionError: active_run_ingress_unexpected_marker，round 9 熔断失败；A 组（src @ ba629d241）压缩 2 次（13→7、15→7 messages，budget_chars=22683），wires 7-8 无 marker，outcome=completed，8 轮 7 次工具调用，最终回答“完成 6 次。”；两组 token 合计约 6 万。"
tags: [subagent, compaction, 熔断, A/B验证, providers]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-20T12:59:48.263661+08:00"
updated_at: "2026-10-20T12:59:48.263661+08:00"
---