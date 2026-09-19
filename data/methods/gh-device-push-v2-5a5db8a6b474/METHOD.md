---
method_id: gh-device-push-v2-5a5db8a6b474
name: gh-device-push 设备码推送链 v2
description: GitHub 设备码流程推送的可复用链：scope 选型→设备码轮询→一次性 credential helper→身份/scope 预检→git 防分叉预检→推送+SHA 精确校验→token 销毁清理；含 gh 缺 read:org 的直接推送兜底与 macOS 清理可移植性修复
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:94e5a13e-232e-436f-8f03-dd4e725ce24f:89:b107f433d81549216fe4
created_at: 2026-09-11T03:40:24.361979+00:00
updated_at: 2026-09-11T03:40:24.361979+00:00
---
适用：无长期凭据/无 TTY 环境下向 GitHub https 远端推送。前置参数：scope、repo_url、branch、account（预期账号）、expected_sha（40位）、worktree_path。
1) scope 选型：仅 git push → repo；需 gh CLI → repo,read:org；推送 .github/workflows 变更 → 另加 workflow。2026-09-11 根因：漏 read:org 致 gh auth login 校验失败。
2) 设备码：POST github.com/login/device/code（client_id+scope），向用户展示 user_code 与有效期，按返回 interval 轮询 /login/oauth/access_token。
3) token 落盘：仅写 0700 临时目录 tok.json（0600），绝不进 git 与日志。
4) 一次性 credential helper：仅响应 get（username=account、password=token），chmod 700；git 用 -c credential.helper= -c credential.helper=!$CRED 覆盖系统凭据。
5) 身份预检：Bearer token 调 api.github.com/user，login 必须精确等于 account 且 X-OAuth-Scopes 含 repo，否则中止。
6) git 预检：fetch 后 merge-base --is-ancestor <远端旧tip> HEAD（防分叉）；rev-list left-right 计数 behind==0（防远端已移动）。
7) 推送 refspec（branch:branch），ls-remote 远端 SHA 与 expected_sha 精确相等才输出 PUSH_OK。
8) 清理：优先 shred -u；macOS 无 shred（exit 127）回退 rm -Pf；删 helper/脚本/临时目录，输出 CLEANUP_OK ALL_DONE。
9) 兜底分支：gh auth login 仅因缺 read:org 失败且 token 已到手 → 不重走设备码，直接从步骤 4 继续即可完成推送。
10) 复盘：save_experience + record_skill/method_manage 固化。
