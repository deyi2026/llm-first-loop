---
title: "GitHub 设备码 token 缺 read:org 时 gh auth login 失败，但可直接用于 git push"
scenario: "无长期凭据环境下用 GitHub 设备码流程向远端推送：gh CLI 要求设备码请求 repo,read:org 等完整 scope，仅请求 repo 时 gh auth login 校验失败，但该 token 足以完成纯 git push"
root_cause: "gh CLI 的 token 校验强制要求 read:org scope；设备码流程只请求 repo 时，token 可用于 git 推送但无法通过 gh auth login"
solution: "设备码 scope 按 gh 要求带上 repo,read:org；或若只需 git push，请求 repo 即可并绕过 gh：用一次性 git credential helper 直接喂 access_token，推送前用 /user API 验证账号与 X-OAuth-Scopes 含 repo，推送后 ls-remote 精确比对 SHA，最后 shred/rm -Pf 销毁 token"
evidence: "job-ded8158482574895a142: AUTH_OK→GH_LOGIN_FAIL(missing read:org)；job-e4ab4cc9290f4ce38c74: LOGIN_OK user=deyi2026 scopes=repo, PREFLIGHT_OK, d072973..c7f3671, PUSH_OK remote_sha=c7f36711911dbe7e23517a1460396da5b6598850；2026-09-11 实时 ls-remote 复核一致"
tags: [github, device-flow, gh-cli, git-push, credential-helper, scope]
source: {}
status: active
created_at: "2026-09-11T11:38:13.601648+08:00"
updated_at: "2026-09-11T11:38:13.601648+08:00"
---

chain.sh（设备码轮询→gh auth login --with-token→push）在 AUTH_OK 后死于 exit 6：error validating token: missing required scope 'read:org'。原因：gh CLI 校验强制要求 read:org，设备码只请求了 repo。兜底 chain2.sh：1) python3 从 tok.json 读 access_token，写一次性 credential helper（printf username/password）覆盖默认 helper；2) curl api.github.com/user 校验 login==期望账号并从 X-OAuth-Scopes 确认含 repo；3) fetch+merge-base 祖先检查+behind==0 后 git push；4) ls-remote 校验远端 SHA 精确相等；5) shred/rm -Pf 销毁 token 与脚本。验证：PUSH_OK 且无认证 ls-remote 复核一致。教训：macOS 无 shred，chain2 尾部 exit 127，清理兜底用 rm -Pf 并由外层命令二次确认目录已删。