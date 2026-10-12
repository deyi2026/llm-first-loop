---
title: GitHub 无交互环境设备码授权与推送恢复全流程（含失败分支与等待兜底）
scenario: "GitHub headless/无浏览器/无 TTY 环境下 push 报 \"could not read Username for 'https://github.com': Device not configured\"，需要完成 OAuth 设备码授权→gh 登录→重试推送→清理凭据临时文件的完整恢复；含跨会话等待（真人异地完成授权）与 schedule(wake) 被拒时的阻塞兜底"
root_cause: headless 环境无 git 凭据（credential.helper 指向 osxkeychain 但无 github.com 条目、gh 未登录、无 SSH key、无 token env），https push 无法交互输入用户名密码
solution: "六步法：0) 诊断链穷举凭据来源（credential.helper 存储、gh auth status、~/.ssh、keychain、GH_TOKEN/GITHUB_TOKEN env），任一命中则直接复用，全空才走授权；1) curl POST https://github.com/login/device/code（client_id=178c6fc778ccc68e1d6a，gh CLI 官方 OAuth app；scope 必须显式传，如 repo）取 user_code/device_code，把 user_code+verification_uri 展示给真人；2) 后台 durable job 轮询 access_token endpoint，umask 077 落盘 token 文件，job stdout 只打 AUTH_OK/pending 不打 token；3) 等待：优先 schedule(wake)；被拒则 adjust_strategy 提 timeout_s 至上限后阻塞轮询目标文件出现即返回；4) sed 提取 token 管道喂 gh auth login --with-token（不回显）→ gh auth setup-git → gh api user 验证身份；5) 重试前回读 evidence 原始失败命令，用完全相同 refspec 重试；6) shred -u 清理设备码与 token 文件并 ls 验证。"
evidence: "push 失败原文 evidence://v1/07e02c7bfd47d10e4ae1c78532e0f5318bb22f943f8faefb453d7561e9d9780f；AUTH_OK 轮询任务 job-f5503676e7e548fdb31a（exit 0，第19次轮询命中）；后续 gh login/setup-git/gh api user=deyi2026、push 新建远端分支 exit=0、临时文件清理验证均为 2026-09-09 04:0x 本会话 execute_command 实测输出"
tags: [github, oauth-device-flow, rfc8628, gh-cli, git-push, headless-auth, credential-recovery, security-hygiene, waiting-strategy, retry-discipline]
source: {}
status: active
created_at: "2026-09-09T04:42:22.636259+08:00"
updated_at: "2026-09-09T04:42:22.636259+08:00"
---

完整流程（2026-09-08 实战验证成功）+ 修正项：

【步骤0 诊断链】push 报 "could not read Username for 'https://github.com'" 时依次探测：(a) git config credential.helper 及对应存储是否有 github.com 条目 (b) gh auth status (c) ~/./*.pub 与 ssh -T git@github.com (d) macOS: security find-internet-password -s github.com（只看元数据）(e) env | grep -E 'GH_TOKEN|GITHUB_TOKEN'。任一命中→直接用（gh 命中则补 gh auth setup-git）；SSH remote（git@github.com:）不适用本方法；GitHub Enterprise 需换 endpoint 域名与 client_id。有 TTY 时优先 gh auth login 交互向导。

【步骤1 设备码】curl -s -X POST https://github.com/login/device/code -H "Accept: application/json" -d client_id=178c6fc778ccc68e1d6a -d scope=repo（修正：scope 必须显式声明；需 org/workflow 权限时相应追加）。响应含 user_code/verification_uri/device_code/interval/expires_in。把 user_code + verification_uri 明确展示给真人。

【步骤2 轮询 job】后台 durable job：umask 077 后轮询 POST https://github.com/login/oauth/access_token（Accept: application/json），分支必须覆盖：authorization_pending→继续；slow_down→按响应 interval 加倍退避（修正：本次硬 10s 未实现，列为已知缺陷）；expired_token→exit 2 报 DEVICE_EXPIRED；access_denied→立即终止报用户拒绝（修正：本次缺失）；curl 非零退出→区分网络错误与协议错误，勿混入 pending（修正：本次缺失）。命中 access_token→写入 077 权限文件（改进：mktemp 私有目录优于 /tmp 固定名）→ echo AUTH_OK。轮询总时长应 < expires_in（设备码通常 900s）。

【步骤3 等待】优先 schedule(wake) 续跑检查；wake 被拒（委派 ingress 不可续跑）→ adjust_strategy 把 timeout_s 提到上限（本环境 600，全局硬顶亦 600）→ execute_command 阻塞轮询目标文件出现即提前返回。更稳修正：直接把 等待+登录+push+清理 整链写进单个后台 job，只需一次短阻塞。

【步骤4 登录验证】sed 从 token 文件提取 access_token 管道喂 gh auth login --with-token（token 不回显、不进日志、不进 evidence）→ gh auth setup-git（桥接 git 凭据）→ gh api user --jq .login 验证身份与预期账号一致后再操作。

【步骤5 重试纪律】重试前必须回读 evidence 中原始失败命令原文（read_evidence / search_evidence），使用与原意图完全相同的 refspec/参数；本次靠回读确认原命令是 git push origin feature/method-learning-v1 而非想当然推当前分支。

【步骤6 清理】shred -u 或 rm -f 设备码与 token 临时文件，ls 验证不存在；报告全程不引用 token 任何片段。

【泛化】步骤1-2 的 pending/slow_down/expired/denied 分支模型是 RFC 8628 OAuth2 Device Flow 通用模式，可迁移至任何支持设备码的 IdP；GitHub 特有部分仅为 endpoint、gh CLI 官方 client_id、setup-git 桥接、api user 验证。