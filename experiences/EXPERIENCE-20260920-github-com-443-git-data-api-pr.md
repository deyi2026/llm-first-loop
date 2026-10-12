---
title: "github.com:443 黑洞时经 Git Data API 推送提交与建 PR"
scenario: "本机网络对 github.com:443 黑洞（DNS 解析 IP 不通），但 api.github.com 正常；git push 挂死零输出，SSH 443 端口无凭据不可用"
root_cause: ""
solution: 改用 Git Data REST API 逐对象推送（blob→tree→commit→ref）+ gh CLI 建 PR；诊断顺序：dig 两域名→nc 测各 IP 443→确认仅 web 主机黑洞
evidence: "分支 refs/heads/fix/evolution-213965a1-20260920 @ a19c2346 经此方法成功创建，PR #55 https://github.com/deyi2026/llm-first-loop/pull/55；nc/curl 测试证据在会话 execute_command 记录（github.com 000 超时、api.github.com 200/0.42s）"
tags: [network, github, git-data-api, push-fallback, blackhole]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-20T13:56:42.682031+08:00"
updated_at: "2026-09-20T13:56:42.682031+08:00"
---

本机 github.com:443 对 DNS 解析到的 IP（如 20.205.243.166）被黑洞（nc/curl 超时），而 api.github.com（20.205.243.168）TLS/REST 完全可用。gh CLI 走 api.github.com 一切正常，git push/fetch over HTTPS 挂死。诊断：dig 对比两域名解析 IP + nc -z 测各自 443。绕行：Git Data REST API 逐对象推送——1) gh api 取 main 的 commit sha 与 base_tree；2) 对每个变更文件 jq -n --rawfile 生成 {content,encoding:utf-8} 后 POST /git/blobs；3) POST /git/trees {base_tree, tree:[{path,mode:100644,type:blob,sha}...]}（注意 tree 是数组，--slurpfile 直接给数组，勿取 [0]）；4) POST /git/commits {message, tree, parents, author/committer}（从本地 git show -s --format='%an|%ae|%aI|%cn|%ce|%cI' 复制身份可尽量对齐本地提交）；5) POST /git/refs 建分支；6) gh pr create 正常工作。坑：bash 管道尾 IFS read 变量子 shell 丢失导致空 date-time 422，需 LINE=$(...) && read <<< "$LINE"；jq slurpfile 误用 $t[0] 导致 tree 422。gh api 单次调用偏慢（网络抖动），长链路放后台任务分步断点续跑（对象已上传可幂等复用 entries.ndjson）。