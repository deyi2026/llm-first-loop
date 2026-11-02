---
title: review_admission 冻结材料在 vendored 大文件上被单路径 400KB 上限拒绝（material_diff>400000）
scenario: "在含大体积 vendored 数据资产（如 skills/ui-ux-pro-max/data/phosphor-icons-upstream.json，3.2 万行）的仓库上调用 review_admission(action=start, kind=full_test)，期望对整合提交（如 62939c22a，82 文件 / 3.8MB delta）取官方 PASS"
root_cause: ""
solution: 该拒绝来自冻结材料获取阶段的单路径 git diff 上限（_GIT_OUTPUT_MAX_BYTES=400000，_diff_acquire_cap 对非 runtime-output/非 vendored 路径返回该值），不是 2.5M 字符的静态材料上限。旧码无 _is_vendored_asset 分支时必然拒；含该分支的新提交（62939c22a：_diff_acquire_cap 对 vendored 资产用更大获取上限 + _project_vendored_asset 投影）才可能放行。因此必须在 runtime 载入新码后重跑准入（service_control publish+restart 会话退出后生效），不可靠放宽上限、截断或改基线绕过。
evidence: "本会话 review_admission(start, kind=full_test, workdir=/tmp/lfl-integrate) 回执 accepted=false, reason='git_state_too_large:material_diff>400000'（21:33，运行时代码 git_head=b008c9fae）；代码比对：新提交 62939c22a 的 _diff_acquire_cap 增 _is_vendored_asset 分支，旧码 b008c9fae 无此分支；vendored 大文件 skills/ui-ux-pro-max/data/phosphor-icons-upstream.json（32582 行）与 google-font-licenses.json（20185 行）为触发路径"
tags: [review_admission, RULE-AI-28, material_cap, deploy, write-scope]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T21:33:08.038048+08:00"
updated_at: "2026-10-31T21:33:08.038048+08:00"
supersedes: [EXPERIENCE-20261031-大体量-vendored-资产会让-rule-ai-28-审查绑定超限-full-test-需改用等]
---