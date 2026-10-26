---
title: 手工转写长标识符清单必错：一律从工具输出程序化派生
scenario: 多轮 git 分支/worktree 清理：需要按名字逐个删除 ~20 个本地分支与 ~30 个 worktree，名字含日期后缀（20261009/20260909）与目录名变形（目录名与注册路径差一段）。
root_cause: ""
solution: 停止手工转写标识符：目标清单全部由 git for-each-ref / git worktree list --porcelain 管道推导（grep -v 过滤保留集），变更循环直接消费该输出；发现 unknown revision/not a working tree 类错误时第一时间怀疑自己转写错位（数字换位/丢段），用 od -c 或 ls 实测名字字节，而不是继续换参数重试。
evidence: "失败与修复全程回执：evidence://v1/e2105643aab3e0f4047b222b99e7b10b5af3e95b77b9ffe34485ea688ed8bc4（手工名单 4 个 worktree 移除失败+knowledge 分支 not found）、evidence://v1/cd91aa203194acd99afdec7a54042b152ff8aa589602b4c6de5d6dbd2edae963（第二轮手工名单仍失败 is not a working tree）、evidence://v1/1c3d1c9d0573d5e566d9a3b88dcf8f594b35ec74203d6cb9f2d828ae82092bd9（改用 git worktree list --porcelain + for-each-ref 程序化推导后全部清理成功，终态仅剩保留集）"
tags: [git, 脚本纪律, 标识符转写, 分支清理]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-23T00:28:44.509635+08:00"
updated_at: "2026-10-23T00:28:44.509635+08:00"
---

分支清理任务中，我把分支名 feat/knowledge-consumption-receipts-20261009 手工转写成命令参数时连续 3 次错写成 20260909（数字换位），导致 unknown revision、worktree remove 失败、branch -D not found 等假故障；另外 worktree 目录名与分支注册路径不完全一致（目录缺 -main- 段）也用手工名单撞了墙。改用 git for-each-ref / git worktree list --porcelain 程序化推导目标清单后，零名称错误完成全部清理。规则：凡是多次出现、含易混字符（日期、长后缀）的标识符清单，禁止手抄进脚本，一律从工具输出管道派生；清单类操作先跑一条只读命令拿到精确清单再执行变更。