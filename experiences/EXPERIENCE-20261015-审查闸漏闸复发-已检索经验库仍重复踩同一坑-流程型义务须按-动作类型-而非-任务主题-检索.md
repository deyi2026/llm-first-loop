---
title: "审查闸漏闸复发：已检索经验库仍重复踩同一坑——流程型义务须按\"动作类型\"而非\"任务主题\"检索"
scenario: 2026-10-15 改 src/llm_loop/usage_net.py（D3 晋升型不清零，EVO-20261015-251ac06d）并跑全量测试，未 spawn 独立代码审查子代理即交付。用户察觉并指出。此前 2026-10-14 已落档同主题 lesson 卡，且本轮确实检索过经验库——仍未命中该卡，重复踩坑。
root_cause: "检索词按当前任务内容（JEV 治理、净分、usage_net）构造，而非按\"失败模式\"抽象（审查闸/全量测试前/spawn 子代理）。经验卡标题以\"故障修复语境\"为场景前缀，与\"日常代码改动\"语义不重叠，故不命中。RULE-AI-28 漏闸第二次独立发生，说明单点 lesson 不足以防再发：闸的触发条件是\"动作类型\"（改 src/ + 跑全量测试），不是\"任务主题\"，用主题词检索必然漏。"
solution: |
  把审查闸触发判据从"主题匹配"改为"动作类型匹配"：凡任务同时满足(1)修改 src//tests//scripts//tools//webui/ 任一文件 (2)要跑全量测试或要 push —— 在动手第一步就 spawn 只读审查子代理，不等收尾、不依赖经验检索命中。检索经验库时，对流程型义务额外用"闸/审查/spawn/全量测试/push"等动作词单独检索一轮（limit≤5），不要只用任务主题词。若判断豁免，必须在答复中明示 RULE-AI-28 三类豁免中的具体类别。
  当前性验证：动手改码前先跑 `git status --porcelain src/ tests/ scripts/ tools/ webui/`；输出非空且本任务要跑全量测试或 push 时，即触发 spawn 只读审查子代理。另跑 `grep -n "规则二十八" docs/ai_rules.md` 确认 RULE-AI-28 行号仍存在（当前为第 444 行起），条款若已改号应重读全文再引用。
evidence: "规则文本 docs/ai_rules.md:444-464（RULE-AI-28 第1条代码闸+豁免三类+反例\"以我自己检查过了替代独立审查\"）。漏闸事实：git status 显示 src/llm_loop/usage_net.py 与 tests/unit/test_usage_net.py 均 Modified（HEAD=2ad0bc06d），父会话在 spawn 前已跑完全量回归（281 failed 差分对比）并声称完成，期间 0 次审查类 spawn。前序同主题卡：experiences/EXPERIENCE-20261014-故障修复语境挤掉审查闸-rule-ai-28-三闸在-fenced-紧急修复链路中被跳过-加载-执行.md（verified，正文已写明\"凡触碰 src/tests 且要跑全量测试的任务，把 spawn 审查子代理写进任务第一步\"）。补审动作：spawn subagent_249e3241f67e / subagent_608fdbf65ff5 两个只读审查子代理（注：误重复派发一次，属操作失误）。被审产物 SHA：src/llm_loop/usage_net.py blob=97c14413cede8f3e80ac5bdf9b8321f03e052d90，tests/unit/test_usage_net.py blob=446679f0cc3456af6158ed5d14f62cc8e03e4bd2。"
tags: [RULE-AI-28, 审查闸, 检索词构造, 规则遵从, 重复踩坑, 动作类型触发]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-15T07:21:56.853749+08:00"
updated_at: "2026-10-15T07:21:56.853749+08:00"
---