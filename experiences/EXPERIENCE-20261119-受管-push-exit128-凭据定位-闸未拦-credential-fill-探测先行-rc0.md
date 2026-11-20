---
title: 受管 push exit128 凭据定位：闸未拦、credential fill 探测先行、rc0 后重审再推
scenario: "LFL 沙箱内受管 git push（RULE-AI-28 git_push 准入 PASS 后）以结构化 argv 重放报 exit128 'could not read Username for https://github.com'，而非闸阻断；需要区分闸拦截与凭据解析失败并给出可验证的修复判据。"
root_cause: ""
solution: "先只读探测凭据解析：printf 'protocol=https\nhost=github.com\n\n' | GIT_TERMINAL_PROMPT=0 git credential fill >/dev/null 2>&1; echo rc=$?（token 绝不落输出）。rc≠0 属凭据问题，不是闸问题——此时勿重开审查循环，先修凭据（本例由用户用进程级 GIT_CONFIG_COUNT 覆盖 repo 内失效的 gh credential.helper，不改共享配置），rc=0 后按精确 (command, workdir) 元组重开 review_admission 取新 PASS 再推。另：push exit0 后本地 refs/remotes 更新报 EPERM（沙箱不可写主仓 .git）属已知无害限制，远端事实以 git ls-remote 独立核验为准。"
evidence: "2026-11-19 23:0x execute_command exit128: fatal: could not read Username for 'https://github.com'（repo 级 credential.helper 指向失效 gh 登录，gh auth status 报 token invalid）；git config --show-origin 实证 helper 链；23:1x 用户进程级 GIT_CONFIG_COUNT 覆盖后 credential fill rc=0；review_admission subagent_49de5955c234 GLM PASS P0=0 P1=0；argv push exit0 且 stderr 传播 423c00423..e22b98680；git ls-remote 核验 refs/heads/fix/issue76-host-review-cap-20261119=e22b98680229252a4095c3f0fee2eed3209d65e7"
tags: [git-push, credential, RULE-AI-28, review_admission, sandbox, GIT_CONFIG_COUNT, credential-fill-probe]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-19T23:21:52.952948+08:00"
updated_at: "2026-11-19T23:21:52.952948+08:00"
---