---
title: review_admission PASS 后重发必须精确单命令：复合 push+fetch 会被 compound_protected_shell_requires_split_commands 拒绝
scenario: "RULE-AI-28 审查闸（review_admission PASS）之后重发 git push；或任何\"审查过的单命令\"想和验证命令拼一条执行"
root_cause: ""
solution: 审查绑定的命令逐字单发，验证命令（fetch/rev-parse/log）拆成独立 execute_command；不要给受保护动作附加任何复合段。
evidence: "execute_command 阻断回执 compound_protected_shell_requires_split_commands（workdir=/Users/<user>/Project/llm-first-loop-mirror, candidate ac3e3bca…）；拆分后单命令 push 成功 0b6138833..67704b794，fetch 回读 HEAD==lfl/main==67704b794。"
tags: [RULE-AI-28, review_admission, git_push, 复合命令, 准入绑定]
source:
  commit: 67704b79495dc1c210d9c906310ea613d750407a
  target: "git_push:7beb11b99320086adaa543324cdbf97dc8ee1ea2bf605a4d825830470eb15447:command:313720ca715e13f7d0934c5ee7b8ad823b0a195fe9d45c153382c47fd36312e2"
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T10:10:51.651206+08:00"
updated_at: "2026-10-29T10:10:51.651206+08:00"
---

事件：review_admission(kind=git_push) 取得 PASS 后，重发时把 push+fetch+rev-parse+status 拼成一条复合命令，被 RULE-AI-28 Host 准入阻断：compound_protected_shell_requires_split_commands——准入回执绑定的是发起审查时的精确单命令"git push lfl HEAD:main"，附加任何受保护 shell 动作都会脱离绑定。
修复：拆开单独执行（1. git push lfl HEAD:main 原样单发 → 通过且真实推送；2. fetch+rev-parse 校验另发）。
适用边界：凡是经 review_admission 审查的命令（full_test/git_push/article_publish），重发必须与审查时 command 参数逐字一致、且不与其它动作复合；事后的验证类只读命令（fetch/rev-parse/status）不需要绑定，单独发即可。