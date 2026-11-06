---
title: github https push 挂死定性：GET 通 POST 黑洞，HTTP/1.1/no-thin 无效，走 SSH/代理恢复
scenario: 国内网络环境向 github（https）推送：GET 类操作正常但 push 无限挂死。
root_cause: ""
solution: 快速定性：curl GET 正常 + sample git-remote-https 阻塞在响应读取 + 包量极小 ⇒ 判 POST 黑洞，不再反复重试；直接走 SSH 注册/代理/择时三条恢复路径，并把推送内容留本地就绪态（门禁全绿）保证随时可推。
evidence: ps/netstat 连接数、sample 调用图、curl 双探、ssh -T 双端口 Permission denied publickey、git remote -v（origin=github https）。
tags: [git-push, github, network, post-blackhole, diagnosis]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T14:06:23.091496+08:00"
updated_at: "2026-11-06T14:06:23.091496+08:00"
supersedes: [EXPERIENCE-20260920-github-com-443-git-data-api-pr]
---

定性证据链：git push origin main（https://github.com）四次尝试全部挂死于 receive-pack 首行响应读取（sample 显示 git-remote-https 主线程 100% 阻塞在 strbuf_getdelim）；GET 正常（api.github.com 200/0.4s、web 200/0.86s）、POST 零返回；osxkeychain 凭证在位（同日清晨有过成功推送）；无 pre-push 钩子业务、无代理；待推仅 11 commits/90 objects。无效对策（实测）：http.version=HTTP/1.1、transfer.thin=false、http.lowSpeed* 熔断均不改变挂死。有效结论：这是网络路径对 github POST 的阻断，客户端无解；恢复路径=用户将本机 SSH 公钥（~/.ssh/id_ed25519.pub 等）加入 github 账户改走 ssh，或换网络/代理环境后重试裸命令（review_admission 的 git_push PASS 按树内容缓存可复用）。注意 host 只认裸命令形态（GIT_TRACE= 前缀会 push_wrapper_not_verified 拒审）。