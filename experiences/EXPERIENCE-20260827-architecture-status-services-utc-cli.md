---
title: architecture_status services 进程归属解读：双工作区 + UTC 时区 + cli 生命周期三陷阱
scenario: "查看 architecture_status/process_versions 判断进程新旧、归属或\"本会话宿主\"时；主区+镜像区双工作区并行运行的运维排障"
root_cause: ""
solution: "services 注册簿含跨工作区进程：判断归属看进程 started_at 与本会话/任务时间线的对应关系，而非默认\"唯一 cli=本会话\"；cli 类前台服务会话结束即退出属正常生命周期；所有表格时间戳按 UTC→北京 +8 换算后再对本地日志"
evidence: "用户澄清消息（2026-08-27 23:46 前后）：\"cli 之谜解开——pid 73797 已经自己退出了……那个 cli 是镜像 AI 的会话宿主——它出完这份表格后会话就结束了，进程随之消亡。旧代码进程已不存在，风险归零。按 restart_system.sh 的设计，cli 本来就是交互式前台服务不能守护化。\"；此前 8ffca98c（architecture_status）显示该 cli 条目 code_current=false。"
tags: [process-registry, dual-workspace, mirror-protocol, utc-timezone, cli-lifecycle]
source: {}
status: active
created_at: "2026-08-27T23:48:38.180195+08:00"
updated_at: "2026-08-27T23:48:38.180195+08:00"
---

误判现场：2026-08-27 深夜，architecture_status 的 process_versions.services 列出 cli(pid 73797, git_head 6da5e9c, code_current=false)，我判定其为"本会话宿主"并建议"重启 cli 会终止本会话，无需专门重启"。用户随后澄清：该 cli 是**镜像区 AI 会话的宿主进程**（18:57 UTC+8 启动，服务于镜像区执行链），它完成自己的会话后已自然退出——与本会话（主区）无关，风险归零。根因：①services 注册簿列的是所有 LFL 进程，主区/镜像区两套会混在一张表里；②交互式 cli 本来就是前台服务，会话结束即退出（不能守护化，restart_system.sh 设计如此），"列表里的 cli"≠"我的会话"；③时间戳是 UTC（表格显示 15:43 实为北京 23:43），容易和本地日志对不上而误判进程新旧。防控：看到 cli 条目时先问"这是谁的会话宿主"——用启动时间与会话时间线对应（本会话开始时刻 vs 进程 started_at），跨区场景检查工作区归属（cwd 记录）；结论拿不准时如实说"归属待确认"而不是直接推断；UTC/本地时区显式换算再对时间线。