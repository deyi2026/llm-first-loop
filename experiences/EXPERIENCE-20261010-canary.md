---
title: 隔离子代理三场景 canary：实测知识卡消费链路与子代理行为基线的可复用框架
scenario: 需要实测 pull-mode 知识库（方法卡/经验卡）在无引导任务下是否真的被消费（发现→水合→使用→回记），或需要为子代理建立行为基线（诚实性、校验契约遵守、检索习惯）。单请求零额度测试不可信，需受控多轮+工具轨迹。
root_cause: ""
solution: "用隔离子代理做三场景 canary：每张目标卡配一个自然触发场景（任务描述不含卡名与方法论措辞），acceptance 强制报告逐次检索清单（工具名+查询词原文，含未命中），以调用形态/重试次数/一次通过率/tokens 客观判分；判分时严格区分\"discovery 链路\"与\"行为基线\"（后者可能是模型先验而非卡贡献），未发现卡不得记 record_use。"
evidence: "subagent_result 回执×3：B=subagent_13c6d6f5b424（completed，1 次 search_records 精确 ref 命中，rounds=2/tokens 25587）；A=subagent_d4f91470a8ae（completed，search_records×3 查重零方法论检索，save_experience 首提 experience+unverified 被拒后修正 lesson+unverified 成功，rounds=4/tokens 84448，stable ref experience:EXPERIENCE-20261010-macos-lsof-np-dns）；C=subagent_ed919ba03039（completed，search_records×14+read_file×8+event_stream×2，结论 0 次使用由台账/事件流/卡目录/源码五路交叉支撑，rounds=13/tokens 489562）。台账缺口独立核实：read_file data/methods/usage.jsonl（6 行无 record-use-v3）+ event_stream(workspace) 显示 2026-09-29T21:22:46 method_manage record_use 决策事件存在。"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-10T00:42:15.011991+08:00"
updated_at: "2026-10-10T00:42:15.011991+08:00"
---

验证方法：spawn_subagent(inherit=false, model=glm-5.3-flash) × 3，任务文本自包含且不出现卡名/方法论词汇，每卡配一个自然触发场景；requires 收紧（不给 execute_command）可顺带观察围栏诚实性；acceptance 数组强制要求子代理报告"逐次检索清单（工具名+查询词原文，含未命中）"，这是判分核心数据。判分四关：①discovery（检索是否朝方法论方向并命中卡）②精确 ref 水合 ③record_use 落账 ④结果质量与成本（rounds/tools/tokens 对比）。关键纠偏：必须区分"discovery 链路通过"与"行为基线通过"——行为对齐可能只是模型先验恰好等于卡内容（B 场景 1 次调用满分但全程未碰卡），不能记为卡的消费证据。子代理超时未结算时：subagent_lease 查租约 + agent_message 催收口（排队到下一 step boundary，生效约 1-2 分钟）。已知结果：discovery 0/2 自然场景命中，A 场景 record_kind 撞校验 1 次（卡定义的反模式重演），成本差最高 19 倍（B 25k/1 调用 vs C 490k/27 调用）。