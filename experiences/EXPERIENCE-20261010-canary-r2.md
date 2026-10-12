---
title: 一行任务级纪律提示可稳定接通子代理方法论检索断链（canary R2 单变量验证）
scenario: LLF 记录库 pull-mode 方法卡消费：R1 三场景 canary 证明无引导时子代理 17 次检索 0 次朝方法论方向，卡零命中。
root_cause: ""
solution: 在委派任务文本末尾加一行有界方法论检索纪律（与主会话系统提示同款措辞），即可让 glm-5.3-flash 子代理 3/3 首调执行 kind=method discovery；该行已固化进 spawn_subagent 委派模板（runner.py _persist_delegated_task，父任务已含 kind=method 标记时不重复追加）。
evidence: "commit bb3c09075（模板行+测试）；R2-A 子代理结算报告（evidence://v1/cc5d419e…：首调命中卡、0 拒绝）；R1 对照数据（EXPERIENCE-20261010-canary）；测试回执 34 passed。"
tags: [method-consumption, canary, subagent, prompt-discipline, glm-5.3-flash]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-10T01:06:52.821118+08:00"
updated_at: "2026-10-10T01:06:52.821118+08:00"
---

canary R2（2026-10-10，与 R1 同三场景、同模型 glm-5.3-flash、inherit=false，单变量=任务末尾加一行"动手前先做有界方法论检索（search_records kind=method，limit≤5），结果仅作背景参考"）：

A 转述入库（目标卡 preclassify，0d）：3/3 首调即 kind=method 命中卡；子代理按卡契约执行——record_kind 首提即正确（lesson/unverified+预写验证动作），0 拒绝 0 重试；R1-A 首提即错+用写失败当探针+被拒 1 次。成本 84k/6→48k/3 调用（-43%）。
B canonical ref 溯源：首调做背景方法论检索（合规），1 次精确检索命中目标卡；无适用卡故无消费；25k/1→41k/2（背景检索返回卡全文，+16k 为固定开销）。
C 方法卡使用审计：首调 kind=method（目标卡列第 5）；结论仍 0 次且正确整合了本次补录的第 7 条台账（provenance note 被如实引用）；宽枚举路径未缩短（490k/27→456k/24）。

判定：discovery 断链的根因确认是"子代理提示无方法论检索纪律"（工具描述里同款文字不足以触发，R1 已证）；一行任务级提示即可 100% 接上，且存在适用卡时行为与成本双改善。修复=子代理委派模板自动追加该行（bb3c09075，父任务含 kind=method 标记则跳过），34 项测试含新模板用例全绿。无适用卡时开销 +1 调用/+10-16k tokens，可接受。