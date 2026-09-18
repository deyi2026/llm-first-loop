---
title: 死循环病理三课：换工具原则、停滞熔断实现要点、并行落盘冲突处置
scenario: 同会话内同工具同参数调用反复复发（get_tool_schema(submit_evolution) 单回合 10 次、save_experience 3 次、architecture_status>=6、submit_evolution>=20 次的历史病例）；已持有信息后仍反射性前置 fetch；模型自我声明停止后依旧复发，纯 prompt 自律不可靠。
root_cause: "1) 生成循环对\"要害调用前的前置动作\"存在病理性固定前缀（schema fetch），声明切换后仍复发。2) 有效逃逸=换工具换路径（shell），在毒化生成前缀之外行动。3) 程序级护栏必须按指纹（tool+规范化参数）在执行前拦截，而非靠提醒。"
solution: "1) 失败/重复处置序列：如实报告→失败分类（拦截类/环境类/参数类）→换路径重试一次→仍失败则持久化产物交人工审阅，不静默。2) 熔断器（已落地）：tool_exec.partition_stagnation_block 同指纹连续第 3 次起不执行、合成 BLOCKED 回执；fp/count 经 runstate.stagnation_carry_* 跨 run 延续、按会话分桶不跨会话泄漏；engine.run 开始时以 carry 播种。3) 停滞场景一切文案只述事实（B-G3 红线）：拦截回执含\"建议:\"即挂 test_break_final_has_facts_no_advice，教训=熔断文案 facts-only。4) 并行落盘冲突：演进管线与本会话编辑同文件交叠产生坏混合态（半套导入+悬空调用 _stagnation_state_of_host），处置=git 三版本对比（HEAD/暂存/工作树）定位、补齐缺失 4 处、删除悬空助手恢复直接访问、全量测试归因（HEAD 基线 84 失败 vs 改后 81，交集外仅 1 项为本会话引入且已修复）。"
evidence: data/evolution/submissions/EVO-20260903-loop-breaker-task-restart-guard.json（提交物+验证结论）；tests/unit/test_stagnation_cross_run_block.py、test_loopbreaker_integration.py、test_loop_stagnation.py、test_stagnation_control_plane.py、test_tool_result_factualization.py、test_task_store.py 全绿；本会话 10 连发现场记录
tags: [death-loop, circuit-breaker, b-g3, facts-only, parallel-apply-conflict, switch-tool-principle]
source: {}
status: archived
created_at: "2026-09-03T00:29:03+08:00"
updated_at: "2026-09-06T00:06:07.826813+08:00"
superseded_by: "rule:RULE-AI-03"
---

# 死循环病理三课

1. 换工具原则：已持有信息后重复同工具同参数=零信息动作；失败后唯一有效动作是换路径。
2. 熔断器：partition_stagnation_block + 跨 run carry + 会话分桶；宿主重启后生效。
3. 冲突处置：演进管线并行写同一工作树时，以三版本对比+全量测试归因收尾，B-G3 facts-only 约束一切停滞文案。
