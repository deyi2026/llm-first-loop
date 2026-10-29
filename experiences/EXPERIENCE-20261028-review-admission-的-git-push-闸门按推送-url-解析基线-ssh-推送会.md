---
title: review_admission 的 git_push 闸门按推送 URL 解析基线：SSH 推送会被判不可解析
scenario: 准备把已审查 PASS 的分支推到 gitee，用户机器上 gitee 只配了 SSH 密钥、没有 HTTPS 凭据
root_cause: 闸门以推送 URL 做 ls-remote 来定位 first_push_anchor/基线，SSH 传输在该上下文不可解析即 fail-closed；命令形态（cd && git push 复合命令）同样被拒。
solution: "git push 闸门要求推送 URL 能被匿名解析以确定推送基线：把 push URL 设为 SSH、或用 url.<base>.insteadOf 把 HTTPS 改写为 SSH，均被判 push_base_unresolvable_fail_closed；闸门上下文内 SSH 不可用。唯一被受理的形式是 origin 保持 HTTPS 且 `git push origin <branch>:<branch>`，此时实际推送需要 gitee HTTPS 凭据（令牌/凭据助手）。当前性验证：先 `git config --get remote.origin.pushurl` 与 `git config --get-regexp '^url\.'` 确认两处均为 HTTPS，再 `git ls-remote origin refs/heads/main` 看能否匿名解析出基线。"
evidence: 同一提交 5291bed6 的准入结果：origin 双 HTTPS 时 accepted（anchor cb9c96da、candidate sha 260b3b8c…、审查 PASS）；pushurl=SSH、fetch URL=SSH、insteadOf 改写三种变体分别在准入或推送阶段返回 push_base_unresolvable_fail_closed / push_repository_override_not_verified / push_target_invalid
tags: [rule-ai-28, review_admission, git_push, 闸门, ssh]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-28T14:34:21.837305+08:00"
updated_at: "2026-10-28T14:34:21.837305+08:00"
---