---
title: "不可信 git config 喂安全子进程 argv 的加固清单（选项注入/ext:: helper/shell 钩子）"
scenario: "安全敏感子进程以 git config 派生值为 argv 操作数（如 review_host_admission._push_base_commit 用 remote get-url --push 结果调 ls-remote）。独立审查两轮 REVISE：P1-① tracking-ref fallback 可被 git update-ref 伪造、且 ls-remote 查 fetch URL 而推送走 push URL；P1-② pushurl 选项注入（--upload-pack=<cmd> 被解析为选项→RCE）与 ext:: helper 命令执行。"
root_cause: ""
solution: "不可信 git config 进安全子进程 argv 的五层防御：① `--` 选项分隔符阻断选项注入；② 前导 `-` 直接拒绝；③ scheme 白名单必须覆盖两种语法——`scheme://host` 和 helper 的 `helper::address`（无斜杠！仅查 `://` 的白名单对 ext:: 完全失效，实测 ext::sh-c-evil 能通过）；④ 拒绝空白字符；⑤ `-c core.sshCommand= -c core.gitProxy=` 中和 shell 执行的传输钩子。基线解析必须走推送真实目的地：`git remote get-url --push`（注意 `ls-remote --push` 在 Apple Git 2.50.1 不存在，rc=129）后直查该 URL；本地 tracking ref 一律不可信（update-ref 可任意改）。破坏性 refspec（:删除、+强推）在解析期拒绝——base..HEAD delta 无法诚实代表其效果。"
evidence: "evidence://v1/158ea0c58cf4e19c598bc13295c246c366b4b3000ac9f27d860846c8a0452fcb; evidence://v1/d8850e8a721c641cdd1e3518d961ed2109a47acfa0e41e6de020c3b7c0c6bb2c"
tags: [git-security, argument-injection, ext-transport, subprocess-hardening, review-gate, threat-model]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-21T15:27:06.655399+08:00"
updated_at: "2026-10-21T15:27:06.655399+08:00"
---

五层防御逐条落地（ccec8dff6）：① argv 加 `--` 分隔符；② 拒绝前导 `-` 的 URL；③ scheme 白名单 {http,https,ssh,git,file}，同时拒绝无 `://` 但含 `::` 的 helper 语法（ext::/fd::）；④ 拒绝含空白字符的 URL；⑤ 调用时 `-c core.sshCommand= -c core.gitProxy=` 中和 shell 钩子（本地路径远端验证无害）。配套单测必须用真实 git config remote.<name>.pushurl 注入恶意值，断言受理被拒且 runner.started==0（reviewer 未被 spawn）。独立审查连续两轮各揪出一个 P1，证明该门"对准发布产物而非过程声明"的价值。