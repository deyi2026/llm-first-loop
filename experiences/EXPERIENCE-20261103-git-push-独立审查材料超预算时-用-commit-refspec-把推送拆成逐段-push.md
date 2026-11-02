---
title: git_push 独立审查材料超预算时：用 commit refspec 把推送拆成逐段（push_head 锚定）
scenario: "一次入库 81 个知识资产 + 前一批 95 个方法卡，两批累计 delta 触发 review_admission(kind=git_push) 的 reviewer_duration_precheck：est=5416s > hard_max=3600s 被拒；且 git_push 不接受 scope=patch paths（代码 review_host_admission.py 对 kind==\"git_push\" 传 paths 直接判 review_scope_not_applicable_for_git_push）。"
root_cause: review_admission 的 git_push 审查材料是「推送目的地 base..push_head 的逐字 delta」，材料规模只随待推 commit 变化，与 scope paths 无关；一次把两批积压一起推就必然超材料预算，只能靠把 push_head 前移到较早 commit 来分段。
solution: "改用「分段推送 + 每段独立审查」：(1) 读 review_host_admission.py 确认 git_push 的材料锚点是 base..push_head，push_head = 命令 refspec 源解析出的 commit，工作区只在 push_head==HEAD 时才计入材料；(2) 先推早的 commit：review_admission(action=start, kind=git_push, command=\"git push origin <sha>:refs/heads/main\") → 材料只含该 commit 的 delta（本次 225,764 字符，est 2257s，PASS）→ 用同一命令推送；(3) origin/main 前移后再对下一段做同样的 admission（本次 318,181 字符，est 3181s，PASS）→ git push origin main；(4) 入库侧配套：先按 git_security_scan 规则 5 脱敏（家目录 → /Users/<user>/，内网地址 → 192.168.x.x，形似私网 IPv4 的构建号按可读日期时间转写并注明数字未改），超单文件 1MB 闸的产物只写 .gitignore 精确条目（不删除文件本体，同内容轻量形态入库），commit 前跑 git_security_scan.sh --staged 预检。"
evidence: "实证：review_admission(kind=git_push, command=\"git push origin 30e9d2b6c:refs/heads/main\") 回执 material_chars=225764 / est=2257.6s / qualification=PASS → git push 成功（86ec7fefb..30e9d2b6c，pre-push 扫描 96 文件通过）；随后 review_admission(command=\"git push origin main\") material_chars=318181 / est=3181.8s / PASS → git push origin main 成功（30e9d2b6c..352df667b，pre-push 扫描 81 文件通过）；远端 refs/heads/main 最终=352df667b，工作区干净。机制依据在仓内代码 src/llm_loop/tools/review_host_admission.py（push_head 锚定；kind==\"git_push\" 拒绝 scope paths）与 docs/EVO-20261102-full-test-material-projection.md（材料预算 est=字符数/100，hard_max=3600s）。"
tags: [git_push, review_admission, RULE-AI-28, 材料预算, 分段推送, 知识资产入库, 脱敏]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-03T07:21:40.072985+08:00"
updated_at: "2026-11-03T07:21:40.072985+08:00"
---