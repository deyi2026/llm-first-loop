---
title: 第三方 skill vendored 数据触发本仓 pre-commit 安全扫描时的处置顺序
scenario: 在 llm-first-loop 仓 vendored 第三方 skill（含 CSV/JSON 数据）时，git commit 被 scripts/git_security_scan.sh 拦截：规则3（本地绝对路径 /Users/<name>/）与规则5（身份隐私）同时命中。上游数据里往往只是通用占位符式的示例路径（如 JavaFX 文档示例），并非真实机器身份，但守卫脚本对形态零容忍。
root_cause: 守卫脚本按字面形态识别 /Users/<用户名>/，无法区分第三方文档里的通用占位符与真实身份路径；因此冲突点在 vendored 内容而非本次改动本身。
solution: 处置顺序：①先用 grep -rn -o 统计命中文件与处数（本例整棵 vendored 树只有 1 处），确认不是自身泄漏；②查该文件是否被数据哈希快照覆盖（本例 catalog-summary.json 的 snapshots 只覆盖 4 个文件，不含 stacks/*.csv），确认脱敏不会破坏一致性校验；③优先做最小单点脱敏（把用户名占位换成 <user> 形态），不要改守卫脚本——改守卫属 RULE-AI-28/RULE-AI-35 范畴，需独立审查与拦截回归证明；④把脱敏写进 NOTICE.md 的本地修改清单，并写明判定依据；⑤重跑上游自带校验脚本确认仍 OK；⑥注意 NOTICE 与文档本身也会被扫描，文档里复述触发形态的字面量会再次触发拦截，需改写为尖括号占位描述。
evidence: "commit c927f29da；拦截回执“❌ [git_security_scan] 命中安全规则（提交被拦截）: 本地绝对路径匹配 [/Users/[A-Za-z0-9_]+/] 文件: skills/ui-ux-pro-max/data/stacks/javafx.csv”；脱敏后“✅ [git_security_scan] 通过（52 个文件无敏感/错误内容）”；validate_data.py 输出“OK: validated 12 domain files, 22 stack files, and ui-reasoning.csv”。"
tags: [skill, vendored, git, security-scan, third-party]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T19:18:18.404106+08:00"
updated_at: "2026-10-31T19:18:18.404106+08:00"
supersedes: [EXPERIENCE-20261030-交付文档写本机绝对路径会被-pre-commit-安全扫描拦截]
---