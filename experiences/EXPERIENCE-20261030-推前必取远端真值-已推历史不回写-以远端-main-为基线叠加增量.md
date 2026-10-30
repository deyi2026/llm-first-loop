---
title: 推前必取远端真值；已推历史不回写，以远端 main 为基线叠加增量
scenario: 并行开发工作流与本会话同时推 origin/main，本地 origin/main 跟踪引用落后于远端真值；本地 main 又处于 detached HEAD 且基于旧基线。若直接推本地改写链，会回退远端已有的修复并需要强推。
root_cause: ""
solution: 推前必跑 `git ls-remote origin main` 取远端真值（本地 origin/main 可能过期数个提交）；确认已推历史不回写——以远端 main 为基线 `git reset --hard origin/main`，再把本地增量按文件移植过去（保留远端较新的修复，移植自己那部分），形成新的快进提交。远端真值与本地跟踪引用不一致时，以 ls-remote 为准。
evidence: 本轮实测：git ls-remote origin main = 6f846ae9c，而本地 origin/main 仍显示 80768312b；本地改写链缺远端 a34dc1507(quotePath 修复) 与 ruff/pyright 修复。据此改为以 6f846ae9c 为基线重做移植，两次推送均为快进（6f846ae9c..7addb16ce、7addb16ce..841fbfea4），无强推。
tags: [git, push, 远端真值, 历史回写, 并发工作流]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T01:46:04.777036+08:00"
updated_at: "2026-10-30T01:46:04.777036+08:00"
---