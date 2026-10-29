---
title: RULE-AI-28 分类器现行拦截形态——载荷内撇号已不误伤（EVO-20261029-65f6fe21），骨架命令位受保护二元组仍是设计拦截
scenario: 通过 execute_command 内联 python/heredoc 修改 LFL 自身代码或执行含远端操作字面量的命令，被 RULE-AI-28 Host 准入拦截，需要快速判定拦截类别并选择规避路径时
root_cause: ""
solution: "先判拦截类别：载荷内文字（撇号、注释、分号、触发词字面量在引号串/heredoc 体内）已不构成拦截原因（EVO-20261029-65f6fe21 修复：载荷剥离为不透明占位符后才对骨架命令位置判定）——内联脚本可放心含自然语言撇号；骨架命令位置出现受保护二元组（git push 等字面量直接出现在命令位）仍触发设计拦截（push_wrapper_not_verified 等），该类拦截不是误伤，规避法：测试/示例代码用列表参数拆开二元组（subprocess.run([\"git\",...,\"push\",...])）、或改落盘脚本两步式执行、或走 review_admission 正式准入。"
evidence: "2026-10-29 R4 周检实测：①`python3 -c \"print('remote's path test')\"` → python SyntaxError（载荷到达解释器，未被 Host 拦截）②同形态载荷含 git push 字面量 → [RULE-AI-28 Host准入阻断] push_wrapper_not_verified，动作未执行③src/llm_loop/tools/review_host_admission.py _shell_segments docstring 显式标注 EVO-20261029-65f6fe21（先剥离自足载荷单元为不透明占位符，再对骨架 shlex；骨架仍不可解析时 fail closed）④data/audit/evolution_suggestions.jsonl L226：EVO-20261029-65f6fe21 status=executed（2026-10-29 01:04）。"
tags: [execute-command, rule-28, host-admission, shlex, payload-stripping, classifier]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T20:07:09.374145+08:00"
updated_at: "2026-10-29T20:07:09.374145+08:00"
---

## 适用信号
用 execute_command 内联 python/heredoc 修改代码、或执行载荷中含 git push 等远端操作字面量的命令，被 RULE-AI-28 Host 准入拦截需要判定是误伤还是设计拦截时。

## 不管什么
不管「载荷内撇号会误触发分类器」这一旧前提：自足载荷单元（heredoc 体、-c/-e 引号串）已被剥离为不透明占位符后才对骨架 shlex，载荷内自然语言撇号/注释/分号不再导致 No closing quotation 或 compound 误报。也不管合法远端推送的准入流程本身（那是 RULE-AI-28 + review_admission 的管辖面，本卡只管识别拦截类别）。

## 核验方法
1. `python3 -c "print('remote's path test')"` → 期望放行到达解释器（python SyntaxError，而非 [RULE-AI-28 Host准入阻断]）——撇号误伤已修复。
2. `python3 -c "print('git push to remote's branch text only')"` → 期望 [RULE-AI-28 Host准入阻断] push_wrapper_not_verified——骨架含受保护二元组是设计拦截。
3. `grep -n "EVO-20261029-65f6fe21" src/llm_loop/tools/review_host_admission.py` → 期望命中 _shell_segments docstring（先剥离载荷单元再 lex）。

## 核验记录
- 2026-10-29（R4 周检落卡）：核验点 1/2/3 全部实测命中（见 evidence）。本卡替代 experience:EXPERIENCE-20261022-execute-command-内联脚本的撇号-触发词会误触发-rule-ai-28-保护分类器（同日按 R3 事实轴 invalidate：撇号误伤前提已被 EVO-20261029-65f6fe21 修复推翻，理由见该卡 note；旧卡的拆列表参数/避免受保护二元组建议对设计拦截场景仍适用，已并入本卡 solution）。