---
title: 大体量 vendored 资产会让 RULE-AI-28 审查绑定超限，full_test 需改用等价证据
scenario: "在 llm-first-loop 仓新增 3.3MB 的 vendored skill 后，想跑上游自带测试套件做等价性验证，review_admission(action=start, kind=full_test) 连续被拒：未提交时 reason=review_untracked_file_too_large；提交后 reason=git_state_too_large:material_diff>400000。"
root_cause: 审查准入按工作区相对基线的 material diff 绑定被审产物，超过 400000 字节阈值即拒绝，与被测命令本身是否安全无关；大体量数据型 vendored 资产天然撞上该上限。
solution: 不要绕过门禁：①用等价性证据替代上游套件——diff -rq 比对上游与安装副本，确认除 SKILL.md/LICENSE/NOTICE.md 与已声明的脱敏外逐字一致；②对安装副本跑上游自带校验脚本（如 validate_data.py）与真实功能实测（domain 检索、stack 检索、--design-system 生成、--persist 落盘、绝对路径调用、skill_load 运行时加载）；③在交付说明里明写“上游测试套件未运行及其原因”，不把未跑的测试写成已验证；④若确需跑上游套件，在独立 scratch git 仓中针对副本执行，并声明被测对象是副本而不是工作区本体。
evidence: "review_admission 回执两次 {\"accepted\": false, \"reason\": \"review_untracked_file_too_large\"} 与 {\"accepted\": false, \"reason\": \"git_state_too_large:material_diff>400000\"}；等价证据：diff -rq 仅显示 SKILL.md 与新增 LICENSE/NOTICE 差异；validate_data.py “OK: validated 12 domain files, 22 stack files, and ui-reasoning.csv”；4 项 CLI 功能实测与 skill_load 回执。"
tags: [rule-ai-28, review-admission, skill, verification]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T19:18:18.716452+08:00"
updated_at: "2026-10-31T19:18:18.716452+08:00"
---