---
title: "机判子代理输出时语言约束优先于格式约束：GLM 审查员\"结论：PASS\"三连败与\"Reply in English only\"一击修复"
scenario: Host 审查准入的机器判定解析 child 输出（review_host_admission.poll 的 VERDICT/P0-P2/SHA 正则），审查员模型默认以中文收尾总结
root_cause: ""
solution: "对需要机器解析的 LLM 子代理输出：①任务首句加全局语言指令（Reply in English only），比格式模板/警告/逐字示例都有效；②格式契约放材料最末（recency）但只作辅助；③解析失败路径必须回显原文尾巴（review_tail），否则诊断靠人工捞 child 输出。当前性验证：grep -n \"Reply in English only\" src/llm_loop/tools/review_host_admission.py 应命中；复现路径见 evidence 中三次 child 输出与第四次 PASS 对照。"
evidence: "evidence://v1/7707b65f1416930bda8398ec26c65509cbdaafe9ccce4c66c090b3d5239ed1ae7 evidence://v1/ec5b2cf8d21e271348bad5b2034cf18574c6503195c5229c4d94dfda90f97989 evidence://v1/3baac40114f459870586019ed99ff5f31bec3dd945ed5119fda69e4b5f605d48 evidence://v1/f3fc2d1bfc0916a78c438f528039a03eaf7ca01349b340e6f21b44cbf22cd901"
tags: [rule28, review-admission, llm-output-contract, machine-parsing, prompt-engineering]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-18T22:08:02.953041+08:00"
updated_at: "2026-10-18T22:08:02.953041+08:00"
---

RULE-AI-28 审查 child（GLM-5.3 spawn，review task 含中文材料）连续 3 次在结尾输出中文"结论：PASS"而非机判要求的英文 `VERDICT: PASS` 行（P0/P1/P2/SHA 行均合规），导致三次实质 PASS 全被机判 fail-closed 拒绝。已试无效：中部指令要求 standalone VERDICT 行、材料尾部警告"localized labels are INVALID"、逐字输出模板（recency anchor）。有效：task 首句 "Reply in English only." ——语言是模型输出的全局属性，语言指令的遵从率远高于局部格式指令；第四次审查即输出标准英文 verdict 并 PASS。同时给 verdict 解析失败路径加了 review_tail（child 原文尾 160 字符）回显，保证此类失败可诊断。教训：与 LLM 子代理的输出机判契约，格式约束要挂在语言约束之上；只修格式模板不解决语言漂移。当前性验证：grep -n "Reply in English only" src/llm_loop/tools/review_host_admission.py 应命中 task 首句；grep -n "review_tail" 同文件应命中 verdict 失败分支。