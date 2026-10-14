---
title: 故障修复语境挤掉审查闸：RULE-AI-28 三闸在 fenced 紧急修复链路中被跳过（加载≠执行）
scenario: 平台级故障（子代理 execute_command 全程被 fence）的紧急修复链路中，RULE-AI-28 三道审查闸（代码全量测试前/文章发布前/push 前的独立审查子代理）被整体跳过
root_cause: ""
solution: 故障修复语境不豁免审查闸。正确路径已有先例可循：spawn 只读审查子代理（静态读码审查有效，tools 配 read_file/search_files/inspect_code）+ 测试由父会话补跑并如实标注分工——这是 2026-10-14 上午验证过的路径，而非省略审查。任何豁免必须对照 RULE-AI-28 三类豁免明示记录；无豁免依据时闸不可跳。事后补救：补独立审查（三态 verdict+回执落盘）、push 后用 ls-remote/dry-run 事后核对缓解、lesson 落档。
evidence: "规则文本：docs/ai_rules.md:444-464（RULE-AI-28 三闸+豁免三类+反例）。修复窗口轨迹：data/event_logs/b1e2c610-ff59-483f-a50b-9ef6586aaae0/2.jsonl（16:50-17:21 共 122 条 tool.execution.declared，0 spawn_subagent/0 code_review；17:11 edit_file×2 写码→17:13 全量测试 job→17:19:39 commit 47773fff5→17:19:44 publish）。今日 spawn 全记录：evidence://v1/1521ccdf5af44fdad6eac3856b0f26a1315c0fb100bd2c1df81019e8c3368717（12:00 后仅 4 次 spawn：能力探测/提案A×2/effect 验证，均非审查）。规则已检索证据：evidence://v1/11793f904a4c4c2daaceca5081c0e37838fb8d976d1db2f035cf6c7d5500e215（16:44 search_records \"RULE-AI-28 代码闸 子代理 审查\"）。push 记录：16:43:21 git push origin main（b1e2c610）、17:05:40/17:06:55 git push lfl（33d3039e，后者 --force-with-lease），均无前置审查 spawn。"
tags: [RULE-AI-28, 审查闸, 规则遵从, 故障修复, 流程遗漏]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-14T17:53:08.674858+08:00"
updated_at: "2026-10-14T17:53:08.674858+08:00"
---

事实：2026-10-14 下午平台故障修复链路（fenced 根因→commit 47773fff5，16:50-17:19）漏走 RULE-AI-28 代码闸——全量测试（7508 passed）前未 spawn 独立代码审查子代理（事件日志 122 条工具声明中 0 次 spawn_subagent、0 次 code_review），当日 16:43 push origin 与 17:05-08 push lfl 也未走 push 闸。规律：修复对象恰是"子代理 effect 被拒"故障本身时，"审查子代理不可用/紧迫修复"语境会把独立审查环节整个挤掉——尽管修复前 5 分钟刚检索过 RULE-AI-28 且存在已验证的替代路径（审查子代理静态读码仍有效+父会话补跑测试，EXPERIENCE-20261014 spawn 前缀那条）。规则反例明文禁止"以自查替代独立审查"，且豁免三类中无"紧急修复"。防再发：凡触碰 src/tests 且要跑全量测试或 push 的任务，把"spawn 审查子代理→回执落盘"写进任务第一步而非收尾；若判断豁免必须在答复中明示豁免类别。发现方式：用户察觉（本例），非程序拦截——ai_rules.md 为"需要时查阅"非自动注入，漏闸无程序提示，这是系统性弱点。